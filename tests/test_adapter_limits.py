"""Offline protocol checks for durable turn tracking."""
import asyncio
from pathlib import Path
import sys
import pytest
from mission_control.adapter import CodexAdapter
from mission_control.rpc import RpcClient
from mission_control.history import History
from mission_control.routing import Complexity


def test_turn_ack_is_persistable_before_outcome_and_history_is_sanitized():
    async def check():
        command=[sys.executable,str(Path(__file__).with_name("fake_server.py")),"limits_wire"]
        async with RpcClient(command) as rpc:
            adapter=CodexAdapter(rpc)
            saved=[]
            outcome=await adapter.run_turn("thread-1","task","first","low",on_started=saved.append)
            assert saved == ["turn-1"] and outcome["turnId"] == "turn-1"
            history=await adapter.read_thread("thread-1")
            assert history["turns"][0]["items"][0]["text"] == "Привет ✓"
            assert "SECRET" not in str(history)
            assert adapter.observed_limits["rateLimitsByLimitId"]["codex"]["primary"]["usedPercent"] == 23
    asyncio.run(check())


def test_idempotent_history_survives_crash_between_history_and_journal(tmp_path):
    path=tmp_path/"history.json"
    history=History()
    history.record_once("job:turn", "model","low",Complexity.LOW,True)
    history.save(path)
    history=History.load(path)
    history.record_once("job:turn", "model","low",Complexity.LOW,True)
    assert history.count("model","low",Complexity.LOW) == (1,0)
