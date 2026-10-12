"""CLI integration for automatic routing; old stage-1 commands remain available."""
from pathlib import Path
import shutil

from .adapter import CodexAdapter
from .execution import RoutedExecutor, exact_output
from .history import History
from .routing import Task, Mode, SmartRouter, RoutingBlocked
from .rpc import RpcClient, RpcError
from .state import state_lock


async def execute_routing(args):
    text = args.task
    if args.task_file is not None:
        text = args.task_file.read_text(encoding="utf-8-sig")
    if text is None:
        raise RoutingBlocked("Specify --task or --task-file")
    task = Task(text, operation=args.operation, estimated_files=args.files,
                risk=args.risk, previous_errors=args.previous_errors)
    if args.model is not None or args.effort is not None:
        raise RoutingBlocked("Routing commands choose automatically; use --exclude-model to constrain")
    if args.command == "route-run" and args.expect is None:
        raise RoutingBlocked("route-run requires --expect for an actual local result check")
    if type(args.max_attempts) is not int or not 1 <= args.max_attempts <= 8:
        raise RoutingBlocked("--max-attempts must be from 1 to 8")
    validator = exact_output(args.expect) if args.command == "route-run" else None
    executable = shutil.which(args.codex)
    cwd = args.cwd.resolve()
    if not executable or not cwd.is_dir():
        raise RoutingBlocked("Codex executable and an existing workspace are required")
    async with RpcClient([executable, "app-server", "--listen", "stdio://"],
                         cwd=str(cwd), timeout=args.rpc_timeout) as rpc:
        adapter = CodexAdapter(rpc)
        router = SmartRouter(excluded=set(args.exclude_model))
        if args.command == "route-plan":
            with state_lock(args.history.resolve()):
                router.history = History.load(args.history)
            models = await adapter.models()
            try:
                limits = await adapter.rate_limits()
            except RpcError as error:
                if error.code != -32601:
                    raise
                limits = None
            decision = router.choose(task, models, Mode(args.mode), limits=limits)
            return {"stage": "planned", "inferenceStarted": False,
                    "decision": decision.to_dict()}
        engine = RoutedExecutor(adapter, router, args.state, cwd=cwd, history_path=args.history)
        return await engine.run(task, Mode(args.mode), validator=validator,
                                thread_id=args.thread_id, max_attempts=args.max_attempts,
                                timeout=args.turn_timeout)
