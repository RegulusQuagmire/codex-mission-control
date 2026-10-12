import asyncio
import json
from pathlib import Path
import sys

import pytest

from mission_control.rpc import RpcClient, RpcError, ConnectionLost
from mission_control.adapter import CodexAdapter, TurnFailed
from mission_control.state import save_state, load_state

SERVER = Path(__file__).with_name("fake_server.py")

def client(scenario="normal", timeout=2):
    return RpcClient([sys.executable, str(SERVER), scenario], timeout=timeout)

def run(coro):
    return asyncio.run(coro)

def test_handshake_and_unicode_roundtrip():
    async def check():
        async with client() as rpc:
            assert rpc.initialization["platformOs"] == "windows"
            result = await rpc.request("echo", {"text": "Задание ✓"})
            assert result == {"text": "Задание ✓"}
        assert rpc.process.returncode is not None
    run(check())

def test_pagination_and_redacted_account():
    async def check():
        async with client('unknown_limits') as rpc:
            adapter = CodexAdapter(rpc)
            assert [m["model"] for m in await adapter.models()] == ["first", "second"]
            info = await adapter.account()
            assert info == {"type": "chatgpt", "planType": "plus", "requiresOpenaiAuth": True}
            assert "private" not in json.dumps(info)
            assert await adapter.rate_limits() == {"rateLimits": None, "rateLimitsByLimitId": None}
    run(check())

def test_repeated_pagination_cursor_fails():
    async def check():
        async with client("cycle") as rpc:
            with pytest.raises(ConnectionLost, match="cursor"):
                await CodexAdapter(rpc).models()
    run(check())

@pytest.mark.parametrize("scenario", ["normal", "stderr"])
def test_events_before_response_and_stderr_drain(scenario):
    async def check():
        async with client(scenario) as rpc:
            adapter = CodexAdapter(rpc)
            thread = await adapter.start_thread(Path.cwd(), "first")
            assert thread["thread"]["id"] == "thread-1"
            resumed = await adapter.resume_thread("thread-1", Path.cwd(), "first")
            assert resumed["thread"]["id"] == "thread-1"
            result = await adapter.run_turn("thread-1", "Reply only", "first", "low", timeout=3)
            assert result == {"turnId": "turn-1", "status": "completed", "text": "Привет ✓"}
    run(check())

def test_failed_turn_is_not_success_or_secret_output():
    async def check():
        async with client("failed") as rpc:
            with pytest.raises(TurnFailed) as error:
                await CodexAdapter(rpc).run_turn("thread-1", "test", "first", "low")
            assert "SECRET" not in str(error.value)
    run(check())

def test_rpc_errors_preserve_code_without_server_secret():
    async def check():
        async with client("error") as rpc:
            with pytest.raises(RpcError) as error:
                await rpc.request("test")
            assert error.value.code == -32602
            assert "SECRET" not in str(error.value)
    run(check())

@pytest.mark.parametrize("scenario", ["exit", "malformed"])
def test_transport_failure_unblocks_pending_request(scenario):
    async def check():
        async with client(scenario) as rpc:
            with pytest.raises(ConnectionLost):
                await rpc.request("test")
    run(check())

def test_timeout_and_process_cleanup():
    async def check():
        rpc = client("hang")
        async with rpc:
            with pytest.raises(TimeoutError):
                await rpc.request("test", timeout=0.2)
            assert not rpc.pending
        assert rpc.process.returncode is not None
    run(check())

def test_server_approval_request_is_refused():
    async def check():
        async with client("approval") as rpc:
            await rpc.request("test")
            event = await asyncio.wait_for(rpc.next_event(), 2)
            assert event["method"] == "approval/refused"
    run(check())

def test_atomic_state_preserves_unicode_and_replaces(tmp_path):
    path = tmp_path / "state.json"
    save_state(path, {"threadId": "a", "text": "тест"})
    assert load_state(path)["text"] == "тест"
    save_state(path, {"threadId": "b"})
    assert load_state(path) == {"threadId": "b"}
    assert list(tmp_path.iterdir()) == [path]



def test_rpc_timeout_includes_waiting_for_write_lock():
    async def check():
        async with client() as rpc:
            await rpc._write_lock.acquire()
            task = asyncio.create_task(rpc.request("echo", timeout=0.05))
            try:
                await asyncio.sleep(0.2)
                assert task.done(), "RPC timeout did not cover blocked send"
                with pytest.raises(TimeoutError):
                    await task
                assert not rpc.pending
            finally:
                rpc._write_lock.release()
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    run(check())


def test_state_lock_excludes_another_process_and_releases(tmp_path):
    import subprocess
    from mission_control import state
    assert hasattr(state, "state_lock"), "State has no exclusive claim"
    path = tmp_path / "state.json"
    script = (
        "from pathlib import Path; from mission_control.state import state_lock; "
        "import sys; "
        "\ntry:\n with state_lock(Path(sys.argv[1])): pass"
        "\nexcept ValueError: sys.exit(42)"
    )
    import os
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "src"))
    command = [sys.executable, "-c", script, str(path)]
    with state.state_lock(path):
        result = subprocess.run(command, env=environment, capture_output=True, timeout=5)
        assert result.returncode == 42
    result = subprocess.run(command, env=environment, capture_output=True, timeout=5)
    assert result.returncode == 0
