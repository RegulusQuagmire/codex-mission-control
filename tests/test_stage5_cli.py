import json
from mission_control.cli import main,parser
from mission_control.queue import MissionQueue
from mission_control.state import StateError
from mission_control.safety import authorize
from test_queue import text_job


def test_default_sqlite_and_explicit_offline_controls(tmp_path,capsys):
    assert parser().parse_args(['queue-list']).queue.suffix=='.sqlite3'
    project=tmp_path/'project';project.mkdir()
    q=tmp_path/'q.sqlite3';manifest=tmp_path/'mission.json'
    manifest.write_text(json.dumps(text_job('a',project=str(project))))
    assert main(['queue-configure','--queue',str(q),'--allow-root',str(project)])==0
    assert main(['queue-add','--queue',str(q),'--mission',str(manifest)])==0
    assert main(['queue-approve','--queue',str(q),'--mission-id','a'])==0
    queue=MissionQueue(q);authorize(queue,queue.read()['missions']['a'])
    backup=tmp_path/'backup.sqlite3'
    assert main(['queue-backup','--queue',str(q),'--destination',str(backup)])==0
    assert main(['queue-backup','--queue',str(q),'--destination',str(backup)])==1
    assert MissionQueue(backup).read()['missions']['a']['status']=='pending'
    assert main(['queue-list','--queue',str(q),'--output',str(q)+'-journal'])==1


def test_cli_refuses_legacy_automation_without_starting_codex(tmp_path,capsys):
    assert main(['queue-run','--queue',str(tmp_path/'legacy.json'),'--codex','absent'])==1
    assert 'Legacy JSON automation is disabled' in capsys.readouterr().err


def test_cli_report_secret_values_are_redacted(tmp_path,monkeypatch,capsys):
    import mission_control.cli as cli
    secret='sk-proj-'+'a'*32
    async def execute(args):return {'stage':'completed','diagnostic':secret}
    monkeypatch.setattr(cli,'execute',execute)
    output=tmp_path/'report.json'
    assert main(['doctor','--output',str(output)])==0
    assert secret not in capsys.readouterr().out and secret not in output.read_text()
    assert '[REDACTED]' in output.read_text()


def test_checkpoint_export_available_for_stopped_uncertain_mission(tmp_path,monkeypatch):
    import asyncio
    from pathlib import Path
    from test_sqlite_queue import project_queue,worker
    monkeypatch.setattr('mission_control.queue.worker_lease_path',lambda:tmp_path/'worker')
    q,s=project_queue(tmp_path);s.drop_ack=True
    result=asyncio.run(worker(q,s).run(max_wait=0));assert result['active']=='code'
    destination=tmp_path/'recovered-baseline'
    assert main(['queue-checkpoint-export','--queue',str(q.path),'--mission-id','code','--destination',str(destination)])==0
    assert (destination/'app.py').read_text()=='VALUE = 1\n'
    assert q.read()['active']=='code' and len(s.submissions)==1
