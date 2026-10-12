import asyncio
import json
from pathlib import Path

from operator_actions import ConfirmedProjectRunner as ProjectRunner
from mission_control.routing import Task
from mission_control.state import load_state, save_state
from test_managed import Service
from test_validator import spec


def runner(tmp_path,s):
    return ProjectRunner(s.factory,tmp_path/'run'/'managed.json',cwd=tmp_path/'run'/'workspace',
                         clock=lambda:s.now,sleep=s.sleep)


def test_project_failure_diagnostics_repair_with_escalation(tmp_path):
    criteria=spec(tmp_path);criteria['contains']={}
    s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 0\n'}]}),
                           json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    result=asyncio.run(runner(tmp_path,s).run_project('Fix value',criteria,mode='economy'))
    assert result['stage']=='completed' and len(s.submissions)==2
    assert s.submissions[0][3]!=s.submissions[1][3]
    assert 'AssertionError' in s.submissions[1][1]
    assert result['attempts'][0]['validation']['commands'][0]['exitCode']!=0
    assert (Path(criteria['project'])/'app.py').read_text()=='VALUE = 1\n'


def test_project_receipt_recovers_completed_validation_without_inference(tmp_path):
    criteria=spec(tmp_path);s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    first=asyncio.run(runner(tmp_path,s).run_project('Fix value',criteria,mode='economy'))
    data=load_state(tmp_path/'run'/'managed.json');data['stage']='completed_unvalidated'
    data['attempts'][-1]['phase']='completed_unvalidated';data['attempts'][-1].pop('validation')
    save_state(tmp_path/'run'/'managed.json',data)
    result=asyncio.run(runner(tmp_path,s).resume())
    assert result['stage']=='completed' and len(s.submissions)==1


def test_constraint_failure_never_escalates(tmp_path):
    criteria=spec(tmp_path);s=Service();s.outcomes=[json.dumps({'edits':[{'path':'check.py','content':'pass'}]})]
    result=asyncio.run(runner(tmp_path,s).run_project('Fix value',criteria,mode='economy'))
    assert result['stage']=='validation_failed' and len(s.submissions)==1


def test_project_limit_wait_keeps_context_without_paid_test_calls(tmp_path):
    from test_limits import snapshot, window
    criteria=spec(tmp_path);s=Service();s.limits=snapshot(window(100,reset=1200))
    s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    result=asyncio.run(runner(tmp_path,s).run_project('Fix value',criteria,mode='economy',max_wait=0))
    assert result['stage']=='waiting_limit' and not s.submissions
    s.now=result['nextCheckAt'];s.limits=snapshot(window(0))
    result=asyncio.run(runner(tmp_path,s).resume(max_wait=0))
    assert result['stage']=='completed' and len(s.submissions)==1


def test_validate_first_success_before_releasing_thread_writer(tmp_path):
    from contextlib import asynccontextmanager
    from mission_control.adapter import TurnFailed
    class OwnerService(Service):
        session=0
        @asynccontextmanager
        async def factory(self):
            self.session+=1
            async with super().factory() as adapter:yield adapter
        async def run_turn(self,*a,**kw):
            self.owner=self.session
            return await super().run_turn(*a,**kw)
        async def configuration(self,identity):
            if self.owner!=self.session:raise TurnFailed('Writer transferred to another client')
            return await super().configuration(identity)
    criteria=spec(tmp_path);s=OwnerService();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    r=asyncio.run(runner(tmp_path,s).run_project('Fix value',criteria,mode='economy'))
    assert r['stage']=='completed'


def test_project_repair_switches_model_after_one_effort_escalation(tmp_path):
    criteria=spec(tmp_path);criteria['contains']={};s=Service()
    bad=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 0\n'}]})
    good=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    s.outcomes=[bad,bad,good]
    r=asyncio.run(runner(tmp_path,s).run_project(Task('Fix value',operation='docs'),criteria,mode='economy'))
    assert r['stage']=='completed'
    assert [(a[2],a[3]) for a in s.submissions]==[('gpt-6-luna','low'),('gpt-6-luna','medium'),('gpt-6.1-sol','medium')]


def test_project_resume_rejects_text_journal_without_inference(tmp_path):
    import pytest
    from mission_control.managed import ManagedRunner
    from mission_control.state import StateError
    criteria=spec(tmp_path);root=tmp_path/'run';(root/'workspace').mkdir(parents=True)
    s=Service()
    asyncio.run(ManagedRunner(s.factory,root/'managed.json',cwd=root/'workspace').run(Task('Return 2',operation='text'),expected='2',mode='economy'))
    with pytest.raises(StateError):asyncio.run(runner(tmp_path,s).resume())
    assert len(s.submissions)==1


def test_completed_project_journal_cannot_hide_drift_on_queue_recovery(tmp_path):
    import pytest
    from mission_control.state import StateError
    criteria=spec(tmp_path);s=Service();s.outcomes=[json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})]
    asyncio.run(runner(tmp_path,s).run_project('Fix value',criteria,mode='economy'))
    (tmp_path/'run'/'workspace'/'app.py').write_text('USER EDIT')
    with pytest.raises(StateError):asyncio.run(runner(tmp_path,s).resume())
    assert len(s.submissions)==1
