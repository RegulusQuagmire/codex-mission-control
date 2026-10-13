"""Pure read-only Router inspection; cached evidence never authorizes submission."""
from copy import deepcopy
import hashlib,json,time
from .routing import Task,Mode,SmartRouter,assess,manual_decision,RoutingBlocked
from .model_policy import policy_context,validate_configuration,allowed_efforts
from .credit_policy import CreditPolicy,check_credit_limits
from .limits import LimitPolicy,check_limits


def inspection_fingerprint(data,identity):
    job=next((j for j in data.get('missions',[]) if j['id']==identity),None)
    preferences=data.get('preferences',{})
    value={'mission':job,'models':data.get('models',[]),'limits':data.get('limits'),'paused':data.get('paused'),
        'observed':data.get('limitsObservedAt'),'connection':data.get('connection'),
        'history':data.get('routingHistoryRevision'),
        'policies':{k:preferences.get(k) for k in ('modelPolicies','creditPolicy')}}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def inspect_mission(data,identity,history,raw_limits,observed_at,*,now=None):
    now=time.time() if now is None else now
    job=next(j for j in data['missions'] if j['id']==identity)
    task=Task(**job['task']);assessment=assess(task)
    preferences=data['preferences'];models=data['models'];live=job.get('live',{})
    attempts=live.get('attempts') or job.get('attempts',[])
    retained=live.get('decision') or (attempts[-1].get('decision') if attempts else None)
    remaining=max(0,job.get('maxAttempts',3)-len(job.get('pastAttempts',[]))-len(attempts))
    blocked=[];decision=None;manual='manual' in job;constraints={}
    with policy_context(lambda:preferences.get('modelPolicies',{})):
        try:
            if retained: decision=deepcopy(retained)
            elif manual: decision=manual_decision(task,models,job['manual'],job.get('mode','balanced')).to_dict()
            else: decision=SmartRouter(history=history).choose(task,models,Mode(job.get('mode','balanced'))).to_dict()
            validate_configuration(models,decision['model'],decision['effort'],automatic=not manual)
        except RoutingBlocked:blocked.append('model_policy')
        if decision:
            entry=next((m for m in models if m.get('model')==decision['model']),{})
            rule=preferences.get('modelPolicies',{}).get(decision['model'],{})
            constraints={'effortCeiling':rule.get('maxEffort'),
                'automaticEnabled':rule.get('automaticEnabled',True),
                'allowedEfforts':allowed_efforts(decision['model'],[e.get('reasoningEffort') for e in entry.get('supportedReasoningEfforts',[])],automatic=not manual)}
    credit={'allowed':False,'reason':'limits_unknown'};limits={'allowed':False,'reason':'limits_unknown'}
    if decision:
        credit=check_credit_limits(raw_limits,decision['model'],policy=CreditPolicy(**preferences.get('creditPolicy',{})),observed_at=observed_at,now=now)
        limits=check_limits(raw_limits,decision['model'],now=now,policy=LimitPolicy(**job.get('policy',{})))
        def allowed_alternative(a):
            with policy_context(lambda:preferences.get('modelPolicies',{})):
                try:validate_configuration(models,a['model'],a['effort'],automatic=not manual)
                except RoutingBlocked:return False
            return a['model']!=decision['model']
        decision['alternatives']=[a for a in decision.get('alternatives',[]) if allowed_alternative(a) and
            check_credit_limits(raw_limits,a['model'],policy=CreditPolicy(**preferences.get('creditPolicy',{})),observed_at=observed_at,now=now)['allowed']
            and check_limits(raw_limits,a['model'],now=now,policy=LimitPolicy(**job.get('policy',{})))['allowed']]
    if not credit['allowed']:blocked.append('credit_gate')
    if not limits['allowed']:blocked.append('limit_gate')
    if not remaining:blocked.append('attempt_budget')
    if attempts and attempts[-1].get('phase')=='paused_turn' and attempts[-1].get('continuationApproved')!=attempts[-1].get('turnId'):
        blocked.append('checkpoint_review')
    stage=live.get('stage') or job['status']
    if stage in {'needs_attention','outcome_unknown','submitted'} or (attempts and attempts[-1].get('phase')=='submitted'):
        blocked.append('outcome_or_active')
    if job.get('status') in {'completed','cancelled','failed'}:blocked.append('terminal_mission')
    if stage=='waiting_approval':blocked.append('execution_approval')
    if data.get('paused'):blocked.append('queue_paused')
    return {'identity':identity,'fingerprint':inspection_fingerprint(data,identity),
        'assessment':{'complexity':assessment.complexity.name,'score':assessment.score,'maximum':15,
                      'features':dict(assessment.features),'signals':list(assessment.reasons)},
        'decision':decision,'retained':bool(retained),'manual':manual,'remainingAttempts':remaining,'currentConstraints':constraints,
        'creditGate':credit,'limitGate':limits,'blocked':blocked,
        'expiresAt':observed_at+60 if isinstance(observed_at,(float,int)) and observed_at+60>now else None}
