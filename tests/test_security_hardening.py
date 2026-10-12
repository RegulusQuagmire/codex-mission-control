"""Regressions for Astra findings; synthetic secrets and owned victims only."""
import asyncio
import json
import os
from pathlib import Path
import sys
import pytest
from mission_control import validator as v
from mission_control.state import StateError, load_state, save_state
from mission_control.safety import reject_secrets, redact
from test_validator import spec
from test_sqlite_queue import project_queue
from mission_control.queue import QueueWorker

def worker(q,s):return QueueWorker(q,lambda cwd:s.factory,clock=lambda:s.now,sleep=s.sleep)


@pytest.fixture(autouse=True)
def lease(tmp_path,monkeypatch):
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')


def response(content='VALUE = 2\n'):
    return json.dumps({'edits':[{'path':'app.py','content':content}]})


def test_astra_c1_model_code_cannot_execute_before_result_confirmation(tmp_path,monkeypatch):
    victim=tmp_path/'outside';victim.write_text('untouched')
    leaked=tmp_path/'leaked'
    monkeypatch.setenv('AUDIT_TEST_SECRET','synthetic-environment-value')
    q,s=project_queue(tmp_path)
    s.outcomes=[response("from pathlib import Path\nimport os\nPath("+repr(str(victim))+ ").write_text('overwritten')\nPath("+repr(str(leaked))+").write_text(os.environ.get('AUDIT_TEST_SECRET',''))\nVALUE = 2\n")]
    r=asyncio.run(worker(q,s).run())
    assert victim.read_text()=='untouched' and not leaked.exists()
    assert r['missions']['code']['status']=='waiting_approval'
    assert len(s.submissions)==1
    asyncio.run(worker(q,s).run())
    assert len(s.submissions)==1 and victim.read_text()=='untouched'


def test_result_confirmation_is_specific_and_can_resume_without_codex(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    text=response()
    assert asyncio.run(v.validate(root,s,'t',text))['kind']=='execution_approval_required'
    review=v.review_result(root)
    with pytest.raises(StateError):v.approve_result(root,review['reviewId'],accept_user_rights=False)
    v.approve_result(root,review['reviewId'],accept_user_rights=True)
    assert asyncio.run(v.validate(root,s,'t',text))['passed']
    assert asyncio.run(v.validate(root,s,'next',response('VALUE = 2\n# new result')))['kind']=='execution_approval_required'


def test_confirmation_invalidated_by_changed_or_extra_file(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s);text=response()
    asyncio.run(v.validate(root,s,'t',text));review=v.review_result(root)
    (root/'workspace'/'injected.py').write_text('raise SystemExit(1)')
    with pytest.raises(StateError):v.approve_result(root,review['reviewId'],accept_user_rights=True)


@pytest.mark.parametrize('target',['workspace/app.py','result.diff'])
def test_astra_h1_hardlink_cannot_overwrite_owned_victim(tmp_path,target):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    victim=Path(s['project'])/'app.py' if target.startswith('workspace') else tmp_path/'victim'
    if not victim.exists():victim.write_text('untouched')
    before=victim.read_bytes();p=root/target
    if p.exists():p.unlink()
    os.link(victim,p)
    result=asyncio.run(v.validate(root,s,'t',response()))
    assert victim.read_bytes()==before
    assert result['kind']=='not_retryable' and not result['commands']


@pytest.mark.parametrize('secret',[
    'password="abcdefg"',
    'DATABASE_URL="postgresql://alice:synthetic-password@localhost/db"',
    'aws_secret_access_key="SYNTHETICONLY123456789012345678901234567890"',
    '{"client_secret": "short"}',
    'Authorization: Basic YWxpY2U6cGFzc3dvcmQ=',
])
def test_astra_h2_typical_secrets_rejected_and_redacted(secret,tmp_path):
    with pytest.raises(StateError):reject_secrets(secret)
    assert redact(secret)!=secret
    s=spec(tmp_path);(Path(s['project'])/'app.py').write_text(secret)
    with pytest.raises(StateError):v.prepare(tmp_path/'run',s)
    assert not (tmp_path/'run/workspace').exists()


def test_checkpoint_rejects_legacy_secret_before_creating_git(tmp_path):
    from mission_control.checkpoints import create
    root=tmp_path/'run';root.mkdir()
    with pytest.raises(StateError):create(root,{'baseline':{'config.py':'password="abcdefg"'}})
    assert not (root/'checkpoint.git').exists()


def test_check_environment_excludes_secrets_and_python_injection(tmp_path,monkeypatch):
    from mission_control.check_process import run_command
    monkeypatch.setenv('AUDIT_TEST_SECRET','synthetic-value')
    monkeypatch.setenv('PYTHONPATH','synthetic-path')
    result=run_command([sys.executable,'-c',"import os; assert 'AUDIT_TEST_SECRET' not in os.environ; assert 'PYTHONPATH' not in os.environ"],tmp_path,5)
    assert result['exitCode']==0


def test_astra_h3_ordinary_retry_rejects_uncertain_validation(tmp_path):
    from mission_control.queue import MissionQueue
    from test_queue import text_job
    from test_managed import Service
    q=MissionQueue(tmp_path/'q.json');q.add(text_job('a',project=str(tmp_path)))
    s=Service();s.outcomes=['wrong'];s.models=lambda:None
    # A durable, terminal receipt with unknown side effects must never become an ordinary retry.
    data=q.read();job=data['missions']['a'];job.update(status='failed',runPath=str(q.run_path(job)))
    save_state(Path(job['runPath']),{'stage':'validation_failed','attempts':[{'phase':'validated','validation':{'passed':False,'kind':'not_retryable'}}]})
    save_state(q.path,data)
    with pytest.raises(StateError):q.control('retry','a')


def test_weekly_requires_weekly_data_even_when_ordinary_allowed():
    from mission_control.limits import check_limits,LimitPolicy
    from test_limits import snapshot,window
    limits=snapshot(window(10));limits['ordinaryUsageAllowed']=True
    assert not check_limits(limits,'gpt-6-luna',now=1000,policy=LimitPolicy('weekly'))['allowed']


def test_legacy_source_cannot_be_migrated_to_two_execution_databases(tmp_path):
    from mission_control.queue import MissionQueue
    from mission_control.migration import migrate
    from test_queue import text_job
    old=MissionQueue(tmp_path/'old.json');old.add(text_job('a',project=str(tmp_path)))
    migrate(old.path,tmp_path/'first.sqlite3')
    with pytest.raises(StateError):migrate(old.path,tmp_path/'second.sqlite3')
    assert not (tmp_path/'second.sqlite3').exists()



def test_secret_dictionary_values_and_prompt_feedback_are_cleaned(tmp_path):
    from mission_control.safety import sanitize
    assert sanitize({'password':'short'})=={'password':'[REDACTED]'}
    with pytest.raises(StateError):reject_secrets({'aws_secret_access_key':'short'})
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    prompt=v.prompt(root,s,'Fix constant',feedback='password="abcdefg"')
    assert 'abcdefg' not in prompt


def test_completed_queue_missing_artifact_stops_without_replay(tmp_path):
    from operator_actions import confirm
    q,s=project_queue(tmp_path)
    r=asyncio.run(worker(q,s).run());root=Path(r['missions']['code']['runPath']).parent
    with q.storage():confirm(root)
    assert asyncio.run(worker(q,s).run())['missions']['code']['status']=='completed'
    (root/'workspace/app.py').unlink()
    r=asyncio.run(worker(q,s).run())
    assert r['missions']['code']['status']=='needs_attention' and len(s.submissions)==1


def test_raced_destination_hardlink_never_truncates_victim(tmp_path,monkeypatch):
    import mission_control.secure_files as fs
    victim=tmp_path/'victim';victim.write_bytes(b'untouched')
    target=tmp_path/'target';target.write_bytes(b'old')
    original=fs.os.fsync
    def swap(fd):
        original(fd)
        if target.exists():target.unlink()
        os.link(victim,target)
    monkeypatch.setattr(fs.os,'fsync',swap)
    fs.write_file(target,b'new')
    assert victim.read_bytes()==b'untouched' and target.read_bytes()==b'new'


def test_windows_pinned_ancestor_cannot_be_redirected_during_write(tmp_path,monkeypatch):
    import mission_control.secure_files as fs
    if os.name!='nt':pytest.skip('Windows handle sharing test')
    directory=tmp_path/'owned';directory.mkdir();outside=tmp_path/'outside';outside.mkdir()
    original=fs.os.fsync;blocked=[]
    def try_redirect(fd):
        original(fd)
        try:directory.rename(tmp_path/'moved')
        except OSError:blocked.append(True)
    monkeypatch.setattr(fs.os,'fsync',try_redirect)
    fs.write_file(directory/'result',b'new')
    assert blocked and not (outside/'result').exists() and (directory/'result').read_bytes()==b'new'


def test_read_rejects_hardlinked_input(tmp_path):
    s=spec(tmp_path);source=Path(s['project']);victim=tmp_path/'victim';victim.write_text('VALUE = 1')
    (source/'app.py').unlink();os.link(victim,source/'app.py')
    with pytest.raises(StateError):v.prepare(tmp_path/'run',s)


def test_approval_consumed_before_unknown_check_and_not_replayed(tmp_path,monkeypatch):
    from operator_actions import confirm
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s);text=response()
    asyncio.run(v.validate(root,s,'t',text));confirm(root)
    async def crash(*args):raise KeyboardInterrupt()
    monkeypatch.setattr(v,'run_check',crash)
    with pytest.raises(KeyboardInterrupt):asyncio.run(v.validate(root,s,'t',text))
    assert asyncio.run(v.validate(root,s,'t',text))['kind']=='not_retryable'


def test_pause_between_commands_prevents_second_command(tmp_path):
    from operator_actions import confirm
    marker=tmp_path/'run/workspace/first'
    s=spec(tmp_path,command=[sys.executable,'-c',"from pathlib import Path; Path('first').write_text('done')"])
    s['commands'].append({'name':'second','kind':'test','argv':[sys.executable,'-c',"from pathlib import Path; Path('second').write_text('bad')"],'timeout':5,'approved':True})
    root=tmp_path/'run';v.prepare(root,s);text=response();asyncio.run(v.validate(root,s,'t',text));confirm(root)
    r=asyncio.run(v.validate(root,s,'t',text,stop_requested=marker.exists))
    assert marker.exists() and not (root/'workspace/second').exists()
    assert r['kind']=='not_retryable' and len(r['commands'])==1



def test_approved_result_changed_before_execution_never_runs(tmp_path):
    from operator_actions import confirm
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s);text=response()
    asyncio.run(v.validate(root,s,'t',text));confirm(root)
    (root/'workspace/app.py').write_text('VALUE = 2\n# tampered')
    result=asyncio.run(v.validate(root,s,'t',text))
    assert result['kind']=='not_retryable' and not result['commands']


def test_success_receipt_requires_durable_files(tmp_path,monkeypatch):
    from operator_actions import confirm
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s);text=response()
    asyncio.run(v.validate(root,s,'t',text));confirm(root)
    def unavailable(*args):raise OSError('Synthetic flush failure')
    monkeypatch.setattr(v,'sync_file',unavailable)
    result=asyncio.run(v.validate(root,s,'t',text))
    assert result['kind']=='not_retryable'
    assert load_state(v.receipt_path(root,'t'))['result']['passed'] is False


def test_completed_diff_loss_is_detected(tmp_path):
    from operator_actions import confirm
    q,s=project_queue(tmp_path);r=asyncio.run(worker(q,s).run())
    root=Path(r['missions']['code']['runPath']).parent
    with q.storage():confirm(root)
    asyncio.run(worker(q,s).run());(root/'result.diff').unlink()
    assert asyncio.run(worker(q,s).run())['missions']['code']['status']=='needs_attention'
    assert len(s.submissions)==1


def test_completed_result_confirmation_does_not_reopen_app_server(tmp_path):
    from operator_actions import confirm
    q,s=project_queue(tmp_path);r=asyncio.run(worker(q,s).run());root=Path(r['missions']['code']['runPath']).parent
    with q.storage():confirm(root)
    from contextlib import asynccontextmanager
    def offline(cwd):
        @asynccontextmanager
        async def connection():
            raise AssertionError('App Server must not be opened for local approved validation')
            yield
        return connection
    r=asyncio.run(QueueWorker(q,offline).run())
    assert r['missions']['code']['status']=='completed' and len(s.submissions)==1


def test_app_server_environment_does_not_inherit_api_secrets(tmp_path,monkeypatch):
    from mission_control.rpc import RpcClient
    monkeypatch.setenv('AUDIT_TEST_SECRET','synthetic-value')
    script=tmp_path/'server.py'
    script.write_text("import json,os,sys\nfor line in sys.stdin:\n m=json.loads(line)\n if 'id' in m: print(json.dumps({'id':m['id'],'result':{'secretPresent':'AUDIT_TEST_SECRET' in os.environ}}),flush=True)\n")
    async def check():
        async with RpcClient([sys.executable,str(script)],timeout=3) as rpc:
            assert rpc.initialization['secretPresent'] is False
    asyncio.run(check())


def test_legacy_plaintext_run_does_not_persist_new_model_secret(tmp_path):
    from mission_control.managed import ManagedRunner
    from mission_control.routing import Task
    from test_managed import Service
    s=Service();s.outcomes=['password="synthetic-secret"'];path=tmp_path/'managed.json'
    runner=ManagedRunner(s.factory,path,cwd=tmp_path,clock=lambda:s.now,sleep=s.sleep)
    result=asyncio.run(runner.run(Task('Return only 2',operation='text'),expected='2'))
    assert result['stage']=='needs_attention' and len(s.submissions)==1
    assert 'synthetic-secret' not in path.read_text()


def test_unknown_retry_requires_distinct_operator_acknowledgment(tmp_path):
    from mission_control.queue import MissionQueue
    from test_queue import text_job
    q=MissionQueue(tmp_path/'q.json');q.add(text_job('a',project=str(tmp_path)))
    data=q.read();job=data['missions']['a'];job.update(status='failed',runPath=str(q.run_path(job)))
    save_state(Path(job['runPath']),{'stage':'validation_failed','attempts':[{'phase':'validated','validation':{'passed':False,'kind':'not_retryable'}}]})
    save_state(q.path,data)
    with pytest.raises(StateError):q.control('retry','a')
    result=q.control('retry','a',acknowledge_uncertain=True)
    assert result['missions']['a']['status']=='pending' and result['missions']['a']['generation']==1



def test_new_nested_result_file_with_absent_parents_is_supported(tmp_path):
    s=spec(tmp_path);s['writeFiles'].append('new/module.py')
    root=tmp_path/'run';v.prepare(root,s)
    assert not (root/'workspace/new/module.py').exists()


@pytest.mark.parametrize('secret',[
    'DB_PASSWORD="synthetic password with spaces"',
    '{"refresh_token": "synthetic"}',
    'password="hello world"',
])
def test_multitoken_and_prefixed_credentials_redact_whole_value(secret):
    with pytest.raises(StateError):reject_secrets(secret)
    assert 'synthetic' not in redact(secret) and 'world' not in redact(secret)


def test_model_json_secret_is_discarded_before_plaintext_journal(tmp_path):
    from mission_control.mission_run import ProjectRunner
    from test_managed import Service
    s=Service();s.outcomes=[response('password="synthetic credential with spaces"\nVALUE = 2\n')]
    criteria=spec(tmp_path);root=tmp_path/'run'
    r=asyncio.run(ProjectRunner(s.factory,root/'managed.json',cwd=root/'workspace',clock=lambda:s.now,sleep=s.sleep).run_project('Fix constant',criteria))
    assert r['stage']=='needs_attention'
    assert 'synthetic credential' not in (root/'managed.json').read_text()
    assert not (root/'result.diff').exists()



def test_nested_json_diagnostic_redacts_complete_secret():
    message=json.dumps({'diagnostic':json.dumps({'password':'synthetic password with spaces'})})
    assert 'synthetic' not in redact(message) and 'spaces' not in redact(message)


def test_finished_receipt_does_not_hide_missing_diff(tmp_path):
    from operator_actions import validate_with_confirmation
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s);text=response()
    assert asyncio.run(validate_with_confirmation(root,s,'t',text))['passed']
    (root/'result.diff').unlink()
    assert asyncio.run(v.validate(root,s,'t',text))['kind']=='not_retryable'


def test_cli_result_approval_requires_current_id_and_user_rights(tmp_path,capsys):
    from mission_control.cli import main
    q,s=project_queue(tmp_path);asyncio.run(worker(q,s).run())
    capsys.readouterr()
    base=['--queue',str(q.path),'--mission-id','code']
    assert main(['queue-review-result',*base])==0
    review=json.loads(capsys.readouterr().out)['review']
    assert main(['queue-approve-result',*base,'--review-id',review['reviewId']])==1
    capsys.readouterr()
    assert main(['queue-approve-result',*base,'--review-id','stale','--accept-user-rights'])==1
    capsys.readouterr()
    assert main(['queue-approve-result',*base,'--review-id',review['reviewId'],'--accept-user-rights'])==0
    assert asyncio.run(worker(q,s).run())['missions']['code']['status']=='completed'
    assert len(s.submissions)==1



def test_cancel_unexecuted_result_releases_reservation_without_commands(tmp_path):
    q,s=project_queue(tmp_path);r=asyncio.run(worker(q,s).run())
    assert r['missions']['code']['status']=='waiting_approval'
    q.control('cancel','code')
    r=asyncio.run(worker(q,s).run())
    assert r['active'] is None and r['missions']['code']['status']=='cancelled'
    assert len(s.submissions)==1 and not r['missions']['code'].get('checks',{}).get('commands')


def test_empty_diff_still_must_exist_for_result_approval(tmp_path):
    s=spec(tmp_path);s['requireChanges']=False;s['contains']={}
    root=tmp_path/'run';v.prepare(root,s)
    assert asyncio.run(v.validate(root,s,'t','{"edits":[]}'))['kind']=='execution_approval_required'
    (root/'result.diff').unlink()
    with pytest.raises(StateError):v.review_result(root)


def test_astra_sqlite_started_check_cannot_be_retried_or_resent(tmp_path):
    from mission_control.safety import approve
    q,s=project_queue(tmp_path)
    with q.storage():
        data=q.read();data['missions']['code']['maxAttempts']=3;q._save(data)
    approve(q,'code');s.drop_ack=True;text=s.outcomes[0]
    r=asyncio.run(worker(q,s).run(max_wait=0));root=Path(r['missions']['code']['runPath']).parent
    with q.storage():
        snapshot=load_state(root/'snapshot.json')
        save_state(v.receipt_path(root,'1'),{'phase':'started','turnId':'1','responseHash':v.digest(text.encode()),'specHash':snapshot['specHash']})
    s.now+=100
    r=asyncio.run(worker(q,s).run())
    assert r['missions']['code']['status']=='failed'
    assert r['missions']['code']['checks']['kind']=='not_retryable'
    with pytest.raises(StateError):q.control('retry','code')
    assert len(s.submissions)==1



def test_cli_report_cannot_overwrite_file_created_during_operation(tmp_path,monkeypatch):
    import mission_control.cli as cli
    output=tmp_path/'report.json'
    async def operation(args):
        output.write_text('concurrent user file')
        return {'stage':'completed'}
    monkeypatch.setattr(cli,'execute',operation)
    assert cli.main(['doctor','--output',str(output)])==1
    assert output.read_text()=='concurrent user file'


def test_migration_report_cannot_overwrite_handoff_marker(tmp_path):
    from mission_control.cli import main
    from mission_control.queue import MissionQueue
    from test_queue import text_job
    old=MissionQueue(tmp_path/'old.json');old.add(text_job('a',project=str(tmp_path)))
    destination=tmp_path/'q.sqlite3';marker=tmp_path/'old.json.migration.json'
    assert main(['queue-migrate','--queue',str(destination),'--legacy-queue',str(old.path),'--output',str(marker)])==1
    assert not destination.exists()
