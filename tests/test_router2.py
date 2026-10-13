"""Stage 13 invariants, with synthetic catalogs and validator observations."""
import pytest
from mission_control.routing import Task,assess,Complexity,SmartRouter,Mode,RoutingBlocked
from mission_control.history import History
from mission_control.model_policy import policy_context
from test_routing import catalog

MULTISTEP='''1. Implement a parser in parser.py.
2. Connect its output to service.py and queue.py with dependencies.
3. Verify behavior with tests and check edge cases.
4. Compare two approaches and explain the trade-offs.'''

def test_multistep_scope_and_verification_raise_floor_without_magic_keyword():
    result=assess(Task(MULTISTEP))
    assert result.complexity >= Complexity.HIGH
    assert dict(result.features)['steps'] >= 2
    assert dict(result.features)['verification'] >= 1
    assert dict(result.features)['dependencies'] >= 1
    assert result==assess(Task(MULTISTEP))
    assert 0 <= result.score <= 16

def test_payload_length_alone_does_not_make_scoped_translation_high():
    result=assess(Task('Translate the following text: '+('hello '*900),operation='text'))
    assert result.complexity==Complexity.LOW
    assert dict(result.features)['scope']>0

def test_ambiguous_work_is_not_classified_as_trivial():
    result=assess(Task('Make it better somehow; requirements are unclear and acceptance criteria missing.'))
    assert result.complexity>=Complexity.MEDIUM
    assert dict(result.features)['ambiguity']>0

def test_explicit_critical_risk_overrides_scoped_text():
    assert assess(Task('Format README',operation='format',risk='critical')).complexity==Complexity.CRITICAL

def test_short_docs_about_architecture_do_not_imply_system_redesign():
    assert assess(Task('Correct spelling in architecture.md',operation='docs')).complexity==Complexity.LOW

def test_extreme_input_is_bounded_and_conservative():
    result=assess(Task('a'*100000))
    assert result.complexity>=Complexity.HIGH
    assert 'analysis input truncated; conservative floor' in result.reasons

@pytest.mark.parametrize('success,failure,changed',[(0,1,False),(0,2,False),(0,7,False),(4,4,False),(7,1,False),(1,7,True),(0,8,True)])
def test_history_requires_substantial_consistent_evidence(success,failure,changed):
    history=History()
    for i in range(success+failure):
        history.record_once(str(i),'gpt-6-luna','low',Complexity.LOW,i<success)
    decision=SmartRouter(history=history).choose(Task('format'),catalog())
    assert (decision.model!='gpt-6-luna') is changed
    assert decision.to_dict()['history']['minimumSamples']==8
    assert 'history' in decision.to_dict()

@pytest.mark.parametrize('kind',['network','unauthorized','limit','interrupted','unknown','not_retryable','execution_approval_required'])
def test_nonquality_outcomes_do_not_pollute_history(kind):
    history=History()
    history.record_validated('one','gpt-6-luna','low',Complexity.LOW,{'passed':False,'kind':kind})
    assert history.records=={} and history.observations==set()

def test_quality_observations_deduplicate_and_persist(tmp_path):
    history=History()
    for _ in range(3):history.record_validated('one','gpt-6-luna','low',Complexity.LOW,{'passed':True,'kind':'quality'})
    path=tmp_path/'history.json';history.save(path)
    loaded=History.load(path)
    loaded.record_validated('one','gpt-6-luna','low',Complexity.LOW,{'passed':True,'kind':'quality'})
    assert loaded.count('gpt-6-luna','low',Complexity.LOW)==(1,0)

def test_duplicate_model_ids_are_not_admissible():
    with pytest.raises(RoutingBlocked):SmartRouter().choose(Task('format'),catalog()[:1]*2)

def test_unknown_fallback_is_catalog_order_independent():
    a={'model':'unknown-a','supportedReasoningEfforts':[{'reasoningEffort':'low'}]}
    b={**a,'model':'unknown-b'}
    assert SmartRouter().choose(Task('format'),[a,b]).model==SmartRouter().choose(Task('format'),[b,a]).model

def test_decision_exposes_only_admissible_alternatives_and_ceiling():
    with policy_context(lambda:{'gpt-6-luna':{'maxEffort':'low','automaticEnabled':True},'gpt-6-astra':{'maxEffort':'max','automaticEnabled':False}}):
        decision=SmartRouter().choose(Task('format'),catalog()).to_dict()
    assert decision['constraints']['effortCeiling']=='low'
    assert decision['analysis']['maximum']==15
    assert 'gpt-6-astra' not in [a['model'] for a in decision['alternatives']]
    assert all(a['model']!=decision['model'] for a in decision['alternatives'])

def test_legacy_counts_with_unknown_validation_kind_cannot_change_route(tmp_path):
    from mission_control.state import save_state
    path=tmp_path/'legacy.json'
    key=History._key('gpt-6-luna','low',Complexity.LOW)
    save_state(path,{'version':1,'records':{key:{'success':0,'failure':100}},'observations':[]})
    loaded=History.load(path)
    assert loaded.count('gpt-6-luna','low',Complexity.LOW)==(0,100)
    assert SmartRouter(history=loaded).choose(Task('format'),catalog()).model=='gpt-6-luna'
