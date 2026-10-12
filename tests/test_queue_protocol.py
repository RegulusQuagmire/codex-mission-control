"""Offline App Server + real local tests/build/lint + persistent queue across processes."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import sys
import pytest
from mission_control.adapter import CodexAdapter
from operator_actions import ConfirmedQueueWorker as QueueWorker
from mission_control.queue import MissionQueue
from mission_control.rpc import RpcClient
from mission_control.state import load_state
from test_validator import spec


@pytest.mark.parametrize('scenario,first_calls',[('project_quota',2),('project_lost_ack',1),('project_repair',2)])
def test_project_queue_protocol_checks_and_recovery(tmp_path,monkeypatch,scenario,first_calls):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    criteria=spec(tmp_path);criteria['contains']={}
    criteria['commands'] += [
        {'name':'build','kind':'build','argv':[sys.executable,'-c',"from pathlib import Path; compile(Path('app.py').read_text(), 'app.py', 'exec')"],'timeout':5,'approved':True},
        {'name':'lint','kind':'lint','argv':[sys.executable,'-c',"from pathlib import Path; assert chr(9) not in Path('app.py').read_text()"],'timeout':5,'approved':True}]
    q=MissionQueue(tmp_path/'queue.json');now=[1000];processes=[]
    for identity,depends in [('first',[]),('next',['first'])]:
        current=json.loads(json.dumps(criteria))
        # Dependent already contains verified VALUE=2; no-op is valid for this validation mission.
        if identity=='next':current['requireChanges']=False
        q.add({'id':identity,'title':identity,'type':'project','task':{'text':'Fix value','operation':'docs'},
               'project':criteria['project'],'criteria':current,'dependsOn':depends,'mode':'economy'})
    def for_cwd(cwd):
        @asynccontextmanager
        async def factory():
            identity=cwd.parent.parent.name
            server_state=tmp_path/(identity+'-server.json')
            actual=scenario if identity=='first' else 'project_normal'
            command=[sys.executable,str(Path(__file__).with_name('persistent_limit_server.py')),str(server_state),actual]
            async with RpcClient(command,timeout=3) as rpc:
                processes.append(rpc.process);yield CodexAdapter(rpc)
        return factory
    async def sleep(seconds):
        assert all(p.returncode is not None for p in processes)
        now[0]+=seconds
    def worker():return QueueWorker(q,for_cwd,clock=lambda:now[0],sleep=sleep)
    async def check():
        result=await worker().run(max_wait=0)
        if result['active']:
            job=result['missions'][result['active']];saved=load_state(Path(job['runPath']))
            now[0]=saved.get('nextCheckAt',now[0]);result=await worker().run()
        assert result['executionOrder']==['first','next']
        assert all(j['status']=='completed' for j in result['missions'].values())
        assert all(c['exitCode']==0 for j in result['missions'].values() for c in j['checks']['commands'])
        assert json.loads((tmp_path/'first-server.json').read_text())['calls']==first_calls
        assert json.loads((tmp_path/'next-server.json').read_text())['calls']==1
        assert result['missions']['next']['attempts'][0]['decision']['effort']=='low'
        if scenario=='project_repair':
            attempts=result['missions']['first']['attempts']
            assert attempts[0]['validation']['passed'] is False and attempts[1]['decision']['effort']=='medium'
        await worker().run()
        assert json.loads((tmp_path/'first-server.json').read_text())['calls']==first_calls
        assert all(p.returncode is not None for p in processes)
        assert (Path(criteria['project'])/'app.py').read_text()=='VALUE = 1\n'
    asyncio.run(check())


def test_killed_controller_recovers_same_turn_without_resubmission(tmp_path):
    import os
    import subprocess
    from test_queue import text_job
    q=MissionQueue(tmp_path/'queue.json');q.add(text_job('one',project=str(tmp_path)))
    state=tmp_path/'server.json';driver=Path(__file__).with_name('queue_crash_driver.py')
    env=os.environ.copy();env['PYTHONPATH']=str(Path(__file__).resolve().parents[1]/'src')
    crashed=subprocess.run([sys.executable,str(driver),str(q.path),str(state),'crash'],env=env,capture_output=True,timeout=15)
    assert crashed.returncode==93
    assert q.read()['active']=='one' and json.loads(state.read_text())['calls']==1
    recovered=subprocess.run([sys.executable,str(driver),str(q.path),str(state),'recover'],env=env,capture_output=True,timeout=15)
    assert recovered.returncode==0, recovered.stderr.decode(errors='replace')
    assert q.read()['missions']['one']['status']=='completed'
    assert json.loads(state.read_text())['calls']==1
