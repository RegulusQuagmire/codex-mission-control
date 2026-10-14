from copy import deepcopy
from test_desktop_gui import app, qt_slot_exceptions, Bridge, empty
from test_orchestration import draft


def review():
    return {'id':'demo','title':'Owner title','goal':'Owner goal','project':'C:/OFFLINE_DEMO',
            'draft':draft(),'revision':1,'reviewId':'exact-review','activated':False}


def test_scope_review_requires_all_sections_and_explicit_consent(app):
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
    from mission_control.desktop.projects import PlanReviewDialog
    bridge=Bridge();dialog=PlanReviewDialog(review(),bridge);dialog.show();app.processEvents()
    assert not dialog.approve_button.isEnabled()
    dialog.consent.setFocus();QTest.keyClick(dialog.consent,Qt.Key_Space)
    assert not dialog.approve_button.isEnabled()
    for i in range(dialog.sections.count()):
        dialog.sections.setCurrentRow(i);app.processEvents()
        dialog.viewer.verticalScrollBar().setValue(dialog.viewer.verticalScrollBar().maximum())
        dialog.mark_viewed()
    assert dialog.approve_button.isEnabled()
    dialog.approve_button.setFocus();QTest.keyClick(dialog.approve_button,Qt.Key_Space);dialog.approve()
    assert bridge.calls==[('confirm_project_plan',{'identity':'demo','review_id':'exact-review','acknowledge':True})]
    dialog.close()


def test_project_node_selection_survives_snapshot_and_language_change(app):
    from mission_control.desktop.projects import ProjectsDialog
    from mission_control.desktop.i18n import set_language
    bridge=Bridge();data=empty();value={**review(),'total':0,'completed':0,'missions':[]}
    value['draft']['missions'].append({**deepcopy(value['draft']['missions'][0]),'id':'second','title':'Second'})
    data['projects']=[value];dialog=ProjectsDialog(bridge,data)
    dialog.resize(800,600);dialog.show();app.processEvents()
    dialog.table.selectRow(1);dialog.update_data(data)
    assert dialog.table.currentRow()==1
    set_language('en');app.processEvents();assert dialog.table.currentRow()==1
    dialog.request_plan();assert not dialog.selector.isEnabled()
    # A result for a different request/project cannot open or release this dialog.
    dialog.result('review_project_plan',{**value,'id':'other'})
    assert dialog.busy
    set_language('ru');dialog.close()


def test_invalid_new_project_keeps_owner_goal_for_correction(app):
    from mission_control.desktop.projects import NewProjectDialog
    from PySide6.QtWidgets import QDialog
    dialog=NewProjectDialog();dialog.title.setText('Owner title');dialog.goal.setPlainText('Owner goal')
    dialog.submit()
    assert dialog.result()!=QDialog.Accepted and dialog.goal.toPlainText()=='Owner goal'
    assert dialog.validation.text();dialog.close()


def test_scope_review_language_change_preserves_ids_but_stale_snapshot_revokes(app):
    from mission_control.desktop.projects import PlanReviewDialog
    from mission_control.desktop.i18n import set_language
    bridge=Bridge();value=review();dialog=PlanReviewDialog(value,bridge)
    dialog.consent.setChecked(True);set_language('en');app.processEvents()
    assert dialog.value['reviewId']=='exact-review' and dialog.value['title']=='Owner title'
    newer=deepcopy(value);newer['revision']=2
    bridge.snapshot.emit({'projects':[newer]})
    assert not dialog.consent.isChecked() and not dialog.approve_button.isEnabled()
    dialog.approve();assert not bridge.calls
    set_language('ru');dialog.close()


def test_project_manager_preserves_selection_and_uses_existing_queue_actions(app):
    from mission_control.desktop.projects import ProjectsDialog
    bridge=Bridge();data=empty();value={**review(),'total':0,'completed':0,'missions':[],
        'planningStatus':None,'queuePaused':True,'context':{'inputFiles':[]}}
    data['projects']=[value]
    dialog=ProjectsDialog(bridge,data);dialog.show();app.processEvents()
    assert dialog.selected()=='demo'
    dialog.request_plan();assert bridge.calls[-1]==('request_project_plan',{'identity':'demo'})
    dialog.update_data(data);assert dialog.selected()=='demo'
    dialog.close()


def test_confirmed_manual_plan_is_not_labelled_draft_and_tooltips_are_opaque(app):
    from mission_control.desktop.projects import ProjectsDialog
    from mission_control.desktop.i18n import set_language
    bridge=Bridge();data=empty();value={**review(),'activated':True,'total':1,'completed':0,
        'planningStatus':None,'missions':[{'id':'demo-build','status':'paused','state':'waiting_resume',
        'blockedBy':[],'accessRequired':False}]}
    value['draft']['missions'][0]['title']='<img src="file:///private.png">'
    data['projects']=[value];dialog=ProjectsDialog(bridge,data)
    dialog.resize(800,600);dialog.show();app.processEvents()
    set_language('en');app.processEvents()
    assert 'Plan confirmed' in dialog.summary.text() and 'Draft' not in dialog.summary.text()
    assert '<img' not in dialog.table.item(0,1).toolTip() and '&lt;img' in dialog.table.item(0,1).toolTip()
    assert dialog.table.item(0,2).text()!='Paused'
    assert dialog.table.columnWidth(1)>=160
    set_language('ru');dialog.close()


def test_planning_and_generated_scope_cannot_open_single_mission_editor(app):
    from mission_control.desktop.missions import MissionsPage
    from test_queue import text_job
    bridge=Bridge();page=MissionsPage(bridge);data=empty()
    job={**text_job('demo-plan',project='C:/OFFLINE_DEMO'),'type':'planning',
        'criteria':{'project':'C:/OFFLINE_DEMO','inputFiles':[]},'status':'pending',
        'dispatchStarted':False,'sequence':0,'attempts':[],'archives':[]}
    data['missions']=[job];page.update_data(data);page.table.selectRow(0)
    assert not page.edit_button.isEnabled()
    job.update(type='project',orchestration={'projectId':'demo','revision':1})
    page.update_data(data);assert not page.edit_button.isEnabled()
    page.close()
