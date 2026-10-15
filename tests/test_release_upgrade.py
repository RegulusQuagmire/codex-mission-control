"""Cross-revision fixture producers are real immutable public source exports."""
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
STAGE14='b394f4b1f23b8913d7def0ab6eaaa39cc96972b6'


@pytest.fixture(scope='module')
def old_source(tmp_path_factory):
    parent=tmp_path_factory.mktemp('upgrade-source');old=parent/'old'
    result=subprocess.run([sys.executable,str(ROOT/'tools/export_upgrade_baseline.py'),str(old)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return old


@pytest.fixture(scope='module')
def stage14_source(tmp_path_factory):
    old=tmp_path_factory.mktemp('upgrade-stage14')/'old'
    result=subprocess.run([sys.executable,str(ROOT/'tools/export_upgrade_baseline.py'),
        str(old),'--revision',STAGE14],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return old


@pytest.mark.parametrize('case',['basic','submitted','lost_ack','result_approval'])
def test_old_070_writer_to_candidate_071_reader(old_source,tmp_path,case):
    if os.name!='nt':pytest.skip('Windows protected upgrade test')
    root=tmp_path/'case';driver=ROOT/'tools/upgrade_fixture.py'
    old=subprocess.run([sys.executable,str(driver),'seed',str(root),'--case',case],
                       env={**os.environ,'PYTHONPATH':str(old_source/'src')},capture_output=True,text=True,timeout=45)
    assert old.returncode==0,old.stderr
    assert json.loads(old.stdout)['producerVersion']=='0.7.0'
    current=subprocess.run([sys.executable,str(driver),'verify',str(root)],
                       env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=45)
    assert current.returncode==0,current.stderr
    report=json.loads(current.stdout)
    assert report['consumerVersion']=='0.7.1' and report['newMockSubmissions']==0


@pytest.mark.parametrize('case',['waiting_resume','project_dag'])
def test_stage14_writer_preserves_exact_consent_and_project_authority(stage14_source,tmp_path,case):
    if os.name!='nt':pytest.skip('Windows protected upgrade test')
    root=tmp_path/'case';driver=ROOT/'tools/upgrade_fixture.py'
    producer=subprocess.run([sys.executable,str(driver),'seed',str(root),'--case',case],
        env={**os.environ,'PYTHONPATH':str(stage14_source/'src')},capture_output=True,text=True,timeout=60)
    assert producer.returncode==0,producer.stderr
    produced=json.loads(producer.stdout)
    assert produced['producerVersion']=='0.7.0' and produced['producerRevision']==STAGE14
    consumer=subprocess.run([sys.executable,str(driver),'verify',str(root)],
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=60)
    assert consumer.returncode==0,consumer.stderr
    report=json.loads(consumer.stdout)
    assert report['consumerVersion']=='0.7.1' and report['producerRevision']==STAGE14
    assert report['protectedDocumentsPreserved'] and report['preferencesPreserved']
    if case=='waiting_resume':
        assert report['invalidConsentRejected']==4
        assert report['continuationTurnId']=='paused-1'
        assert report['newMockSubmissions']==1 and report['queuePausePreserved']
        assert report['checkpointPreserved'] and report['repeatResumeRejected']
    else:
        assert report['newMockSubmissions']==0
        assert report['dependenciesPreserved'] and report['accessApprovalsPreserved']
        assert report['resultApprovalRequired'] and report['planAuthorityPreserved']
