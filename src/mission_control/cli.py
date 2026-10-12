"""Codex Mission Control CLI: diagnostics and deterministic routed text tasks."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import secrets
import shutil
import subprocess
import sys

from .adapter import CodexAdapter, TurnFailed
from .rpc import ConnectionLost, RpcClient, RpcError
from .routing import RoutingBlocked
from .routing_cli import execute_routing
from .managed_cli import execute_managed
from .queue_cli import execute_queue
from .limits import number
from .state import load_state, save_state, state_lock, StateError


class UserError(ValueError):
    """A local, application-authored message safe to display."""


def select_configuration(models: list[dict], model: str | None,
                         effort: str | None) -> tuple[str, str]:
    """Manual/catalog-default selection only; not the stage-2 smart router."""
    visible = [entry for entry in models if not entry.get("hidden", False)]
    if not visible:
        raise UserError("Codex returned no visible models")
    if model is None:
        selected = next((entry for entry in visible if entry.get("isDefault")), visible[0])
    else:
        selected = next((entry for entry in visible if entry.get("model") == model), None)
        if selected is None:
            raise UserError("Requested model is absent from the current catalog")
    chosen_effort = effort or selected.get("defaultReasoningEffort")
    supported = {entry["reasoningEffort"] for entry in selected.get("supportedReasoningEfforts", [])}
    if chosen_effort not in supported:
        raise UserError("Reasoning effort is not advertised by the selected model")
    return selected["model"], chosen_effort


def require_resume_state(path: Path, cwd: Path) -> dict:
    data = load_state(path)
    if data.get("stage") != "first_completed":
        raise UserError("State must contain a verified first turn; no uncertain turn is retried")
    if Path(data["cwd"]).resolve() != cwd.resolve():
        raise UserError("Resume cwd differs from the saved workspace")
    for field in ("threadId", "model", "effort", "nonce"):
        if not isinstance(data.get(field), str) or not data[field]:
            raise UserError("Incomplete smoke state")
    return data


def version(command: list[str]) -> str | None:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=10, creationflags=flags, check=True)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def model_summary(models: list[dict]) -> list[dict]:
    fields = ("id", "model", "displayName", "hidden", "isDefault",
              "defaultReasoningEffort", "supportedReasoningEfforts")
    return [{field: entry[field] for field in fields if field in entry} for entry in models]


async def execute(args) -> dict:
    if args.command.startswith("queue-"):
        return await execute_queue(args)
    if args.command in {"limits", "managed-run", "managed-resume"}:
        return await execute_managed(args)
    if args.command in {"route-plan", "route-run"}:
        return await execute_routing(args)
    if args.command == "doctor":
        return await _execute_claimed(args)
    with state_lock(args.state.resolve()):
        return await _execute_claimed(args)


async def _execute_claimed(args) -> dict:
    cwd = args.cwd.resolve()
    if not cwd.is_dir():
        raise UserError("Workspace directory does not exist")
    executable = shutil.which(args.codex)
    if executable is None:
        raise UserError("Codex executable not found; use --codex with its full path")
    if args.command == "smoke" and args.state.exists():
        raise UserError("State already exists; use a new --state path to start another check")
    saved = require_resume_state(args.state, cwd) if args.command == "resume-check" else None
    async with RpcClient([executable, "app-server", "--listen", "stdio://"],
                         cwd=str(cwd), timeout=args.rpc_timeout) as rpc:
        adapter = CodexAdapter(rpc)
        if args.command == "doctor":
            report = {
                "checkedAt": now(), "platform": platform.platform(),
                "python": platform.python_version(),
                "git": version(["git", "--version"]),
                "codex": version([executable, "--version"]),
                "server": {key: rpc.initialization[key] for key in
                           ("userAgent", "platformFamily", "platformOs")
                           if key in rpc.initialization},
                "account": await adapter.account(),
                "models": model_summary(await adapter.models())}
            try:
                report["limits"] = await adapter.rate_limits()
            except RpcError as error:
                report["limits"] = {"available": False, "rpcCode": error.code}
            return report
        if saved:
            model, effort = select_configuration(await adapter.models(),
                                                 saved["model"], saved["effort"])
            resumed = await adapter.resume_thread(saved["threadId"], cwd, model)
            if resumed["thread"]["id"] != saved["threadId"]:
                raise UserError("Server resumed a different thread")
            data = saved
            data["resumeServerPid"] = rpc.process.pid
            data["stage"] = "resume_submitted"
            save_state(args.state, data)
            prompt = ("Return only the marker that I asked you to remember in my "
                      "previous message. Do not use tools.")
        else:
            model, effort = select_configuration(await adapter.models(), args.model, args.effort)
            started = await adapter.start_thread(cwd, model)
            nonce = "MC-" + secrets.token_hex(8)
            data = {"threadId": started["thread"]["id"], "model": model,
                    "effort": effort, "cwd": str(cwd), "nonce": nonce,
                    "createdAt": now(), "firstServerPid": rpc.process.pid,
                    "stage": "first_submitted"}
            save_state(args.state, data)
            prompt = ("Remember this marker for my next message: " + nonce +
                      ". Reply with exactly this marker and nothing else. Do not use tools.")
        outcome = await adapter.run_turn(data["threadId"], prompt, model, effort,
                                         timeout=args.turn_timeout)
        data["resumeTurn" if saved else "firstTurn"] = outcome
        data["updatedAt"] = now()
        valid = outcome["text"].strip() == data["nonce"]
        data["stage"] = ("verified" if saved else "first_completed") if valid else "validation_failed"
        save_state(args.state, data)
        if not valid:
            raise UserError("Completed turn did not return the expected marker; state preserved")
        return data


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Codex Mission Control - Smart Model Router")
    result.add_argument("command", choices=("doctor", "smoke", "resume-check", "route-plan", "route-run", "limits", "managed-run", "managed-resume", "queue-add", "queue-list", "queue-run",
                                            "queue-priority", "queue-pause", "queue-resume", "queue-cancel", "queue-retry",
                                            "queue-configure", "queue-approve", "queue-migrate", "queue-backup", "queue-checkpoint-export", "queue-review-result", "queue-approve-result"),
                        help="doctor/route-plan: metadata only; other commands run real inference")
    result.add_argument("--queue", type=Path, default=Path(".local/missions.sqlite3"))
    result.add_argument("--allow-root", action="append", default=[], help="Allowed original project root (repeatable)")
    result.add_argument("--destination", type=Path, help="New backup file or checkpoint export directory")
    result.add_argument("--legacy-queue", type=Path, help="Existing JSON queue to import without replay")
    result.add_argument("--mission", type=Path, help="Trusted mission manifest JSON (queue-add)")
    result.add_argument('--review-id',help='Exact result review ID; approval applies only to these bytes')
    result.add_argument('--accept-user-rights',action='store_true',help='Accept that reviewed code runs with your OS file/network rights; not sandboxed')
    result.add_argument('--acknowledge-uncertain-result',action='store_true',help='After manual reconciliation, explicitly permit retry despite unknown prior side effects')
    result.add_argument("--mission-id", help="Mission ID for queue controls")
    result.add_argument("--priority", type=int, help="New priority (larger runs first)")
    result.add_argument("--codex", default="codex", help="Executable name or full path")
    result.add_argument("--cwd", type=Path, default=Path.cwd())
    result.add_argument("--state", type=Path, default=None)
    result.add_argument("--output", type=Path, help="Save sanitized report atomically")
    result.add_argument("--model", help="Manual model identifier from model/list (smoke)")
    result.add_argument("--effort", help="Advertised effort (smoke)")
    result.add_argument("--rpc-timeout", type=float, default=30)
    result.add_argument("--turn-timeout", type=float, default=120)
    task_input = result.add_mutually_exclusive_group()
    task_input.add_argument("--task", help="Task text; --task-file avoids shell quoting")
    task_input.add_argument("--task-file", type=Path, help="UTF-8 task file")
    result.add_argument("--mode", choices=("economy", "balanced", "quality"), default="balanced")
    result.add_argument("--operation", choices=("auto", "text", "docs", "format", "code",
                                               "refactor", "debug", "architecture"), default="auto")
    result.add_argument("--risk", choices=("auto", "low", "medium", "high", "critical"), default="auto")
    result.add_argument("--files", type=int, help="Estimated number of changed files")
    result.add_argument("--previous-errors", type=int, default=0)
    result.add_argument("--expect", help="Exact expected text; required for route-run")
    result.add_argument("--exclude-model", action="append", default=[])
    result.add_argument("--history", type=Path, default=Path(".local/router-history.json"))
    result.add_argument("--max-attempts", type=int, default=3)
    result.add_argument("--thread-id", help="Explicit existing thread for route-run")
    result.add_argument("--limit-policy", choices=("balanced", "weekly", "reserve", "stop"), default="balanced")
    result.add_argument("--limit-threshold", type=float, default=100, help="Used-percent ceiling for stop policy")
    result.add_argument("--max-wait", type=float, help="Maximum seconds to wait this invocation; default unlimited")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.state is None:
        args.state = Path(".local/managed-run.json" if args.command.startswith("managed-") else
                          ".local/route-run.json" if args.command == "route-run" else ".local/smoke.json")
    if not number(args.rpc_timeout) or not number(args.turn_timeout) or args.rpc_timeout <= 0 or args.turn_timeout <= 0:
        print("Timeouts must be positive", file=sys.stderr)
        return 2
    try:
        if args.command.startswith("queue-") and args.output:
            queue_path=args.queue.resolve()
            forbidden={queue_path,queue_path.parent/(queue_path.name+".history.json")}
            from .storage import guard_path
            guard_path(args.output)
            forbidden.update(Path(str(queue_path)+suffix) for suffix in ('-journal','-wal','-shm','.lock'))
            from .queue import MissionQueue, worker_lease_path
            forbidden.update({worker_lease_path().resolve(),Path(str(worker_lease_path().resolve())+".lock")})
            q=MissionQueue(queue_path)
            runs=q.journal().run_root if queue_path.suffix=='.sqlite3' else queue_path.parent/(queue_path.name+".runs")
            if queue_path.suffix=='.sqlite3':forbidden.add(q.journal().history_path)
            if args.destination:
                forbidden.add(args.destination.resolve())
                forbidden.update(Path(str(args.destination.resolve())+suffix) for suffix in ("-journal","-wal","-shm",".lock"))
            if args.legacy_queue:
                forbidden.add(args.legacy_queue.resolve())
                forbidden.add(args.legacy_queue.with_name(args.legacy_queue.name+'.migration.json').resolve())
            if args.output.exists() or args.output.resolve() in forbidden or args.output.resolve().is_relative_to(runs):
                raise UserError("Queue report must be a new file outside queue journals/history/workspaces")
        if args.output and args.output.resolve() in {args.state.resolve(), args.history.resolve()}:
            raise UserError("Report output must differ from run state and routing history")
        from .safety import sanitize
        report = sanitize(asyncio.run(execute(args)))
        if args.output:
            from .secure_files import write_file
            write_file(args.output,(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'),new=True)
        print(json.dumps(report, ensure_ascii=True, indent=2))
        return 1 if args.command in {"route-run", "managed-run", "managed-resume", "queue-run"} and report.get("stage") != "completed" else 0
    except (RpcError, ConnectionLost, TurnFailed, TimeoutError, OSError, ValueError) as error:
        # Do not print arbitrary server messages, stderr, prompts or credentials.
        safe = str(error) if isinstance(error, (RpcError, ConnectionLost, TurnFailed, UserError, StateError, RoutingBlocked)) else type(error).__name__
        print(f"Mission Control: {safe}. Check local state before any retry.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Interrupted; saved state retained. No automatic retry.", file=sys.stderr)
        return 130
