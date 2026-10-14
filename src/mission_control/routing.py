"""Deterministic routing from current capabilities and explicit qualitative policy."""
from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum, IntEnum
import re

from .history import History


class Complexity(IntEnum):
    LOW = 0
    MEDIUM = 1
    HIGH = 2
    CRITICAL = 3


class Mode(str, Enum):
    ECONOMY = "economy"
    BALANCED = "balanced"
    QUALITY = "quality"


class RoutingBlocked(ValueError):
    """No admissible configuration; never imply a reset or retry."""


def check_manual(value):
    if (not isinstance(value,dict) or set(value)!={'model','effort'} or
            any(not isinstance(v,str) or not v.strip() for v in value.values())):
        raise ValueError('Manual configuration requires model and effort')


def manual_decision(task,models,value,mode):
    check_manual(value)
    from .model_policy import validate_configuration
    validate_configuration(models, value['model'], value['effort'])
    entry=next((m for m in models if m.get('model')==value['model'] and not m.get('hidden')),None)
    if (entry is None or value['effort'] not in {x.get('reasoningEffort') for x in entry.get('supportedReasoningEfforts',[])}
            or ('inputModalities' in entry and 'text' not in entry['inputModalities'])):
        raise RoutingBlocked('Manual model or effort unavailable in current catalog')
    return Decision(value['model'],value['effort'],assess(task),Mode(mode),
                    'Explicit manual configuration; automatic escalation disabled',
                    'operator selection validated against live catalog',False)


EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "max")
# Qualitative policy, not quota multipliers or benchmark scores. IDs are intersected
# with live model/list. Unknown IDs never inherit a guessed rank from a name suffix.
# Source: https://developers.openai.com/api/docs/guides/model-selection, 2026-10-11.
DEFAULT_PROFILES = {
    "gpt-6-luna": 0,
    "gpt-6.1-sol": 1,
    "gpt-6-astra": 2,
}


@dataclass(frozen=True)
class Task:
    text: str
    operation: str = "auto"
    estimated_files: int | None = None
    risk: str = "auto"
    previous_errors: int = 0

    def __post_init__(self):
        if not isinstance(self.text, str) or not self.text.strip():
            raise ValueError("Task text must be nonempty")
        if self.operation not in {"auto", "text", "docs", "format", "code", "refactor", "debug", "architecture"}:
            raise ValueError("Unknown task operation")
        if self.risk not in {"auto", "low", "medium", "high", "critical"}:
            raise ValueError("Unknown risk")
        for number in (self.estimated_files, self.previous_errors):
            if number is not None and (type(number) is not int or number < 0):
                raise ValueError("Task counts must be nonnegative integers")


@dataclass(frozen=True)
class Assessment:
    complexity: Complexity
    reasons: tuple[str, ...]
    estimated_files: int
    score: int = 0
    features: tuple[tuple[str, int], ...] = ()


def assess(task: Task) -> Assessment:
    from .task_analysis import analyze
    level,reasons,files,score,features=analyze(task)
    return Assessment(Complexity(level),reasons,files,score,features)


@dataclass(frozen=True)
class Decision:
    model: str
    effort: str
    assessment: Assessment
    mode: Mode
    reason: str
    profile_source: str
    limits_known: bool
    history_evidence: dict | None = None
    constraints: dict | None = None
    alternatives: tuple[dict, ...] = ()

    def to_dict(self):
        return {"model": self.model, "effort": self.effort,
                "complexity": self.assessment.complexity.name,
                "estimatedFiles": self.assessment.estimated_files,
                "signals": list(self.assessment.reasons), "mode": self.mode.value,
                "reason": self.reason, "profileSource": self.profile_source,
                "limitsKnown": self.limits_known,
                "analysis": {"version":2,"score":self.assessment.score,"maximum":15,
                             "features":dict(self.assessment.features)},
                "history":self.history_evidence or {}, "constraints":self.constraints or {},
                "alternatives":list(self.alternatives)}


def _limit_status(limits: dict | None, model: str) -> tuple[bool, bool, bool]:
    if not limits:
        return False, False, False
    blocked = limits.get("ordinaryUsageAllowed") is False
    known = type(limits.get("ordinaryUsageAllowed")) is bool
    pressure = False
    by_id = limits.get("rateLimitsByLimitId")
    snapshots = list(by_id.items()) if isinstance(by_id, dict) else []
    legacy = limits.get("rateLimits")
    if isinstance(legacy, dict):
        identity = legacy.get("limitId") or "codex"
        if not any((value.get("limitId") or key) == identity
                   for key, value in snapshots if isinstance(value, dict)):
            snapshots.append((identity, legacy))
    for key, snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        identity = snapshot.get("limitId") or key
        # normalModelSlug supplies quota-alias display/effort metadata. It is
        # not evidence that the ordinary parent model spends that alias quota.
        ordinary_global = identity == "codex" and snapshot.get("normalModelSlug") is None
        if not ordinary_global and model not in {key, identity}:
            continue
        if snapshot.get("spendControlReached") is True or snapshot.get("rateLimitReachedType") is not None:
            blocked = known = True
        for name in ("primary", "secondary"):
            window = snapshot.get(name)
            value = window.get("usedPercent") if isinstance(window, dict) else None
            if type(value) in (int, float) and 0 <= value <= 100:
                known = True
                blocked |= value >= 100
                pressure |= value >= 85
    return blocked, pressure, known


class SmartRouter:
    def __init__(self, *, history: History | None = None,
                 excluded: set[str] | None = None, profiles: dict[str, int] | None = None):
        self.history = history if history is not None else History()
        self.excluded = set(excluded or ())
        self.profiles = dict(DEFAULT_PROFILES if profiles is None else profiles)
        self.profile_source = ("official-model-selection guidance; qualitative policy"
                               if profiles is None else "explicit operator profiles; qualitative policy")
        if any(type(rank) is not int or rank < 0 for rank in self.profiles.values()):
            raise ValueError("Profile ranks must be explicit nonnegative integers")

    def _models(self, models, limits):
        from .model_policy import allowed_efforts, current_policy
        policy = current_policy()
        candidates = []
        seen = set()
        identities=[entry.get("model") for entry in models]
        for entry in models:
            model = entry.get("model")
            efforts = [effort for effort in EFFORTS if effort in {
                option.get("reasoningEffort") for option in entry.get("supportedReasoningEfforts", [])}]
            efforts = allowed_efforts(model, efforts, automatic=True, policy=policy)
            if (not isinstance(model, str) or not model or model in seen
                    or identities.count(model)!=1 or entry.get("hidden") or model in self.excluded or not efforts
                    or ("inputModalities" in entry and "text" not in entry["inputModalities"])):
                continue
            seen.add(model)
            blocked, pressure, known = _limit_status(limits, model)
            if not blocked:
                candidates.append((entry, efforts, pressure, known))
        return sorted(candidates, key=lambda item:item[0]["model"])

    @staticmethod
    def _effort(efforts, target):
        rank = EFFORTS.index(target)
        return next((effort for effort in efforts if EFFORTS.index(effort) >= rank), efforts[-1])

    def choose(self, task: Task, models: list[dict], mode: Mode = Mode.BALANCED,
               *, limits: dict | None = None) -> Decision:
        mode = Mode(mode)
        assessment = assess(task)  # Always fresh; no sticky previous-task state.
        level = int(assessment.complexity)
        targets = {
            Mode.ECONOMY: ((0, 0, 1, 2), ("low", "medium", "high", "high")),
            Mode.BALANCED: ((0, 1, 1, 2), ("low", "medium", "high", "xhigh")),
            Mode.QUALITY: ((1, 1, 2, 2), ("medium", "high", "xhigh", "max")),
        }
        tier = targets[mode][0][level]
        target = targets[mode][1][level]
        candidates = self._models(models, limits)
        if not candidates:
            raise RoutingBlocked("No visible model with supported text effort and available limits")
        admissible = list(candidates)
        ranked = [candidate for candidate in candidates if candidate[0]["model"] in self.profiles]
        source = self.profile_source
        if ranked:
            candidates = ranked
            target_candidates = [candidate for candidate in candidates
                                 if self.profiles[candidate[0]["model"]] >= tier]
            target_rank = (min(self.profiles[item[0]["model"]] for item in target_candidates)
                           if target_candidates else
                           max(self.profiles[item[0]["model"]] for item in candidates))
            pressure_for_target = all(item[2] for item in candidates
                                      if self.profiles[item[0]["model"]] == target_rank)
            if level <= 1 and pressure_for_target:
                tier = max(0, tier - 1)
                target = EFFORTS[max(EFFORTS.index("low"), EFFORTS.index(target) - 1)]
            viable = [candidate for candidate in candidates if self.profiles[candidate[0]["model"]] >= tier]
            if viable:
                candidates = viable
            else:
                strongest = max(self.profiles[candidate[0]["model"]] for candidate in candidates)
                candidates = [candidate for candidate in candidates if self.profiles[candidate[0]["model"]] == strongest]
                source += "; requested tier unavailable, strongest known fallback"

            def score(candidate):
                model = candidate[0]["model"]
                effort = self._effort(candidate[1], target)
                success, failure = self.history.count(model, effort, assessment.complexity)
                unreliable = int(self.history.evidence(model,effort,assessment.complexity)["unreliable"])
                return unreliable, self.profiles[model], not candidate[0].get("isDefault", False), model
            selected = min(candidates, key=score)
        else:
            source = "unranked catalog fallback; comparative capability unknown"
            selected = next((candidate for candidate in candidates if candidate[0].get("isDefault")), candidates[0])
        model = selected[0]["model"]
        effort = self._effort(selected[1], target)
        selected_evidence=self.history.evidence(model,effort,assessment.complexity)
        success,failure=selected_evidence['success'],selected_evidence['failure']
        reason = (f"{assessment.complexity.name}: chose {model} / {effort} ({mode.value}); "
                  + "; ".join(assessment.reasons)
                  + f"; observed validated outcomes={success} success/{failure} failure")
        reason += "; personal model policy applied"
        if selected[2]:
            reason += "; known limit usage >=85%, conserve easy-task resources"
        if not selected[3]:
            reason += "; applicable limits unknown"
        from .model_policy import current_policy
        evidence=self.history.evidence(model,effort,assessment.complexity)
        compared=[{"model":item[0]["model"],"effort":self._effort(item[1],target),
                   **self.history.evidence(item[0]["model"],self._effort(item[1],target),assessment.complexity)}
                  for item in candidates]
        base=min(candidates,key=lambda item:(self.profiles.get(item[0]["model"],0),not item[0].get("isDefault",False),item[0]["model"]))
        adjusted=bool(ranked and base[0]["model"]!=model)
        evidence={**evidence,"model":model,"effort":effort,"compared":compared,"adjusted":adjusted}
        reason += "; history adjustment after repeated validated failures" if adjusted else "; history does not justify changing the preferred profile"
        rule=current_policy().get(model,{})
        constraints={"effortCeiling":rule.get("maxEffort","ultra"),
                     "automaticEnabled":rule.get("automaticEnabled",True),
                     "supportedEfforts":list(selected[1]),"targetEffort":target,
                     "effortClamped":effort!=target}
        alternatives=tuple({"model":item[0]["model"],"effort":self._effort(item[1],target),
                            "rankKnown":item[0]["model"] in self.profiles}
                           for item in admissible if item[0]["model"]!=model)
        return Decision(model,effort,assessment,mode,reason,source,selected[3],evidence,constraints,alternatives)

    def escalate(self, previous: Decision, models: list[dict],
                 visited: set[tuple[str, str]], *, effort_raised: bool = False,
                 limits: dict | None = None) -> Decision | None:
        candidates = self._models(models, limits)
        if not candidates:
            raise RoutingBlocked("No available configuration for escalation; limits/catalog changed")
        current = next((item for item in candidates if item[0]["model"] == previous.model), None)
        if current and not effort_raised:
            higher = [effort for effort in current[1] if EFFORTS.index(effort) > EFFORTS.index(previous.effort)
                      and (previous.model, effort) not in visited]
            if higher:
                return self._escalated(previous,current,higher[0],candidates,
                               f"; validation failed: raise effort to {higher[0]}")
        rank = self.profiles.get(previous.model)
        if rank is None:
            return None  # Cannot invent a more powerful model.
        stronger = [item for item in candidates if self.profiles.get(item[0]["model"], -1) > rank]
        for item in sorted(stronger, key=lambda item: self.profiles[item[0]["model"]]):
            effort = self._effort(item[1], previous.effort)
            if (item[0]["model"], effort) not in visited:
                return self._escalated(previous,item,effort,candidates,
                               f"; validation failed: switch to stronger profile {item[0]['model']}")
        return None

    def _escalated(self,previous,selected,effort,candidates,reason):
        from .model_policy import current_policy
        model=selected[0]['model'];rule=current_policy().get(model,{})
        evidence={**self.history.evidence(model,effort,previous.assessment.complexity),
                  'model':model,'effort':effort,'adjusted':False}
        constraints={'effortCeiling':rule.get('maxEffort','ultra'),
            'automaticEnabled':rule.get('automaticEnabled',True),'supportedEfforts':list(selected[1]),
            'targetEffort':effort,'effortClamped':False}
        alternatives=tuple({'model':item[0]['model'],'effort':self._effort(item[1],effort),
            'rankKnown':item[0]['model'] in self.profiles} for item in candidates if item[0]['model']!=model)
        return replace(previous,model=model,effort=effort,profile_source=self.profile_source,
            limits_known=selected[3],reason=previous.reason+reason,history_evidence=evidence,
            constraints=constraints,alternatives=alternatives)
