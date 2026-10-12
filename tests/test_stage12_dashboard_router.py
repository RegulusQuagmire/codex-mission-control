from test_desktop_gui import app, Bridge, empty, qt_slot_exceptions
from test_stage12_core import mission

def test_stage12_dashboard_explains_next_action_without_empty_cards(app):
    from mission_control.desktop.window import MainWindow
    window=MainWindow(Bridge(),system_integration=False);window.update_snapshot(empty())
    assert window.control_banner.title.text()
    assert window.queue_metrics.values['pending'].text()=='0'
    assert all(card.isHidden() for _,_,card in window.queue_cards)
    data=empty();data['missions']=[mission(status='needs_attention')];data['active']='a'
    window.update_snapshot(data)
    assert window.control_banner.property('fluentSeverity')=='danger'
    assert not window.run_button.isEnabled()
    window.close()


def test_stage12_router_inspection_never_changes_backend_selection(app):
    from mission_control.desktop.router import RouterPage
    bridge=Bridge();page=RouterPage(bridge);data=empty()
    data['models']=[{'model':'actual','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]
    page.update_data(data);page.network.model_inspected.emit('actual')
    assert page.catalog.currentData()=='actual'
    assert 'actual' in page.inspection.toPlainText()
    assert not bridge.calls
    page.close()


def test_stage12_missing_model_inspection_survives_refresh(app):
    from mission_control.desktop.router import RouterPage
    bridge=Bridge();page=RouterPage(bridge);data=empty()
    data['models']=[{'model':'present','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]
    data['missions']=[mission(status='running',model={'model':'missing','effort':'low'})];data['active']='a'
    page.update_data(data);page.inspect_model('missing');page.update_data(data)
    assert page.network.inspected=='missing'
    assert page.catalog.currentData()=='missing'
    assert not page.effort.isEnabled() and not bridge.calls
    page.close()


def test_stage12_manual_active_mode_is_not_balanced(app):
    from mission_control.desktop.router import RouterPage
    page=RouterPage(Bridge());data=empty();data['active']='a'
    data['missions']=[mission(status='running',mode='balanced',manual={'model':'x','effort':'low'})]
    page.update_data(data)
    from mission_control.desktop.i18n import enum_label
    assert str(enum_label('manual')) in page.route_state.title.text()
    page.close()
