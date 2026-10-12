"""Persistent offline service and virtual time exercise the durable controller."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import pytest
from mission_control.managed import ManagedRunner
from mission_control.adapter import TurnFailed
from mission_control.rpc import ConnectionLost
from mission_control.routing import Task, Mode
from mission_control.state import load_state, save_state
from mission_control.history import History
from test_limits import snapshot, window
from test_routing import catalog


class Service:
    def __init__(self):
        self.now=1000
        self.limits=snapshot(window(10))
        self.turns=[]
        self.connected=0
        self.sleeps=[]
        self.submissions=[]
        self.config={}
        self.outcomes=["2"]
        self.drop_ack=False
        self.lose=False
        self.auth=True
        self.on_sleep=None
        self.metadata_errors=0

    @asynccontextmanager
    async def factory(self):
        self.connected+=1
        try: yield self
        finally: self.connected-=1

    async def sleep(self,seconds):
        assert self.connected == 0, "App Server must be closed during quota waiting"
        self.sleeps.append(seconds)
        self.now+=seconds
        if self.on_sleep: self.on_sleep()

    async def account(self):
        if self.metadata_errors:
            self.metadata_errors-=1
            raise ConnectionLost("network")
        return {"type":"chatgpt" if self.auth else None,"requiresOpenaiAuth":True}

    async def models(self): return catalog()
    async def rate_limits(self): return deepcopy(self.limits)
    async def start_thread(self,cwd,model):
        return {"thread":{"id":"thread"},"model":model}
    async def resume_thread(self,thread_id,cwd,model):
        await self.assert_idle(thread_id)
        return {"thread":{"id":thread_id},"model":model}
    async def assert_idle(self,thread_id):
        if any(t["status"]=="inProgress" for t in self.turns):
            raise TurnFailed("active",status="not_started",error_kind="activeOrUnknownThread")
    async def read_thread(self,thread_id):
        return {"id":thread_id,"status":{"type":"active" if any(t["status"]=="inProgress" for t in self.turns) else "idle"},"turns":deepcopy(self.turns)}
    async def configuration(self,thread_id): return self.config.copy()
    async def run_turn(self,thread_id,text,model,effort,*,timeout,on_started):
        self.submissions.append((thread_id,text,model,effort))
        tid=str(len(self.turns)+1)
        outcome=self.outcomes.pop(0)
        turn={"id":tid,"status":"completed","itemsView":"full","items":[
            {"type":"userMessage","content":[{"type":"text","text":text}]},
            {"type":"agentMessage","phase":"final_answer","text":outcome if isinstance(outcome,str) else ""}],
            "failure":{"kind":"unknown","httpStatus":None}}
        self.config={"model":model,"reasoningEffort":effort}
        if isinstance(outcome,TurnFailed):
            turn["status"]="failed"
            turn["failure"]={"kind":outcome.error_kind,"httpStatus":outcome.http_status}
        self.turns.append(turn)
        if not self.drop_ack: on_started(tid)
        if self.lose or self.drop_ack:
            self.lose=self.drop_ack=False
            raise ConnectionLost("lost response")
        if isinstance(outcome,BaseException): raise outcome
        return {"turnId":tid,"status":"completed","text":outcome}


def engine(tmp_path,service):
    return ManagedRunner(service.factory,tmp_path/"job.json",cwd=tmp_path,
                         clock=lambda:service.now,sleep=service.sleep)


def start(tmp_path,service,**kwargs):
    return asyncio.run(engine(tmp_path,service).run(Task("Return only 2",operation="text"),
          expected="2",mode=Mode.ECONOMY,history_path=tmp_path/"history.json",**kwargs))


def test_quota_wait_preserves_config_and_runs_once_after_both_reset(tmp_path):
    s=Service();s.limits=snapshot(window(100,300,1200),window(100,10080,1500))
    s.on_sleep=lambda:setattr(s,"limits",snapshot(window(0),window(0,10080,9000)))
    result=start(tmp_path,s)
    assert result["stage"]=="completed" and s.sleeps==[505]
    assert [(t[2],t[3]) for t in s.submissions]==[("gpt-6-luna","low")]
    assert result["attempts"][0]["turnId"]=="1"


def test_unknown_reset_backoff_and_pause_can_resume_without_task_input(tmp_path):
    s=Service();s.limits=snapshot(window(100,reset=None))
    result=start(tmp_path,s,max_wait=301)
    assert result["stage"]=="waiting_limit" and len(s.sleeps)==2
    assert s.submissions==[]
    saved=load_state(tmp_path/"job.json")
    assert saved["task"]["text"]=="Return only 2" and saved["expected"]=="2"
    s.limits=snapshot(window(1));s.now=saved["nextCheckAt"]
    result=asyncio.run(engine(tmp_path,s).resume(max_wait=0))
    assert result["stage"]=="completed" and len(s.submissions)==1


@pytest.mark.parametrize("drop_ack",[False,True])
def test_lost_response_recovers_completed_turn_without_resending(tmp_path,drop_ack):
    s=Service();s.drop_ack=drop_ack;s.lose=not drop_ack
    result=start(tmp_path,s)
    assert result["stage"]=="completed" and len(s.submissions)==1
    again=asyncio.run(engine(tmp_path,s).resume())
    assert again["stage"]=="completed" and len(s.submissions)==1
    assert list(History.load(tmp_path/"history.json").records.values())==[{"success":1,"failure":0}]


def test_explicit_failed_quota_waits_and_retries_same_model_not_stronger(tmp_path):
    s=Service();s.outcomes=[TurnFailed("quota",error_kind="usageLimitExceeded"),"2"]
    s.on_sleep=lambda:setattr(s,"limits",snapshot(window(0)))
    result=start(tmp_path,s)
    assert result["stage"]=="completed" and len(s.sleeps)==1
    assert [(t[2],t[3]) for t in s.submissions]==[("gpt-6-luna","low")]*2
    assert list(History.load(tmp_path/"history.json").records.values())==[{"success":1,"failure":0}]


def test_metadata_network_errors_backoff_without_inference(tmp_path):
    s=Service();s.metadata_errors=2
    result=start(tmp_path,s)
    assert result["stage"]=="completed" and s.sleeps==[30,60] and len(s.submissions)==1


def test_auth_failure_stops_and_can_resume_after_login(tmp_path):
    s=Service();s.auth=False
    result=start(tmp_path,s)
    assert result["stage"]=="auth_required" and not s.submissions and not s.sleeps
    s.auth=True
    result=asyncio.run(engine(tmp_path,s).resume())
    assert result["stage"]=="completed"


def test_uncertain_send_with_no_server_evidence_never_replays(tmp_path):
    s=Service();s.lose=True
    start(tmp_path,s,max_wait=0)
    data=load_state(tmp_path/"job.json")
    data["attempts"][-1].pop("turnId",None)
    data["stage"]="submitted"
    save_state(tmp_path/"job.json",data);s.turns=[]
    result=asyncio.run(engine(tmp_path,s).resume())
    assert result["stage"]=="needs_attention" and len(s.submissions)==1


def test_active_turn_is_observed_until_completion_without_new_send(tmp_path):
    s=Service();s.lose=True
    start(tmp_path,s,max_wait=0)
    data=load_state(tmp_path/"job.json");data["stage"]="submitted";data.pop("nextCheckAt",None)
    save_state(tmp_path/"job.json",data);s.turns[0]["status"]="inProgress"
    s.on_sleep=lambda:s.turns[0].update(status="completed")
    result=asyncio.run(engine(tmp_path,s).resume())
    assert result["stage"]=="completed" and len(s.submissions)==1 and s.sleeps


def test_quality_failure_still_uses_router_escalation(tmp_path):
    s=Service();s.outcomes=["wrong","2"]
    result=start(tmp_path,s)
    assert result["stage"]=="completed"
    assert [(t[2],t[3]) for t in s.submissions]==[("gpt-6-luna","low"),("gpt-6-luna","medium")]


def test_inconsistent_quota_rejections_respect_total_inference_budget(tmp_path):
    s=Service();s.outcomes=[TurnFailed("quota",error_kind="usageLimitExceeded")]*3
    result=start(tmp_path,s,max_attempts=2)
    assert result["stage"]=="attempts_exhausted" and len(s.submissions)==2


def test_foreign_state_cannot_be_resumed_as_managed_job(tmp_path):
    save_state(tmp_path/"job.json",{"version":1,"stage":"completed"})
    with pytest.raises(ValueError): asyncio.run(engine(tmp_path,Service()).resume())


def test_completed_result_after_history_write_crash_is_not_counted_twice(tmp_path):
    s=Service();start(tmp_path,s)
    data=load_state(tmp_path/"job.json")
    data["stage"]="completed_unvalidated";data["attempts"][-1]["phase"]="completed_unvalidated"
    data["attempts"][-1].pop("validation")
    save_state(tmp_path/"job.json",data)
    result=asyncio.run(engine(tmp_path,s).resume())
    assert result["stage"]=="completed" and len(s.submissions)==1
    assert list(History.load(tmp_path/"history.json").records.values())==[{"success":1,"failure":0}]


@pytest.mark.parametrize("change",["summary","missing","ambiguous","interrupted"])
def test_incomplete_or_ambiguous_server_history_never_replays(tmp_path,change):
    s=Service();s.lose=True;start(tmp_path,s,max_wait=0)
    data=load_state(tmp_path/"job.json");data["stage"]="submitted";data.pop("nextCheckAt",None)
    if change=="summary": s.turns[0]["itemsView"]="summary"
    if change=="missing": s.turns=[]
    if change=="ambiguous":
        data["attempts"][-1].pop("turnId",None)
        s.turns.append({**s.turns[0],"id":"foreign"})
    if change=="interrupted": s.turns[0]["status"]="interrupted"
    save_state(tmp_path/"job.json",data)
    result=asyncio.run(engine(tmp_path,s).resume())
    assert result["stage"]=="needs_attention" and len(s.submissions)==1


def test_stale_exhausted_snapshot_is_rechecked_not_assumed_reset(tmp_path):
    s=Service();s.limits=snapshot(window(100,reset=1200))
    checks=[]
    def reset_later():
        checks.append(s.now)
        if len(checks)==2: s.limits=snapshot(window(0))
    s.on_sleep=reset_later
    result=start(tmp_path,s)
    assert result["stage"]=="completed" and s.sleeps==[205,600] and len(s.submissions)==1


def test_attempt_budget_stops_before_waiting_for_unusable_next_model(tmp_path):
    s=Service();s.outcomes=["wrong"]
    original=s.run_turn
    async def exhaust(*args,**kwargs):
        outcome=await original(*args,**kwargs)
        s.limits=snapshot(window(100,reset=9000))
        return outcome
    s.run_turn=exhaust
    result=start(tmp_path,s,max_attempts=1,max_wait=0)
    assert result["stage"]=="attempts_exhausted" and not s.sleeps


def test_corrupt_attempt_phase_is_rejected_without_another_submission(tmp_path):
    s=Service();start(tmp_path,s)
    data=load_state(tmp_path/"job.json");data["stage"]="ready";data["attempts"][0]["phase"]="UNKNOWN"
    save_state(tmp_path/"job.json",data)
    with pytest.raises(ValueError): asyncio.run(engine(tmp_path,s).resume())
    assert len(s.submissions)==1


@pytest.mark.parametrize("phase",["validated","failed"])
def test_changed_outer_stage_never_replays_terminal_attempt(tmp_path,phase):
    s=Service()
    if phase=="failed": s.outcomes=[TurnFailed("bad",error_kind="badRequest")]
    start(tmp_path,s)
    data=load_state(tmp_path/"job.json");data["stage"]="ready"
    save_state(tmp_path/"job.json",data)
    result=asyncio.run(engine(tmp_path,s).resume())
    assert result["stage"]==("completed" if phase=="validated" else "needs_attention")
    assert len(s.submissions)==1


@pytest.mark.parametrize("phase",["quota_failed","auth_failed","escalated"])
def test_retry_phase_requires_actual_failure_evidence(tmp_path,phase):
    s=Service();start(tmp_path,s)
    data=load_state(tmp_path/"job.json");data["stage"]="ready";data["attempts"][0]["phase"]=phase
    save_state(tmp_path/"job.json",data)
    with pytest.raises(ValueError): asyncio.run(engine(tmp_path,s).resume())
    assert len(s.submissions)==1


def test_unresolved_earlier_attempt_cannot_be_skipped_by_later_one(tmp_path):
    s=Service();s.outcomes=["wrong","2"];start(tmp_path,s)
    data=load_state(tmp_path/"job.json");data["stage"]="ready";data["attempts"][0]["phase"]="submitted"
    save_state(tmp_path/"job.json",data)
    with pytest.raises(ValueError): asyncio.run(engine(tmp_path,s).resume())
    assert len(s.submissions)==2


def test_configuration_rpc_refusal_preserves_completed_output_without_replay(tmp_path):
    from mission_control.rpc import RpcError
    s=Service()
    async def refuse(thread_id): raise RpcError("thread/resume",-32600)
    s.configuration=refuse
    result=start(tmp_path,s)
    assert result["stage"]=="needs_attention"
    assert result["attempts"][0]["phase"]=="completed_unvalidated"
    assert result["attempts"][0]["outcome"]["text"]=="2"
    assert len(s.submissions)==1
    assert asyncio.run(engine(tmp_path,s).resume())["stage"]=="needs_attention"
    assert len(s.submissions)==1
