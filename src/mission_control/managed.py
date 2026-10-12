"""Durable read-only text runs. Never infer success or replay uncertain sends."""
from __future__ import annotations
import asyncio
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
import time
import uuid

from .adapter import TurnFailed
from .execution import exact_output, thread_lease_path, timestamp
from .history import History
from .limits import LimitPolicy, check_limits, inspect_limits, number
from .routing import Task, Mode, SmartRouter, Decision, assess, RoutingBlocked
from .rpc import ConnectionLost, RpcError
from .state import state_exists, load_state, save_state, state_lock, StateError


TERMINAL = {"completed", "validation_failed", "attempts_exhausted", "needs_attention", "limits_unsupported"}
QUOTA = {"usageLimitExceeded", "rateLimitExceeded"}


class ManagedRunner:
    def __init__(self, factory, state_path: Path, *, cwd: Path, clock=time.time,
                 sleep=asyncio.sleep, stop_requested=None):
        self.factory = factory  # Async context manager yielding a fresh adapter.
        self.path = Path(state_path).resolve()
        self.cwd = Path(cwd).resolve()
        self.clock = clock
        self.sleep = sleep
        self.stop_requested = stop_requested

    def save(self, data):
        data["updatedAt"] = timestamp()
        save_state(self.path, data)

    async def run(self, task: Task, *, expected: str, mode=Mode.BALANCED,
                  policy=None, history_path=None, excluded=(), thread_id=None,
                  max_attempts=3, turn_timeout=120, max_wait=None, validation_spec=None, manual=None):
        from .safety import reject_secrets
        reject_secrets(task.text);reject_secrets(expected)
        exact_output(expected)
        if max_wait is not None and (not number(max_wait) or max_wait < 0):
            raise StateError("--max-wait must be finite and nonnegative")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 8:
            raise StateError("Attempt budget must be from 1 to 8")
        if not number(turn_timeout) or turn_timeout <= 0 or not self.cwd.is_dir():
            raise StateError("Positive timeout and existing workspace required")
        history = Path(history_path or self.cwd / ".local/router-history.json").resolve()
        if history == self.path:
            raise StateError("History and run state must differ")
        policy = policy or LimitPolicy()
        data = {"version": 1, "kind": "managed-text-run", "jobId": uuid.uuid4().hex,
                "createdAt": timestamp(), "stage": "planning", "cwd": str(self.cwd),
                "task": asdict(task), "expected": expected, "mode": Mode(mode).value,
                "policy": asdict(policy), "excluded": sorted(set(excluded)),
                "historyPath": str(history), "threadId": thread_id,
                "maxAttempts": max_attempts, "turnTimeout": turn_timeout,
                "attempts": [], "checks": 0, "backoff": 0}
        if validation_spec is not None:
            self._check_validation_spec(validation_spec)
            data["validationSpec"] = validation_spec
        if manual is not None:
            from .routing import check_manual
            check_manual(manual);data['manual']=dict(manual)
        with state_lock(self.path):
            if state_exists(self.path):
                raise StateError("State exists; use managed-resume, never overwrite a run")
            self.save(data)
            return await self._drive(data, max_wait)

    async def resume(self, *, max_wait=None):
        with state_lock(self.path):
            data = load_state(self.path)
            try:
                self._validate_state(data)
            except (KeyError, TypeError) as error:
                raise StateError("Incomplete managed journal; no inference submitted") from error
            return await self._drive(data, max_wait)

    def _validate_state(self, data):
        if (data.get("version") != 1 or data.get("kind") != "managed-text-run"
                or Path(data.get("cwd", "")).resolve() != self.cwd
                or not isinstance(data.get("attempts"), list)
                or not isinstance(data.get("jobId"), str)
                or type(data.get("maxAttempts")) is not int or not 1 <= data["maxAttempts"] <= 8
                or not number(data.get("turnTimeout")) or data["turnTimeout"] <= 0):
            raise StateError("Invalid managed state or different workspace")
        stages = TERMINAL | {"planning", "ready", "submitted", "completed_unvalidated",
                             "waiting_limit", "waiting_credit", "waiting_network", "waiting_active", "waiting_model", "waiting_approval", "auth_required"}
        phases = {"submitted", "completed_unvalidated", "validated", "escalated", "quota_failed", "auth_failed", "failed"}
        if data.get("stage") not in stages or len(data["attempts"]) > data["maxAttempts"]:
            raise StateError("Invalid managed stage or attempt count")
        for index, attempt in enumerate(data["attempts"]):
            if not isinstance(attempt, dict) or attempt.get("phase") not in phases:
                raise StateError("Invalid managed attempt phase; no replay")
            decision = attempt.get("decision")
            if (not isinstance(decision, dict) or not isinstance(decision.get("model"), str)
                    or not isinstance(decision.get("effort"), str)
                    or not isinstance(attempt.get("prompt"), str)
                    or not isinstance(attempt.get("baseline"), list)
                    or any(not isinstance(identity, str) for identity in attempt["baseline"])):
                raise StateError("Incomplete managed attempt")
            if attempt.get("turnId") is not None and (not isinstance(attempt["turnId"], str) or not attempt["turnId"]):
                raise StateError("Invalid saved turn ID")
            if attempt["phase"] in {"completed_unvalidated", "validated", "escalated"}:
                outcome = attempt.get("outcome", {})
                if not attempt.get("turnId") or outcome.get("turnId") != attempt["turnId"] or not isinstance(outcome.get("text"), str):
                    raise StateError("Incomplete completed outcome; no replay")
            if attempt["phase"] in {"validated", "escalated"} and type(attempt.get("validation", {}).get("passed")) is not bool:
                raise StateError("Incomplete saved validation")
            phase = attempt["phase"]
            if phase == "escalated" and attempt["validation"]["passed"]:
                raise StateError("Successful attempt cannot be escalated")
            if phase in {"quota_failed", "auth_failed"}:
                failure = attempt.get("failure", {})
                if failure.get("status") != "failed" or not attempt.get("turnId"):
                    raise StateError("Retry phase lacks terminal failure evidence")
                kind, http = failure.get("kind"), failure.get("httpStatus")
                quota = kind in QUOTA or http == 429
                auth = kind == "unauthorized" or http in {401, 403}
                if (phase == "quota_failed" and not quota) or (phase == "auth_failed" and not auth):
                    raise StateError("Retry phase contradicts failure category")
            if index < len(data["attempts"])-1 and phase not in {"escalated", "quota_failed", "auth_failed"}:
                raise StateError("Earlier unresolved or terminal attempt cannot be skipped")
        if data["stage"] == "completed" and (not data["attempts"] or
                data["attempts"][-1]["phase"] != "validated" or
                data["attempts"][-1]["validation"]["passed"] is not True):
            raise StateError("Completed state lacks validated success")
        if "validationSpec" in data:
            self._check_validation_spec(data["validationSpec"])
        Task(**data["task"])
        if 'manual' in data:
            from .routing import check_manual
            check_manual(data['manual'])
        exact_output(data["expected"])
        Mode(data["mode"])
        LimitPolicy(**data["policy"])
        if Path(data["historyPath"]).resolve() == self.path:
            raise StateError("History and state must differ")

    async def _drive(self, data, max_wait):
        if max_wait is not None and (not number(max_wait) or max_wait < 0):
            raise StateError("--max-wait must be a finite nonnegative duration")
        # The attempt evidence is authoritative even if the outer display stage is stale.
        if data["attempts"]:
            last = data["attempts"][-1]
            if last["phase"] == "validated" and last["validation"]["passed"]:
                data["stage"] = "completed"
                self.save(data)
            elif last["phase"] == "failed":
                data["stage"] = "needs_attention"
                self.save(data)
        deadline = None if max_wait is None else self.clock() + max_wait
        with ExitStack() as claims:
            claimed = None
            def claim_thread(thread_id):
                nonlocal claimed
                if claimed is None:
                    claims.enter_context(state_lock(thread_lease_path(self.cwd, thread_id)))
                    claimed = thread_id
                elif claimed != thread_id:
                    raise StateError("Run attempted to change thread identity")
            while data["stage"] not in TERMINAL:
                unresolved = data["attempts"] and data["attempts"][-1]["phase"] in {"submitted", "completed_unvalidated"}
                if self.stop_requested and self.stop_requested() and not unresolved:
                    return data
                thread = data.get("threadId")
                if thread:
                    claim_thread(thread)
                target = data.get("nextCheckAt")
                if number(target) and target > self.clock():
                    delay = target - self.clock()
                    if deadline is not None:
                        delay = min(delay, max(0, deadline-self.clock()))
                        if delay <= 0:
                            return data
                    await self.sleep(min(delay, 30) if self.stop_requested else delay)
                    if self.stop_requested and self.stop_requested():
                        return data
                    if self.clock() < target:
                        if deadline is not None and self.clock() >= deadline:
                            return data
                        continue
                data.pop("nextCheckAt", None)
                # A completed response with verified configuration can be checked locally.
                # Approval waits must not keep App Server alive or spend quota.
                last=data['attempts'][-1] if data['attempts'] else None
                if last and last['phase']=='completed_unvalidated' and last.get('effectiveConfiguration'):
                    await self._validate(data,None,last)
                    if data['stage']=='waiting_approval':return data
                    continue
                try:
                    async with self.factory() as adapter:
                        await self._step(data, adapter, claim_thread)
                except (ConnectionLost, TimeoutError, OSError):
                    self._schedule(data, "waiting_network", network=True)
                except RpcError as error:
                    if error.code == -32601:
                        data["stage"] = "limits_unsupported"
                        data["stopReason"] = "Required App Server method unsupported"
                    else:
                        data["stage"] = "needs_attention"
                        data["stopReason"] = "RPC failure; no inference retry"
                    self.save(data)
                except (TurnFailed, RoutingBlocked) as error:
                    data["stage"] = "needs_attention"
                    data["stopReason"] = "Thread/configuration not safe for submission"
                    self.save(data)
                if data["stage"] in {"auth_required","waiting_approval","waiting_credit"}:
                    return data
            return data

    def _schedule(self, data, stage, *, wake=None, network=False):
        count = data.get("backoff", 0)
        base = 30 if network else 300
        delay = min(3600, base * 2**min(count, 7))
        data["backoff"] = count + 1
        data["stage"] = stage
        data["nextCheckAt"] = wake if number(wake) and wake > self.clock() else self.clock()+delay
        self.save(data)

    def _decision(self, data):
        value = data["decision"]
        return Decision(value["model"], value["effort"], assess(Task(**data["task"])),
                        Mode(data["mode"]), value["reason"], value["profileSource"], value["limitsKnown"])

    def _router(self, data):
        with state_lock(Path(data["historyPath"])):
            history = History.load(Path(data["historyPath"]))
        return SmartRouter(history=history, excluded=set(data["excluded"]))

    async def _step(self, data, adapter, claim_thread):
        account = await adapter.account()
        if account.get("requiresOpenaiAuth") and not account.get("type"):
            data["stage"] = "auth_required"
            data["stopReason"] = "Codex login required; repair auth then managed-resume"
            self.save(data)
            return
        if data["stage"] == "auth_required":
            data["stage"] = "ready"
        last = data["attempts"][-1] if data["attempts"] else None
        if last and last["phase"] == "submitted":
            await self._reconcile(data, adapter, last)
            return
        if last and last["phase"] == "completed_unvalidated":
            await self._validate(data, adapter, last)
            return
        if len(data["attempts"]) >= data["maxAttempts"]:
            data["stage"] = "attempts_exhausted"
            self.save(data)
            return
        models = await adapter.models()
        limits = await adapter.rate_limits()  # Always full read before new inference.
        data["checks"] += 1
        data["limits"] = inspect_limits(limits)
        data['limitsObservedAt']=self.clock()
        router = self._router(data)
        if "decision" not in data:
            # Preserve preferred configuration even if its quota is currently exhausted.
            try:
                if 'manual' in data:
                    from .routing import manual_decision
                    selected=manual_decision(Task(**data['task']),models,data['manual'],data['mode'])
                else:selected=router.choose(Task(**data["task"]), models, Mode(data["mode"]))
                data['decision']=selected.to_dict()
            except RoutingBlocked:
                self._schedule(data,"waiting_model")
                return
            self.save(data)
        decision = self._decision(data)
        if last and last["phase"] == "validated" and not last["validation"]["passed"]:
            if 'manual' in data:
                data['stage']='validation_failed';self.save(data);return
            visited={(item["decision"]["model"],item["decision"]["effort"]) for item in data["attempts"]}
            raised=any(item["decision"]["model"]==decision.model and item["decision"]["effort"] != decision.effort for item in data["attempts"])
            # Escalation itself must also wait for quota; use the full catalog first.
            next_decision=router.escalate(decision,models,visited,effort_raised=raised)
            if next_decision is None:
                data["stage"]="validation_failed"
                self.save(data)
                return
            decision=next_decision
            data["decision"]=decision.to_dict()
            last["phase"]="escalated"
            self.save(data)
        if hasattr(adapter, 'credit_gate'):
            credit_gate = await adapter.credit_gate(decision.model, limits=limits)
            if not credit_gate['allowed']:
                self._credit_wait(data, credit_gate)
                return
        gate=check_limits(limits,decision.model,now=self.clock(),policy=LimitPolicy(**data["policy"]),failures=data["backoff"])
        if not gate["allowed"]:
            data["waitReason"]=gate["reason"]
            self._schedule(data,"waiting_limit",wake=gate["wakeAt"])
            return
        supported=next((entry for entry in models if entry.get("model")==decision.model),None)
        if (not supported or supported.get("hidden") or decision.effort not in {
                option.get("reasoningEffort") for option in supported.get("supportedReasoningEfforts",[])}):
            self._schedule(data,"waiting_model")
            return
        from .model_policy import validate_configuration, PolicyBlocked, submission_mode
        try:
            validate_configuration(models, decision.model, decision.effort, automatic='manual' not in data)
        except PolicyBlocked as error:
            data['stage']='needs_attention'
            data['stopReason']=str(error)
            self.save(data)
            return
        if self.stop_requested and self.stop_requested():
            return
        created = not data.get("threadId")
        if created:
            result=await adapter.start_thread(self.cwd,decision.model)
            if result.get("model") != decision.model:
                raise RoutingBlocked("Thread model differs")
            data["threadId"]=result["thread"]["id"]
            self.save(data)
            # Empty Codex threads are not resumable after their owning process exits.
            # Claim immediately and keep this adapter alive through the first turn.
            claim_thread(data["threadId"])
        else:
            result=await adapter.resume_thread(data["threadId"],self.cwd,decision.model)
        if result.get("model") != decision.model or result.get("thread",{}).get("id") != data["threadId"]:
            raise RoutingBlocked("Resumed thread/configuration differs")
        thread=await adapter.read_thread(data["threadId"])
        await adapter.assert_idle(data["threadId"])
        if self.stop_requested and self.stop_requested():
            if created:
                # Proven never submitted: no conversation history exists to preserve.
                data["unusedEmptyThreadId"]=data.pop("threadId")
                self.save(data)
            return
        prompt=self._prompt(data)
        from .safety import reject_secrets
        reject_secrets(prompt)
        attempt={"decision":decision.to_dict(),"phase":"submitted","prompt":prompt,
                 "baseline":[t["id"] for t in thread["turns"]],"submittedAt":timestamp()}
        data["attempts"].append(attempt)
        data["stage"]="submitted"
        data["backoff"]=0
        self.save(data)  # Before turn/start; crash here must not lead to a blind resend.
        def acknowledged(turn_id):
            attempt["turnId"]=turn_id
            self.save(data)
        from .credit_policy import CreditBlocked
        try:
            with submission_mode('manual' not in data):
                outcome=await adapter.run_turn(data["threadId"],prompt,decision.model,decision.effort,
                                              timeout=data["turnTimeout"],on_started=acknowledged)
        except CreditBlocked as error:
            # Only the adapter's explicit pre-write rejection permits removing this attempt.
            data['preSendRejection']={'at':timestamp(), 'decision':attempt['decision'],
                                      'status':'not_started', 'reason':error.gate['reason']}
            data['attempts'].pop()
            if created:
                data['unusedEmptyThreadId']=data.pop('threadId')
            self._credit_wait(data, error.gate)
            return
        except PolicyBlocked as error:
            # Explicit adapter guarantee: no bytes for turn/start were sent.
            attempt['phase']='failed'
            attempt['failure']={'kind':'modelPolicy', 'status':'not_started', 'httpStatus':None}
            data['stage']='needs_attention';data['stopReason']=str(error)
            if created:
                data['unusedEmptyThreadId']=data.pop('threadId')
            self.save(data)
            return
        except TurnFailed as error:
            self._failed(data,attempt,error.error_kind,error.http_status,error.status)
            return
        if not self._accept_outcome(data,attempt,outcome):return
        attempt["phase"]="completed_unvalidated"
        data["stage"]="completed_unvalidated"
        self.save(data)
        # Confirm retained configuration while this process still owns the writer.
        # Durable completed_unvalidated remains recoverable if validation crashes.
        await self._validate(data,adapter,attempt)

    def _credit_wait(self, data, gate):
        data['creditGate']=gate
        data['waitReason']=gate['reason']
        self._schedule(data, 'waiting_credit', wake=gate['wakeAt'])

    def _failed(self,data,attempt,kind,http,status):
        attempt["failure"]={"kind":kind,"httpStatus":http,"status":status}
        if status=="failed" and (kind in QUOTA or http==429):
            attempt["phase"]="quota_failed"
            if len(data["attempts"]) >= data["maxAttempts"]:
                data["stage"]="attempts_exhausted"
                self.save(data)
            else:
                self._schedule(data,"waiting_limit")
        elif status=="failed" and (kind=="unauthorized" or http in {401,403}):
            attempt["phase"]="auth_failed"
            data["stage"]="auth_required"
            self.save(data)
        else:
            attempt["phase"]="failed"
            data["stage"]="needs_attention"
            data["stopReason"]="Known non-quota failure/interruption; no automatic resend"
            self.save(data)

    async def _reconcile(self,data,adapter,attempt):
        thread=await adapter.read_thread(data["threadId"])
        turns=thread["turns"]
        turn_id=attempt.get("turnId")
        if turn_id:
            matches=[turn for turn in turns if turn["id"]==turn_id]
        else:
            added=[turn for turn in turns if turn["id"] not in attempt["baseline"]]
            matches=[turn for turn in added if any(
                item.get("type")=="userMessage" and item.get("content")==[{"type":"text","text":attempt["prompt"]}]
                for item in turn["items"])] if len(added)==1 else []
        if len(matches)!=1:
            data["stage"]="needs_attention"
            data["stopReason"]="Submission outcome cannot be identified; never resend"
            self.save(data)
            return
        turn=matches[0]
        attempt["turnId"]=turn["id"]
        if turn["status"]=="inProgress":
            self._schedule(data,"waiting_active",network=True)
            return
        if turn["status"]!="completed":
            failure=turn.get("failure",{})
            self._failed(data,attempt,failure.get("kind","unknown"),failure.get("httpStatus"),turn["status"])
            return
        if turn.get("itemsView")!="full":
            data["stage"]="needs_attention"
            data["stopReason"]="Full completed turn items unavailable; no resend"
            self.save(data)
            return
        messages=[item for item in turn["items"] if item.get("type")=="agentMessage"]
        final=[item.get("text","") for item in messages if item.get("phase")=="final_answer"]
        if not final:
            final=[item.get("text","") for item in messages if item.get("phase")!="commentary"]
        if not self._accept_outcome(data,attempt,{"turnId":turn["id"],"status":"completed","text":"\n".join(final)}):return
        attempt["phase"]="completed_unvalidated"
        data["stage"]="completed_unvalidated"
        self.save(data)

    def _accept_outcome(self,data,attempt,outcome):
        from .safety import redact
        text=outcome['text']
        if redact(text)!=text:
            # Preserve identity/evidence without persisting the newly disclosed secret.
            attempt['outcome']={**outcome,'text':'[REDACTED: possible secret in model output]'}
            attempt['phase']='failed'
            data['stage']='needs_attention'
            data['stopReason']='Possible secret in model output; remove sensitive context, no automatic retry'
            self.save(data)
            return False
        attempt['outcome']=outcome
        return True

    async def _validate(self,data,adapter,attempt):
        decision=attempt["decision"]
        configured=attempt.get('effectiveConfiguration')
        if configured is None:
            configured=await adapter.configuration(data["threadId"])
        if (configured.get("model") != decision["model"] or configured.get("reasoningEffort") != decision["effort"]
                or attempt["outcome"].get("reroutedModel") not in {None,decision["model"]}):
            raise RoutingBlocked("Retained model/effort differs from selected configuration")
        attempt['effectiveConfiguration']=configured
        self.save(data)
        result=await self._validation(data,attempt)
        if result['kind']=='execution_approval_required':
            data['stage']='waiting_approval'
            self.save(data)
            return
        history_path=Path(data["historyPath"])
        with state_lock(history_path):
            history=History.load(history_path)
            history.record_once(data["jobId"]+":"+attempt["turnId"],decision["model"],decision["effort"],
                                decision["complexity"],result["passed"])
            history.save(history_path)
        attempt["validation"]=result
        attempt["effectiveConfiguration"]=configured
        attempt["phase"]="validated"
        data["stage"]="completed" if result["passed"] else "validation_failed" if result["kind"]=="not_retryable" else "ready"
        data["backoff"]=0
        self.save(data)

    def _check_validation_spec(self, spec):
        raise StateError("Project validation requires ProjectRunner; no text fallback")

    def _prompt(self, data):
        prompt=data["task"]["text"]
        if any("validation" in a and not a["validation"]["passed"] for a in data["attempts"]):
            prompt+="\n\nPrevious attempt failed local exact-output validation. Return only the requested answer."
        return prompt

    async def _validation(self, data, attempt):
        result=exact_output(data["expected"])(attempt["outcome"]["text"])
        return {"passed":result.passed,"kind":result.kind}
