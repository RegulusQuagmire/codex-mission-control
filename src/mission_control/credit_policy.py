"""Conservative client preflight. No service-side paid-usage control is established."""
from dataclasses import dataclass
import time

from .limits import applicable, snapshots, number
from .model_policy import PolicyBlocked

PAID_CONTINUATION_SUPPORTED = False  # Verified installed protocol: no source-of-payment selector.


@dataclass(frozen=True)
class CreditPolicy:
    mode: str = 'never'
    fiveHourReserve: float = 10
    weeklyReserve: float = 10
    paidAcknowledged: bool = False

    def __post_init__(self):
        if self.mode not in {'never','confirm','always'} or type(self.paidAcknowledged) is not bool:
            raise ValueError('Invalid credit policy')
        if any(not number(v) or not 10 <= v <= 100 for v in (self.fiveHourReserve,self.weeklyReserve)):
            raise ValueError('Remaining quota reserve must be 10..100 percent')
        if self.mode=='always' and not self.paidAcknowledged:
            raise ValueError('Always-use policy requires explicit informed acknowledgement')


class CreditBlocked(PolicyBlocked):
    def __init__(self, gate):
        self.gate=gate
        super().__init__('Credit preflight blocked: '+gate['reason'])


def current_credit_policy():
    from .storage import ACTIVE_STORE
    store=ACTIVE_STORE.get()
    value=store.load('gui-preferences').get('creditPolicy',{}) if store is not None and store.exists('gui-preferences') else {}
    return CreditPolicy(**value)


def check_credit_limits(limits, model, *, policy=None, observed_at=None, now=None):
    now=time.time() if now is None else now
    policy=policy or current_credit_policy()
    result={'allowed':False,'reason':'limits_unknown','wakeAt':now+300,
            'confirmationRequired':False,'paidContinuationSupported':PAID_CONTINUATION_SUPPORTED,
            'policy':policy.mode}
    if not number(observed_at) or not -5 <= now-observed_at <= 60:
        result['reason']='limits_stale';return result
    if not isinstance(limits,dict) or limits.get('ordinaryUsageAllowed') is not True:
        result['reason']='included_usage_unconfirmed';return result
    by_id=limits.get('rateLimitsByLimitId')
    if isinstance(by_id,dict) and any(key in by_id and not isinstance(by_id[key],dict)
                                      for key in ('codex',model)):
        return result
    relevant=[v for k,v in snapshots(limits) if applicable(k,v,model)]
    if not relevant:return result
    blocked=[]
    for value in relevant:
        found=set()
        if 'spendControlReached' in value and value['spendControlReached'] is not None and type(value['spendControlReached']) is not bool:
            return result
        if value.get('spendControlReached') is True or value.get('rateLimitReachedType') is not None:
            result['reason']='service_limit_or_spend_control';return result
        for position in ('primary','secondary'):
            window=value.get(position)
            if not isinstance(window,dict):return result
            used=window.get('usedPercent');duration=window.get('windowDurationMins')
            if not number(used) or not 0<=used<=100 or type(duration) is not int or duration not in (300,10080):
                return result
            found.add(duration)
            reserve=policy.fiveHourReserve if duration==300 else policy.weeklyReserve
            if 100-used <= reserve:
                reset=window.get('resetsAt')
                blocked.append(reset+5 if number(reset) and reset>now else None)
        if found!={300,10080}:return result
    if blocked:
        result['reason']='reserve_reached' if policy.mode=='never' else 'paid_continuation_unsupported'
        result['confirmationRequired']=policy.mode=='confirm'
        if all(reset is not None for reset in blocked):result['wakeAt']=max(blocked)
        return result
    result.update(allowed=True,reason='included_quota_available',wakeAt=None)
    return result
