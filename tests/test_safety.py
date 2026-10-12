from pathlib import Path
import asyncio
import os
import subprocess
import pytest
from mission_control.queue import MissionQueue
from mission_control.state import StateError, load_state
from mission_control.safety import configure, approve, authorize, reject_secrets, redact
from mission_control.checkpoints import create, verify, export
from test_queue import text_job


def test_explicit_approval_bound_to_definition_and_roots(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('a',project=str(project)))
    job=q.read()['missions']['a']
    with pytest.raises(StateError):authorize(q,job)
    configure(q,[str(project)] )
    with pytest.raises(StateError):authorize(q,job)
    approve(q,'a');authorize(q,job)
    job['task']['text']='different'
    with pytest.raises(StateError):authorize(q,job)
    with pytest.raises(StateError):configure(q,[str(tmp_path)])


def test_policy_frozen_during_active_mission(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('a',project=str(project)))
    configure(q,[str(project)]);approve(q,'a')
    with q.storage():
        data=q.read();data['active']='a';q._save(data)
    with pytest.raises(StateError):configure(q,[str(project)])
    with pytest.raises(StateError):approve(q,'a')


def test_secret_detection_and_diagnostic_redaction(monkeypatch):
    monkeypatch.setenv('EXAMPLE_API_KEY','private-value-123456789')
    for value in ['password = "supersecretvalue"','sk-proj-'+'x'*30,'private-value-123456789','{"password":"supersecretvalue"}']:
        with pytest.raises(StateError):reject_secrets(value)
        assert value not in redact(value)
    reject_secrets('def password_is_valid(): return True')


def test_checkpoint_does_not_touch_user_git_and_exports_new_only(tmp_path):
    user=tmp_path/'user';user.mkdir()
    subprocess.run(['git','init',str(user)],check=True,capture_output=True)
    (user/'a.txt').write_text('staged')
    subprocess.run(['git','-C',str(user),'add','a.txt'],check=True)
    (user/'a.txt').write_text('unstaged');(user/'loose.txt').write_text('untracked')
    index=(user/'.git/index').read_bytes()
    root=tmp_path/'run';(root/'workspace').mkdir(parents=True)
    (root/'workspace/a.txt').write_text('baseline')
    snapshot={'baseline':{'a.txt':'baseline','new.txt':None},'project':str(user)}
    create(root,snapshot);verify(root,snapshot)
    (root/'workspace/a.txt').write_text('changed')
    verify(root,snapshot)
    dest=tmp_path/'export';export(root,snapshot,dest,[user])
    assert (dest/'a.txt').read_text()=='baseline' and not (dest/'new.txt').exists()
    assert (user/'.git/index').read_bytes()==index
    assert (user/'a.txt').read_text()=='unstaged' and (user/'loose.txt').read_text()=='untracked'
    with pytest.raises(StateError):export(root,snapshot,dest,[user])
    with pytest.raises(StateError):export(root,snapshot,user/'new',[user])
    receipt=load_state(root/'checkpoint.json')
    subprocess.run(['git','--git-dir',str(root/'checkpoint.git'),'update-ref','-d','refs/checkpoints/baseline'],check=True)
    with pytest.raises(StateError):verify(root,snapshot)


def test_command_approval_cannot_be_reused_for_changed_argv(tmp_path):
    from test_validator import spec
    criteria=spec(tmp_path)
    q=MissionQueue(tmp_path/'q.sqlite3')
    q.add({'id':'a','title':'A','type':'project','project':criteria['project'],
           'task':{'text':'Change constant'},'criteria':criteria})
    configure(q,[criteria['project']]);approve(q,'a')
    job=q.read()['missions']['a'];authorize(q,job)
    job['criteria']['commands'][0]['argv'].append('different')
    with pytest.raises(StateError):authorize(q,job)


def test_obvious_secret_file_rejected_before_snapshot(tmp_path):
    from mission_control import validator
    from test_validator import spec
    criteria=spec(tmp_path);source=Path(criteria['project'])
    (source/'app.py').write_text('password = "secretvalue123456"')
    with pytest.raises(StateError):validator.prepare(tmp_path/'run',criteria)
    assert not (tmp_path/'run/workspace').exists()


def test_nested_checkpoint_and_poisoned_git_environment(tmp_path,monkeypatch):
    user_index=tmp_path/'user-index';user_index.write_bytes(b'untouched')
    monkeypatch.setenv('GIT_INDEX_FILE',str(user_index));monkeypatch.setenv('GIT_DIR',str(tmp_path/'user-git'))
    root=tmp_path/'run';root.mkdir()
    snapshot={'baseline':{'folder/a.txt':'nested','empty.txt':''},'project':str(tmp_path/'source')}
    create(root,snapshot);verify(root,snapshot)
    assert user_index.read_bytes()==b'untouched' and not (tmp_path/'user-git').exists()


def test_unknown_settings_fail_closed(tmp_path):
    project=tmp_path/'project';project.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('a',project=str(project)))
    configure(q,[str(project)]);approve(q,'a')
    q.journal().save('settings',{'version':1,'allowedRoots':[str(project)],'password':'not-supported'})
    with pytest.raises(StateError):authorize(q,q.read()['missions']['a'])


def test_secret_in_quoted_task_is_rejected_before_queue_persistence(tmp_path):
    q=MissionQueue(tmp_path/'q.sqlite3')
    job=text_job('a',project=str(tmp_path));job['task']['text']='password = "secretvalue123456"'
    with pytest.raises(StateError):q.add(job)
    assert not q.path.exists()


def test_root_change_and_approval_revocation_are_one_transaction(tmp_path,monkeypatch):
    first=tmp_path/'first';first.mkdir();second=tmp_path/'second';second.mkdir()
    q=MissionQueue(tmp_path/'q.sqlite3');q.add(text_job('a',project=str(first)))
    configure(q,[str(first)]);approve(q,'a');store=q.journal()
    before=store.load('settings');write=store.write
    def fail(c,key,data):
        if key=='approvals':raise StateError('simulated interrupted revocation')
        return write(c,key,data)
    monkeypatch.setattr(store,'write',fail)
    with pytest.raises(StateError):configure(q,[str(second)])
    assert store.load('settings')==before
    authorize(q,q.read()['missions']['a'])
