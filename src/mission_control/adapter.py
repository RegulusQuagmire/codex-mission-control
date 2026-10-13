"""Versioned App Server operations, independent of UI and persistence."""
from __future__ import annotations

import asyncio
import contextlib
import time
from pathlib import Path

from .rpc import ConnectionLost, RpcClient
from .limits import sanitize_limits


class TurnFailed(RuntimeError):
    def __init__(self, message: str, *, status: str = "failed",
                 error_kind: str = "unknown", http_status: int | None = None):
        self.status = status
        self.error_kind = error_kind
        self.http_status = http_status
        super().__init__(message)


class TurnPaused(TurnFailed):
    def __init__(self, receipt):
        self.receipt=receipt
        super().__init__('Planned interruption confirmed; review checkpoint before continuing',
                         status='interrupted',error_kind='plannedPause')


def safe_failure(error: dict | None) -> tuple[str, int | None]:
    info = (error or {}).get("codexErrorInfo")
    known = {
        "contextWindowExceeded", "sessionBudgetExceeded", "usageLimitExceeded",
        "rateLimitExceeded", "flexUnavailable", "serverOverloaded", "unauthorized",
        "badRequest", "sandboxError", "internalServerError", "other",
        "httpConnectionFailed", "responseStreamConnectionFailed",
        "responseStreamDisconnected", "responseTooManyFailedAttempts",
    }
    if isinstance(info, str):
        return (info if info in known else "unknown"), None
    if isinstance(info, dict) and len(info) == 1:
        kind, details = next(iter(info.items()))
        status = details.get("httpStatusCode") if isinstance(details, dict) else None
        return (kind if kind in known else "unknown"), status if type(status) is int else None
    return "unknown", None


class CodexAdapter:
    """One active run_turn per adapter; arbitrary RPC requests may overlap."""
    def __init__(self, rpc: RpcClient):
        self.rpc = rpc
        self._turn_lock = asyncio.Lock()
        # Only threads created by this adapter, before it has sent their first turn.
        # Codex supports summary reads but not full history before materialization.
        self._fresh_threads: set[str] = set()
        self._pause_options = None

    def configure_pause(self, *, stop_requested=None, on_receipt=None, on_checkpoint=None, grace=5):
        self._pause_options={'stop_requested':stop_requested,'receipt':on_receipt,
                             'checkpoint':on_checkpoint,'grace':grace}

    async def account(self) -> dict:
        result = await self.rpc.request("account/read", {"refreshToken": False})
        account = result.get("account") or {}
        return {"type": account.get("type"), "planType": account.get("planType"),
                "requiresOpenaiAuth": result.get("requiresOpenaiAuth")}

    async def models(self) -> list[dict]:
        models = []
        cursor = None
        seen = set()
        while True:
            params = {"limit": 100, "includeHidden": False}
            if cursor is not None:
                params["cursor"] = cursor
            result = await self.rpc.request("model/list", params)
            models.extend(result["data"])
            cursor = result.get("nextCursor")
            if cursor is None:
                return models
            if cursor in seen:
                raise ConnectionLost("Repeated model pagination cursor")
            seen.add(cursor)

    async def rate_limits(self) -> dict:
        raw = await self.rpc.request("account/rateLimits/read")

        result = sanitize_limits(raw)
        self.rpc.rate_limit_snapshot = result
        return result

    @property
    def observed_limits(self):
        return getattr(self.rpc, "rate_limit_snapshot", None)

    async def credit_gate(self, model, *, limits=None):
        from .credit_policy import check_credit_limits
        if limits is None:
            limits = await self.rate_limits()
        return check_credit_limits(limits, model, observed_at=time.time())

    async def read_thread(self, thread_id: str) -> dict:
        fresh = thread_id in self._fresh_threads
        raw = await self.rpc.request("thread/read", {"threadId": thread_id, "includeTurns": not fresh})
        thread = raw.get("thread") or {}
        turns = thread.get("turns")
        if thread.get("id") != thread_id or not isinstance(turns, list):
            raise ConnectionLost("Incomplete or mismatched thread history")
        if fresh and turns:
            raise TurnFailed("Fresh thread unexpectedly contains turns; no submission",
                             status="not_started", error_kind="activeOrUnknownThread")
        clean = {"id": thread_id, "status": thread.get("status"), "turns": []}
        for turn in turns:
            items = []
            for item in turn.get("items", []):
                if item.get("type") == "agentMessage":
                    items.append({key: item[key] for key in ("id", "type", "text", "phase") if key in item})
                elif item.get("type") == "userMessage":
                    content = [{"type": "text", "text": value.get("text", "")} for value in item.get("content", []) if value.get("type") == "text"]
                    items.append({"type": "userMessage", "content": content})
            kind, http = safe_failure(turn.get("error"))
            clean["turns"].append({"id": turn.get("id"), "status": turn.get("status"),
                                   "itemsView": turn.get("itemsView", "full"), "items": items,
                                   "failure": {"kind": kind, "httpStatus": http}})
        return clean

    async def start_thread(self, cwd: Path, model: str) -> dict:
        result = await self.rpc.request("thread/start", {
            "cwd": str(cwd.resolve()), "model": model, "ephemeral": False,
            "sandbox": "read-only", "approvalPolicy": "never",
            "developerInstructions":
                "This is a minimal integration test. Do not use tools, commands, "
                "connectors, subagents or file access. Answer the user text only."})
        thread_id = result.get("thread", {}).get("id")
        if not isinstance(thread_id, str) or not thread_id:
            raise ConnectionLost("Server did not return a new thread ID")
        self._fresh_threads.add(thread_id)
        return result

    async def assert_idle(self, thread_id: str):
        thread = await self.read_thread(thread_id)
        status = thread.get("status", {})
        turns = thread.get("turns")
        if (not isinstance(status, dict) or status.get("type") not in {"idle", "notLoaded"}
                or not isinstance(turns, list)
                or any(turn.get("status") not in {"completed", "failed", "interrupted"}
                       for turn in turns)):
            raise TurnFailed("Target thread is not idle; no turn was submitted",
                             status="not_started", error_kind="activeOrUnknownThread")

    async def resume_thread(self, thread_id: str, cwd: Path, model: str) -> dict:
        await self.assert_idle(thread_id)
        return await self.rpc.request("thread/resume", {
            "threadId": thread_id, "cwd": str(cwd.resolve()), "model": model,
            "sandbox": "read-only", "approvalPolicy": "never"})

    async def configuration(self, thread_id: str) -> dict:
        # No model/effort override: observe the configuration actually retained.
        await self.assert_idle(thread_id)
        result = await self.rpc.request("thread/resume", {
            "threadId": thread_id, "sandbox": "read-only", "approvalPolicy": "never"})
        return {"model": result.get("model"), "reasoningEffort": result.get("reasoningEffort")}

    async def run_turn(self, thread_id: str, text: str, model: str, effort: str,
                       *, timeout: float = 120, on_started=None) -> dict:
        async with self._turn_lock:
            turn_id = None
            control = None
            completed_text: dict[str, tuple[str, str | None]] = {}
            rerouted_model = None
            try:
                async with asyncio.timeout(timeout):
                    await self.assert_idle(thread_id)
                    from .model_policy import AUTOMATIC, validate_configuration, submission_guard
                    models = await self.models()
                    from .credit_policy import check_credit_limits, CreditBlocked
                    limits = await self.rate_limits()
                    observed_at = time.time()
                    def check_credit():
                        # Sparse updates may revoke permission while waiting for the writer.
                        # They never renew the freshness timestamp of the full read.
                        gate = check_credit_limits(self.observed_limits, model, observed_at=observed_at)
                        if not gate['allowed']:
                            raise CreditBlocked(gate)
                    def guard():
                        return submission_guard(models, model, effort, automatic=AUTOMATIC.get(),
                                                extra_check=check_credit)
                    validate_configuration(models, model, effort, automatic=AUTOMATIC.get())
                    # Once submission is possible, never use empty-thread summary fallback.
                    self._fresh_threads.discard(thread_id)
                    result = await self.rpc.request("turn/start", {
                        "threadId": thread_id,
                        "input": [{"type": "text", "text": text}],
                        "model": model, "effort": effort,
                        "approvalPolicy": "never",
                        "sandboxPolicy": {"type": "readOnly"}}, timeout=timeout, before_send=guard)
                    turn_id = result["turn"]["id"]
                    if not isinstance(turn_id,str) or not turn_id:
                        raise ConnectionLost('Invalid acknowledged turn ID')
                    if on_started is not None:
                        on_started(turn_id)
                    control=None;checkpoint_text='';last_checkpoint=0
                    active_acknowledged=result['turn'].get('status')=='inProgress'
                    if self._pause_options is not None:
                        from .pause import TurnControl
                        options=self._pause_options
                        control=TurnControl(self,thread_id,turn_id,model,
                            stop_requested=options['stop_requested'],receipt=options['receipt'],grace=options['grace'],
                            active_target=lambda:active_acknowledged)
                    def checkpoint(text):
                        if self._pause_options and self._pause_options['checkpoint']:
                            self._pause_options['checkpoint'](text[-65536:])
                    while True:
                        if control:
                            await control.tick()
                            if control.confirm_by is not None and time.monotonic()>=control.confirm_by:
                                raise ConnectionLost('Interrupt terminal status not confirmed; reconcile saved turn')
                        try:event = await asyncio.wait_for(self.rpc.next_event(),.25) if control else await self.rpc.next_event()
                        except TimeoutError:continue
                        params = event.get("params", {})
                        if params.get("threadId") != thread_id:
                            continue
                        if event['method']=='turn/started' and params.get('turn',{}).get('id')==turn_id:
                            active_acknowledged=params['turn'].get('status')=='inProgress'
                        if event['method']=='item/agentMessage/delta' and params.get('turnId')==turn_id:
                            checkpoint_text=(checkpoint_text+str(params.get('delta','')))[-65536:]
                            if time.monotonic()-last_checkpoint>=1:
                                checkpoint(checkpoint_text);last_checkpoint=time.monotonic()
                        if event["method"] == "item/completed" and params.get("turnId") == turn_id:
                            item = params["item"]
                            if item.get("type") == "agentMessage":
                                completed_text[item["id"]] = (item.get("text", ""), item.get("phase"))
                                checkpoint_text='\n'.join(text for text,phase in completed_text.values())[-65536:]
                                checkpoint(checkpoint_text)
                        if (event["method"] == "model/rerouted"
                                and params.get("turnId") == turn_id):
                            rerouted_model = params.get("toModel")
                        if event["method"] == "turn/completed" and params["turn"]["id"] == turn_id:
                            active_acknowledged=False
                            status = params["turn"]["status"]
                            if status=='interrupted' and control and control.reason:
                                receipt={'threadId':thread_id,'turnId':turn_id,'reason':control.reason,
                                         'phase':'terminal_interrupted','terminalConfirmed':True,'at':time.time()}
                                control.receipt(receipt);checkpoint(checkpoint_text)
                                raise TurnPaused(receipt)
                            if status != "completed":
                                kind, http_status = safe_failure(params["turn"].get("error"))
                                raise TurnFailed(f"Turn {turn_id} ended with status={status}",
                                                 status=status, error_kind=kind, http_status=http_status)
                            final = [text for text, phase in completed_text.values() if phase == "final_answer"]
                            if not final:
                                final = [text for text, phase in completed_text.values() if phase != "commentary"]
                            outcome = {"turnId": turn_id, "status": status, "text": "\n".join(final)}
                            if control and control.reason:
                                receipt={'threadId':thread_id,'turnId':turn_id,'reason':control.reason,
                                         'phase':'terminal_completed','terminalConfirmed':True,'at':time.time()}
                                control.receipt(receipt);outcome['pauseReceipt']=receipt
                            if rerouted_model is not None:
                                outcome["reroutedModel"] = rerouted_model
                            return outcome
            except (TimeoutError, asyncio.CancelledError):
                if turn_id and not (control and control.interrupted):
                    with contextlib.suppress(Exception):
                        await self.rpc.request("turn/interrupt", {
                            "threadId": thread_id, "turnId": turn_id}, timeout=2)
                raise
