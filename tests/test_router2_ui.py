import time
from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from test_desktop_gui import app,Bridge
from test_router2_service import inspection_service
from mission_control.desktop.router import RouterPage
from mission_control.desktop.i18n import set_language

def prepare(app,tmp_path):
    facade=inspection_service(tmp_path)
    bridge=Bridge();page=RouterPage(bridge)
    page.update_data(facade.snapshot());page.show();app.processEvents()
    return page,bridge,facade

def test_inspection_ui_only_requests_read_only_action_and_blocks_duplicate(app,tmp_path):
    page,bridge,facade=prepare(app,tmp_path)
    QTest.mouseClick(page.preview_button,Qt.LeftButton)
    QTest.mouseClick(page.preview_button,Qt.LeftButton)
    assert bridge.calls==[('inspect_route',{'identity':'demo'})]
    bridge.result.emit('inspect_route',facade.inspect_route('demo'));app.processEvents()
    assert facade.inspect_route('demo')['decision']['model'] in page.recommendation.toPlainText()
    assert page.preview_button.isEnabled()

def test_policy_changed_while_reply_pending_discards_stale_preview(app,tmp_path):
    page,bridge,facade=prepare(app,tmp_path)
    QTest.mouseClick(page.preview_button,Qt.LeftButton)
    stale=facade.inspect_route('demo')
    facade.save_preferences({'modelPolicies':{'gpt-6-luna':{'maxEffort':'low','automaticEnabled':False}}})
    page.update_data(facade.snapshot());bridge.result.emit('inspect_route',stale);app.processEvents()
    assert page.preview_result is None
    assert stale['decision']['model'] not in page.recommendation.toPlainText()

def test_language_switch_keeps_ids_and_retranslates_explanation(app,tmp_path):
    set_language('ru')
    page,bridge,facade=prepare(app,tmp_path)
    bridge.result.emit('inspect_route',facade.inspect_route('demo'));app.processEvents()
    ru=page.recommendation.toPlainText();set_language('en');app.processEvents()
    en=page.recommendation.toPlainText()
    assert ru!=en and 'gpt-6-luna' in ru and 'gpt-6-luna' in en
    assert 'Reasoning effort' in en
    set_language('ru')

def test_expiring_metadata_invalidates_inspection_without_backend_call(app,tmp_path):
    page,bridge,facade=prepare(app,tmp_path)
    value=facade.inspect_route('demo');value['expiresAt']=time.time()-.1
    bridge.result.emit('inspect_route',value);page.expire_preview()
    assert page.preview_result is None
    assert bridge.calls==[]

def test_catalog_change_and_mission_removal_clear_selection_preview(app,tmp_path):
    page,bridge,facade=prepare(app,tmp_path)
    bridge.result.emit('inspect_route',facade.inspect_route('demo'))
    data=facade.snapshot();data['missions']=[];page.update_data(data)
    assert page.preview_result is None and not page.preview_button.isEnabled()

def test_history_adjustment_names_actual_evidence_in_ui(app,tmp_path):
    from mission_control.history import History
    from mission_control.route_inspection import inspect_mission
    from mission_control.routing import Complexity
    from test_router2_service import included_limits
    set_language('en');page,bridge,facade=prepare(app,tmp_path)
    history=History()
    for i in range(8):history.record_once(str(i),'gpt-6-luna','low',Complexity.LOW,False)
    value=inspect_mission(facade.snapshot(),'demo',history,included_limits(),time.time())
    bridge.result.emit('inspect_route',value)
    assert value['decision']['history']['adjusted']
    text=page.recommendation.toPlainText()
    assert 'gpt-6-luna' in text and '8 failed' in text
    set_language('ru')

def test_inspection_shows_actual_mission_mode_not_new_mission_preference(app,tmp_path):
    set_language('en');page,bridge,facade=prepare(app,tmp_path)
    value=facade.inspect_route('demo')
    assert value['decision']['mode']=='economy'
    bridge.result.emit('inspect_route',value)
    assert 'Selected mission mode: Economy' in page.recommendation.toPlainText()
    set_language('ru')

def test_keyboard_activation_uses_same_read_only_action(app,tmp_path):
    page,bridge,facade=prepare(app,tmp_path)
    page.preview_button.setFocus(Qt.TabFocusReason)
    QTest.keyClick(page.preview_button,Qt.Key_Space)
    assert bridge.calls==[('inspect_route',{'identity':'demo'})]
