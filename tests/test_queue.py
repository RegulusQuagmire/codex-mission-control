import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import pytest

from operator_actions import ConfirmedQueueWorker as QueueWorker
from mission_control.queue import MissionQueue, worker_lease_path
from mission_control.state import StateError, load_state, save_state, state_lock
from test_managed import Service
from test_validator import spec


@pytest.fixture(autouse=True)
def private_worker_lock(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'global-worker')


def text_job(identity,priority=0,depends=(),**extra):
    return {'id':identity,'title':identity,'task':{'text':'Return only 2','operation':'text'},
            'type':'text','project':extra.pop('project','.'),'expected':'2','priority':priority,
            'dependsOn':list(depends),'mode':'economy',**extra}


def worker(q,s):return QueueWorker(q,lambda cwd:s.factory,clock=lambda:s.now,sleep=s.sleep)


def test_priorities_dependencies_and_completed_jobs_never_replay(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');s=Service();s.outcomes=['2']*3
    q.add(text_job('low',project=str(tmp_path)))
    q.add(text_job('first',10,project=str(tmp_path)))
    q.add(text_job('dependent',100,['first'],project=str(tmp_path)))
    r=asyncio.run(worker(q,s).run())
    assert r['executionOrder']==['first','dependent','low']
    assert all(j['status']=='completed' for j in r['missions'].values())
    assert len(s.submissions)==3
    asyncio.run(worker(q,s).run());assert len(s.submissions)==3


def test_invalid_graph_and_duplicate_are_atomic(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    before=q.path.read_bytes()
    for job in [text_job('a'),text_job('b',depends=['absent']),text_job('../escape')]:
        with pytest.raises(StateError):q.add(job)
        assert q.path.read_bytes()==before
    data=q.read();data['missions']['a']['dependsOn']=['a'];save_state(q.path,data)
    with pytest.raises(StateError):q.read()


def test_controls_priority_pause_cancel_and_resume(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)));q.add(text_job('b',project=str(tmp_path)))
    q.control('priority','b',priority=10);q.control('pause','b')
    s=Service();s.outcomes=['2'];r=asyncio.run(worker(q,s).run())
    assert r['executionOrder']==['a'] and r['missions']['b']['status']=='paused'
    q.control('cancel','b');q.control('pause')
    assert q.read()['paused'] and q.read()['missions']['b']['status']=='cancelled'
    q.control('resume');assert not q.read()['paused']


def test_limit_recovery_reserves_queue_and_retains_same_run(tmp_path):
    from test_limits import snapshot,window
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)));q.add(text_job('b',project=str(tmp_path)))
    s=Service();s.limits=snapshot(window(100,reset=1200));s.outcomes=['2','2']
    first=asyncio.run(worker(q,s).run(max_wait=0));assert first['active']=='a' and not s.submissions
    saved=first['missions']['a']['runPath'];s.now=1205;s.limits=snapshot(window(0))
    second=asyncio.run(worker(q,s).run(max_wait=0))
    assert second['missions']['a']['runPath']==saved and len(s.submissions)==2
    assert second['missions']['b']['status']=='completed'


def test_global_worker_lease_prevents_two_queues(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    with state_lock(__import__("mission_control.queue",fromlist=["worker_lease_path"]).worker_lease_path()):
        with pytest.raises(StateError):asyncio.run(worker(q,Service()).run())
    assert q.read()['missions']['a']['status']=='pending'


def test_crash_after_managed_completion_recovers_without_submission(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)));s=Service()
    r=asyncio.run(worker(q,s).run());data=q.read();data['active']='a';data['missions']['a']['status']='running'
    save_state(q.path,data)
    result=asyncio.run(worker(q,s).run())
    assert result['missions']['a']['status']=='completed' and len(s.submissions)==1


def test_failed_dependency_blocks_children_but_not_independent_jobs(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',maxAttempts=1,project=str(tmp_path)))
    q.add(text_job('child',depends=['a'],project=str(tmp_path)));q.add(text_job('other',project=str(tmp_path)))
    s=Service();s.outcomes=['wrong','2']
    r=asyncio.run(worker(q,s).run());assert r['missions']['a']['status']=='failed'
    assert r['missions']['child']['status']=='pending' and r['missions']['other']['status']=='completed'
    with pytest.raises(StateError):q.control('retry','a') # cumulative budget exhausted


def test_pause_during_wait_closes_server_and_preserves_active(tmp_path):
    from test_limits import snapshot,window
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();s.limits=snapshot(window(100,reset=9000));s.on_sleep=lambda:q.control('pause')
    r=asyncio.run(worker(q,s).run());assert r['paused'] and r['active']=='a'
    assert not s.submissions and s.connected==0 and s.sleeps==[30]


def test_project_dependency_sees_verified_changes_without_touching_original(tmp_path):
    criteria=spec(tmp_path);criteria['contains']={}
    q=MissionQueue(tmp_path/'queue.json')
    for identity,depends in [('a',[]),('b',['a'])]:
        q.add({'id':identity,'title':identity,'type':'project','task':{'text':'Fix value','operation':'docs'},
               'project':criteria['project'],'criteria':criteria,'dependsOn':depends,'mode':'economy'})
    s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]}),
                           json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n# dependency succeeded\n'}]})]
    r=asyncio.run(worker(q,s).run())
    assert r['missions']['b']['status']=='completed' and 'VALUE = 2' in s.submissions[1][1]
    assert (Path(criteria['project'])/'app.py').read_text()=='VALUE = 1\n'


def test_active_queue_reservation_survives_worker_exit(tmp_path):
    from test_limits import snapshot,window
    qa=MissionQueue(tmp_path/'a.json');qa.add(text_job('a',project=str(tmp_path)))
    qb=MissionQueue(tmp_path/'b.json');qb.add(text_job('b',project=str(tmp_path)))
    s=Service();s.limits=snapshot(window(100,reset=9000))
    asyncio.run(worker(qa,s).run(max_wait=0))
    with pytest.raises(StateError):asyncio.run(worker(qb,s).run(max_wait=0))
    assert not s.submissions
    qa.control('cancel','a')
    asyncio.run(worker(qa,s).run(max_wait=0))
    assert qa.read()['active'] is None
    s.limits=snapshot(window(0));asyncio.run(worker(qb,s).run(max_wait=0))
    assert qb.read()['missions']['b']['status']=='completed'


def test_pause_after_turn_prevents_repair_then_resumes_saved_context(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();s.outcomes=['wrong','2'];original=s.run_turn
    async def pause_after(*a,**kw):
        result=await original(*a,**kw);q.control('pause','a');return result
    s.run_turn=pause_after
    r=asyncio.run(worker(q,s).run());assert len(s.submissions)==1 and r['active']=='a'
    assert r['missions']['a']['status']=='paused'
    s.run_turn=original;q.control('resume','a')
    r=asyncio.run(worker(q,s).run());assert r['missions']['a']['status']=='completed' and len(s.submissions)==2
    assert s.submissions[0][0]==s.submissions[1][0]


def test_cancel_after_turn_keeps_evidence_and_does_not_repair(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();s.outcomes=['wrong'];original=s.run_turn
    async def cancel_after(*a,**kw):
        result=await original(*a,**kw);q.control('cancel','a');return result
    s.run_turn=cancel_after
    r=asyncio.run(worker(q,s).run());assert len(s.submissions)==1 and r['active'] is None
    assert r['missions']['a']['status']=='cancelled' and r['missions']['a']['checks']['passed'] is False


def test_explicit_retry_uses_remaining_budget_and_archives_previous_run(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',maxAttempts=3,project=str(tmp_path)))
    s=Service();s.outcomes=['wrong'];original=s.models
    async def one_config():return [{'model':'gpt-6-luna','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]
    s.models=one_config
    r=asyncio.run(worker(q,s).run());assert r['missions']['a']['status']=='failed' and len(s.submissions)==1
    q.control('retry','a');s.outcomes=['2'];s.models=original
    r=asyncio.run(worker(q,s).run());assert r['missions']['a']['status']=='completed'
    assert len(s.submissions)==2 and len(r['missions']['a']['archives'])==1
    assert load_state(Path(r['missions']['a']['runPath']))['maxAttempts']==2


def test_dependency_merge_keeps_disjoint_changes_from_shared_allowlist(tmp_path):
    criteria=spec(tmp_path);source=Path(criteria['project']);(source/'other.py').write_text('OTHER = 0\n')
    criteria['inputFiles'].append('other.py');criteria['writeFiles'].append('other.py');criteria['contains']={}
    q=MissionQueue(tmp_path/'queue.json')
    for identity,depends in [('a',[]),('b',[]),('d',['a','b'])]:
        q.add({'id':identity,'title':identity,'type':'project','task':{'text':'Fix value','operation':'docs'},
               'project':criteria['project'],'criteria':criteria,'dependsOn':depends,'mode':'economy','maxAttempts':1})
    # B passes its checks with original app.py; each branch has its own check script.
    s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]}),
                           json.dumps({'edits':[{'path':'other.py','content':'OTHER = 3\n'}]}),
                           json.dumps({'edits':[{'path':'other.py','content':'OTHER = 4\n'}]})]
    # Make the test command accept both branch values, without changing it in the model.
    (source/'check.py').write_text('from app import VALUE\nassert VALUE in (1,2)\n')
    r=asyncio.run(worker(q,s).run());assert r['missions']['d']['status']=='completed'
    prompt=s.submissions[2][1]
    assert 'VALUE = 2' in prompt and 'OTHER = 3' in prompt


def test_modified_dependency_workspace_cannot_be_used_as_verified_input(tmp_path):
    criteria=spec(tmp_path);q=MissionQueue(tmp_path/'queue.json')
    q.add({'id':'a','title':'a','type':'project','task':{'text':'Fix value','operation':'docs'},
           'project':criteria['project'],'criteria':criteria,'mode':'economy'})
    s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    r=asyncio.run(worker(q,s).run())
    dep=Path(r['missions']['a']['runPath']).parent
    (dep/'workspace'/'app.py').write_text('TAMPERED')
    q.add({'id':'b','title':'b','type':'project','task':{'text':'Fix value','operation':'docs'},
           'project':criteria['project'],'criteria':criteria,'mode':'economy','dependsOn':['a']})
    r=asyncio.run(worker(q,s).run())
    assert r['missions']['a']['status']=='needs_attention' and r['missions']['b']['status']=='pending' and len(s.submissions)==1


def test_cancel_paused_active_mission_releases_reservation(tmp_path):
    from test_limits import snapshot,window
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();s.limits=snapshot(window(100,reset=9000))
    asyncio.run(worker(q,s).run(max_wait=0));q.control('pause','a');q.control('pause')
    q.control('cancel','a')
    r=asyncio.run(worker(q,s).run(max_wait=0))
    assert r['active'] is None and r['missions']['a']['status']=='cancelled'
    assert not s.submissions


def test_cancel_arriving_during_metadata_does_not_submit_paid_turn(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();original=s.rate_limits
    async def cancel_during():
        r=await original();q.control('cancel','a');return r
    s.rate_limits=cancel_during
    r=asyncio.run(worker(q,s).run())
    assert not s.submissions and r['missions']['a']['status']=='cancelled'


def test_pause_after_fresh_thread_creation_can_resume_without_empty_thread_recovery(tmp_path):
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();original=s.start_thread
    async def pause_during(*a):
        r=await original(*a);q.control('pause','a');return r
    s.start_thread=pause_during
    r=asyncio.run(worker(q,s).run())
    assert not s.submissions and r['active']=='a'
    journal=load_state(Path(r['missions']['a']['runPath']));assert not journal.get('threadId')
    s.start_thread=original;q.control('resume','a')
    assert asyncio.run(worker(q,s).run())['missions']['a']['status']=='completed'


def test_missing_active_journal_never_creates_new_conversation(tmp_path):
    from test_limits import snapshot,window
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();s.lose=True
    r=asyncio.run(worker(q,s).run(max_wait=0));assert len(s.submissions)==1
    Path(r['missions']['a']['runPath']).unlink()
    s.outcomes=['2'];r=asyncio.run(worker(q,s).run(max_wait=0))
    assert r['missions']['a']['status']=='needs_attention' and len(s.submissions)==1


def test_other_project_dependency_is_ordering_only_even_after_source_drift(tmp_path):
    criteria=spec(tmp_path);q=MissionQueue(tmp_path/'queue.json')
    q.add({'id':'a','title':'a','type':'project','task':{'text':'Fix value','operation':'docs'},
           'project':criteria['project'],'criteria':criteria,'mode':'economy'})
    s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    asyncio.run(worker(q,s).run());(Path(criteria['project'])/'app.py').write_text('USER CHANGE')
    other=tmp_path/'other';other.mkdir();(other/'app.py').write_text('VALUE = 1\n');(other/'check.py').write_text('from app import VALUE\nassert VALUE == 2\n')
    criteria['project']=str(other)
    q.add({'id':'b','title':'b','type':'project','task':{'text':'Fix value','operation':'docs'},
           'project':str(other),'criteria':criteria,'mode':'economy','dependsOn':['a']})
    s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    r=asyncio.run(worker(q,s).run());assert r['missions']['b']['status']=='completed'
