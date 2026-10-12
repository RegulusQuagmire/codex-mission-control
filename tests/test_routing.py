"""Offline policies: catalogs here are test fixtures, never runtime data."""
import pytest

from mission_control.routing import (
    Task, Complexity, Mode, SmartRouter, RoutingBlocked, assess,
)
from mission_control.history import History

def catalog():
    efforts = [{"reasoningEffort": effort} for effort in ("low", "medium", "high", "xhigh", "max")]
    return [
        {"model": "gpt-6-luna", "supportedReasoningEfforts": efforts, "defaultReasoningEffort": "medium"},
        {"model": "gpt-6.1-sol", "supportedReasoningEfforts": efforts, "isDefault": True},
        {"model": "gpt-6-astra", "supportedReasoningEfforts": efforts},
    ]

@pytest.mark.parametrize("task,expected", [
    (Task("Исправь опечатку в README"), Complexity.LOW),
    (Task("Format this text"), Complexity.LOW),
    (Task("Return only 2, the sum of 1 and 1.", operation="text"), Complexity.LOW),
    (Task("Добавь API endpoint"), Complexity.MEDIUM),
    (Task("Непонятное задание"), Complexity.MEDIUM),
    (Task("Отладь deadlock в нескольких модулях", estimated_files=8), Complexity.HIGH),
    (Task("Переработай архитектуру приложения"), Complexity.CRITICAL),
    (Task("Обнови текст", risk="critical"), Complexity.CRITICAL),
    (Task("Обнови документацию", previous_errors=2), Complexity.HIGH),
    (Task("Удалить таблицы базы данных"), Complexity.CRITICAL),
])
def test_complexity_signals(task, expected):
    result = assess(task)
    assert result.complexity == expected
    assert result.reasons

@pytest.mark.parametrize("kwargs", [{"text": ""}, {"text": "x", "estimated_files": -1},
                                  {"text": "x", "previous_errors": -1},
                                  {"text": "x", "risk": "madeup"},
                                  {"text": "x", "operation": "madeup"}])
def test_invalid_task_hints_rejected(kwargs):
    with pytest.raises(ValueError):
        Task(**kwargs)

def test_modes_and_fresh_assessment_drop_power():
    router = SmartRouter()
    low = Task("Format a short text")
    economy = router.choose(low, catalog(), Mode.ECONOMY)
    quality = router.choose(low, catalog(), Mode.QUALITY)
    assert (economy.model, economy.effort) == ("gpt-6-luna", "low")
    assert quality.model == "gpt-6.1-sol"
    assert quality.effort == "medium"
    assert router.choose(Task("Измени архитектуру"), catalog()).model == "gpt-6-astra"
    assert router.choose(low, catalog()).model == "gpt-6-luna"
    assert "LOW" in economy.reason

def test_unknown_models_never_get_invented_power_ranks():
    models = [{"model": "future-model", "isDefault": True,
               "supportedReasoningEfforts": [{"reasoningEffort": "medium"}]}]
    decision = SmartRouter().choose(Task("text", operation="text"), models)
    assert decision.model == "future-model"
    assert decision.effort == "medium"
    assert "unranked" in decision.profile_source

def test_hidden_missing_efforts_and_exclusions_are_not_used():
    models = catalog()
    models[0]["hidden"] = True
    models.append({"model": "broken"})
    router = SmartRouter(excluded={"gpt-6.1-sol"})
    assert router.choose(Task("format"), models).model == "gpt-6-astra"
    with pytest.raises(RoutingBlocked):
        router.choose(Task("format"), [])

def test_sparse_efforts_always_use_advertised_value():
    models = catalog()[:1]
    models[0]["supportedReasoningEfforts"] = [{"reasoningEffort": "high"}]
    assert SmartRouter().choose(Task("format"), models).effort == "high"

def test_global_exhaustion_blocks_without_consuming_reset_credits():
    for limits in ({"ordinaryUsageAllowed": False},
                   {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 100}}},
                   {"rateLimits": {"limitId": "codex", "spendControlReached": True}}):
        with pytest.raises(RoutingBlocked):
            SmartRouter().choose(Task("format"), catalog(), limits=limits)

def test_unknown_and_per_model_limits():
    router = SmartRouter()
    task = Task("format")
    assert router.choose(task, catalog(), limits=None).limits_known is False
    limits = {"rateLimitsByLimitId": {"gpt-6-luna": {
        "limitId": "gpt-6-luna", "primary": {"usedPercent": 100}}}}
    assert router.choose(task, catalog(), limits=limits).model == "gpt-6.1-sol"
    unrelated = {"rateLimitsByLimitId": {"other_service": {"primary": {"usedPercent": 100}}}}
    assert router.choose(task, catalog(), limits=unrelated).model == "gpt-6-luna"

def test_near_limit_reduces_easy_effort_but_not_critical_floor():
    limits = {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 92}}}
    router = SmartRouter()
    low = Task("format")
    normal = router.choose(low, catalog(), Mode.QUALITY)
    scarce = router.choose(low, catalog(), Mode.QUALITY, limits=limits)
    assert scarce.model == "gpt-6-luna"
    assert scarce.effort == "low"
    assert normal.model != scarce.model
    critical = router.choose(Task("архитектура"), catalog(), limits=limits)
    assert critical.model == "gpt-6-astra"

def test_escalation_effort_then_stronger_model_no_revisit():
    router = SmartRouter()
    task = Task("format")
    first = router.choose(task, catalog(), Mode.ECONOMY)
    second = router.escalate(first, catalog(), {(first.model, first.effort)})
    assert (second.model, second.effort) == ("gpt-6-luna", "medium")
    third = router.escalate(second, catalog(),
                           {(first.model, first.effort), (second.model, second.effort)},
                           effort_raised=True)
    assert third.model == "gpt-6.1-sol"
    assert third.effort in ("medium", "high", "xhigh", "max")
    assert third.assessment == first.assessment

def test_real_observations_influence_next_selection_and_roundtrip(tmp_path):
    history = History()
    assert history.records == {}
    for _ in range(2):
        history.record("gpt-6-luna", "low", Complexity.LOW, False)
    router = SmartRouter(history=history)
    assert router.choose(Task("format"), catalog()).model == "gpt-6.1-sol"
    path = tmp_path / "history.json"
    history.save(path)
    loaded = History.load(path)
    assert loaded.records == history.records
    assert loaded.count("gpt-6-luna", "low", Complexity.LOW) == (0, 2)
    assert loaded.count("gpt-6-luna", "low", Complexity.CRITICAL) == (0, 0)

def test_history_rejects_corrupt_counts(tmp_path):
    path = tmp_path / "history.json"
    path.write_text('{"version":1,"records":{"bad":{"success":-1,"failure":0}}}')
    with pytest.raises(ValueError):
        History.load(path)

def test_quota_alias_exhaustion_does_not_exclude_ordinary_parent_model():
    limits = {"ordinaryUsageAllowed": True, "rateLimitsByLimitId": {
        "sol-quota-alias": {"limitId": "sol-quota-alias", "normalModelSlug": "gpt-6.1-sol",
                           "primary": {"usedPercent": 100}}}}
    decision = SmartRouter().choose(Task("format"), catalog(), Mode.QUALITY, limits=limits)
    assert decision.model == "gpt-6.1-sol"

def test_partial_model_limit_map_keeps_global_legacy_limit():
    limits = {"rateLimits": {"limitId": "codex", "primary": {"usedPercent": 100}},
              "rateLimitsByLimitId": {"unrelated": {"limitId": "unrelated"}}}
    with pytest.raises(RoutingBlocked):
        SmartRouter().choose(Task("format"), catalog(), limits=limits)

def test_unrelated_model_pressure_does_not_lower_selected_quality():
    limits = {"rateLimitsByLimitId": {"gpt-6-astra": {
        "limitId": "gpt-6-astra", "primary": {"usedPercent": 92}}}}
    decision = SmartRouter().choose(Task("format"), catalog(), Mode.QUALITY, limits=limits)
    assert decision.model == "gpt-6.1-sol"
    assert decision.effort == "medium"

def test_automatic_policy_caps_at_max_and_does_not_opt_into_ultra():
    models = catalog()
    for entry in models:
        entry["supportedReasoningEfforts"].append({"reasoningEffort": "ultra"})
    decision = SmartRouter().choose(Task("architecture"), models, Mode.QUALITY)
    assert decision.effort == "max"
    models[0]["supportedReasoningEfforts"] = [{"reasoningEffort": "ultra"}]
    with pytest.raises(RoutingBlocked):
        SmartRouter().choose(Task("format"), models[:1])
