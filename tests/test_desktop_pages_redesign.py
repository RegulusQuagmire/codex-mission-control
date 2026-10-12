"""Factual summaries and selection-aware actions on redesigned desktop pages."""
from test_desktop_gui import app,Bridge,empty,qt_slot_exceptions


def test_analytics_summary_counts_observations_without_invented_models(app):
    from mission_control.desktop.insights import AnalyticsPage
    page=AnalyticsPage();data=empty();page.update_data(data)
    assert page.metrics['attempts'].text()=='0'
    assert page.model_distribution.rowCount()==0
    assert not page.empty_state.isHidden()
    data['missions']=[{'title':'Actual mission','status':'completed','attempts':[
        {'decision':{'model':'from-codex'},'validation':{'passed':True}},
        {'decision':{'model':'from-codex'},'validation':{'passed':False,'kind':'execution_approval_required'}}]}]
    page.update_data(data)
    assert page.metrics['missions'].text()=='1'
    assert page.metrics['completed'].text()=='1'
    assert page.metrics['attempts'].text()=='2'
    assert page.model_distribution.item(0,0).text()=='from-codex'
    assert page.model_distribution.item(0,1).text()=='2'
    assert '0 не пройдено' in page.validation_summary.text()
    assert '1 ожидают разрешения' in page.validation_summary.text()
    assert 'Actual mission' in page.detail.toPlainText()


def test_limits_keep_missing_and_each_observed_window_separate(app):
    from mission_control.desktop.insights import LimitsPage
    bridge=Bridge();page=LimitsPage(bridge);data=empty()
    data['limits']['windows']=[{'kind':'weekly','limitId':'one','usedPercent':20,'remainingPercent':80,'resetsAt':None},
        {'kind':'weekly','limitId':'two','usedPercent':None,'remainingPercent':None,'resetsAt':None}]
    page.update_data(data)
    assert 'Нет данных' in page.window_labels['five_hour'].text()
    weekly=page.window_labels['weekly'].text()
    assert 'one: 80% осталось' in weekly and 'two: Нет данных' in weekly
    assert '5 часов' not in weekly
    assert 'Offline' in page.availability.text()


def test_router_exposes_only_received_catalog_and_supported_efforts(app):
    from mission_control.desktop.router import RouterPage
    bridge=Bridge();page=RouterPage(bridge);data=empty();page.update_data(data)
    assert page.catalog.count()==0 and not page.catalog.isEnabled()
    data['models']=[{'model':'actual','displayName':'Actual model','description':'Observed model',
        'supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]
    page.update_data(data)
    assert page.catalog.currentData()=='actual' and page.effort.currentData()=='low'
    assert page.model_detail.text()=='Observed model'
    assert 'Решений пока нет' in page.history.toPlainText()


def test_approvals_actions_follow_real_status_and_preserve_identity(app):
    from mission_control.desktop.approvals import ApprovalsPage
    bridge=Bridge();page=ApprovalsPage(bridge);data=empty();page.update_data(data)
    assert not page.review_button.isEnabled() and not page.inspect_button.isEnabled()
    failed={'id':'failed','title':'Failed','status':'failed'}
    waiting={'id':'waiting','title':'Waiting','status':'waiting_approval'}
    data['missions']=[failed,waiting];page.update_data(data)
    assert not page.review_button.isEnabled() and page.inspect_button.isEnabled()
    page.list.setCurrentRow(1);assert page.review_button.isEnabled()
    data['missions']=[waiting,failed];page.update_data(data)
    assert page.selected()['id']=='waiting'
    page.review_button.click();assert bridge.calls[-1]==('review_result',{'identity':'waiting'})
    page.list.setCurrentRow(1);page.review();assert len(bridge.calls)==1


def test_empty_missions_disable_selection_commands(app):
    from mission_control.desktop.missions import MissionsPage
    page=MissionsPage(Bridge());page.update_data(empty())
    assert page.add_button.isEnabled() and not page.empty_state.isHidden()
    for control in (page.edit_button,page.access_button,page.pause_button,page.resume_button,
                    page.cancel_button,page.retry_button,page.ack_button,page.result_button):
        assert not control.isEnabled()
