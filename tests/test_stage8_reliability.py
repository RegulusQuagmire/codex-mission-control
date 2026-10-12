import asyncio
import json
from pathlib import Path
import pytest
from mission_control.queue import MissionQueue
from mission_control.desktop.service import DesktopService
from mission_control.state import StateError
from test_queue import text_job


def test_missing_historical_project_does_not_disable_queue(tmp_path):
    project=tmp_path/'old';project.mkdir()
    queue=MissionQueue(tmp_path/'q.sqlite3')
    DesktopService(queue).configure_roots([str(project)])
    queue.add(text_job('old',project=str(project)))
    queue.control('cancel','old')
    project.rename(tmp_path/'moved')
    service=DesktopService(queue)
    assert service.initialize()['missions'][0]['status']=='cancelled'
    current=tmp_path/'current';current.mkdir()
    service.add(text_job('new',project=str(current)))
    assert len(service.snapshot()['missions'])==2
    with pytest.raises(StateError):queue.add(text_job('invalid',project=str(project)))


def test_timed_out_check_stops_chain_and_requires_reconciliation(tmp_path,monkeypatch):
    from mission_control import validator as v
    from test_validator import spec
    from operator_actions import validate_with_confirmation
    criteria=spec(tmp_path)
    criteria['commands'].append({**criteria['commands'][0],'name':'must-not-run'})
    root=tmp_path/'run';v.prepare(root,criteria);calls=[]
    async def timeout(*args):
        calls.append(args)
        return {'exitCode':None,'timedOut':True,'output':'uncertain side effects'}
    monkeypatch.setattr(v,'run_check',timeout)
    text=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    result=asyncio.run(validate_with_confirmation(root,criteria,'turn',text))
    assert result['kind']=='not_retryable' and not result['passed']
    assert len(calls)==1
    assert asyncio.run(v.validate(root,criteria,'turn',text))==result
    assert len(calls)==1


def test_missing_pending_project_stops_only_affected_work(tmp_path,monkeypatch):
    from mission_control.queue import QueueWorker
    from test_managed import Service
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    old=tmp_path/'old';old.mkdir();current=tmp_path/'current';current.mkdir()
    q=MissionQueue(tmp_path/'q.json');q.add(text_job('missing',priority=10,project=str(old)))
    q.add(text_job('current',project=str(current)));old.rename(tmp_path/'moved')
    adapter=Service();adapter.outcomes=['2']
    result=asyncio.run(QueueWorker(q,lambda cwd:adapter.factory).run())
    assert result['missions']['missing']['status']=='needs_attention'
    assert not result['missions']['missing']['dispatchStarted']
    assert result['missions']['current']['status']=='completed'
    assert len(adapter.submissions)==1


def test_timeout_queue_never_escalates_or_offers_plain_retry(tmp_path,monkeypatch):
    from mission_control import validator as v
    from test_sqlite_queue import project_queue
    from operator_actions import ConfirmedQueueWorker
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    async def timeout(*args):return {'exitCode':None,'timedOut':True,'output':''}
    monkeypatch.setattr(v,'run_check',timeout)
    q,adapter=project_queue(tmp_path)
    result=asyncio.run(ConfirmedQueueWorker(q,lambda cwd:adapter.factory).run())
    assert result['missions']['code']['status']=='failed'
    assert len(adapter.submissions)==1
    with pytest.raises(StateError):q.control('retry','code')
    assert len(adapter.submissions)==1


def test_missing_project_history_retains_structural_checks(tmp_path):
    from test_validator import spec
    from mission_control.state import save_state
    criteria=spec(tmp_path);project=Path(criteria['project'])
    q=MissionQueue(tmp_path/'q.sqlite3');service=DesktopService(q)
    service.configure_roots([str(project)])
    q.add({'id':'project','title':'Project','task':{'text':'Update value'},
           'type':'project','project':str(project),'criteria':criteria})
    q.control('cancel','project');project.rename(tmp_path/'moved')
    assert service.initialize()['missions'][0]['status']=='cancelled'
    with pytest.raises(StateError):
        service.configure_roots([str(project)])
    with q.storage():
        data=q.read();data['missions']['project']['criteria']['writeFiles']=['../escape']
        q._save(data)
    with pytest.raises(StateError):q.read()


def test_missing_active_project_retains_reservation_without_send(tmp_path,monkeypatch):
    from mission_control.queue import QueueWorker
    from test_managed import Service
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'lease')
    project=tmp_path/'old';project.mkdir();q=MissionQueue(tmp_path/'q.json')
    q.add(text_job('active',project=str(project)))
    data=q.read();data['active']='active';data['missions']['active']['status']='running';q._save(data)
    project.rename(tmp_path/'moved');adapter=Service()
    result=asyncio.run(QueueWorker(q,lambda cwd:adapter.factory).run())
    assert result['active']=='active' and result['missions']['active']['status']=='needs_attention'
    assert not adapter.submissions
