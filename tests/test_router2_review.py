from copy import deepcopy
import pytest
from mission_control.routing import Task,assess,Complexity,SmartRouter
from mission_control.history import History
from mission_control.route_inspection import inspection_fingerprint,inspect_mission
from test_routing import catalog
from test_router2_service import inspection_service,included_limits

@pytest.mark.parametrize('task',[
    Task('Format text',operation='format',risk='medium'),
    Task('Fix spelling',operation='docs',estimated_files=2)])
def test_explicit_medium_scope_floor_remains_conservative(task):
    assert assess(task).complexity>=Complexity.MEDIUM

def test_documentation_addition_cannot_downgrade_system_design():
    task=Task('Design a distributed system architecture and update README')
    assert assess(task).complexity==Complexity.CRITICAL

def test_escalation_rebuilds_metadata_for_actual_configuration():
    router=SmartRouter();first=router.choose(Task('format'),catalog())
    second=router.escalate(first,catalog(),{(first.model,first.effort)})
    third=router.escalate(second,catalog(),{(first.model,first.effort),(second.model,second.effort)},effort_raised=True)
    for decision in (second,third):
        value=decision.to_dict()
        assert value['constraints']['targetEffort']==decision.effort
        assert all(a['model']!=decision.model for a in value['alternatives'])
        assert value['history']['effort']==decision.effort

def test_global_pause_is_part_of_inspection_freshness(tmp_path):
    facade=inspection_service(tmp_path);data=facade.snapshot()
    changed=deepcopy(data);changed['paused']=not data['paused']
    assert inspection_fingerprint(data,'demo')!=inspection_fingerprint(changed,'demo')

def test_retained_alternatives_revalidate_catalog_policy_and_effort(tmp_path):
    facade=inspection_service(tmp_path);data=facade.snapshot()
    retained=SmartRouter().choose(Task('format'),catalog()).to_dict()
    assert retained['alternatives']
    data['missions'][0]['live']={'stage':'waiting_limit','decision':retained,'attempts':[]}
    data['preferences']['modelPolicies']={'gpt-6-astra':{'maxEffort':'none','automaticEnabled':False},'gpt-6.1-sol':{'maxEffort':'none','automaticEnabled':True}}
    value=inspect_mission(data,'demo',History(),included_limits(),facade._raw_limits_observed_at)
    assert value['decision']['alternatives']==[]

def test_legacy_observation_alias_prevents_upgrade_double_count():
    history=History()
    history.record_once('old-job:turn','gpt-6-luna','low',Complexity.LOW,True)
    history.quality_records={}
    history.record_validated('thread:turn','gpt-6-luna','low',Complexity.LOW,{'passed':True,'kind':'quality'},legacy_observation='old-job:turn')
    assert history.count('gpt-6-luna','low',Complexity.LOW)==(1,0)
    assert history.evidence('gpt-6-luna','low',Complexity.LOW)['samples']==0
