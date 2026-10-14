import asyncio
import json
import pytest
from mission_control.queue import MissionQueue, QueueWorker
from mission_control.desktop.service import DesktopService
from mission_control.state import StateError
from mission_control import safety
from test_managed import Service


def draft():
    return {'version':1,'missions':[{'id':'build','stage':'Implementation','title':'Implement',
        'task':'Implement a feature','dependsOn':[], 'inputFiles':['app.py'],
        'writeFiles':['app.py'],'commands':[{'name':'Tests','kind':'test',
        'argv':['python','-m','pytest'],'timeout':60}]}]}


def setup(tmp_path):
    project=tmp_path/'project';project.mkdir();(project/'app.py').write_text('VALUE = 1\n')
    q=MissionQueue(tmp_path/'q.sqlite3');s=DesktopService(q);s.initialize()
    s.configure_roots([str(project)])
    return q,s,project


def test_draft_never_grants_authority_and_confirmation_is_exact(tmp_path):
    q,s,p=setup(tmp_path)
    s.create_project('demo','Demo','Goal',str(p),['app.py'])
    assert not q.read()['missions']
    s.save_project_plan('demo',draft(),revision=0)
    review=s.review_project_plan('demo')
    with pytest.raises(StateError):s.confirm_project_plan('demo',review['reviewId'],acknowledge=False)
    assert not q.read()['missions']
    s.save_project_plan('demo',draft(),revision=1)
    with pytest.raises(StateError):s.confirm_project_plan('demo',review['reviewId'],acknowledge=True)
    review=s.review_project_plan('demo')
    s.confirm_project_plan('demo',review['reviewId'],acknowledge=True)
    job=q.read()['missions']['demo-build']
    assert job['criteria']['commands'][0]['approved'] is True
    with pytest.raises(StateError):safety.authorize(q,job)
    with pytest.raises(StateError):s.confirm_project_plan('demo',review['reviewId'],acknowledge=True)
    assert len(q.read()['missions'])==1
    restored=DesktopService(MissionQueue(q.path)).project_view('demo')
    assert restored['total']==1 and restored['completed']==0


@pytest.mark.parametrize('change',[
    lambda d:d['missions'][0].update(inputFiles=['../secret']),
    lambda d:d['missions'][0].update(dependsOn=['missing']),
    lambda d:d['missions'][0].update(dependsOn=['build']),
    lambda d:d['missions'][0]['commands'][0].update(approved=True),
    lambda d:d['missions'][0].update(project='C:/outside'),
])
def test_untrusted_plan_rejects_unsafe_or_authoritative_fields(tmp_path,change):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),['app.py'])
    value=draft();change(value)
    with pytest.raises(StateError):s.save_project_plan('demo',value,revision=0)
    assert not q.read()['missions']


def test_planner_runs_through_existing_queue_and_only_produces_draft(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();mock.outcomes=[json.dumps(draft())]
    s.create_project('demo','Demo','Goal',str(p),['app.py'])
    identity=s.request_project_plan('demo')['id']
    assert len(q.read()['missions'])==1
    safety.approve(q,identity)
    result=asyncio.run(QueueWorker(q,lambda cwd:mock.factory).run())
    assert result['missions'][identity]['status']=='completed'
    view=s.project_view('demo')
    assert view['draft']==draft() and view['total']==0
    assert len(q.read()['missions'])==1 and len(mock.submissions)==1
    asyncio.run(QueueWorker(q,lambda cwd:mock.factory).run())
    assert len(mock.submissions)==1


def test_plan_edit_revokes_scope_and_access_without_replacing_dispatched_work(tmp_path):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),['app.py'])
    s.save_project_plan('demo',draft(),0);r=s.review_project_plan('demo');s.confirm_project_plan('demo',r['reviewId'],True)
    safety.approve(q,'demo-build');old=q.read()['missions']['demo-build']
    with pytest.raises(StateError):s.edit('demo-build',old)
    changed=draft();changed['missions'][0]['commands'][0]['argv']=['python','-V']
    s.save_project_plan('demo',changed,1)
    assert not q.read()['missions'] and 'demo-build' not in q.journal().load('approvals')
    r=s.review_project_plan('demo');s.confirm_project_plan('demo',r['reviewId'],True)
    with pytest.raises(StateError):safety.authorize(q,q.read()['missions']['demo-build'])
    data=q.read();data['missions']['demo-build']['dispatchStarted']=True;q._save(data)
    with pytest.raises(StateError):s.save_project_plan('demo',draft(),2)
    assert s.project_view('demo')['draft']==changed


def test_confirmation_does_not_expand_roots_and_is_atomic(tmp_path):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),[])
    value=draft();node={**value['missions'][0],'id':'next','dependsOn':['build']};value['missions'].append(node)
    s.save_project_plan('demo',value,0);r=s.review_project_plan('demo')
    outside=tmp_path/'outside';outside.mkdir();s.configure_roots([str(outside)])
    with pytest.raises(StateError):s.confirm_project_plan('demo',r['reviewId'],True)
    assert not q.read()['missions'] and not s.project_view('demo')['activated']
    assert safety.settings(q)['allowedRoots']==[str(outside)]


def test_dag_topological_order_and_dependency_block_reasons_survive_restart(tmp_path):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),[])
    value=draft();node={**value['missions'][0],'id':'next','dependsOn':['build']};value['missions'].insert(0,node)
    s.save_project_plan('demo',value,0);r=s.review_project_plan('demo');s.confirm_project_plan('demo',r['reviewId'],True)
    q.control('pause');view=DesktopService(MissionQueue(q.path)).project_view('demo')
    assert view['queuePaused'] and view['missions'][0]['id']=='demo-build'
    assert view['missions'][1]['blockedBy']==[{'dependency':'demo-build','status':'pending'}]
    assert all(j['accessRequired'] for j in view['missions'])


@pytest.mark.parametrize('drop_ack',[True,False])
def test_unknown_planning_response_reconciles_once_after_restart(tmp_path,monkeypatch,drop_ack):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();mock.outcomes=[json.dumps(draft())];mock.drop_ack=drop_ack;mock.lose=not drop_ack
    s.create_project('demo','Demo','Goal',str(p),['app.py']);job=s.request_project_plan('demo');safety.approve(q,job['id'])
    run=lambda queue:QueueWorker(queue,lambda cwd:mock.factory,clock=lambda:mock.now,sleep=mock.sleep)
    asyncio.run(run(q).run(max_wait=0));assert len(mock.submissions)==1
    mock.now+=100;q=MissionQueue(q.path);result=asyncio.run(run(q).run())
    assert result['missions'][job['id']]['status']=='completed' and len(mock.submissions)==1
    assert DesktopService(q).project_view('demo')['draft']==draft()
    history=q.journal().load('history')
    assert not history.get('qualityRecords')


def test_plan_parser_rejects_duplicate_json_keys_and_nan(tmp_path):
    from mission_control.orchestration import parse_plan
    with pytest.raises(StateError):parse_plan('{"version":1,"version":1,"missions":[]}',str(tmp_path))
    value=draft();value['missions'][0]['commands'][0]['timeout']=float('nan')
    with pytest.raises(StateError):parse_plan(json.dumps(value),str(tmp_path))


def test_planning_access_review_is_read_only_context(tmp_path):
    from mission_control.desktop.approvals import access_text
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),['app.py'])
    job=s.request_project_plan('demo');view=s.access_review(job['id'])
    assert 'app.py' in str(access_text(view))
    assert 'writeFiles' not in view['criteria'] and not q.journal().load('approvals')


def test_retry_history_prevents_plan_replacement(tmp_path):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),[])
    s.save_project_plan('demo',draft(),0);r=s.review_project_plan('demo');s.confirm_project_plan('demo',r['reviewId'],True)
    data=q.read();job=data['missions']['demo-build'];job['generation']=1
    job['archives']=[{'path':'retained-evidence','count':1,'stage':'validation_failed'}];q._save(data)
    with pytest.raises(StateError):s.save_project_plan('demo',draft(),1)
    assert q.read()['missions']['demo-build']['archives']==job['archives']


def test_service_queue_runner_two_nodes_with_verified_new_file_and_result_approvals(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();s.factory_for_cwd=lambda cwd:mock.factory
    s.create_project('demo','Demo','Goal',str(p),['app.py']);value=draft()
    command={'name':'Check','kind':'test','argv':[sys.executable,'-c','print("offline check")'],'timeout':20}
    first=value['missions'][0];first.update(writeFiles=['derived.py'],commands=[command])
    second={**first,'id':'next','title':'Consumer','dependsOn':['build'],
            'inputFiles':['derived.py'],'writeFiles':['final.py']};value['missions'].append(second)
    s.save_project_plan('demo',value,0);review=s.review_project_plan('demo');s.confirm_project_plan('demo',review['reviewId'],True)
    for key in ('demo-build','demo-next'):
        view=s.access_review(key);s.approve_access(key,safety.fingerprint(view))
    mock.outcomes=[json.dumps({'edits':[{'path':'derived.py','content':'VALUE = 2\n'}]}),
                   json.dumps({'edits':[{'path':'final.py','content':'RESULT = 2\n'}]})]
    result=asyncio.run(s.start());assert result['missions']['demo-build']['status']=='waiting_approval'
    assert len(mock.submissions)==1 and not (p/'derived.py').exists()
    review=s.review_result('demo-build');s.approve_result('demo-build',review['review']['reviewId'],accept_user_rights=True)
    result=asyncio.run(s.start());assert result['missions']['demo-next']['status']=='waiting_approval'
    assert len(mock.submissions)==2 and 'VALUE = 2' in mock.submissions[-1][1]
    assert not (p/'derived.py').exists() and not (p/'final.py').exists()
    review=s.review_result('demo-next');s.approve_result('demo-next',review['review']['reviewId'],accept_user_rights=True)
    result=asyncio.run(s.start());assert result['executionOrder']==['demo-build','demo-next']
    assert s.project_view('demo')['completed']==2
    asyncio.run(s.start());assert len(mock.submissions)==2


def test_missing_project_journal_never_authorizes_or_infers_idle(tmp_path):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),[])
    s.save_project_plan('demo',draft(),0);r=s.review_project_plan('demo');s.confirm_project_plan('demo',r['reviewId'],True)
    safety.approve(q,'demo-build')
    with q.journal().transaction() as c:c.execute('delete from documents where key=?',('projects',))
    with pytest.raises(StateError):safety.authorize(q,q.read()['missions']['demo-build'])
    with pytest.raises(StateError):s.snapshot()


def test_planning_checkpoint_consent_survives_restart_and_queue_pause(tmp_path,monkeypatch):
    from test_stage11_backend_service import PausingService
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=PausingService();mock.outcomes=[json.dumps(draft())]
    s.factory_for_cwd=lambda cwd:mock.factory
    s.create_project('demo','Demo','Goal',str(p),['app.py']);job=s.request_project_plan('demo');safety.approve(q,job['id'])
    result=asyncio.run(s.start());assert result['missions'][job['id']]['status']=='waiting_resume'
    s.control('pause');restored=DesktopService(MissionQueue(q.path),factory_for_cwd=lambda cwd:mock.factory)
    assert restored.project_view('demo')['planningStatus']=='waiting_resume'
    asyncio.run(restored.resume_queue());assert len(mock.submissions)==1
    with pytest.raises(StateError):asyncio.run(restored.resume_mission(job['id'],acknowledge_uncertain=True,expected_turn_id='stale'))
    assert len(mock.submissions)==1
    result=asyncio.run(restored.resume_mission(job['id'],acknowledge_uncertain=True,expected_turn_id='paused-1'))
    assert result['missions'][job['id']]['status']=='completed'
    assert restored.project_view('demo')['draft']==draft() and len(mock.submissions)==2


def test_current_model_policy_blocks_planning_before_send(tmp_path,monkeypatch):
    from test_routing import catalog
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();s.create_project('demo','Demo','Goal',str(p),[])
    job=s.request_project_plan('demo');safety.approve(q,job['id'])
    s.save_preferences({'modelPolicies':{m['model']:{'maxEffort':'low','automaticEnabled':False} for m in catalog()}})
    result=asyncio.run(QueueWorker(q,lambda cwd:mock.factory).run(max_wait=0))
    assert result['missions'][job['id']]['status']=='waiting_model' and not mock.submissions


def test_missing_planning_evidence_never_recreates_context_or_resends(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();mock.lose=True;mock.outcomes=[json.dumps(draft())]
    s.create_project('demo','Demo','Goal',str(p),['app.py']);job=s.request_project_plan('demo');safety.approve(q,job['id'])
    result=asyncio.run(QueueWorker(q,lambda cwd:mock.factory).run(max_wait=0))
    from pathlib import Path
    path=Path(result['missions'][job['id']]['runPath']).parent/'planning-context.json';store=q.journal()
    with store.transaction() as connection:connection.execute('delete from documents where key=?',(store.key(path),))
    result=asyncio.run(QueueWorker(MissionQueue(q.path),lambda cwd:mock.factory).run(max_wait=0))
    assert result['missions'][job['id']]['status']=='needs_attention' and len(mock.submissions)==1


def test_planning_obeys_fresh_credit_gate_without_submission(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();calls=[]
    async def credit_gate(model,**kwargs):
        calls.append((model,kwargs['limits']))
        return {'allowed':False,'reason':'reserve_reached','wakeAt':None}
    mock.credit_gate=credit_gate
    s.create_project('demo','Demo','Goal',str(p),[]);job=s.request_project_plan('demo');safety.approve(q,job['id'])
    result=asyncio.run(QueueWorker(q,lambda cwd:mock.factory).run(max_wait=0))
    assert result['missions'][job['id']]['status']=='waiting_credit' and calls and not mock.submissions


def test_existing_owner_draft_does_not_queue_discarded_planning_output(tmp_path):
    q,s,p=setup(tmp_path);s.create_project('demo','Demo','Goal',str(p),[])
    s.save_project_plan('demo',draft(),0)
    with pytest.raises(StateError):s.request_project_plan('demo')
    assert not q.read()['missions'] and s.project_view('demo')['draft']==draft()


def test_conflicting_verified_fork_blocks_downstream_before_inference(tmp_path,monkeypatch):
    import sys
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    q,s,p=setup(tmp_path);mock=Service();s.factory_for_cwd=lambda cwd:mock.factory
    s.create_project('demo','Demo','Goal',str(p),[]);value=draft()
    command={'name':'Check','kind':'test','argv':[sys.executable,'-c','print("offline check")'],'timeout':20}
    first=value['missions'][0];first.update(writeFiles=['shared.py'],commands=[command])
    value['missions'] += [{**first,'id':'fork','title':'Other branch'},
        {**first,'id':'join','title':'Join','dependsOn':['build','fork'],'inputFiles':['shared.py'],'writeFiles':['final.py']}]
    s.save_project_plan('demo',value,0);review=s.review_project_plan('demo');s.confirm_project_plan('demo',review['reviewId'],True)
    for key in ('demo-build','demo-fork','demo-join'):
        view=s.access_review(key);s.approve_access(key,safety.fingerprint(view))
    mock.outcomes=[json.dumps({'edits':[{'path':'shared.py','content':'VALUE = 1\n'}]}),
                   json.dumps({'edits':[{'path':'shared.py','content':'VALUE = 2\n'}]})]
    for key in ('demo-build','demo-fork'):
        result=asyncio.run(s.start());assert result['missions'][key]['status']=='waiting_approval'
        review=s.review_result(key);s.approve_result(key,review['review']['reviewId'],accept_user_rights=True)
    result=asyncio.run(s.start())
    assert result['missions']['demo-join']['status']=='needs_attention' and len(mock.submissions)==2
    assert not (p/'shared.py').exists() and not (p/'final.py').exists()
    asyncio.run(s.start());assert len(mock.submissions)==2
