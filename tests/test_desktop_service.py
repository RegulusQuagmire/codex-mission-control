import asyncio
from pathlib import Path
import pytest
from mission_control.queue import MissionQueue
from mission_control.state import StateError
from test_queue import text_job
from test_managed import Service


def test_desktop_snapshot_is_real_and_preferences_survive(tmp_path):
    from mission_control.desktop.service import DesktopService
    q = MissionQueue(tmp_path/'q.sqlite3')
    service = DesktopService(q, factory_for_cwd=lambda cwd: Service().factory)
    assert service.snapshot()['missions'] == []
    assert service.snapshot()['limits']['windows'] == []
    service.save_preferences({'theme':'light'})
    assert DesktopService(MissionQueue(q.path)).preferences()['theme'] == 'light'


def test_desktop_add_does_not_silently_authorize(tmp_path):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import authorize
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');service=DesktopService(q)
    service.configure_roots([str(project)])
    service.add(text_job('a',project=str(project)))
    with pytest.raises(StateError):authorize(q,q.read()['missions']['a'])


def test_pending_edit_validates_cycle_and_revokes_authorization(tmp_path):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import approve,authorize
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');service=DesktopService(q)
    service.configure_roots([str(project)])
    service.add(text_job('a',project=str(project)))
    service.add(text_job('b',project=str(project),dependsOn=['a']))
    approve(q,'a')
    changed=text_job('a',project=str(project));changed['task']['text']='Changed'
    service.edit('a',changed)
    with pytest.raises(StateError):authorize(q,q.read()['missions']['a'])
    changed['dependsOn']=['b']
    with pytest.raises(StateError):service.edit('a',changed)
    assert q.read()['missions']['a']['dependsOn']==[]


def test_manual_model_real_queue_and_resume_no_replay(tmp_path,monkeypatch):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import fingerprint
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();q=MissionQueue(tmp_path/'q.sqlite3')
    s=Service();s.outcomes=['2']
    facade=DesktopService(q,factory_for_cwd=lambda cwd:s.factory)
    facade.configure_roots([str(project)])
    job=text_job('manual',project=str(project));job['manual']={'model':'gpt-6-astra','effort':'high'}
    facade.add(job);view=facade.access_review('manual');facade.approve_access('manual',fingerprint(view))
    result=asyncio.run(facade.start())
    assert result['missions']['manual']['status']=='completed'
    assert result['missions']['manual']['model']['model']=='gpt-6-astra'
    assert result['missions']['manual']['model']['effort']=='high'
    asyncio.run(facade.start());assert len(s.submissions)==1


def test_manual_unsupported_effort_does_not_submit(tmp_path,monkeypatch):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import approve
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();q=MissionQueue(tmp_path/'q.sqlite3');s=Service()
    facade=DesktopService(q,factory_for_cwd=lambda cwd:s.factory);facade.configure_roots([str(project)])
    job=text_job('manual',project=str(project));job['manual']={'model':'gpt-6-astra','effort':'unsupported'}
    facade.add(job);approve(q,'manual')
    result=asyncio.run(__import__('mission_control.queue',fromlist=['QueueWorker']).QueueWorker(q,lambda cwd:s.factory).run(max_wait=0))
    assert result['missions']['manual']['status']=='waiting_model' and not s.submissions


def test_preview_never_executes_and_stale_approval_rejected(tmp_path,monkeypatch):
    from test_sqlite_queue import project_queue
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import QueueWorker
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    q,s=project_queue(tmp_path)
    result=asyncio.run(QueueWorker(q,lambda cwd:s.factory).run())
    assert result['missions']['code']['status']=='waiting_approval'
    service=DesktopService(q);view=service.review_result('code')
    assert 'VALUE = 2' in view['sources']['app.py']
    root=Path(result['missions']['code']['runPath']).parent
    with pytest.raises(StateError):service.approve_result('code',view['review']['reviewId'])
    (root/'workspace/app.py').write_text('VALUE = 99\n')
    with pytest.raises(StateError):service.approve_result('code',view['review']['reviewId'],accept_user_rights=True)
    assert len(s.submissions)==1


def test_paused_approved_result_can_resume_and_fresh_limits_win(tmp_path,monkeypatch):
    from test_sqlite_queue import project_queue
    from mission_control.desktop.service import DesktopService
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    q,s=project_queue(tmp_path);facade=DesktopService(q,factory_for_cwd=lambda cwd:s.factory)
    asyncio.run(facade.start());facade.control('pause');view=facade.review_result('code')
    facade.approve_result('code',view['review']['reviewId'],accept_user_rights=True)
    assert facade.snapshot()['missions'][0]['executionApproved']
    facade.limits={'windows':[],'marker':'fresh'};facade.limits_observed_at=1e15
    assert facade.snapshot()['limits'].get('marker')=='fresh'
    asyncio.run(facade.resume_queue())
    assert q.read()['missions']['code']['status']=='completed' and len(s.submissions)==1


def test_result_approval_resumes_same_turn_and_cancel_releases(tmp_path,monkeypatch):
    from test_sqlite_queue import project_queue
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import QueueWorker
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    q,s=project_queue(tmp_path);service=DesktopService(q,factory_for_cwd=lambda cwd:s.factory)
    asyncio.run(service.start());view=service.review_result('code')
    service.approve_result('code',view['review']['reviewId'],accept_user_rights=True)
    asyncio.run(service.start())
    assert q.read()['missions']['code']['status']=='completed' and len(s.submissions)==1


def test_worker_is_single_and_shutdown_preserves_uncertainty(tmp_path,monkeypatch):
    from contextlib import asynccontextmanager
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import approve
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();q=MissionQueue(tmp_path/'q.sqlite3');s=Service()
    entered=asyncio.Event();released=[]
    original=s.run_turn
    async def blocked(*args,**kwargs):
        entered.set();await asyncio.Event().wait()
    s.run_turn=blocked
    @asynccontextmanager
    async def factory():
        try:yield s
        finally:released.append(True)
    service=DesktopService(q,factory_for_cwd=lambda cwd:factory);service.configure_roots([str(project)])
    service.add(text_job('a',project=str(project)));approve(q,'a')
    async def scenario():
        task=asyncio.create_task(service.start());await asyncio.wait_for(entered.wait(),5)
        with pytest.raises(StateError):await service.start()
        await service.shutdown();assert task.cancelled()
    asyncio.run(scenario())
    assert q.read()['paused'] and q.read()['active']=='a' and released


def test_connection_failure_clears_old_data_and_unknown_weekly_stays_unknown(tmp_path):
    from contextlib import asynccontextmanager
    from mission_control.desktop.service import DesktopService
    s=Service();facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'),factory_for_cwd=lambda cwd:s.factory)
    facade.initialize();asyncio.run(facade.refresh_connection())
    assert facade.connection['status']=='connected'
    @asynccontextmanager
    async def offline():raise OSError('offline');yield
    facade.factory_for_cwd=lambda cwd:offline
    asyncio.run(facade.refresh_connection())
    assert facade.connection['status']=='error' and facade.models==[] and facade.limits['windows']==[]


def test_cancel_waiting_approval_releases_reservation_without_execution(tmp_path,monkeypatch):
    from test_sqlite_queue import project_queue
    from mission_control.desktop.service import DesktopService
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    q,s=project_queue(tmp_path);facade=DesktopService(q,factory_for_cwd=lambda cwd:s.factory)
    asyncio.run(facade.start());facade.control('cancel','code')
    assert q.read()['active'] is None and q.read()['missions']['code']['status']=='cancelled'
    assert len(s.submissions)==1
    from mission_control.queue import worker_lease_path
    from mission_control.state import load_state
    assert load_state(worker_lease_path())['queuePath'] is None


@pytest.mark.parametrize('mode,model,effort',[('economy','gpt-6-luna','medium'),('balanced','gpt-6.1-sol','medium'),('quality','gpt-6.1-sol','high')])
def test_desktop_strategy_changes_real_router_decision(tmp_path,monkeypatch,mode,model,effort):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import approve
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();q=MissionQueue(tmp_path/'q.sqlite3');s=Service();s.outcomes=['2']
    facade=DesktopService(q,factory_for_cwd=lambda cwd:s.factory);facade.configure_roots([str(project)])
    job=text_job('a',project=str(project));job['mode']=mode;job['task']={'text':'Implement a function','operation':'code'}
    facade.add(job);approve(q,'a');asyncio.run(facade.start())
    decision=q.read()['missions']['a']['model']
    assert (decision['model'],decision['effort'])==(model,effort)


def test_mission_continue_restarts_idle_worker_without_replay(tmp_path,monkeypatch):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import approve
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();q=MissionQueue(tmp_path/'q.sqlite3');s=Service();s.outcomes=['2']
    facade=DesktopService(q,factory_for_cwd=lambda cwd:s.factory);facade.configure_roots([str(project)])
    facade.add(text_job('a',project=str(project)));approve(q,'a');facade.control('pause','a')
    asyncio.run(facade.resume_mission('a'))
    assert q.read()['missions']['a']['status']=='completed' and len(s.submissions)==1


def test_missing_weekly_policy_never_submits_in_desktop(tmp_path,monkeypatch):
    from mission_control.desktop.service import DesktopService
    from mission_control.safety import approve
    from mission_control.queue import QueueWorker
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();q=MissionQueue(tmp_path/'q.sqlite3');s=Service()
    async def missing():return {'ordinaryUsageAllowed':True,'rateLimits':{'limitId':'codex','primary':{'usedPercent':1,'windowDurationMins':300}}}
    s.rate_limits=missing
    facade=DesktopService(q);facade.configure_roots([str(project)])
    job=text_job('a',project=str(project));job['policy']={'mode':'weekly'};facade.add(job);approve(q,'a')
    result=asyncio.run(QueueWorker(q,lambda cwd:s.factory).run(max_wait=0))
    assert result['missions']['a']['status']=='waiting_limit' and not s.submissions


def test_corrupt_gui_preferences_fail_closed(tmp_path):
    from mission_control.desktop.service import DesktopService
    q=MissionQueue(tmp_path/'q.sqlite3');service=DesktopService(q);service.initialize()
    q.journal().save('gui-preferences',{'resumeOnLaunch':'yes'})
    with pytest.raises(StateError):service.preferences()
