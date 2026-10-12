import asyncio
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import pytest
from PySide6.QtWidgets import QApplication,QWizard,QDialog
from mission_control.desktop.service import DesktopService
from mission_control.desktop.settings import SetupWizard
from mission_control.queue import MissionQueue
from mission_control.state import StateError
from test_desktop_gui import Bridge
from test_managed import Service

@pytest.fixture(scope='session')
def app():
    return QApplication.instance() or QApplication([])


def test_discovery_finds_packaged_app_without_path(tmp_path,monkeypatch):
    from mission_control.desktop.discovery import resolve_codex
    install=tmp_path/'WindowsApps'/'OpenAI.Codex_1.2.3_x64__test'/'app'/'resources'/'codex.exe'
    install.parent.mkdir(parents=True);install.write_bytes(b'executable')
    monkeypatch.setenv('ProgramFiles',str(tmp_path))
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path/'local'))
    monkeypatch.setenv('APPDATA',str(tmp_path/'roaming'))
    monkeypatch.setenv('ProgramW6432',str(tmp_path))
    monkeypatch.setenv('ProgramFiles(x86)',str(tmp_path))
    monkeypatch.setattr('shutil.which',lambda name:None)
    assert resolve_codex('codex')==str(install)


def test_discovery_honors_explicit_path_and_does_not_fallback(tmp_path,monkeypatch):
    from mission_control.desktop.discovery import resolve_codex
    installed=tmp_path/'codex.exe';installed.write_bytes(b'executable')
    monkeypatch.setattr('shutil.which',lambda name:str(installed) if name=='codex' else None)
    with pytest.raises(StateError,match='Codex'):
        resolve_codex(str(tmp_path/'missing.exe'))
    assert resolve_codex(str(installed))==str(installed)


def test_discovery_finds_newest_openai_versioned_install(tmp_path,monkeypatch):
    from mission_control.desktop.discovery import resolve_codex
    old=tmp_path/'OpenAI/Codex/bin/ffff/codex.exe'
    new=tmp_path/'OpenAI/Codex/bin/aaaa/codex.exe'
    for path,timestamp in ((old,100),(new,200)):
        path.parent.mkdir(parents=True);path.write_bytes(b'executable');os.utime(path,(timestamp,timestamp))
    monkeypatch.setenv('LOCALAPPDATA',str(tmp_path))
    monkeypatch.setattr('shutil.which',lambda name:None)
    assert resolve_codex('codex')==str(new)


def test_setup_rejects_root_before_connection_and_preferences(tmp_path):
    facade=DesktopService(MissionQueue(tmp_path/'state'/'q.sqlite3'))
    facade.initialize()
    result=asyncio.run(facade.complete_setup('codex',str(tmp_path)))
    assert result['status']=='error' and result['kind']=='workspace'
    assert not facade.preferences()['setupComplete']
    assert facade.snapshot()['roots']==[]


def test_setup_success_persists_roots_and_preferences_together(tmp_path):
    project=tmp_path/'project';project.mkdir();server=Service()
    facade=DesktopService(MissionQueue(tmp_path/'state'/'q.sqlite3'),factory_for_cwd=lambda cwd:server.factory)
    facade.initialize()
    result=asyncio.run(facade.complete_setup('codex',str(project)))
    assert result['status']=='connected'
    assert facade.preferences()['setupComplete']
    assert facade.snapshot()['roots']==[str(project.resolve())]
    assert not server.submissions


def test_setup_failure_never_persists_or_overwrites_previous_preferences(tmp_path):
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def offline():
        raise OSError('unavailable')
        yield
    project=tmp_path/'project';project.mkdir()
    facade=DesktopService(MissionQueue(tmp_path/'state'/'q.sqlite3'),factory_for_cwd=lambda cwd:offline)
    facade.initialize();facade.save_preferences({'codex':'original'})
    result=asyncio.run(facade.complete_setup('new',str(project)))
    assert result['status']=='error' and result['kind']=='connection'
    assert facade.preferences()['codex']=='original'
    assert not facade.preferences()['setupComplete'] and facade.snapshot()['roots']==[]


def test_setup_cannot_be_bypassed_by_preferences(tmp_path):
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'));facade.initialize()
    with pytest.raises(StateError):facade.save_preferences({'setupComplete':True})
    assert not facade.preferences()['setupComplete']


def test_setup_transaction_rolls_back_on_preference_write_failure(tmp_path,monkeypatch):
    project=tmp_path/'project';project.mkdir();server=Service()
    facade=DesktopService(MissionQueue(tmp_path/'state'/'q.sqlite3'),factory_for_cwd=lambda cwd:server.factory)
    facade.initialize();store=facade.queue.journal();original=store.write
    def fail(connection,key,value):
        if key=='gui-preferences':raise StateError('Simulated storage failure')
        return original(connection,key,value)
    monkeypatch.setattr(store,'write',fail)
    result=asyncio.run(facade.complete_setup('codex',str(project)))
    assert result['status']=='error'
    assert facade.snapshot()['roots']==[] and not facade.preferences()['setupComplete']
    assert not store.exists('approvals')


def test_setup_requires_authentication_without_marking_complete(tmp_path):
    project=tmp_path/'project';project.mkdir();server=Service()
    async def account():return {'requiresOpenaiAuth':True}
    server.account=account
    facade=DesktopService(MissionQueue(tmp_path/'state'/'q.sqlite3'),factory_for_cwd=lambda cwd:server.factory)
    facade.initialize();result=asyncio.run(facade.complete_setup('codex',str(project)))
    assert result['status']=='auth_required'
    assert not facade.preferences()['setupComplete'] and facade.snapshot()['roots']==[]


def test_probe_keeps_selected_path_unsaved_and_reports_executable_failure(tmp_path):
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'));facade.initialize()
    result=asyncio.run(facade.probe_connection(str(tmp_path/'missing.exe')))
    assert result['status']=='error' and result['kind']=='executable'
    assert facade.preferences()['codex']=='codex'


def test_reduced_motion_setting_round_trips_through_settings(app,tmp_path):
    from mission_control.desktop.settings import SettingsPage
    facade=DesktopService(MissionQueue(tmp_path/'q.sqlite3'));facade.initialize()
    bridge=Bridge();settings=SettingsPage(bridge);settings.update_data(facade.snapshot())
    settings.reduced_motion.setChecked(True);settings.save()
    operation,values=bridge.calls[-1]
    facade.save_preferences(**values)
    assert operation=='save_preferences' and facade.preferences()['reducedMotion'] is True
    settings.update_data(facade.snapshot());assert settings.reduced_motion.isChecked()
    settings.close()


def test_bridge_dispatches_atomic_setup_operation(app,tmp_path):
    from mission_control.desktop.bridge import BackendBridge
    project=tmp_path/'project';project.mkdir();server=Service()
    bridge=BackendBridge(tmp_path/'state'/'q.sqlite3')
    bridge.service=DesktopService(MissionQueue(bridge.path),factory_for_cwd=lambda cwd:server.factory)
    bridge.service.initialize();results=[];errors=[]
    bridge.result.connect(lambda action,value:results.append((action,value)))
    bridge.error.connect(errors.append)
    asyncio.run(bridge._dispatch('complete_setup',{'codex':'codex','root':str(project)}))
    assert not errors and results[0][0]=='complete_setup'
    assert results[0][1]['status']=='connected' and bridge.service.preferences()['setupComplete']


def test_wizard_waits_for_backend_and_failure_stays_open(app,tmp_path):
    bridge=Bridge();wizard=SetupWizard(bridge,{});wizard.show();wizard.next()
    wizard.root.setText(str(tmp_path));wizard.accept()
    assert wizard.isVisible()
    assert bridge.calls[-1][0]=='complete_setup'
    assert bridge.calls[-1][1]=={'codex':'codex','root':str(tmp_path),'_request_token':wizard._request_token}
    bridge.result.emit('complete_setup',{'status':'error','kind':'workspace','message':'Папка недоступна','_requestToken':wizard._request_token})
    assert wizard.isVisible() and 'Папка недоступна' in wizard.status.text()
    wizard.accept();bridge.result.emit('complete_setup',{'status':'connected','message':'Codex подключён','_requestToken':wizard._request_token})
    assert wizard.result()==QDialog.Accepted
    wizard.close()


def test_wizard_uses_russian_buttons_and_read_only_probe(app):
    bridge=Bridge();wizard=SetupWizard(bridge,{})
    for key in (QWizard.BackButton,QWizard.NextButton,QWizard.FinishButton,QWizard.CancelButton):
        assert wizard.buttonText(key).replace('&','') in {'Назад','Далее','Готово','Отмена'}
    wizard.codex.setText('chosen');wizard.check()
    assert bridge.calls==[('probe_connection',{'codex':'chosen','_request_token':wizard._request_token})]
    bridge.result.emit('probe_connection',{'status':'connected','message':'Проверено','_requestToken':wizard._request_token})
    wizard.close()
