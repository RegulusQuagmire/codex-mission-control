from test_desktop_gui import app, Bridge, empty, qt_slot_exceptions
from test_stage12_core import mission

def test_stage12_mission_filters_preserve_identity_and_disable_hidden_actions(app):
    from mission_control.desktop.missions import MissionsPage
    bridge=Bridge();page=MissionsPage(bridge);data=empty()
    data['missions']=[mission('a'),mission('b',status='failed')]
    page.update_data(data);page.table.selectRow(0)
    page.search.setText('mission b');app.processEvents()
    assert [j['id'] for j in page.jobs]==['b']
    assert page.selected() is None and not page.cancel_button.isEnabled()
    page.search.clear();page.status_filter.selectData('failed');app.processEvents()
    assert [j['id'] for j in page.jobs]==['b']
    assert not bridge.calls and len(data['missions'])==2
    page.close()


def test_stage12_limits_show_unknown_age_and_pause_reason(app):
    from mission_control.desktop.insights import LimitsPage
    page=LimitsPage(Bridge());data=empty();data['paused']=True
    page.update_data(data)
    assert 'неизвестно' in page.freshness.text()
    assert 'паузе' in page.pause_state.text()
    assert 'не гарантировано' in page.credits.text()
    page.close()
