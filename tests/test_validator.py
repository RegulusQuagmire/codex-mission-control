import asyncio
import json
from pathlib import Path
import sys

import pytest
from mission_control import validator as v
from operator_actions import validate_with_confirmation
from mission_control.state import StateError, load_state, save_state


def spec(tmp_path, *, command=None):
    source=tmp_path/'source';source.mkdir()
    (source/'app.py').write_text('VALUE = 1\n',encoding='utf-8')
    (source/'check.py').write_text('from app import VALUE\nassert VALUE == 2\n',encoding='utf-8')
    return {'project':str(source),'inputFiles':['app.py','check.py'],
            'writeFiles':['app.py'],'requireChanges':True,'contains':{'app.py':['VALUE = 2']},
            'commands':[{'name':'tests','kind':'test','argv':command or [sys.executable,'check.py'],
                         'timeout':5,'approved':True}]}


def test_actual_files_and_command_exit_determine_result_and_source_is_untouched(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    result=asyncio.run(validate_with_confirmation(root,s,'t1',json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})))
    assert result['passed'] and result['commands'][0]['exitCode']==0
    assert result['changes']==['app.py'] and '+VALUE = 2' in (root/'result.diff').read_text()
    assert (Path(s['project'])/'app.py').read_text()=='VALUE = 1\n'


def test_success_is_not_inferred_from_ready_message(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    r=asyncio.run(validate_with_confirmation(root,s,'t1','Done!'))
    assert not r['passed'] and r['kind']=='test_failure'
    assert not r['commands']


@pytest.mark.parametrize('name',['../app.py','/app.py','C:/app.py','a/../../x','a\\x','CON','a:ads','AUX.txt','.git/config','APP.py.'])
def test_unsafe_paths_are_rejected(name,tmp_path):
    s=spec(tmp_path);s['writeFiles']=[name]
    with pytest.raises(StateError):v.check_spec(s)


def test_unapproved_command_and_duplicate_case_paths_rejected(tmp_path):
    s=spec(tmp_path);s['commands'][0]['approved']=False
    with pytest.raises(StateError):v.check_spec(s)
    s['commands'][0]['approved']=True;s['inputFiles'].append('APP.py')
    with pytest.raises(StateError):v.check_spec(s)


def test_protected_file_is_not_writable_by_model(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    r=asyncio.run(validate_with_confirmation(root,s,'t1',json.dumps({'edits':[{'path':'check.py','content':'pass'}]})))
    assert not r['passed'] and r['kind']=='not_retryable'
    assert (root/'workspace'/'check.py').read_text().startswith('from app')


def test_partial_edit_envelope_never_applies_any_edits(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    edits=[{'path':'app.py','content':'changed'},{'path':'../escape','content':'x'}]
    r=asyncio.run(validate_with_confirmation(root,s,'t1',json.dumps({'edits':edits})))
    assert not r['passed'] and (root/'workspace'/'app.py').read_text()=='VALUE = 1\n'


def test_started_receipt_is_not_replayed(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    receipt=v.receipt_path(root,'t1');save_state(receipt,{'phase':'started'})
    r=asyncio.run(validate_with_confirmation(root,s,'t1','{}'))
    assert not r['passed'] and r['kind']=='not_retryable'
    assert 'uncertain' in r['feedback'].lower()


def test_finished_receipt_does_not_repeat_command(tmp_path):
    s=spec(tmp_path,command=[sys.executable,'-c',"from pathlib import Path; p=Path('counter'); p.write_text(str(int(p.read_text())+1) if p.exists() else '1')"])
    root=tmp_path/'run';v.prepare(root,s)
    text=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    first=asyncio.run(validate_with_confirmation(root,s,'t1',text))
    second=asyncio.run(validate_with_confirmation(root,s,'t1',text))
    assert first==second and (root/'workspace'/'counter').read_text()=='1'


def test_failed_tests_and_timeout_are_real_failures(tmp_path):
    s=spec(tmp_path,command=[sys.executable,'-c','raise SystemExit(7)']);root=tmp_path/'run';v.prepare(root,s)
    text=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    r=asyncio.run(validate_with_confirmation(root,s,'t1',text))
    assert not r['passed'] and r['commands'][0]['exitCode']==7
    s['commands']=[{'name':'hang','kind':'build','argv':[sys.executable,'-c','import time; time.sleep(30)'],'timeout':0.1,'approved':True}]
    root=tmp_path/'timeout-run';v.prepare(root,s)
    r=asyncio.run(validate_with_confirmation(root,s,'t2',text))
    assert not r['passed'] and r['commands'][0]['timedOut']


def test_source_drift_stops_before_commands(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    (Path(s['project'])/'app.py').write_text('USER CHANGE',encoding='utf-8')
    r=asyncio.run(validate_with_confirmation(root,s,'t1',json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})))
    assert not r['passed'] and r['kind']=='not_retryable' and not r['commands']
    assert (Path(s['project'])/'app.py').read_text()=='USER CHANGE'


def test_linked_input_is_rejected(tmp_path):
    s=spec(tmp_path);p=Path(s['project'])/'app.py';p.unlink()
    try:p.symlink_to(Path(s['project'])/'check.py')
    except OSError:pytest.skip('Symlink privilege unavailable')
    with pytest.raises(StateError):v.prepare(tmp_path/'run',s)


def test_commands_cannot_invalidate_content_after_precheck(tmp_path):
    s=spec(tmp_path,command=[sys.executable,'-c',"from pathlib import Path; Path('app.py').write_text('BROKEN')"])
    root=tmp_path/'run';v.prepare(root,s)
    text=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    r=asyncio.run(validate_with_confirmation(root,s,'t1',text))
    assert not r['passed']


def test_receipt_cannot_validate_different_model_response(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    text=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    assert asyncio.run(validate_with_confirmation(root,s,'t1',text))['passed']
    assert not asyncio.run(validate_with_confirmation(root,s,'t1','Done'))['passed']


def test_finished_receipt_cannot_hide_workspace_changes(tmp_path):
    s=spec(tmp_path);root=tmp_path/'run';v.prepare(root,s)
    text=json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})
    assert asyncio.run(validate_with_confirmation(root,s,'t1',text))['passed']
    (root/'workspace'/'app.py').write_text('USER EDIT')
    assert not asyncio.run(validate_with_confirmation(root,s,'t1',text))['passed']


def test_successful_command_cannot_delete_a_writable_file(tmp_path):
    s=spec(tmp_path,command=[sys.executable,'-c',"from pathlib import Path; Path('app.py').unlink()"]);s['contains']={}
    root=tmp_path/'run';v.prepare(root,s)
    r=asyncio.run(validate_with_confirmation(root,s,'t1',json.dumps({'edits':[{'path':'app.py','content':'VALUE = 2\n'}]})))
    assert not r['passed'] and r['kind']=='not_retryable'


def test_windows_junction_input_is_rejected_without_symlink_privilege(tmp_path):
    import os
    import subprocess
    if os.name!='nt':pytest.skip('Windows junction test')
    s=spec(tmp_path);outside=tmp_path/'outside';outside.mkdir();(outside/'file.py').write_text('secret')
    junction=Path(s['project'])/'linked'
    result=subprocess.run(['cmd','/c','mklink','/J',str(junction),str(outside)],capture_output=True)
    if result.returncode!=0:pytest.skip('Junction creation unavailable')
    s['inputFiles'].append('linked/file.py')
    try:
        with pytest.raises(StateError):v.prepare(tmp_path/'run',s)
    finally:junction.rmdir()
