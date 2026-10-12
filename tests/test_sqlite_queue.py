import asyncio
from pathlib import Path
import pytest
from operator_actions import ConfirmedQueueWorker as QueueWorker
from mission_control.queue import MissionQueue
from mission_control.state import load_state, save_state, state_exists, StateError
from test_queue import text_job
from test_managed import Service
from mission_control.safety import configure, approve


@pytest.fixture(autouse=True)
def private_lock(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')


def worker(q,s):return QueueWorker(q,lambda cwd:s.factory,clock=lambda:s.now,sleep=s.sleep)


def test_sqlite_queue_completion_has_no_plaintext_side_journals(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('one',project=str(project)))
    configure(q,[str(project)]);approve(q,'one')
    s=Service();r=asyncio.run(worker(q,s).run());assert r['missions']['one']['status']=='completed'
    path=Path(r['missions']['one']['runPath'])
    with q.storage():assert state_exists(path) and load_state(path)['threadId']=='thread'
    assert not path.exists()
    asyncio.run(worker(MissionQueue(q.path),s).run());assert len(s.submissions)==1


def test_sqlite_lost_ack_recovers_same_turn_and_preserves_queue(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('one',project=str(project)))
    configure(q,[str(project)]);approve(q,'one')
    s=Service();s.drop_ack=True
    r=asyncio.run(worker(q,s).run(max_wait=0));assert r['active']=='one'
    s.now+=100
    r=asyncio.run(worker(MissionQueue(q.path),s).run())
    assert r['missions']['one']['status']=='completed' and len(s.submissions)==1


def test_sqlite_missing_run_document_never_replays(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('one',project=str(project)))
    configure(q,[str(project)]);approve(q,'one')
    s=Service();s.lose=True;r=asyncio.run(worker(q,s).run(max_wait=0))
    path=Path(r['missions']['one']['runPath'])
    store=q.journal()
    with store.transaction() as c:c.execute('delete from documents where key=?',(store.key(path),))
    r=asyncio.run(worker(MissionQueue(q.path),s).run())
    assert r['missions']['one']['status']=='needs_attention' and len(s.submissions)==1


def project_queue(tmp_path,command=None):
    from test_validator import spec
    criteria=spec(tmp_path,command=command)
    q=MissionQueue(tmp_path/'q.sqlite3')
    job={'id':'code','title':'Change constant','type':'project','project':criteria['project'],
         'task':{'text':'Change VALUE to 2','operation':'code'},'criteria':criteria,'mode':'economy','maxAttempts':1}
    q.add(job);configure(q,[criteria['project']]);approve(q,'code')
    s=Service();s.outcomes=['{"edits":[{"path":"app.py","content":"VALUE = 2\\n"}]}']
    return q,s


def test_sqlite_project_checks_checkpoint_and_completed_receipt_survive_restart(tmp_path):
    q,s=project_queue(tmp_path)
    result=asyncio.run(worker(q,s).run())
    assert result['missions']['code']['status']=='completed'
    root=Path(result['missions']['code']['runPath']).parent
    with q.storage():
        assert state_exists(root/'snapshot.json') and state_exists(root/'checkpoint.json')
        from mission_control.checkpoints import verify
        verify(root,load_state(root/'snapshot.json'))
    assert not (root/'snapshot.json').exists()
    assert (tmp_path/'source/app.py').read_text()=='VALUE = 1\n'
    asyncio.run(worker(MissionQueue(q.path),s).run());assert len(s.submissions)==1


def test_missing_checkpoint_stops_resume_without_resending(tmp_path):
    q,s=project_queue(tmp_path);s.drop_ack=True
    result=asyncio.run(worker(q,s).run(max_wait=0))
    root=Path(result['missions']['code']['runPath']).parent;store=q.journal()
    with store.transaction() as c:c.execute('delete from documents where key=?',(store.key(root/'checkpoint.json'),))
    s.now+=100
    result=asyncio.run(worker(MissionQueue(q.path),s).run())
    assert result['missions']['code']['status']=='needs_attention' and len(s.submissions)==1


def test_check_diagnostics_redacted_before_receipt_or_feedback(tmp_path):
    import sys
    command=[sys.executable,'-c',"print('api_'+'key'+'='+'x'*32); raise SystemExit(1)"]
    q,s=project_queue(tmp_path,command=command)
    # Command literals themselves contain no credential; diagnostic output does.
    result=asyncio.run(worker(q,s).run(max_wait=0))
    job=result['missions']['code']
    assert 'x'*32 not in str(job['attempts'])
    assert '[REDACTED]' in str(job['attempts'])


def test_explicit_approval_is_required_before_dispatch(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('one',project=str(project)))
    s=Service()
    with pytest.raises(StateError):asyncio.run(worker(q,s).run())
    assert q.read()['active'] is None and not s.submissions


def test_backup_is_not_an_independent_executable_copy(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('one',project=str(project)))
    configure(q,[str(project)]);approve(q,'one')
    backup=tmp_path/'backup.sqlite3';q.journal().backup(backup)
    s=Service()
    with pytest.raises(StateError):asyncio.run(worker(MissionQueue(backup),s).run())
    assert not s.submissions
