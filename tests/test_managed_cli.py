"""Command validation runs before starting Codex or inference."""
from mission_control.cli import main, parser
from mission_control.state import save_state


def test_managed_commands_have_explicit_wait_and_budget_controls():
    args=parser().parse_args(["managed-run","--task","return 2","--expect","2",
          "--limit-policy","weekly","--max-wait","60"])
    assert args.limit_policy=="weekly" and args.max_wait==60
    assert parser().parse_args(["limits"]).command=="limits"
    assert parser().parse_args(["managed-resume"]).task is None


def test_missing_expected_output_is_rejected_without_creating_state(tmp_path):
    state=tmp_path/"state.json"
    assert main(["managed-run","--task","return 2","--state",str(state)])==1
    assert not state.exists()


def test_resume_rejects_new_task_and_does_not_touch_journal(tmp_path):
    state=tmp_path/"state.json";save_state(state,{"original":True})
    before=state.read_bytes()
    assert main(["managed-resume","--task","new task","--state",str(state)])==1
    assert state.read_bytes()==before


def test_invalid_wait_is_rejected_before_saving_a_job(tmp_path):
    state=tmp_path/"state.json"
    assert main(["managed-run","--task","return 2","--expect","2","--state",str(state),
                 "--max-wait","nan"])==1
    assert not state.exists()
