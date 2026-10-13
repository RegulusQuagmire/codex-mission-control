import asyncio,time
from copy import deepcopy
import pytest
from mission_control.desktop.service import DesktopService
from mission_control.queue import MissionQueue
from mission_control.routing import Task,SmartRouter
from test_queue import text_job
from test_routing import catalog

def included_limits():
    return {'ordinaryUsageAllowed':True,'rateLimits':{'limitId':'codex',
        'primary':{'usedPercent':1,'windowDurationMins':300},
        'secondary':{'usedPercent':1,'windowDurationMins':10080}}}

def inspection_service(tmp_path,**job_values):
    project=tmp_path/'project';project.mkdir()
    def forbidden(_):raise AssertionError('Inspection attempted remote access')
    facade=DesktopService(MissionQueue(tmp_path/'queue.sqlite3'),factory_for_cwd=forbidden)
    facade.initialize();facade.add(text_job('demo',project=str(project),**job_values))
    facade.models=catalog();facade._raw_limits=included_limits()
    facade.limits_observed_at=facade._raw_limits_observed_at=time.time()
    return facade

def test_inspection_is_read_only_and_matches_initial_runner_route(tmp_path):
    facade=inspection_service(tmp_path)
    before=deepcopy(facade.queue.read())
    result=facade.inspect_route('demo')
    expected=SmartRouter().choose(Task(**before['missions']['demo']['task']),catalog())
    assert (result['decision']['model'],result['decision']['effort'])==(expected.model,expected.effort)
    assert facade.queue.read()==before
    assert result['creditGate']['allowed'] and result['limitGate']['allowed']
    assert result['fingerprint']

def test_manual_inspection_never_replaces_model_and_honors_ceiling(tmp_path):
    facade=inspection_service(tmp_path,manual={'model':'gpt-6-astra','effort':'low'})
    facade.save_preferences({'modelPolicies':{'gpt-6-astra':{'maxEffort':'low','automaticEnabled':False}}})
    first=facade.inspect_route('demo')
    assert first['decision']['model']=='gpt-6-astra' and first['manual']
    facade.save_preferences({'modelPolicies':{'gpt-6-astra':{'maxEffort':'none','automaticEnabled':False}}})
    second=facade.inspect_route('demo')
    assert second['decision'] is None and 'model_policy' in second['blocked']
    assert first['fingerprint']!=second['fingerprint']

@pytest.mark.parametrize('limits,age',[(None,0),(included_limits(),120),({'ordinaryUsageAllowed':False},0)])
def test_unknown_stale_exhausted_limits_are_not_permission(tmp_path,limits,age):
    facade=inspection_service(tmp_path);facade._raw_limits=limits
    facade._raw_limits_observed_at=time.time()-age
    result=facade.inspect_route('demo')
    assert not result['creditGate']['allowed']
    assert 'credit_gate' in result['blocked']

def test_stage11_inspection_retains_exact_route_and_requires_review(tmp_path,monkeypatch):
    from test_stage11_backend_service import paused_service
    facade,remote=paused_service(tmp_path,monkeypatch)
    facade.models=catalog();calls=len(remote.submissions)
    result=facade.inspect_route('mission')
    assert result['retained'] and 'checkpoint_review' in result['blocked']
    assert len(remote.submissions)==calls
    original=result['decision']['model']
    facade.models=[m for m in catalog() if m['model']!=original]
    changed=facade.inspect_route('mission')
    assert changed['decision']['model']==original and 'model_policy' in changed['blocked']

def test_budget_exhaustion_is_visible_without_submission(tmp_path,monkeypatch):
    from test_stage11_backend_service import paused_service
    facade,remote=paused_service(tmp_path,monkeypatch,max_attempts=1)
    facade.models=catalog()
    result=facade.inspect_route('mission')
    assert result['remainingAttempts']==0 and 'attempt_budget' in result['blocked']
    assert len(remote.submissions)==1

def test_runner_does_not_record_nonretryable_check_infrastructure(tmp_path,monkeypatch):
    from test_stage11_backend_service import paused_service
    from mission_control.managed import ManagedRunner
    from mission_control.history import History
    facade,remote=paused_service(tmp_path,monkeypatch)
    async def uncertain(*args):return {'passed':False,'kind':'not_retryable'}
    monkeypatch.setattr(ManagedRunner,'_validation',uncertain)
    asyncio.run(facade.resume_mission('mission',acknowledge_uncertain=True,expected_turn_id='paused-1'))
    with facade.queue.storage():
        history=History.load(facade.queue.journal().history_path)
    assert history.records=={}
