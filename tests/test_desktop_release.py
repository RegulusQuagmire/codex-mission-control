from pathlib import Path
import asyncio
import pytest
from mission_control.state import StateError


def test_smoke_parser_requires_explicit_report_and_queue():
    from mission_control.desktop.app import parse_args
    args=parse_args(['--queue','C:/isolated/missions.sqlite3','--smoke-report','C:/isolated/report.json'])
    assert args.queue==Path('C:/isolated/missions.sqlite3')
    assert args.smoke_report==Path('C:/isolated/report.json')
    assert not args.check_codex


def test_normal_launch_has_no_smoke_or_codex_request():
    from mission_control.desktop.app import parse_args
    args=parse_args([])
    assert args.smoke_report is None and not args.check_codex


def test_build_contract_preserves_state_and_no_elevation():
    root=Path(__file__).resolve().parents[1]
    installer=(root/'packaging/installer.iss').read_text(encoding='utf-8')
    assert 'PrivilegesRequired=lowest' in installer
    assert '[UninstallDelete]' not in installer
    assert 'RestartApplications=no' in installer
    spec=(root/'packaging/MissionControl.spec').read_text(encoding='utf-8')
    assert "'icuuc.dll'" in spec and 'a.binaries=' in spec


def test_portable_service_import_requires_empty_queue_and_never_grants_roots(tmp_path):
    from mission_control.desktop.service import DesktopService
    from mission_control.queue import MissionQueue
    from test_queue import text_job
    source=DesktopService(MissionQueue(tmp_path/'source.sqlite3'));source.initialize()
    source.save_preferences({'theme':'light'})
    archive=tmp_path/'transfer.cmc'
    asyncio.run(source.export_portable(str(archive),'long portable password'))
    dest=DesktopService(MissionQueue(tmp_path/'dest.sqlite3'));dest.initialize()
    asyncio.run(dest.import_portable(str(archive),'long portable password'))
    assert dest.preferences()['theme']=='light'
    assert not dest.preferences()['setupComplete'] and not dest.preferences()['resumeOnLaunch']
    assert dest.snapshot()['roots']==[] and dest.snapshot()['missions']==[]
    with pytest.raises(StateError):asyncio.run(dest.import_portable(str(archive),'long portable password'))
    busy=DesktopService(MissionQueue(tmp_path/'busy.sqlite3'));busy.initialize()
    busy.queue.add(text_job('pending',project=str(tmp_path)))
    with pytest.raises(StateError):asyncio.run(busy.import_portable(str(archive),'long portable password'))
