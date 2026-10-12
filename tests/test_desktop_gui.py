import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
import time
from PySide6.QtCore import QObject,Signal,Qt
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest


@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def qt_slot_exceptions(monkeypatch):
    import sys
    errors=[]
    monkeypatch.setattr(sys,'excepthook',lambda kind,value,traceback:errors.append((kind,value)))
    yield
    assert not errors,f'Unhandled Qt slot exceptions: {errors}'


class Bridge(QObject):
    snapshot=Signal(dict)
    error=Signal(str)
    result=Signal(str,object)
    stopped=Signal()
    def __init__(self):
        super().__init__();self.calls=[]
    def request(self,operation,**values):self.calls.append((operation,values))


def empty():
    return {'missions':[],'active':None,'paused':False,'workerRunning':False,
            'connection':{'status':'error','message':'Offline'},'models':[],
            'limits':{'windows':[]},'preferences':{'theme':'dark'},'roots':[],'account':{},'limitHistory':[]}


def wait_until(app,predicate,timeout=10000):
    deadline=time.monotonic()+timeout/1000
    while not predicate() and time.monotonic()<deadline:
        # QtTest's C++ wait can retain the Python GIL on Windows. Real app.exec()
        # releases it; explicitly yield here so the Python backend QThread runs.
        app.processEvents();time.sleep(.01)
    assert predicate()


def test_real_bridge_metadata_queue_updates_shutdown_and_restart(app,tmp_path,monkeypatch):
    from mission_control.desktop.bridge import BackendBridge
    from mission_control.desktop.window import MainWindow
    from mission_control.safety import fingerprint
    from test_managed import Service
    from test_queue import text_job
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    project=tmp_path/'project';project.mkdir();service=Service();service.outcomes=['2']
    from mission_control.managed import ManagedRunner
    runner_errors=[];original_drive=ManagedRunner._drive
    async def traced_drive(self,*args,**kwargs):
        try:return await original_drive(self,*args,**kwargs)
        except Exception as error:runner_errors.append(repr(error));raise
    monkeypatch.setattr(ManagedRunner,'_drive',traced_drive)
    bridge=BackendBridge(tmp_path/'gui.sqlite3',factory_for_cwd=lambda cwd:service.factory)
    window=MainWindow(bridge,system_integration=False);snapshots=[];results=[];errors=[]
    bridge.snapshot.connect(snapshots.append);bridge.result.connect(lambda action,value:results.append((action,value)))
    bridge.error.connect(errors.append);bridge.start();window.show()
    try:
        wait_until(app,lambda:bool(snapshots))
        bridge.request('refresh_connection');wait_until(app,lambda:bool(window.router.models))
        assert window.router.catalog.count()>0
        bridge.request('configure_roots',roots=[str(project)])
        bridge.request('add',definition=text_job('a',project=str(project),priority=9))
        wait_until(app,lambda:bool(window.missions.jobs))
        bridge.request('access_review',identity='a')
        wait_until(app,lambda:any(a=='access_review' for a,v in results))
        view=next(v for a,v in results if a=='access_review')
        from mission_control.desktop.approvals import AccessDialog
        dialog=window.findChildren(AccessDialog)[0]
        dialog.viewer.verticalScrollBar().setValue(dialog.viewer.verticalScrollBar().maximum())
        dialog.consent.setChecked(True);QTest.mouseClick(dialog.approve_button,Qt.LeftButton)
        wait_until(app,lambda:any(a=='approve_access' for a,v in results))
        QTest.mouseClick(window.run_button,Qt.LeftButton)
        wait_until(app,lambda:window.missions.jobs[0]['status'] in {'completed','needs_attention'},20000)
        assert window.missions.jobs[0]['status']=='completed',runner_errors
        assert window.missions.jobs[0]['priority']==9 and len(service.submissions)==1
        assert not errors
    finally:
        for child in window.findChildren(__import__('PySide6.QtWidgets',fromlist=['QDialog']).QDialog):child.close()
        bridge.request('shutdown');wait_until(app,lambda:not bridge.isRunning());window.close()
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    restored=DesktopService(MissionQueue(tmp_path/'gui.sqlite3')).snapshot()
    assert restored['missions'][0]['status']=='completed'


def test_real_gui_result_review_executes_only_after_explicit_click(app,tmp_path,monkeypatch):
    from test_sqlite_queue import project_queue
    from mission_control.desktop.bridge import BackendBridge
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.approvals import ResultApprovalDialog
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    q,service=project_queue(tmp_path)
    bridge=BackendBridge(q.path,factory_for_cwd=lambda cwd:service.factory)
    window=MainWindow(bridge,system_integration=False);errors=[];bridge.error.connect(errors.append)
    bridge.start();window.show()
    try:
        wait_until(app,lambda:bool(window.data))
        QTest.mouseClick(window.run_button,Qt.LeftButton)
        wait_until(app,lambda:window.missions.jobs[0]['status']=='waiting_approval' and not window.data['workerRunning'],20000)
        last=window.missions.jobs[0]['attempts'][-1]
        assert last['phase']=='completed_unvalidated' and 'validation' not in last
        from mission_control.validator import receipt_path
        from mission_control.state import load_state
        from pathlib import Path
        with q.storage():
            receipt=load_state(receipt_path(Path(window.missions.jobs[0]['runPath']).parent,last['turnId']))
        assert receipt['phase']=='awaiting_approval' and 'executionApproval' not in receipt
        bridge.request('review_result',identity='code')
        wait_until(app,lambda:bool(window.findChildren(ResultApprovalDialog)))
        dialog=window.findChildren(ResultApprovalDialog)[0]
        assert not dialog.approve_button.isEnabled()
        for index in range(dialog.sections.count()):
            dialog.sections.setCurrentRow(index);app.processEvents()
            dialog.viewer.verticalScrollBar().setValue(dialog.viewer.verticalScrollBar().maximum())
            QTest.mouseClick(dialog.read_button,Qt.LeftButton)
        assert len(dialog.viewed)==len(dialog.contents),(dialog.viewed,dialog.progress.text())
        dialog.consent.setChecked(True);assert dialog.approve_button.isEnabled()
        QTest.mouseClick(dialog.approve_button,Qt.LeftButton)
        wait_until(app,lambda:window.missions.jobs[0]['status']=='completed',20000)
        assert len(service.submissions)==1 and not errors
        assert (tmp_path/'source/app.py').read_text()=='VALUE = 1\n'
    finally:
        for dialog in window.findChildren(ResultApprovalDialog):dialog.close()
        bridge.request('shutdown');wait_until(app,lambda:not bridge.isRunning());window.close()


def test_shutdown_requested_during_initialization_is_not_lost(app,tmp_path,monkeypatch):
    import threading
    from mission_control.desktop.bridge import BackendBridge
    from mission_control.desktop.service import DesktopService
    entered=threading.Event();release=threading.Event();original=DesktopService.initialize
    def slow(self):
        entered.set();assert release.wait(5);return original(self)
    monkeypatch.setattr(DesktopService,'initialize',slow)
    bridge=BackendBridge(tmp_path/'startup.sqlite3');bridge.start()
    try:
        wait_until(app,entered.is_set);bridge.request('shutdown');release.set()
        wait_until(app,lambda:bridge._closing)
        wait_until(app,lambda:not bridge.isRunning())
    finally:
        release.set()
        if bridge.isRunning():bridge.request('shutdown');wait_until(app,lambda:not bridge.isRunning())


def test_paused_approval_controls_require_real_approval_state(app):
    from mission_control.desktop.window import MainWindow
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    data=empty();data['paused']=True;data['active']='a'
    job={'id':'a','title':'A','project':'X','status':'waiting_approval','priority':0,'sequence':0,
        'dependsOn':[],'dispatchStarted':True,'attempts':[],'archives':[],'maxAttempts':3,'executionApproved':False}
    data['missions']=[job];bridge.snapshot.emit(data)
    assert not window.resume_button.isEnabled()
    job['executionApproved']=True;bridge.snapshot.emit(data)
    assert window.resume_button.isEnabled()
    QTest.mouseClick(window.resume_button,Qt.LeftButton)
    assert bridge.calls[-1][0]=='resume_queue';window.close()


def test_dashboard_has_no_fabricated_limits_and_remains_responsive(app):
    from mission_control.desktop.window import MainWindow
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    window.show();bridge.snapshot.emit(empty());app.processEvents()
    assert 'Нет данных' in window.limit_summary.text()
    assert 'Offline' in window.connection.text()
    QTest.mouseClick(window.run_button,Qt.LeftButton)
    assert bridge.calls[-1][0]=='start'
    assert window.isVisible()
    window.close()


def test_overlay_expand_pin_and_update_without_activation(app):
    from mission_control.desktop.overlay import MissionOverlay
    bridge=Bridge();overlay=MissionOverlay(bridge,lambda:None)
    overlay.show();app.processEvents();overlay.update_data(empty())
    assert overlay.testAttribute(Qt.WA_ShowWithoutActivating)
    assert overlay.windowFlags() & Qt.WindowDoesNotAcceptFocus
    height=overlay.height();overlay.toggle_compact();app.processEvents()
    assert overlay.height()!=height
    overlay.set_pinned(False)
    assert not (overlay.windowFlags() & Qt.WindowStaysOnTopHint)
    overlay.move(120,90);assert overlay.pos().x()==120
    overlay.close()


def test_hotkey_parser_rejects_unsafe_or_invalid_combinations():
    from mission_control.desktop.windows import parse_hotkey
    assert parse_hotkey('Ctrl+Shift+M')==(2|4|0x4000,ord('M'))
    with pytest.raises(ValueError):parse_hotkey('M')
    with pytest.raises(ValueError):parse_hotkey('Ctrl+Ctrl+M')


def test_quota_reset_outside_os_date_range_does_not_break_ui(app):
    from mission_control.desktop.widgets import limits_text
    text=limits_text({'windows':[{'kind':'weekly','limitId':'codex','usedPercent':20,'remainingPercent':80,'resetsAt':1e300}]})
    assert '80%' in text and 'Нет достоверного времени' in text


def test_windows_hotkey_conflict_is_reported_and_hook_is_released(app):
    if os.name!='nt':pytest.skip('Windows API')
    from mission_control.desktop.windows import WindowsIntegration
    first=WindowsIntegration(app);second=WindowsIntegration(app);warnings=[]
    second.warning.connect(warnings.append)
    try:
        key=next((k for k in ['Ctrl+Alt+F11','Ctrl+Alt+F10','Ctrl+Alt+F9'] if first.set_hotkey(k)),None)
        assert key is not None,'No test hotkey could be registered'
        assert not second.set_hotkey(key) and warnings
        first.set_monitoring(True);assert first.monitoring and isinstance(first.is_codex_foreground(),bool)
        first.close();assert not first.registered and first.hook is None
    finally:first.close();second.close()


def test_foreground_detection_uses_process_location_not_window_title(monkeypatch):
    from mission_control.desktop.windows import codex_image
    monkeypatch.setenv('LOCALAPPDATA','C:/Users/test/AppData/Local')
    assert codex_image('C:/Users/test/AppData/Local/OpenAI/Codex/app/Codex.exe')
    assert not codex_image('C:/Unknown/Codex.exe')
    assert not codex_image('Codex — a window title')


@pytest.mark.parametrize('scale',['1','1.5','2'])
def test_native_layout_and_fonts_at_dpi_scales(tmp_path,scale):
    import subprocess,sys,textwrap
    code=textwrap.dedent('''
        from pathlib import Path
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QFont,QRawFont
        from PySide6.QtCore import QObject,Signal,Qt
        from mission_control.desktop.window import MainWindow
        from mission_control.desktop.service import DesktopService
        from mission_control.queue import MissionQueue
        class Bridge(QObject):
            snapshot=Signal(dict);result=Signal(str,object);error=Signal(str);stopped=Signal()
            def request(self,*args,**kwargs):pass
        app=QApplication([]);bridge=Bridge();window=MainWindow(bridge,system_integration=False)
        window.resize(800,600);window.show()
        bridge.snapshot.emit(DesktopService(MissionQueue(Path('unused-dpi.sqlite3').absolute())).snapshot())
        app.processEvents()
        assert QRawFont.fromFont(QFont('Segoe UI',10)).supportsCharacter(0x42F)
        for page in range(window.pages.count()):
            window.navigation.setCurrentRow(page);app.processEvents()
            assert window.width()==800,(page,window.width(),window.minimumSizeHint().width())
        assert window.devicePixelRatioF()>=SCALE
        window.close()
    ''').replace('SCALE',scale)
    environment={**os.environ,'QT_QPA_PLATFORM':'offscreen','QT_SCALE_FACTOR':scale}
    result=subprocess.run([sys.executable,'-B','-c',code],capture_output=True,text=True,env=environment,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


def test_limit_policy_defaults_are_real_and_settings_round_trip_intent(app):
    from mission_control.desktop.window import MainWindow
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    data=empty();bridge.snapshot.emit(data)
    assert 'Нет данных' in window.limits.detail.toPlainText()
    window.settings.theme.selectData('light');window.settings.save()
    assert bridge.calls[-1][0]=='save_preferences'
    assert bridge.calls[-1][1]['values']['theme']=='light'
    window.close()


def test_approval_requires_all_review_sections_and_explicit_consent(app):
    from mission_control.desktop.approvals import ResultApprovalDialog
    bridge=Bridge();value={'missionId':'a','review':{'reviewId':'current','spec':{'commands':[]}},
        'sources':{'app.py':'print(1)','check.py':'assert True'},'diff':'diff'}
    dialog=ResultApprovalDialog(value,bridge)
    assert not dialog.approve_button.isEnabled()
    dialog.consent.setChecked(True)
    assert not dialog.approve_button.isEnabled()
    dialog.show()
    for index in range(dialog.sections.count()):
        dialog.sections.setCurrentRow(index);app.processEvents();dialog.mark_viewed()
    assert dialog.approve_button.isEnabled()
    QTest.mouseClick(dialog.approve_button,Qt.LeftButton)
    assert bridge.calls[-1]==('approve_result',{'identity':'a','review_id':'current','accept_user_rights':True})
    dialog.close()


def test_queue_editor_builds_real_definition_and_dependencies(app,tmp_path):
    from mission_control.desktop.missions import MissionDialog
    dialog=MissionDialog([],{'mode':'economy','policy':'weekly','maxAttempts':2},[])
    dialog.project.setText(str(tmp_path));dialog.title.setText('Translate')
    dialog.description.setPlainText('Return only hello')
    dialog.kind.setCurrentIndex(1);dialog.expected.setText('hello');dialog.priority.setValue(5)
    value=dialog.definition()
    assert value['type']=='text' and value['priority']==5 and value['mode']=='economy'
    assert value['project']==str(tmp_path) and value['maxAttempts']==2


def test_queue_selection_uncertain_disables_normal_retry(app):
    from mission_control.desktop.window import MainWindow
    bridge=Bridge();window=MainWindow(bridge,system_integration=False)
    data=empty();data['missions']=[{'id':'a','title':'A','project':'X','status':'failed',
        'priority':0,'sequence':0,'dependsOn':[],'generation':0,'dispatchStarted':True,
        'attempts':[{'phase':'validated','decision':{'model':'advertised','effort':'low'},'validation':{'passed':False,'kind':'not_retryable'}}],
        'checks':{'kind':'not_retryable'},'archives':[],'maxAttempts':3}]
    bridge.snapshot.emit(data);window.missions.table.selectRow(0);app.processEvents()
    assert not window.missions.retry_button.isEnabled()
    assert window.missions.ack_button.isEnabled()
    QTest.mouseClick(window.pause_button,Qt.LeftButton)
    assert bridge.calls[-1]==('control',{'action':'pause'})
    window.close()
