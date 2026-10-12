"""Executor tests use an explicitly local adapter; no inference or fabricated telemetry."""
import asyncio
from pathlib import Path

import pytest

from mission_control.adapter import TurnFailed
from mission_control.execution import RoutedExecutor, Validation, exact_output
from mission_control.routing import Task, SmartRouter, RoutingBlocked, Mode
from mission_control.rpc import ConnectionLost, RpcError
from mission_control.state import load_state
from test_routing import catalog


class LocalAdapter:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.calls = []
        self.configuration_value = {}
        self.limit_value = None

    async def models(self):
        return catalog()

    async def rate_limits(self):
        return self.limit_value

    async def start_thread(self, cwd, model):
        self.calls.append(("start", model))
        return {"thread": {"id": "local-test-thread"}, "model": model}

    async def resume_thread(self, thread_id, cwd, model):
        self.calls.append(("resume", model))
        return {"thread": {"id": thread_id}, "model": model}

    async def configuration(self, thread_id):
        return self.configuration_value

    async def run_turn(self, thread_id, text, model, effort, *, timeout):
        self.calls.append(("turn", model, effort, text, thread_id))
        self.configuration_value = {"model": model, "reasoningEffort": effort}
        result = next(self.outcomes)
        if isinstance(result, BaseException):
            raise result
        return {"turnId": str(len(self.calls)), "status": "completed", "text": result}

def run(coro):
    return asyncio.run(coro)

def test_validation_drives_effort_then_model_and_sends_feedback(tmp_path):
    adapter = LocalAdapter(["wrong one", "wrong two", "2"])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    result = run(engine.run(Task("Return only 2", operation="text"), Mode.ECONOMY,
                            validator=exact_output("2")))
    turns = [call for call in adapter.calls if call[0] == "turn"]
    assert [(call[1], call[2]) for call in turns] == [
        ("gpt-6-luna", "low"), ("gpt-6-luna", "medium"), ("gpt-6.1-sol", "medium")]
    assert "validation" in turns[1][3].lower()
    assert all(call[4] == "local-test-thread" for call in turns)
    assert result["stage"] == "completed"
    assert len(result["attempts"]) == 3
    assert engine.router.history.count("gpt-6-luna", "low", engine.router.choose(
        Task("format"), catalog()).assessment.complexity) == (0, 1)
    with pytest.raises(RoutingBlocked):
        run(engine.run(Task("format"), validator=exact_output("2")))
    assert len([call for call in adapter.calls if call[0] == "turn"]) == 3

@pytest.mark.parametrize("error", [
    ConnectionLost("gone"), TimeoutError(), RpcError("turn/start", -32602),
    TurnFailed("safe", status="failed", error_kind="unauthorized"),
    TurnFailed("safe", status="failed", error_kind="usageLimitExceeded"),
    TurnFailed("safe", status="failed", error_kind="responseStreamDisconnected"),
    TurnFailed("safe", status="interrupted"),
])
def test_infrastructure_errors_never_raise_model_power_or_retry(tmp_path, error):
    adapter = LocalAdapter([error, "2"])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    with pytest.raises(type(error)):
        run(engine.run(Task("format"), validator=exact_output("2")))
    assert len([call for call in adapter.calls if call[0] == "turn"]) == 1
    assert engine.router.history.records == {}
    assert load_state(tmp_path / "run.json")["stage"] in {"stopped", "outcome_unknown"}

def test_max_attempts_caps_bad_results_and_preserves_completed_output(tmp_path):
    adapter = LocalAdapter(["wrong"] * 8)
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    result = run(engine.run(Task("format"), validator=exact_output("2"), max_attempts=2))
    assert result["stage"] == "validation_failed"
    assert len(result["attempts"]) == 2
    assert result["attempts"][-1]["outcome"]["text"] == "wrong"

def test_validator_exception_does_not_repeat_completed_turn(tmp_path):
    adapter = LocalAdapter(["2", "2"])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    def broken(text):
        raise RuntimeError("local validator broke")
    with pytest.raises(RuntimeError):
        run(engine.run(Task("format"), validator=broken))
    assert len([call for call in adapter.calls if call[0] == "turn"]) == 1
    assert load_state(tmp_path / "run.json")["stage"] == "completed_unvalidated"

def test_explicit_existing_thread_is_used_and_history_persists(tmp_path):
    adapter = LocalAdapter(["2"])
    history_path = tmp_path / "history.json"
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json",
                            cwd=tmp_path, history_path=history_path)
    result = run(engine.run(Task("format"), validator=exact_output("2"),
                            thread_id="existing-thread"))
    assert result["threadId"] == "existing-thread"
    assert ("resume", "gpt-6-luna") in adapter.calls
    assert load_state(history_path)["records"]

def test_live_limits_are_rechecked_before_escalation(tmp_path):
    adapter = LocalAdapter(["wrong", "2"])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    def validator(text):
        adapter.limit_value = {"ordinaryUsageAllowed": False}
        return Validation(False, feedback="test did not pass")
    with pytest.raises(RoutingBlocked):
        run(engine.run(Task("format"), validator=validator))
    assert len([call for call in adapter.calls if call[0] == "turn"]) == 1

def test_effective_model_mismatch_is_not_recorded_as_success(tmp_path):
    class Mismatch(LocalAdapter):
        async def configuration(self, thread_id):
            return {"model": "different", "reasoningEffort": "low"}
    adapter = Mismatch(["2", "2"])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    with pytest.raises(RoutingBlocked):
        run(engine.run(Task("format"), validator=exact_output("2")))
    assert engine.router.history.records == {}

@pytest.mark.parametrize("maximum", [0, -1, 9, True])
def test_invalid_attempt_budget_is_rejected_before_inference(tmp_path, maximum):
    adapter = LocalAdapter([])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    with pytest.raises(ValueError):
        run(engine.run(Task("format"), validator=exact_output("2"), max_attempts=maximum))
    assert adapter.calls == []

def test_irrecoverable_validation_does_not_escalate(tmp_path):
    adapter = LocalAdapter(["wrong", "2"])
    engine = RoutedExecutor(adapter, SmartRouter(), tmp_path / "run.json", cwd=tmp_path)
    result = run(engine.run(Task("format"), validator=lambda text:
                            Validation(False, kind="not_retryable", feedback="needs user decision")))
    assert result["stage"] == "validation_failed"
    assert len(result["attempts"]) == 1
