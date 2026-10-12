"""Durable execution through real subprocess pipes, using offline persistent history."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import pytest
from mission_control.adapter import CodexAdapter
from mission_control.managed import ManagedRunner
from mission_control.routing import Task,Mode
from mission_control.rpc import RpcClient


@pytest.mark.parametrize("scenario,expected_calls",[("normal",1),("lost_ack",1),("quota",2),("unmaterialized",1)])
def test_controller_reconnects_over_stdio_without_replaying_completed_turn(tmp_path,scenario,expected_calls):
    async def check():
        server_state=tmp_path/"server.json"
        now=[1000];sleeps=[];processes=[]
        @asynccontextmanager
        async def factory():
            command=[sys.executable,str(Path(__file__).with_name("persistent_limit_server.py")),str(server_state),scenario]
            async with RpcClient(command,timeout=3) as rpc:
                processes.append(rpc.process)
                yield CodexAdapter(rpc)
        async def sleep(seconds):
            assert all(process.returncode is not None for process in processes)
            sleeps.append(seconds);now[0]+=seconds
        engine=ManagedRunner(factory,tmp_path/"job.json",cwd=tmp_path,clock=lambda:now[0],sleep=sleep)
        result=await engine.run(Task("Return only 2",operation="text"),expected="2",mode=Mode.ECONOMY)
        assert result["stage"]=="completed"
        state=json.loads(server_state.read_text(encoding="utf-8"))
        assert state["calls"]==expected_calls
        assert state["model"]=="gpt-6-luna" and state["effort"]=="low"
        assert all(process.returncode is not None for process in processes)
        assert result["attempts"][-1]["outcome"]["text"]=="2"
        if scenario in {"lost_ack","quota"}: assert sleeps
        assert (await engine.resume())["stage"]=="completed"
        assert json.loads(server_state.read_text(encoding="utf-8"))["calls"]==expected_calls
    asyncio.run(check())


def test_resume_after_quota_uses_original_thread_and_prior_context(tmp_path):
    async def check():
        state_path=tmp_path/"server.json"
        state_path.write_text(json.dumps({"turns":[{"id":"prior","status":"completed","itemsView":"full",
            "items":[{"type":"userMessage","content":[{"type":"text","text":"Remember marker CONTEXT-914"}]},
                     {"type":"agentMessage","phase":"final_answer","text":"acknowledged"}],"error":None}],
            "model":"gpt-6-luna","effort":"low","calls":0,"threadStarts":0}),encoding="utf-8")
        now=[1000]
        @asynccontextmanager
        async def factory():
            command=[sys.executable,str(Path(__file__).with_name("persistent_limit_server.py")),str(state_path),"context"]
            async with RpcClient(command,timeout=3) as rpc: yield CodexAdapter(rpc)
        async def sleep(seconds): now[0]+=seconds
        def runner(): return ManagedRunner(factory,tmp_path/"job.json",cwd=tmp_path,clock=lambda:now[0],sleep=sleep)
        task=Task("Return only the marker remembered earlier.",operation="text")
        first=await runner().run(task,expected="CONTEXT-914",mode=Mode.ECONOMY,thread_id="wire-thread",max_wait=0)
        assert first["stage"]=="waiting_limit" and first["threadId"]=="wire-thread"
        assert first["attempts"][0]["phase"]=="quota_failed"
        second=await runner().resume()
        assert second["stage"]=="completed" and second["threadId"]=="wire-thread"
        assert second["attempts"][-1]["outcome"]["text"]=="CONTEXT-914"
        state=json.loads(state_path.read_text(encoding="utf-8"))
        assert state["threadStarts"]==0 and state["calls"]==2
        assert set(state["resumeIds"])=={"wire-thread"}
        assert state["requestThreadIds"]==["wire-thread","wire-thread"]
        assert "CONTEXT-914" not in first["attempts"][0]["prompt"]
    asyncio.run(check())


def test_new_thread_first_turn_does_not_require_persisted_full_history(tmp_path):
    async def check():
        command=[sys.executable,str(Path(__file__).with_name("persistent_limit_server.py")),str(tmp_path/"server.json"),"unmaterialized"]
        async with RpcClient(command,timeout=3) as rpc:
            adapter=CodexAdapter(rpc)
            await adapter.start_thread(tmp_path,"gpt-6-luna")
            outcome=await adapter.run_turn("wire-thread","Return 2","gpt-6-luna","low")
            assert outcome["text"]=="2"
    asyncio.run(check())
