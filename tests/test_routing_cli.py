from pathlib import Path

import pytest

from mission_control import cli

def test_route_plan_and_run_arguments_are_available():
    args = cli.parser().parse_args(["route-plan", "--task", "format", "--mode", "economy"])
    assert args.command == "route-plan"
    assert args.mode == "economy"
    args = cli.parser().parse_args(["route-run", "--task-file", "task.txt",
                                   "--expect", "2", "--files", "2", "--max-attempts", "1"])
    assert args.task_file == Path("task.txt")
    assert args.expect == "2"
    assert args.files == 2

def test_route_run_failed_validation_is_nonzero(monkeypatch, capsys):
    async def failure(args):
        return {"stage": "validation_failed", "attempts": []}
    monkeypatch.setattr(cli, "execute", failure)
    assert cli.main(["route-run", "--task", "format", "--expect", "2"]) == 1
    assert "validation_failed" in capsys.readouterr().out

def test_output_cannot_overwrite_state_or_history(monkeypatch, tmp_path):
    async def should_not_run(args):
        pytest.fail("Overwrite validation must precede execution")
    monkeypatch.setattr(cli, "execute", should_not_run)
    for protected in ("state", "history"):
        path = tmp_path / (protected + ".json")
        assert cli.main(["route-run", "--task", "x", "--expect", "x",
                         "--" + protected, str(path), "--output", str(path)]) == 1

def test_route_run_requires_validator_before_opening_server(monkeypatch, tmp_path):
    from mission_control import routing_cli
    import asyncio
    args = cli.parser().parse_args(["route-run", "--task", "text", "--state", str(tmp_path / "run.json")])
    args.state = tmp_path / "run.json"
    class NoConnection:
        def __init__(self, *args, **kwargs):
            pytest.fail("Missing validator must be rejected before server starts")
    monkeypatch.setattr(routing_cli, "RpcClient", NoConnection)
    with pytest.raises(ValueError):
        asyncio.run(routing_cli.execute_routing(args))
