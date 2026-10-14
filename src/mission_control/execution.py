"""Bounded, validator-driven text-task execution; not a mission queue or scheduler."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import tempfile
from pathlib import Path
import time
from collections.abc import Callable

from .adapter import CodexAdapter, TurnFailed
from .history import History
from .routing import Task, Mode, SmartRouter, RoutingBlocked
from .rpc import ConnectionLost, RpcError
from .state import state_exists, save_state, state_lock


@dataclass(frozen=True)
class Validation:
    passed: bool
    kind: str = "quality"
    feedback: str = ""

    def __post_init__(self):
        if type(self.passed) is not bool:
            raise ValueError("Validator must provide a boolean outcome")
        if self.kind not in {"quality", "test_failure", "not_retryable"}:
            raise ValueError("Unknown validation failure category")
        if not isinstance(self.feedback, str):
            raise ValueError("Validator feedback must be text")


def exact_output(expected: str) -> Callable[[str], Validation]:
    if not isinstance(expected, str) or not expected.strip():
        raise ValueError("Expected output must be nonempty")

    def validate(text: str) -> Validation:
        passed = text.strip() == expected.strip()
        return Validation(passed, feedback="" if passed else
                          "Exact-output validation failed; return only the requested answer.")
    return validate


def thread_lease_path(cwd: Path, thread_id: str) -> Path:
    identity = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
    return Path(tempfile.gettempdir()) / "codex-mission-control" / "thread-locks" / identity


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class RoutedExecutor:
    def __init__(self, adapter: CodexAdapter, router: SmartRouter, state_path: Path,
                 *, cwd: Path, history_path: Path | None = None):
        self.adapter = adapter
        self.router = router
        self.state_path = Path(state_path).resolve()
        self.cwd = Path(cwd).resolve()
        self.history_path = Path(history_path).resolve() if history_path is not None else None
        if self.history_path == self.state_path:
            raise RoutingBlocked("Routing history and run state must be different files")

    async def run(self, task: Task, mode: Mode = Mode.BALANCED, *,
                  validator: Callable[[str], Validation], thread_id: str | None = None,
                  max_attempts: int = 3, timeout: float = 120) -> dict:
        if type(max_attempts) is not int or not 1 <= max_attempts <= 8:
            raise RoutingBlocked("Attempt budget must be an integer from 1 to 8")
        if timeout <= 0 or not self.cwd.is_dir():
            raise RoutingBlocked("Positive timeout and existing workspace required")
        mode = Mode(mode)
        with ExitStack() as claims:
            claims.enter_context(state_lock(self.state_path))
            if state_exists(self.state_path):
                raise RoutingBlocked("Run state already exists; uncertain/completed runs are never replayed")
            if self.history_path is not None:
                claims.enter_context(state_lock(self.history_path))
                self.router.history = History.load(self.history_path)
            if thread_id is not None:
                claims.enter_context(state_lock(thread_lease_path(self.cwd, thread_id)))
            return await self._run(task, mode, validator, thread_id, max_attempts, timeout, claims)

    async def _run(self, task, mode, validator, thread_id, maximum, timeout, claims):
        data = {"version": 1, "stage": "planning", "createdAt": timestamp(),
                "taskHash": hashlib.sha256(task.text.encode("utf-8")).hexdigest(),
                "mode": mode.value, "attempts": []}
        save_state(self.state_path, data)
        previous = None
        visited = set()
        raised_models = set()
        feedback = ""
        try:
            for _ in range(maximum):
                models = await self.adapter.models()
                try:
                    limits = await self.adapter.rate_limits()
                except RpcError as error:
                    if error.code != -32601:
                        raise
                    limits = None  # Unknown, never fabricate quota or reset time.
                if previous is None:
                    decision = self.router.choose(task, models, mode, limits=limits)
                else:
                    decision = self.router.escalate(
                        previous, models, visited, effort_raised=previous.model in raised_models,
                        limits=limits)
                    if decision is None:
                        data["stage"] = "validation_failed"
                        data["stopReason"] = "No unvisited stronger supported configuration"
                        save_state(self.state_path, data)
                        return data
                    if decision.model == previous.model:
                        raised_models.add(decision.model)
                pair = (decision.model, decision.effort)
                if pair in visited:
                    raise RoutingBlocked("Routing pair already attempted")
                visited.add(pair)
                if not data.get("threadId"):
                    if thread_id is None:
                        started = await self.adapter.start_thread(self.cwd, decision.model)
                    else:
                        started = await self.adapter.resume_thread(thread_id, self.cwd, decision.model)
                    actual_id = started["thread"]["id"]
                    if thread_id is None:
                        claims.enter_context(state_lock(thread_lease_path(self.cwd, actual_id)))
                    if thread_id is not None and actual_id != thread_id:
                        raise RoutingBlocked("Server resumed a different thread")
                    if started.get("model") != decision.model:
                        raise RoutingBlocked("Server did not apply selected thread model")
                    data["threadId"] = actual_id
                    save_state(self.state_path, data)
                prompt = task.text
                if feedback:
                    prompt += ("\n\nPrevious attempt failed local validation. "
                               "Use the existing conversation context and correct the result.\n"
                               + feedback[:2048])
                attempt = {"decision": decision.to_dict(), "phase": "submitted",
                           "submittedAt": timestamp()}
                data["attempts"].append(attempt)
                data["stage"] = "submitted"
                save_state(self.state_path, data)  # Persist before any inference.
                begin = time.monotonic()
                from .model_policy import submission_mode, PolicyBlocked
                try:
                    with submission_mode(True):
                        outcome = await self.adapter.run_turn(data["threadId"], prompt,
                                                             decision.model, decision.effort, timeout=timeout)
                except PolicyBlocked:
                    attempt['phase'] = 'not_started'
                    raise
                attempt["elapsedSeconds"] = round(time.monotonic() - begin, 3)
                attempt["outcome"] = outcome
                attempt["phase"] = "completed_unvalidated"
                data["stage"] = "completed_unvalidated"
                save_state(self.state_path, data)
                configured = await self.adapter.configuration(data["threadId"])
                attempt["effectiveConfiguration"] = configured
                if (configured.get("model") != decision.model
                        or configured.get("reasoningEffort") != decision.effort
                        or outcome.get("reroutedModel") not in (None, decision.model)):
                    raise RoutingBlocked("Server configuration/reroute differs from selected model or effort")
                result = validator(outcome["text"])
                if not isinstance(result, Validation):
                    raise RoutingBlocked("Validator must return a Validation value")
                attempt["validation"] = {"passed": result.passed, "kind": result.kind,
                                         "feedback": result.feedback[:2048]}
                attempt["phase"] = "validated"
                self.router.history.record_validated(History.turn_observation(data['threadId'],outcome['turnId']),decision.model,
                    decision.effort,decision.assessment.complexity,{'passed':result.passed,'kind':result.kind})
                if self.history_path is not None:
                    self.router.history.save(self.history_path)
                data["updatedAt"] = timestamp()
                data["stage"] = "completed" if result.passed else "validation_failed"
                save_state(self.state_path, data)
                if result.passed or result.kind == "not_retryable":
                    return data
                previous = decision
                feedback = result.feedback or "Local result checks did not pass."
            data["stopReason"] = "Attempt budget exhausted"
            save_state(self.state_path, data)
            return data
        except (ConnectionLost, TimeoutError):
            data["stage"] = "outcome_unknown"
            data["stopReason"] = "Transport/timeout; no automatic retry"
            save_state(self.state_path, data)
            raise
        except (TurnFailed, RpcError, RoutingBlocked) as error:
            data["stage"] = "stopped"
            data["stopReason"] = type(error).__name__
            if isinstance(error, TurnFailed):
                data["codexFailure"] = {"status": error.status, "kind": error.error_kind,
                                        "httpStatus": error.http_status}
            save_state(self.state_path, data)
            raise
