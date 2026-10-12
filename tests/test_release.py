import json
import pytest
from mission_control.state import StateError


def test_release_manifest_is_information_only(tmp_path):
    from mission_control.release import inspect_manifest
    path=tmp_path/'release.json'
    path.write_text(json.dumps({'version':'1.1.0','notes':'Исправления','url':'https://example.org/release','sha256':'a'*64}),encoding='utf-8')
    result=inspect_manifest(path)
    assert result['newer'] and result['version']=='1.1.0'
    assert result['trusted'] is False and result['automaticInstall'] is False


@pytest.mark.parametrize('values',[
    {'version':'1.1.0','url':'file:///C:/bad.exe'},
    {'version':'1.1.0','url':'https://user:password@example.org'},
    {'version':'1.1.0','command':'powershell bad'},
    {'version':'invalid'},
])
def test_manifest_rejects_unsafe_or_unknown_fields(tmp_path,values):
    from mission_control.release import inspect_manifest
    path=tmp_path/'release.json';path.write_text(json.dumps(values),encoding='utf-8')
    with pytest.raises(StateError):inspect_manifest(path)


def test_manifest_bounds_and_current_version(tmp_path):
    from mission_control.release import inspect_manifest
    from mission_control import __version__
    path=tmp_path/'release.json';path.write_text(json.dumps({'version':__version__}),encoding='utf-8')
    assert not inspect_manifest(path)['newer']
    path.write_bytes(b' '*65537)
    with pytest.raises(StateError):inspect_manifest(path)
