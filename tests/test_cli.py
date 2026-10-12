from pathlib import Path

import pytest

from mission_control.cli import select_configuration, require_resume_state, main
from mission_control.state import save_state

MODELS = [
    {"model": "default", "isDefault": True, "defaultReasoningEffort": "medium",
     "supportedReasoningEfforts": [{"reasoningEffort": "low"}, {"reasoningEffort": "medium"}]},
    {"model": "other", "defaultReasoningEffort": "low",
     "supportedReasoningEfforts": [{"reasoningEffort": "low"}]},
]

def test_configuration_uses_catalog_default_or_explicit_model():
    assert select_configuration(MODELS, None, None) == ("default", "medium")
    assert select_configuration(MODELS, "other", "low") == ("other", "low")

@pytest.mark.parametrize("model, effort", [("missing", None), ("other", "high")])
def test_configuration_rejects_unsupported_values(model, effort):
    with pytest.raises(ValueError):
        select_configuration(MODELS, model, effort)

def test_configuration_rejects_empty_catalog():
    with pytest.raises(ValueError):
        select_configuration([], None, None)

def test_resume_requires_completed_first_turn_and_same_directory(tmp_path):
    path = tmp_path / "state.json"
    data = {"stage": "first_submitted", "cwd": str(tmp_path.resolve()),
            "threadId": "test", "model": "default", "effort": "low", "nonce": "abc"}
    save_state(path, data)
    with pytest.raises(ValueError):
        require_resume_state(path, tmp_path)
    data["stage"] = "first_completed"
    save_state(path, data)
    assert require_resume_state(path, tmp_path)["threadId"] == "test"
    with pytest.raises(ValueError):
        require_resume_state(path, tmp_path / "other")
    data["stage"] = "verified"
    save_state(path, data)
    with pytest.raises(ValueError):
        require_resume_state(path, tmp_path)

def test_help_is_available_without_codex(capsys):
    with pytest.raises(SystemExit) as exit_info:
        main(["--help"])
    assert exit_info.value.code == 0
    assert "resume-check" in capsys.readouterr().out


def test_known_configuration_errors_are_actionable_and_do_not_echo_arbitrary_errors(monkeypatch, capsys):
    import mission_control.cli as cli
    assert hasattr(cli, "UserError"), "CLI hides its own actionable validation errors"

    async def known(args):
        raise cli.UserError("State already exists; use a new --state path")
    monkeypatch.setattr(cli, "execute", known)
    assert cli.main(["smoke"]) == 1
    assert "use a new --state path" in capsys.readouterr().err

    async def unknown(args):
        raise ValueError("SECRET_SERVER_DATA")
    monkeypatch.setattr(cli, "execute", unknown)
    assert cli.main(["doctor"]) == 1
    assert "SECRET_SERVER_DATA" not in capsys.readouterr().err
