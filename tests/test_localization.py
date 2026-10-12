import importlib.util
import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture
def application():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def reset_language_and_capture_qt_errors(monkeypatch):
    from mission_control.desktop.i18n import set_language
    import sys
    errors=[]
    monkeypatch.setattr(sys,'excepthook',lambda kind,value,trace:errors.append((kind,value)))
    set_language('ru')
    yield
    set_language('ru')
    assert not errors,errors


def test_localization_is_available_and_russian_by_default():
    assert importlib.util.find_spec('mission_control.desktop.i18n') is not None
    from mission_control.desktop.i18n import language, tr, set_language
    set_language('ru')
    assert language() == 'ru'
    assert str(tr('Настройки')) == 'Настройки'


def test_live_switch_preserves_user_text_and_combo_identity(application):
    from mission_control.desktop.i18n import tr, set_language
    from mission_control.desktop.localized_widgets import QLabel, QLineEdit, QComboBox
    set_language('ru')
    label = QLabel(tr('Настройки'))
    user = QLineEdit('Настройки')
    combo = QComboBox(); combo.addItem(tr('Сбалансированная'), 'balanced')
    set_language('en')
    assert label.text() == 'Settings'
    assert user.text() == 'Настройки'
    assert combo.currentText() == 'Balanced'
    assert combo.currentData() == 'balanced'
    set_language('ru')
    assert label.text() == 'Настройки'


def test_language_persistence_and_old_preferences(tmp_path):
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    from mission_control.state import StateError
    queue = MissionQueue(tmp_path / 'language.sqlite3')
    service = DesktopService(queue); service.initialize()
    assert service.preferences()['language'] == 'ru'
    original = service.save_preferences({'theme': 'light', 'maxAttempts': 5})
    # Existing pre-localization records have no language field.
    queue.journal().save('gui-preferences', {k:v for k,v in original.items() if k != 'language'})
    assert service.preferences()['language'] == 'ru'
    service.save_preferences({'language': 'en'})
    restored = DesktopService(MissionQueue(queue.path)).preferences()
    assert restored['language'] == 'en'
    assert restored['theme'] == 'light' and restored['maxAttempts'] == 5
    with pytest.raises(StateError): service.save_preferences({'language': 'de'})


def test_catalog_coverage_placeholders_and_missing_keys():
    from mission_control.desktop.i18n import CATALOG, tr, set_language
    from string import Formatter
    assert CATALOG
    for source, values in CATALOG.items():
        assert set(values) == {'ru', 'en'} and all(values.values()), source
        fields = lambda s: [f for _,f,_,_ in Formatter().parse(s) if f is not None]
        assert fields(values['ru']) == fields(values['en']), source
    set_language('en')
    assert str(tr('missing.translation.key')) == '[missing.translation.key]'
    assert str(tr('Модель')) == 'Model'
    set_language('ru')


def test_security_warnings_keep_scope_in_both_languages():
    from mission_control.desktop.i18n import tr, set_language
    from mission_control.desktop.approvals import WARNING
    set_language('en')
    warning = str(WARNING)
    assert 'Windows user' in warning and 'isolation' in warning
    set_language('ru')
    assert 'правами' in str(WARNING) and 'отсутствует' in str(WARNING)


def test_long_checkbox_wraps_without_changing_native_toggle(application):
    from mission_control.desktop.localized_widgets import QCheckBox
    from mission_control.desktop.i18n import tr, set_language
    set_language('ru')
    checkbox = QCheckBox(tr('Я понимаю риск и разрешаю выполнение этой версии с правами моего пользователя Windows'))
    assert checkbox.hasHeightForWidth()
    assert checkbox.heightForWidth(250) > checkbox.heightForWidth(900)
    checkbox.click(); assert checkbox.isChecked()


def test_dynamic_controller_diagnostics_are_localized_without_changing_ids():
    from mission_control.desktop.i18n import message_text, set_language
    set_language('ru')
    source = 'LOW: chose gpt-6-luna / low (economy); scoped text/document operation; observed validated outcomes=2 success/1 failure; personal model policy applied'
    text = str(message_text(source))
    assert 'выбрана' in text and 'gpt-6-luna' in text and 'chose' not in text
    set_language('en')
    text = str(message_text('Рабочая папка: Allowed root must exist'))
    assert text == 'Working directory: Allowed root must exist'
    set_language('ru')


def test_tray_status_updates_and_live_language_switch(application):
    from test_desktop_gui import Bridge, empty
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.tray import DesktopIntegration
    from mission_control.desktop.i18n import set_language
    set_language('ru')
    bridge = Bridge(); window = MainWindow(bridge, system_integration=False)
    integration = DesktopIntegration(window, bridge)
    try:
        data = empty(); data['preferences']['hotkey'] = ''; window.update_snapshot(data)
        integration.update_data(data)
        assert 'Готово' in integration.tray.toolTip()
        set_language('en')
        assert 'Done' in integration.tray.toolTip()
        assert 'Open Mission Control' in [a.text() for a in integration.tray.contextMenu().actions()]
    finally:
        integration.closing = True; integration.finished(); window.close(); set_language('ru')


def test_switching_language_does_not_reset_unsaved_settings(application):
    from copy import deepcopy
    from test_desktop_gui import Bridge, empty
    from mission_control.desktop.window import MainWindow
    bridge=Bridge(); window=MainWindow(bridge,system_integration=False)
    data=empty(); data['preferences']['language']='ru'; window.update_snapshot(data)
    window.settings.codex.setText('my-unsaved-codex.exe')
    window.settings.theme.selectData('light')
    window.settings.language.selectData('en')
    translated=deepcopy(data);translated['preferences']['language']='en'
    window.update_snapshot(translated)
    assert window.settings.codex.text()=='my-unsaved-codex.exe'
    assert window.settings.theme.currentData()=='light'
    assert window.navigation.item(6).text()=='Settings'
    window.close()
    from mission_control.desktop.i18n import set_language
    set_language('ru')


def test_default_dashboard_and_overlay_translate_effort(application):
    from test_desktop_gui import Bridge, empty
    from mission_control.desktop.window import MainWindow
    from mission_control.desktop.overlay import MissionOverlay
    data=empty();data['missions']=[{'id':'demo','title':'User title','project':'C:/Demo',
        'status':'running','priority':1,'sequence':0,'dependsOn':[],
        'model':{'model':'gpt-6-luna','effort':'low'},'dispatchStarted':True,'maxAttempts':3}]
    data['active']='demo'
    window=MainWindow(Bridge(),system_integration=False);window.update_snapshot(data)
    overlay=MissionOverlay(Bridge(),lambda:None);overlay.update_data(data)
    assert 'Низкий' in window.active_summary.text()
    assert 'Низкий' in overlay.summary.text()
    assert 'gpt-6-luna' in overlay.summary.text()
    window.close();overlay.close()


def test_every_literal_translation_key_has_both_languages():
    import ast
    from pathlib import Path
    from mission_control.desktop import i18n
    for path in Path(i18n.__file__).parent.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='tr' and node.args and isinstance(node.args[0],ast.Constant):
                assert node.args[0].value in i18n.CATALOG,(path.name,node.lineno,node.args[0].value)


def test_qt_standard_actions_follow_language(application):
    from PySide6.QtCore import QCoreApplication
    from mission_control.desktop.i18n import set_language
    set_language('ru')
    assert QCoreApplication.translate('QPlatformTheme','Cancel')=='Отмена'
    set_language('en')
    assert QCoreApplication.translate('QPlatformTheme','Cancel')=='Cancel'
    set_language('ru')


def test_missing_language_falls_back_to_russian_and_arguments_stay_opaque(monkeypatch):
    from mission_control.desktop.i18n import tr, set_language, CATALOG
    monkeypatch.setitem(CATALOG,'test.fallback',{'ru':'Значение: {value}','en':''})
    set_language('en')
    assert str(tr('test.fallback',value='gpt-6-luna {user text}'))=='Значение: gpt-6-luna {user text}'
    set_language('ru')


def test_mission_definition_keeps_protocol_values_after_switch(application):
    from mission_control.desktop.missions import MissionDialog, CommandDialog
    from mission_control.desktop.i18n import set_language
    model={'model':'gpt-6-luna','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}
    dialog=MissionDialog([],{},[model]);dialog.mode.selectData('manual')
    dialog.title.setText('Настройки');dialog.description.setPlainText('Settings: user text')
    before=dialog.definition();set_language('en');after=dialog.definition()
    before.pop('id');after.pop('id')  # A new mission gets a fresh UUID on each definition().
    assert before==after
    assert after['manual']=={'model':'gpt-6-luna','effort':'low'}
    command=CommandDialog();command.kind.setCurrentIndex(2)
    assert command.value()['kind']=='lint'
    dialog.close();command.close();set_language('ru')


def test_live_result_approval_does_not_grant_permission(application):
    from test_desktop_gui import Bridge
    from mission_control.desktop.approvals import ResultApprovalDialog
    from mission_control.desktop.i18n import set_language
    bridge=Bridge()
    value={'missionId':'demo','diff':'untrusted content Настройки',
           'review':{'spec':{'commands':[]},'reviewId':'exact-review'},'sources':{'code.py':'print(1)'}}
    dialog=ResultApprovalDialog(value,bridge)
    assert not dialog.approve_button.isEnabled()
    set_language('en')
    assert not dialog.approve_button.isEnabled() and not dialog.consent.isChecked()
    assert not dialog.viewed and dialog.viewer.toPlainText()=='untrusted content Настройки'
    assert not bridge.calls
    dialog.close();set_language('ru')


def test_deleted_retry_dialog_disconnects_language_callback(application):
    from PySide6.QtCore import Qt, QCoreApplication, QEvent
    from test_desktop_gui import Bridge
    from mission_control.desktop.approvals import ResultDialog
    from mission_control.desktop.i18n import set_language
    job={'id':'uncertain','title':'User title','project':'C:/Demo','status':'failed',
         'type':'text','attempts':[{'phase':'failed','decision':{'model':'gpt-6-luna','effort':'low'},
         'validation':{'kind':'not_retryable','passed':False}}]}
    dialog=ResultDialog({'mission':job},Bridge())
    dialog.setAttribute(Qt.WA_DeleteOnClose);dialog.show();application.processEvents();dialog.close()
    QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)
    set_language('en');application.processEvents();set_language('ru')


def test_repopulated_combo_retains_accessibility_and_tooltip_bindings(application):
    from mission_control.desktop.localized_widgets import QComboBox
    from mission_control.desktop.i18n import tr, set_language
    combo=QComboBox();combo.setAccessibleName(tr('Модель'));combo.setToolTip(tr('Модель'))
    combo.addItem(tr('Настройки'));combo.clear();combo.addItem(tr('Настройки'))
    set_language('en')
    assert combo.accessibleName()==combo.toolTip()=='Model'
    assert combo.currentText()=='Settings'


def test_diagnostic_filename_and_unknown_output_remain_opaque():
    from mission_control.desktop.i18n import message_text
    for prefix in ('Required file content missing: ', 'Required file content missing after checks: '):
        assert str(message_text(prefix+'validated')).endswith(': validated')
        assert str(message_text(prefix+'Настройки; validated')).endswith(': Настройки; validated')
    assert str(message_text('command output; validated'))=='command output; validated'
