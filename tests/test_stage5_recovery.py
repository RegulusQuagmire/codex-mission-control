import asyncio
from pathlib import Path
import subprocess
import sys
import pytest
from mission_control.queue import MissionQueue
from mission_control.state import StateError, load_state
from mission_control.safety import configure, approve
from mission_control.migration import migrate
from test_queue import text_job
from test_managed import Service, start, engine
from test_sqlite_queue import worker


@pytest.fixture(autouse=True)
def private_lock(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')


def test_model_unavailable_before_send_waits_then_recovers(tmp_path):
    s=Service()
    # Plan with a full catalog, then make the selected model unavailable during a quota wait.
    from test_limits import snapshot,window
    s.limits=snapshot(window(100,reset=None))
    r=start(tmp_path,s,max_wait=0);decision=r['decision'].copy()
    s.limits=snapshot(window(1));s.now=r['nextCheckAt']
    original=s.models
    async def unavailable():return [m for m in await original() if m['model']!=decision['model']]
    s.models=unavailable
    r=asyncio.run(engine(tmp_path,s).resume(max_wait=0))
    assert r['stage']=='waiting_model' and not s.submissions and r['decision']==decision
    s.models=original;s.now=r['nextCheckAt']
    r=asyncio.run(engine(tmp_path,s).resume())
    assert r['stage']=='completed' and len(s.submissions)==1


def test_legacy_migration_keeps_exact_journal_paths_and_ambiguous_turn(tmp_path):
    project=tmp_path/'project';project.mkdir()
    old=MissionQueue(tmp_path/'old.json');old.add(text_job('a',project=str(project)))
    s=Service();s.drop_ack=True
    r=asyncio.run(worker(old,s).run(max_wait=0));path=r['missions']['a']['runPath']
    target=tmp_path/'new.sqlite3'
    migrate(old.path,target);q=MissionQueue(target)
    assert q.read()['missions']['a']['runPath']==path
    configure(q,[str(project)]);approve(q,'a')
    migrate(old.path,target) # idempotent; never overwrite progressed DB
    s.now+=100
    r=asyncio.run(worker(q,s).run())
    assert r['missions']['a']['status']=='completed' and len(s.submissions)==1
    assert old.path.exists() and Path(path).exists()
    with q.storage():assert load_state(Path(path))['threadId']=='thread'


def test_sqlite_forced_exit_after_ack_recovers_one_server_turn(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('a',project=str(project)))
    configure(q,[str(project)]);approve(q,'a')
    server=tmp_path/'server.json'
    driver=Path(__file__).with_name('queue_crash_driver.py')
    result=subprocess.run([sys.executable,str(driver),str(q.path),str(server),'crash'],capture_output=True,timeout=20)
    assert result.returncode==93,result.stderr
    result=subprocess.run([sys.executable,str(driver),str(q.path),str(server),'resume'],capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr
    assert q.read()['missions']['a']['status']=='completed'
    assert len(load_state(server)['turns'])==1


def test_legacy_project_resume_gets_baseline_checkpoint_at_migration(tmp_path):
    from test_validator import spec
    criteria=spec(tmp_path)
    old=MissionQueue(tmp_path/'old.json')
    old.add({'id':'code','title':'Code','type':'project','project':criteria['project'],
             'criteria':criteria,'task':{'text':'Change VALUE to 2'},'mode':'economy'})
    s=Service();s.outcomes=['{"edits":[{"path":"app.py","content":"VALUE = 2\\n"}]}'];s.drop_ack=True
    r=asyncio.run(worker(old,s).run(max_wait=0))
    target=tmp_path/'new.sqlite3';migrate(old.path,target);q=MissionQueue(target)
    configure(q,[criteria['project']]);approve(q,'code');s.now+=100
    result=asyncio.run(worker(q,s).run())
    assert result['missions']['code']['status']=='completed' and len(s.submissions)==1
    assert (Path(criteria['project'])/'app.py').read_text()=='VALUE = 1\n'
