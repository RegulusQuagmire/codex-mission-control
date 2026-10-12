"""Real NDJSON subprocess boundary with explicitly synthetic offline server."""
import asyncio
import json
from pathlib import Path
import sys

import pytest

from mission_control.adapter import CodexAdapter, TurnFailed, safe_failure
from mission_control.rpc import RpcClient
from mission_control.routing import SmartRouter, Task, Mode


def test_router_selection_crosses_stdio_and_configuration_is_observed():
    async def check():
        command = [sys.executable, str(Path(__file__).with_name("fake_server.py")), "wire"]
        async with RpcClient(command) as rpc:
            adapter = CodexAdapter(rpc)
            models = await adapter.models()
            router = SmartRouter(profiles={"first": 0, "second": 1})
            task = Task("Return the selected configuration", operation="text")
            first = router.choose(task, models, Mode.ECONOMY)
            second = router.choose(task, models, Mode.QUALITY)
            assert first.model != second.model
            await adapter.start_thread(Path.cwd(), first.model)
            for decision in (first, second):
                outcome = await adapter.run_turn("thread-1", task.text, decision.model, decision.effort)
                wire = json.loads(outcome["text"])
                assert wire == {"model": decision.model, "effort": decision.effort}
                assert await adapter.configuration("thread-1") == {
                    "model": decision.model, "reasoningEffort": decision.effort}
    asyncio.run(check())

@pytest.mark.parametrize("info,expected", [
    ("unauthorized", ("unauthorized", None)),
    ("usageLimitExceeded", ("usageLimitExceeded", None)),
    ({"httpConnectionFailed": {"httpStatusCode": 401}}, ("httpConnectionFailed", 401)),
    ({"responseStreamDisconnected": {"httpStatusCode": 503}}, ("responseStreamDisconnected", 503)),
    ("SECRET_UNKNOWN", ("unknown", None)),
    ({"SECRET_UNKNOWN": "PRIVATE"}, ("unknown", None)),
    (None, ("unknown", None)),
])
def test_error_classification_never_uses_arbitrary_messages(info, expected):
    assert safe_failure({"codexErrorInfo": info, "message": "PRIVATE"}) == expected

def test_structured_failure_arrives_through_protocol_without_secret():
    async def check():
        command = [sys.executable, str(Path(__file__).with_name("fake_server.py")), "classified"]
        async with RpcClient(command) as rpc:
            with pytest.raises(TurnFailed) as error:
                await CodexAdapter(rpc).run_turn("thread-1", "text", "first", "low")
            assert error.value.error_kind == "unauthorized"
            assert error.value.status == "failed"
            assert "SECRET" not in str(error.value)
    asyncio.run(check())

@pytest.mark.parametrize("scenario", ["active_status", "active_turn", "missing_status"])
def test_existing_active_or_unknown_thread_never_receives_resume_turn_or_interrupt(scenario):
    async def check():
        command = [sys.executable, str(Path(__file__).with_name("fake_server.py")), scenario]
        async with RpcClient(command) as rpc:
            adapter = CodexAdapter(rpc)
            with pytest.raises(TurnFailed, match="not idle"):
                await adapter.resume_thread("thread-1", Path.cwd(), "first")
            with pytest.raises(TurnFailed, match="not idle"):
                await adapter.run_turn("thread-1", "Do not inject this", "first", "low")
            counters = await rpc.request("test/counters")
            assert counters == {"resume": 0, "turn": 0, "interrupt": 0}
    asyncio.run(check())
