from copy import deepcopy
import pytest
from test_desktop_gui import app, Bridge, empty, qt_slot_exceptions


def mission(identity='a',status='pending',**values):
    return {'id':identity,'title':'User mission '+identity,'project':'C:/Project',
            'status':status,'priority':5,'sequence':0,'dependsOn':[],
            'dispatchStarted':False,'attempts':[],'maxAttempts':3,**values}


def test_stage12_state_priority_and_unconfirmed_cancellation():
    from mission_control.desktop.presentation import control_state
    data=empty();data['missions']=[mission(status='waiting_approval')];data['active']='a'
    state=control_state(data)
    assert state['severity']=='warning' and 'подтверждение' in str(state['title']).lower()
    data['missions'][0].update(status='running',cancelRequested=True)
    state=control_state(data)
    assert 'не подтверждена' in str(state['detail'])
    assert 'запрошена' in str(state['title'])
    data['missions'][0]['status']='needs_attention'
    assert control_state(data)['severity']=='danger'


def test_stage12_limit_freshness_is_explicit():
    from mission_control.desktop.presentation import quota_freshness
    data=empty();text,severity=quota_freshness(data,now=1000)
    assert severity=='warning' and 'неизвестно' in str(text)
    data['limitsObservedAt']=999
    assert quota_freshness(data,now=1000)[1]=='info'
    data['limitsObservedAt']=100
    text,severity=quota_freshness(data,now=1000)
    assert severity=='warning' and '5 минут' in str(text)
    data['limitsObservedAt']=2000
    assert quota_freshness(data,now=1000)[1]=='warning'


def test_stage12_model_facts_use_existing_policy_and_keep_unknowns():
    from mission_control.desktop.presentation import model_facts
    data=empty();data['models']=[{'model':'actual','supportedReasoningEfforts':[
        {'reasoningEffort':e} for e in ('low','high')]},
        {'model':'hidden','hidden':True,'supportedReasoningEfforts':[{'reasoningEffort':'low'}]}]
    data['preferences']['modelPolicies']={'actual':{'maxEffort':'low','automaticEnabled':True}}
    original=deepcopy(data);facts=model_facts(data)
    assert facts[0]['efforts']==['low'] and facts[0]['available']
    assert not facts[1]['available']
    assert data==original
    data['active']='a';data['missions']=[mission(status='running',model={'model':'missing','effort':'low'})]
    facts=model_facts(data)
    missing=next(f for f in facts if f['model']=='missing')
    assert missing['chosen'] and not missing['available']
    assert {f['model'] for f in facts}=={'actual','hidden','missing'}


def test_stage12_responsive_columns(app):
    from PySide6.QtWidgets import QLabel, QBoxLayout
    from mission_control.desktop.components import ResponsiveColumns
    columns=ResponsiveColumns(QLabel('Left'),QLabel('Right'));columns.show()
    columns.resize(700,400);app.processEvents()
    assert columns.box.direction()==QBoxLayout.TopToBottom
    columns.resize(1100,400);app.processEvents()
    assert columns.box.direction()==QBoxLayout.LeftToRight
    columns.close()
