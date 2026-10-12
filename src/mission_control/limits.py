"""Quota policy over official snapshots; unknown is never treated as zero usage."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
import math


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def snapshots(limits):
    if not isinstance(limits, dict):
        return []
    by_id = limits.get("rateLimitsByLimitId")
    result = [(key, value) for key, value in by_id.items() if isinstance(value, dict)] if isinstance(by_id, dict) else []
    legacy = limits.get("rateLimits")
    if isinstance(legacy, dict):
        identity = legacy.get("limitId") or "codex"
        if not any((value.get("limitId") or key) == identity for key, value in result):
            result.append((identity, legacy))
    return result


def applicable(key, value, model):
    identity = value.get("limitId") or key
    return ((identity == "codex" and value.get("normalModelSlug") is None)
            or model in {key, identity})


def inspect_limits(limits):
    rows = []
    credits = []
    for key, value in snapshots(limits):
        if isinstance(value.get('credits'),dict):
            credits.append({'limitId':value.get('limitId') or key,**value['credits']})
        for position in ("primary", "secondary"):
            window = value.get(position)
            if not isinstance(window, dict):
                continue
            used = window.get("usedPercent")
            used = used if number(used) and 0 <= used <= 100 else None
            duration = window.get("windowDurationMins")
            duration = duration if number(duration) and duration > 0 else None
            reset = window.get("resetsAt")
            reset = reset if number(reset) and reset > 0 else None
            rows.append({"limitId": value.get("limitId") or key, "position": position,
                         "kind": {300: "five_hour", 10080: "weekly"}.get(duration, "unknown" if duration is None else "other"),
                         "usedPercent": used, "remainingPercent": None if used is None else 100-used,
                         "windowDurationMins": duration, "resetsAt": reset})
    return {"windows": rows, "credits":credits, "available": bool(rows),
            "ordinaryUsageAllowed": limits.get("ordinaryUsageAllowed") if isinstance(limits,dict) else None}


def sanitize_limits(raw):
    """Allowlist snapshot data; no account IDs, raw messages, credit links or tokens."""
    raw = raw if isinstance(raw, dict) else {}
    def snapshot(value):
        if not isinstance(value, dict):
            return None
        result = {key: value[key] for key in ("limitId", "limitName", "normalModelSlug", "rateLimitReachedType", "spendControlReached") if key in value}
        if 'credits' in value:
            credits=value['credits']
            clean={}
            if isinstance(credits,dict):
                for key in ('hasCredits','unlimited'):
                    clean[key]=credits.get(key) if type(credits.get(key)) is bool else None
                balance=credits.get('balance')
                if isinstance(balance,str) and len(balance)<=80:
                    from decimal import Decimal, InvalidOperation
                    try:
                        parsed=Decimal(balance)
                        balance=balance if parsed.is_finite() and 0<=parsed<=Decimal('1e18') else None
                    except InvalidOperation:balance=None
                else:balance=None
                clean['balance']=balance
            result['credits']=clean or None
        for name in ("primary", "secondary"):
            if name in value:
                window = value[name]
                result[name] = {key: window[key] for key in ("usedPercent", "windowDurationMins", "resetsAt") if key in window} if isinstance(window,dict) else None
        return result
    result = {}
    if "rateLimits" in raw:
        result["rateLimits"] = snapshot(raw["rateLimits"])
    if "rateLimitsByLimitId" in raw:
        by_id = raw["rateLimitsByLimitId"]
        result["rateLimitsByLimitId"] = {key: snapshot(value) for key,value in by_id.items()} if isinstance(by_id,dict) else None
    if "ordinaryUsageAllowed" in raw:
        result["ordinaryUsageAllowed"] = raw["ordinaryUsageAllowed"] if type(raw["ordinaryUsageAllowed"]) is bool else None
    return result


def merge_limit_update(previous, update):
    """Sparse notification merge. A full read is still required before inference."""
    result = deepcopy(previous) if isinstance(previous,dict) else {}
    clean = sanitize_limits(update)
    buckets = result.get("rateLimitsByLimitId")
    buckets = deepcopy(buckets) if isinstance(buckets,dict) else {}
    if 'rateLimitsByLimitId' in clean and clean['rateLimitsByLimitId'] is None:
        buckets = {}
        result['rateLimits'] = None
    updates = list((clean.get("rateLimitsByLimitId") or {}).items())
    if isinstance(clean.get("rateLimits"),dict):
        value=clean["rateLimits"]
        updates.append((value.get("limitId") or "codex",value))
    elif 'rateLimits' in clean:
        updates.append(('codex',None))
    for key,value in updates:
        if not isinstance(value,dict):
            buckets[key]=None  # Explicit unknown revokes; omission alone retains a sparse field.
            continue
        current=buckets.get(key)
        current=current if isinstance(current,dict) else {}
        for field,item in value.items():
            if field in {"primary","secondary"} and isinstance(item,dict):
                current[field] = {**(current.get(field) or {}),**item}
            else:
                current[field]=item
        buckets[key]=current
    result["rateLimitsByLimitId"]=buckets
    if "rateLimits" in clean:
        value=clean["rateLimits"]
        result["rateLimits"]=deepcopy(buckets.get(value.get("limitId") or "codex")) if isinstance(value,dict) else None
    if "ordinaryUsageAllowed" in clean:
        result["ordinaryUsageAllowed"]=clean["ordinaryUsageAllowed"]
    return result


@dataclass(frozen=True)
class LimitPolicy:
    mode: str = "balanced"
    threshold: float = 100

    def __post_init__(self):
        if self.mode not in {"balanced","weekly","reserve","stop"} or not number(self.threshold) or not 0 < self.threshold <= 100:
            raise ValueError("Invalid quota policy or threshold (must be >0 and <=100)")

    def ceiling(self,duration):
        if self.mode == "weekly" and duration == 10080:
            return 85
        if self.mode == "reserve":
            return 90
        return self.threshold if self.mode == "stop" else 100


def check_limits(limits,model,*,now,policy=None,failures=0):
    policy=policy or LimitPolicy()
    delay=min(3600,300 * 2**min(max(0,failures),4))
    relevant=[(key,value) for key,value in snapshots(limits) if applicable(key,value,model)]
    windows=[]
    blockers=[]
    unknown=False
    reason="limit_reached"
    flags=False
    for key,value in relevant:
        spend=value.get("spendControlReached") is True
        reached=value.get("rateLimitReachedType") is not None
        flags |= spend or reached
        if spend or (reached and value.get("rateLimitReachedType") != "rate_limit_reached"):
            reason="spend_control"
            unknown=True
        for position in ("primary","secondary"):
            window=value.get(position)
            if not isinstance(window,dict):
                continue
            usage=window.get("usedPercent")
            if not number(usage) or not 0 <= usage <= 100:
                unknown=True
                continue
            windows.append(window)
            if usage >= policy.ceiling(window.get("windowDurationMins")):
                reset=window.get("resetsAt")
                blockers.append(reset+5 if number(reset) and reset > now else None)
    if policy.mode=='weekly' and not any(w.get('windowDurationMins')==10080 for w in windows):
        unknown=True
    ordinary=limits.get("ordinaryUsageAllowed") if isinstance(limits,dict) else None
    if flags and not blockers:
        unknown=True
    if ordinary is False:
        flags=True
        if not blockers: unknown=True
    if not windows and ordinary is not True:
        unknown=True
    allowed=not blockers and not flags and not unknown
    if allowed:
        return {"allowed":True,"reason":"available","wakeAt":None}
    if not blockers and not flags:
        reason="limits_unknown"
    wake = max(blockers) if blockers and all(value is not None for value in blockers) and not unknown else now+delay
    return {"allowed":False,"reason":reason,"wakeAt":wake}
