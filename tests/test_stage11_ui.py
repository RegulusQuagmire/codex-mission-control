"""Offline Qt integration; the real service/queue/managed chain uses a synthetic remote."""
import asyncio
from copy import deepcopy

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from test_desktop_gui import app, Bridge, empty, qt_slot_exceptions
from test_queue import text_job
from test_stage11_backend_service import paused_service


@pytest.fixture(autouse=True)
def russian_ui():
    from mission_control.desktop.i18n import set_language
    set_language('ru')
    yield
    set_language('ru')


def pause_value(checkpoint='Settings <b>opaque</b> Настройки', turn='turn-demo'):
    job=text_job('demo',project='C:/OfflineDemo',maxAttempts=3)
    job.update(status='waiting_resume',dispatchStarted=True,sequence=0,runPath='offline-only')
    attempt={'phase':'paused_turn','turnId':turn,'checkpoint':checkpoint,
        'decision':{'model':'demo-model','effort':'low'},'pauseReceipt':{
            'threadId':'thread-demo','turnId':turn,'terminalConfirmed':True,
            'phase':'terminal_interrupted','reason':'user_pause'}}
    run={'stage':'waiting_resume','threadId':'thread-demo','attempts':[attempt]}
    job['live']=deepcopy(run)
    return {'mission':job,'run':run}


def pause_snapshot(value=None,*,paused=False):
    data=empty();data.update(active='demo',paused=paused)
    data['missions']=[deepcopy((value or pause_value())['mission'])]
    return data


@pytest.mark.parametrize('phase,receipt,approved,expected',[
    ('submitted',None,False,'running'),
    ('submitted','steer_requested',False,'soft_stop_requested'),
    ('submitted','steer_acknowledged',False,'soft_stop_requested'),
    ('submitted','interrupt_requested',False,'interrupt_requested'),
    ('submitted','interrupt_acknowledged',False,'interrupt_requested'),
    ('submitted','interrupt_unavailable_or_unknown',False,'stop_unconfirmed'),
    ('paused_turn','terminal_interrupted',False,'checkpoint_review'),
    ('paused_turn','terminal_completed',False,'checkpoint_review'),
    ('paused_turn','terminal_interrupted',True,'continuation_authorized'),
    ('completed_unvalidated',None,False,'turn_ended'),
])
def test_state_codes_distinguish_receipts_from_terminal_confirmation(phase,receipt,approved,expected):
    from mission_control.desktop.presentation import control_state
    value=pause_value();job=value['mission'];attempt=job['live']['attempts'][-1]
    attempt['phase']=phase
    job['status']='running' if phase!='paused_turn' else 'paused'
    job['live']['stage']='submitted' if phase=='submitted' else 'waiting_resume' if phase=='paused_turn' else phase
    if receipt:attempt['pauseReceipt'].update(phase=receipt,terminalConfirmed=phase=='paused_turn')
    else:attempt.pop('pauseReceipt')
    if approved:attempt['continuationApproved']=attempt['turnId']
    data=pause_snapshot(value,paused=phase=='paused_turn');data['workerRunning']=phase=='submitted'
    assert control_state(data)['code']==expected
    assert control_state(data)['mission_id']=='demo'


def test_unknown_outcome_wins_over_queue_pause_and_checkpoint(app):
    from mission_control.desktop.presentation import control_state
    value=pause_value();value['mission']['live']['stage']='needs_attention'
    data=pause_snapshot(value,paused=True)
    assert control_state(data)['code']=='outcome_unknown'
    assert control_state(data)['severity']=='danger'


@pytest.mark.parametrize('outer', ['waiting_resume','paused'])
def test_missions_resume_opens_checkpoint_review_and_filter_keeps_identity(app,outer):
    from mission_control.desktop.missions import MissionsPage
    bridge=Bridge();page=MissionsPage(bridge);value=pause_value();value['mission']['status']=outer
    data=pause_snapshot(value,paused=True);page.update_data(data);page.table.selectRow(0)
    assert page.resume_button.isEnabled()
    page.resume_button.click()
    assert bridge.calls==[('result',{'identity':'demo'})]
    page.status_filter.selectData('waiting_resume');app.processEvents()
    assert [j['id'] for j in page.jobs]==['demo']
    page.search.setText('no matching mission');app.processEvents()
    assert page.selected() is None and not page.resume_button.isEnabled()
    page.control('resume');assert len(bridge.calls)==1


def test_stage10_plain_paused_mission_keeps_ordinary_resume(app):
    from mission_control.desktop.missions import MissionsPage
    value=pause_value();value['mission'].pop('live');value['mission']['status']='paused'
    bridge=Bridge();page=MissionsPage(bridge);page.update_data(pause_snapshot(value));page.table.selectRow(0)
    page.resume_button.click();assert bridge.calls==[('resume_mission',{'identity':'demo'})]


@pytest.mark.parametrize('language',['ru','en'])
def test_checkpoint_consent_requires_reading_and_sends_exact_turn_once(app,language):
    from mission_control.desktop.i18n import set_language
    from mission_control.desktop.approvals import ResultDialog
    set_language(language);bridge=Bridge();value=pause_value(('opaque {"id":"Settings"}\n'*500))
    dialog=ResultDialog(value,bridge);dialog.resize(800,600);dialog.show();app.processEvents()
    assert dialog.checkpoint_view.toPlainText()==value['run']['attempts'][-1]['checkpoint']
    dialog.continue_paused();assert not bridge.calls
    dialog.pause_consent.setChecked(True);assert not dialog.continue_button.isEnabled()
    dialog.checkpoint_view.verticalScrollBar().setValue(dialog.checkpoint_view.verticalScrollBar().maximum())
    app.processEvents();assert dialog.continue_button.isEnabled()
    dialog.continue_paused();dialog.continue_paused()
    assert bridge.calls==[('resume_mission',{'identity':'demo','acknowledge_uncertain':True,'expected_turn_id':'turn-demo'})]


def test_live_language_switch_never_translates_checkpoint_or_grants_consent(app):
    from mission_control.desktop.approvals import ResultDialog
    from mission_control.desktop.i18n import set_language
    dialog=ResultDialog(pause_value(),Bridge());dialog.show();app.processEvents()
    before=dialog.checkpoint_view.toPlainText();set_language('en');app.processEvents()
    assert dialog.checkpoint_view.toPlainText()==before
    assert not dialog.pause_consent.isChecked() and not dialog.continue_button.isEnabled()
    dialog.pause_consent.setChecked(True);app.processEvents();set_language('ru');app.processEvents()
    assert dialog.pause_consent.isChecked() and dialog.continue_button.isEnabled()


@pytest.mark.parametrize('change',['turn','checkpoint','removed','approved','unknown','cancel','auth','submitted'])
def test_snapshot_change_permanently_invalidates_open_checkpoint_consent(app,change):
    from mission_control.desktop.approvals import ResultDialog
    bridge=Bridge();dialog=ResultDialog(pause_value(),bridge);dialog.show();app.processEvents()
    dialog.pause_consent.setChecked(True);assert dialog.continue_button.isEnabled()
    data=pause_snapshot();attempt=data['missions'][0]['live']['attempts'][-1]
    if change=='turn':attempt['turnId']='new-turn'
    elif change=='checkpoint':attempt['checkpoint']='New evidence'
    elif change=='removed':data['missions']=[]
    elif change=='approved':attempt['continuationApproved']='turn-demo'
    elif change=='unknown':data['missions'][0]['live']['stage']='needs_attention'
    elif change=='cancel':data['missions'][0]['cancelRequested']=True
    else:data['missions'][0]['live']['stage']='auth_required' if change=='auth' else 'submitted'
    bridge.snapshot.emit(data);app.processEvents()
    assert not dialog.continue_button.isEnabled() and not dialog.pause_consent.isChecked()
    bridge.snapshot.emit(pause_snapshot());dialog.pause_consent.setChecked(True)
    dialog.continue_paused();assert not bridge.calls


@pytest.mark.parametrize('malformed',['empty','missing_id','unconfirmed'])
def test_empty_checkpoint_warns_and_unconfirmed_evidence_cannot_continue(app,malformed):
    from mission_control.desktop.approvals import ResultDialog
    value=pause_value('');attempt=value['run']['attempts'][-1]
    if malformed=='missing_id':attempt.pop('turnId')
    if malformed=='unconfirmed':attempt['pauseReceipt']['terminalConfirmed']=False
    bridge=Bridge();dialog=ResultDialog(value,bridge);dialog.show();app.processEvents()
    assert dialog.checkpoint_warning.text()
    dialog.pause_consent.setChecked(True);app.processEvents()
    if malformed!='empty':assert not dialog.continue_button.isEnabled()
    else:assert dialog.continue_button.isEnabled()


def test_dashboard_limits_overlay_and_approvals_agree_on_checkpoint_wait(app):
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.overlay import MissionOverlay
    bridge=Bridge();window=MainWindow(bridge,system_integration=False);data=pause_snapshot(paused=True)
    window.update_snapshot(data);overlay=MissionOverlay(bridge,lambda:None);overlay.update_data(data)
    title=window.control_banner.title.text()
    assert 'checkpoint' in title.lower()
    assert overlay.control_status.text()==title
    assert title in window.limits.pause_state.text()
    assert window.urgent_action.isVisibleTo(window.pages.widget(0))
    assert window.queue_metrics.values['approval'].text()=='1'
    assert not window.run_button.isEnabled()
    window.urgent_action.click();assert window.navigation.currentRow()==3
    assert window.approvals.selected()['id']=='demo'
    window.approvals.review_button.click();assert bridge.calls==[('result',{'identity':'demo'})]
    overlay.close();window.close()


def test_keyboard_checkpoint_path_reaches_real_service_queue_and_managed_runner(app,tmp_path,monkeypatch):
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.approvals import ResultDialog
    from test_stage11_backend_service import saved_run
    facade,remote=paused_service(tmp_path,monkeypatch)
    facade.control('pause')

    class ServiceBridge(Bridge):
        def request(self,operation,**values):
            super().request(operation,**values)
            if operation=='result':self.result.emit(operation,facade.result(**values))
            elif operation=='resume_mission':
                asyncio.run(facade.resume_mission(**values));self.snapshot.emit(facade.snapshot())
            elif operation=='resume_queue':
                asyncio.run(facade.resume_queue());self.snapshot.emit(facade.snapshot())
            else:raise AssertionError(operation)

    bridge=ServiceBridge();window=MainWindow(bridge,system_integration=False)
    window.update_snapshot(facade.snapshot());window.show();window.navigation.setCurrentRow(1)
    window.missions.table.selectRow(0);window.missions.resume_button.click();app.processEvents()
    dialog=next(d for d in window.findChildren(ResultDialog) if d.isVisible())
    assert len(remote.submissions)==1
    dialog.checkpoint_view.verticalScrollBar().setValue(dialog.checkpoint_view.verticalScrollBar().maximum())
    dialog.pause_consent.setFocus();QTest.keyClick(dialog.pause_consent,Qt.Key_Space);app.processEvents()
    assert dialog.continue_button.isEnabled()
    QTest.keyClick(dialog.continue_button,Qt.Key_Space);app.processEvents()
    assert saved_run(facade)['attempts'][-1]['continuationApproved']=='paused-1'
    assert len(remote.submissions)==1  # Whole queue pause still applies.
    window.resume_button.click();app.processEvents()
    assert len(remote.submissions)==2 and saved_run(facade)['stage']=='completed'
    assert remote.submissions[0][0]==remote.submissions[1][0]
    assert not any(op=='approve_result' for op,_ in bridge.calls)
    window.close()


@pytest.mark.parametrize('stage',['needs_attention','submitted'])
def test_open_review_cannot_authorize_unknown_or_unreconciled_run(app,stage):
    from mission_control.desktop.approvals import ResultDialog
    value=pause_value();value['run']['stage']=stage
    bridge=Bridge();dialog=ResultDialog(value,bridge);dialog.show();app.processEvents()
    dialog.pause_consent.setChecked(True);dialog.continue_paused()
    assert not bridge.calls and not dialog.continue_button.isEnabled()


def test_already_authorized_checkpoint_is_read_only_and_clearly_identified(app):
    from mission_control.desktop.approvals import ResultDialog
    value=pause_value();value['run']['attempts'][-1]['continuationApproved']='turn-demo'
    dialog=ResultDialog(value,Bridge());dialog.show();app.processEvents()
    assert not dialog.pause_consent.isEnabled()
    assert 'разрешено' in dialog.checkpoint_status.text()
    assert not dialog.continue_button.isEnabled()


def test_urgent_action_uses_one_target_when_execution_and_checkpoint_reviews_coexist(app):
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.i18n import tr
    data=pause_snapshot();execution=deepcopy(data['missions'][0])
    execution.update(id='execution',title='Execution review',status='waiting_approval',live={'stage':'waiting_approval','attempts':[]},attempts=[])
    data['missions'].insert(0,execution);data['active']='execution'
    bridge=Bridge();window=MainWindow(bridge,system_integration=False);window.update_snapshot(data)
    assert window.urgent_action.text()==str(tr('Открыть подтверждения'))
    window.urgent_action.click();assert window.approvals.selected()['id']=='execution'
    window.approvals.review_button.click()
    assert bridge.calls==[('review_result',{'identity':'execution'})]
    window.close()


def test_urgent_unknown_stop_opens_exact_mission_log_without_resume(app):
    from mission_control.desktop.window import MainWindow
    data=pause_snapshot();job=data['missions'][0];job['status']='running'
    job['live']['stage']='waiting_network';attempt=job['live']['attempts'][-1]
    attempt['phase']='submitted';attempt['pauseReceipt'].update(phase='interrupt_acknowledged',terminalConfirmed=False)
    bridge=Bridge();window=MainWindow(bridge,system_integration=False);window.update_snapshot(data)
    assert not window.urgent_action.isHidden()
    window.urgent_action.click()
    assert bridge.calls==[('result',{'identity':'demo'})]
    window.close()


@pytest.mark.parametrize('outer',['running','paused','waiting_approval'])
def test_live_unknown_outcome_updates_metrics_approvals_and_blocks_start(app,outer):
    from mission_control.desktop.window import MainWindow
    data=pause_snapshot(paused=False);job=data['missions'][0]
    job.update(status=outer);job['live']['stage']='needs_attention'
    bridge=Bridge();window=MainWindow(bridge,system_integration=False);window.update_snapshot(data)
    assert window.queue_metrics.values['attention'].text()=='1'
    assert window.queue_metrics.values['approval'].text()=='0'
    assert not window.run_button.isEnabled()
    assert window.approvals.selected()['id']=='demo'
    assert not window.approvals.review_button.isEnabled()
    window.approvals.inspect_button.click()
    assert bridge.calls==[('result',{'identity':'demo'})]
    window.close()


def test_approved_policy_wait_can_resume_after_mission_pause_via_checkpoint_ui(app,tmp_path,monkeypatch):
    import time
    from mission_control.queue import QueueWorker
    from mission_control.credit_policy import check_credit_limits
    from mission_control.desktop.approvals import ResultDialog
    from test_credit_policy import limits
    from test_stage11_backend_service import saved_run
    facade,remote=paused_service(tmp_path,monkeypatch)
    async def credit_gate(model,*,limits=None):
        return check_credit_limits(limits,model,observed_at=time.time())
    remote.credit_gate=credit_gate;remote.limits=None
    facade.control('resume','mission',acknowledge_uncertain=True,expected_turn_id='paused-1')
    asyncio.run(QueueWorker(facade.queue,lambda cwd:remote.factory).run(max_wait=0))
    assert saved_run(facade)['stage']=='waiting_credit'
    facade.control('pause','mission');asyncio.run(facade.start())
    remote.limits=limits()
    # Expire only the synthetic wait; no wall-clock delay or real account is used.
    from mission_control.state import load_state,save_state
    from pathlib import Path
    with facade.queue.storage():
        path=Path(facade.queue.read()['missions']['mission']['runPath'])
        run=load_state(path);run.pop('nextCheckAt',None);save_state(path,run)
    class ServiceBridge(Bridge):
        def request(self,operation,**values):
            super().request(operation,**values)
            assert operation=='resume_mission'
            asyncio.run(facade.resume_mission(**values))
    bridge=ServiceBridge();dialog=ResultDialog(facade.result('mission'),bridge);dialog.show();app.processEvents()
    assert dialog.pause_consent.isEnabled()
    dialog.pause_consent.setChecked(True);dialog.continue_paused()
    assert not facade.queue.read()['missions']['mission']['pauseRequested']
    assert saved_run(facade)['stage']=='completed' and len(remote.submissions)==2
