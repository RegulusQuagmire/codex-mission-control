"""Offline quota snapshots; no production statistics are fabricated."""
import math
import pytest
from mission_control.limits import LimitPolicy, inspect_limits, check_limits


def snapshot(primary=None, secondary=None, **extra):
    return {"rateLimitsByLimitId": {"codex": {"limitId": "codex",
            "primary": primary, "secondary": secondary, **extra}}}


def window(used, duration=300, reset=2000):
    return {"usedPercent": used, "windowDurationMins": duration, "resetsAt": reset}


def test_windows_are_classified_by_duration_and_both_reset_times_gate():
    data = snapshot(window(100,10080,5000),window(100,300,2000))
    report = inspect_limits(data)
    assert [row["kind"] for row in report["windows"]] == ["weekly", "five_hour"]
    result = check_limits(data,"gpt-6-luna",now=1000)
    assert not result["allowed"] and result["wakeAt"] == 5005


@pytest.mark.parametrize("used", [None, -1, 101, True, math.nan, math.inf, "100"])
def test_invalid_usage_does_not_manufacture_available_quota(used):
    result = check_limits(snapshot(window(used)),"gpt-6-luna",now=1000)
    assert not result["allowed"] and result["reason"] == "limits_unknown"


def test_reset_passing_never_means_available_without_new_snapshot():
    result = check_limits(snapshot(window(100,reset=999)),"gpt-6-luna",now=1000)
    assert not result["allowed"] and result["wakeAt"] == 1300


def test_one_unknown_blocked_window_prevents_claiming_known_full_reset():
    result = check_limits(snapshot(window(100,reset=None),window(100,10080,5000)),
                          "gpt-6-luna",now=1000)
    assert not result["allowed"] and result["wakeAt"] == 1300


def test_sparse_notifications_do_not_erase_other_window_or_mutate_input():
    from mission_control.limits import merge_limit_update
    original = snapshot(window(20),window(30,10080,5000))
    merged = merge_limit_update(original,{"rateLimits":{"limitId":"codex","primary":window(100)}})
    rows=inspect_limits(merged)["windows"]
    assert [r["usedPercent"] for r in rows] == [100,30]
    assert inspect_limits(original)["windows"][0]["usedPercent"] == 20


def test_alias_metadata_is_not_parent_model_quota():
    data={"rateLimitsByLimitId":{
      "codex":{"limitId":"codex","primary":window(20)},
      "alias":{"limitId":"alias","normalModelSlug":"gpt-6-luna","primary":window(100)}}}
    assert check_limits(data,"gpt-6-luna",now=1000)["allowed"]
    assert not check_limits(data,"alias",now=1000)["allowed"]


def test_weekly_reserve_and_stop_policies_are_enforced():
    data=snapshot(window(50),window(86,10080,5000))
    assert check_limits(data,"model",now=1000)["allowed"]
    assert not check_limits(data,"model",now=1000,policy=LimitPolicy("weekly"))["allowed"]
    assert not check_limits(snapshot(window(91)),"model",now=1000,policy=LimitPolicy("reserve"))["allowed"]
    assert not check_limits(snapshot(window(61)),"model",now=1000,policy=LimitPolicy("stop",60))["allowed"]


def test_unknown_duration_is_not_labelled_five_hour():
    row=inspect_limits(snapshot(window(42,None,None)))["windows"][0]
    assert row["kind"] == "unknown" and row["resetsAt"] is None


def test_workspace_spend_control_has_no_invented_reset():
    result=check_limits(snapshot(window(20),spendControlReached=True),"model",now=1000)
    assert not result["allowed"] and result["reason"] == "spend_control"
    assert result["wakeAt"] == 1300


def test_unknown_backoff_is_capped():
    assert check_limits(None,"model",now=1000,failures=0)["wakeAt"] == 1300
    assert check_limits(None,"model",now=1000,failures=50)["wakeAt"] == 4600


@pytest.mark.parametrize("policy", [("stop",0),("stop",101),("stop",float("nan")),("invalid",100)])
def test_invalid_policy_is_rejected(policy):
    with pytest.raises(ValueError): LimitPolicy(*policy)
