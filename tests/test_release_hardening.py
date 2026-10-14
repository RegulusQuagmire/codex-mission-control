"""Offline release gates, using synthetic payloads and disposable state only."""
import importlib.util
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def audit_module():
    spec = importlib.util.spec_from_file_location('release_audit', ROOT/'tools/release_audit.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize('argv', [
    ['--smoke-report', 'report.json'],
    ['--smoke-language', 'en'],
    ['--smoke-theme', 'light'],
    ['--smoke-screenshots', 'frames'],
])
def test_smoke_cannot_fall_back_to_user_database(argv):
    from mission_control.desktop.app import parse_args
    with pytest.raises(SystemExit): parse_args(argv)


def test_smoke_rejects_real_default_queue(monkeypatch, tmp_path):
    from mission_control.desktop.app import parse_args
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path))
    with pytest.raises(SystemExit):
        parse_args(['--queue', str(tmp_path/'CodexMissionControl/missions.sqlite3'),
                    '--smoke-report', str(tmp_path/'report.json')])


@pytest.mark.parametrize('name', ['auth.json', '.env', 'private.key', 'missions.sqlite3',
                                  '.codex/config.toml', 'assistant.exe', 'Qt6Qml.dll'])
def test_bundle_audit_rejects_private_or_unneeded_payload(tmp_path, name):
    target = tmp_path/name; target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b'synthetic')
    with pytest.raises(ValueError): audit_module().inventory(tmp_path)


def test_bundle_audit_rejects_secret_content_without_reporting_secret(tmp_path):
    (tmp_path/'notes.txt').write_text('-----BEGIN '+'PRIVATE KEY-----\nSYNTHETIC')
    with pytest.raises(ValueError, match='Sensitive content: notes.txt'):
        audit_module().inventory(tmp_path)


def test_manifest_is_stable_relative_and_detects_tampering(tmp_path):
    audit = audit_module()
    (tmp_path/'MissionControl.exe').write_bytes(b'synthetic PE')
    (tmp_path/'LICENSE').write_text('synthetic license')
    before = audit.inventory(tmp_path)
    assert before == audit.inventory(tmp_path)
    assert [f['path'] for f in before] == ['LICENSE', 'MissionControl.exe']
    assert all(str(tmp_path) not in str(f) for f in before)
    (tmp_path/'MissionControl.exe').write_bytes(b'changed')
    assert audit.inventory(tmp_path) != before


def test_binary_crypto_format_constant_is_not_a_private_key(tmp_path):
    target=tmp_path/'crypto.dll'
    target.write_bytes(b'PE\x00-----BEGIN '+b'PRIVATE KEY-----\x00format string')
    assert len(audit_module().inventory(tmp_path))==1
    target.write_bytes(b'-----BEGIN '+b'PRIVATE KEY-----\n'+(b'A'*64+b'\n')*3)
    with pytest.raises(ValueError): audit_module().inventory(tmp_path)


def test_modified_installed_wheel_file_is_rejected(tmp_path,monkeypatch):
    import hashlib
    from zipfile import ZipFile
    audit=audit_module()
    (tmp_path/'packaging').mkdir(); (tmp_path/'wheels').mkdir(); (tmp_path/'installed').mkdir()
    wheel=tmp_path/'wheels/dep.whl'
    with ZipFile(wheel,'w') as z:z.writestr('dep.py',b'original')
    digest=hashlib.sha256(wheel.read_bytes()).hexdigest()
    (tmp_path/'packaging/requirements-build.txt').write_text('dep==1.0 --hash=sha256:'+digest)
    (tmp_path/'installed/dep.py').write_bytes(b'tampered')
    class Dist:
        version='1.0'
        def locate_file(self,name):return tmp_path/'installed'/name
    monkeypatch.setattr(audit,'distribution',lambda _:Dist())
    monkeypatch.setattr(audit.sys,'version_info',(3,14,8))
    monkeypatch.setattr(audit,'verify_runtime',lambda *args: {})
    with pytest.raises(ValueError,match='Installed build file mismatch'):
        audit.environment(tmp_path,tmp_path/'wheels',tmp_path/'runtime.zip')


def test_release_environment_cannot_inherit_developer_native_paths(tmp_path,monkeypatch):
    audit=audit_module();monkeypatch.setenv('PATH','C:/untrusted/poppler;C:/untrusted/libheif')
    monkeypatch.setenv('PYTHONPATH','C:/untrusted/modules');monkeypatch.setenv('QT_PLUGIN_PATH','C:/untrusted/plugins')
    env=audit.clean_environment(tmp_path/'python',tmp_path/'cache')
    assert 'untrusted' not in env['PATH']
    assert 'PYTHONPATH' not in env and 'QT_PLUGIN_PATH' not in env
    assert env['PYTHONNOUSERSITE']=='1' and env['PYTHONHASHSEED']=='0'


def test_native_provenance_rejects_unpinned_external_dll(tmp_path):
    audit=audit_module();python=tmp_path/'python';python.mkdir()
    external=tmp_path/'poppler/libssl-3-x64.dll';external.parent.mkdir();external.write_bytes(b'wrong SSL')
    with pytest.raises(ValueError,match='Unpinned native input'):
        audit.binary_provenance([('libssl-3-x64.dll',str(external),'BINARY')],python,{})


def test_native_provenance_has_only_relative_authenticated_provider(tmp_path):
    audit=audit_module();python=tmp_path/'python';python.mkdir()
    dll=python/'python314.dll';dll.write_bytes(b'synthetic')
    import hashlib
    owners={dll.resolve():('CPython','3.14.8','python314.dll',hashlib.sha256(dll.read_bytes()).hexdigest())}
    result=audit.binary_provenance([('python314.dll',str(dll),'BINARY')],python,owners)
    assert result[0]['provider']=='CPython' and result[0]['source']=='python314.dll'
    assert str(tmp_path) not in str(result)


def test_runtime_archive_rejects_changed_installed_file(tmp_path):
    import hashlib
    from zipfile import ZipFile
    archive=tmp_path/'python.zip';runtime=tmp_path/'runtime';runtime.mkdir()
    with ZipFile(archive,'w') as z:z.writestr('python314.dll',b'expected')
    (runtime/'python314.dll').write_bytes(b'changed')
    with pytest.raises(ValueError,match='Runtime file mismatch'):
        audit_module().verify_archive(archive,runtime,hashlib.sha256(archive.read_bytes()).hexdigest())


def test_source_smoke_captures_consistent_english_light_settings(tmp_path):
    import subprocess,sys,os,json
    target=tmp_path/'report.json'
    result=subprocess.run([sys.executable,'-m','mission_control.desktop.app','--queue',str(tmp_path/'qa.sqlite3'),
        '--smoke-report',str(target),'--smoke-language','en','--smoke-theme','light',
        '--smoke-screenshots',str(tmp_path/'screens')],
        env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stderr
    report=json.loads(target.read_text(encoding='utf-8'))
    assert report['errors']==[] and report['language']=='en' and report['settingsTitle']=='Settings'
    assert report['theme']==report['settingsTheme']=='light' and report['settingsReducedMotion']
    assert report['frozen'] is False and len(report['screenshots'])==8


def test_build_lock_pins_every_wheel_and_has_hashes():
    lines = [line for line in (ROOT/'packaging/requirements-build.txt').read_text(encoding='utf-8').splitlines()
             if line and not line.startswith('#')]
    assert len(lines) == 12
    assert all('==' in line and '--hash=sha256:' in line for line in lines)


def test_installer_has_localized_tasks_and_license():
    source = (ROOT/'packaging/installer.iss').read_text(encoding='utf-8')
    assert '[CustomMessages]' in source and 'english.DesktopIcon=' in source
    assert 'LicenseFile=' in source
    assert 'AppVersion' in source and 'UninstallDelete' not in source.replace('; No UninstallDelete', '')

@pytest.mark.parametrize('name',['PySide6/opengl32sw.dll','PySide6/plugins/imageformats/qjpeg.dll'])
def test_retired_runtime_plugins_fail_closed(tmp_path,name):
    path=tmp_path/name;path.parent.mkdir(parents=True);path.write_bytes(b'synthetic')
    with pytest.raises(ValueError,match='Retired native component'):audit_module().inventory(tmp_path)


def test_release_metadata_and_component_terms_are_consistent():
    import tomllib
    from mission_control import __version__
    version=tomllib.loads((ROOT/'pyproject.toml').read_text(encoding='utf-8'))['project']['version']
    assert version==__version__=='0.7.1'
    assert '#define AppVersion "'+version+'"' in (ROOT/'packaging/installer.iss').read_text(encoding='utf-8')
    terms=(ROOT/'packaging/INSTALLER_LICENSE.txt').read_text(encoding='utf-8')
    assert 'These restrictions apply only to the Microsoft Distributable Code' in terms
    assert 'MIT License' in terms and 'LGPL' in terms


def test_source_archive_rejects_private_files_and_missing_build_inputs(tmp_path):
    import tarfile,io
    spec=importlib.util.spec_from_file_location('source_audit',ROOT/'tools/source_audit.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    archive=tmp_path/'source.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        value=tarfile.TarInfo('project/auth.json');value.size=2;tar.addfile(value,io.BytesIO(b'{}'))
    with pytest.raises(ValueError,match='Private source'):module.audit(archive)

def test_basic_smoke_reports_actual_qt_platform_without_screenshots(tmp_path):
    import subprocess,sys,os,json
    report=tmp_path/'report.json'
    process=subprocess.run([sys.executable,'-m','mission_control.desktop.app','--queue',str(tmp_path/'qa.sqlite3'),'--smoke-report',str(report)],env={**os.environ,'PYTHONPATH':str(ROOT/'src')},capture_output=True,text=True,timeout=45)
    assert process.returncode==0,process.stderr
    value=json.loads(report.read_text(encoding='utf-8'))
    assert value['qtPlatform'] in {'windows','offscreen'} and not value['errors']

def test_installer_russian_labels_are_readable_utf8():
    source=(ROOT/'packaging/installer.iss').read_text(encoding='utf-8')
    assert 'russian.DesktopIcon=Создать ярлык на рабочем столе' in source
    assert 'russian.OpenApp=Открыть Mission Control' in source

def test_native_runtime_extra_file_does_not_gain_trust_from_directory(tmp_path):
    audit=audit_module();runtime=tmp_path/'python';runtime.mkdir()
    dll=runtime/'injected.dll';dll.write_bytes(b'untrusted')
    with pytest.raises(ValueError,match='Unpinned native input'):
        audit.binary_provenance([('injected.dll',str(dll),'BINARY')],runtime,{})


def test_native_bytes_must_match_authenticated_archive_member(tmp_path):
    audit=audit_module();dll=tmp_path/'wheel.dll';dll.write_bytes(b'tampered')
    owners={dll.resolve():('example','1.0','wheel.dll','0'*64)}
    with pytest.raises(ValueError,match='Native input hash mismatch'):
        audit.binary_provenance([('wheel.dll',str(dll),'BINARY')],tmp_path/'python',owners)

def test_native_owner_catalog_ignores_forged_installed_record(tmp_path,monkeypatch):
    import hashlib,json
    from zipfile import ZipFile
    audit=audit_module();runtime=tmp_path/'runtime';runtime.mkdir();wheels=tmp_path/'wheels';wheels.mkdir()
    packaging=tmp_path/'packaging';packaging.mkdir();archive=tmp_path/'python.zip'
    with ZipFile(archive,'w') as z:z.writestr('python314.dll',b'official')
    (packaging/'python-runtime.json').write_text(json.dumps({'version':'3.14.8','sha256':hashlib.sha256(archive.read_bytes()).hexdigest()}))
    wheel=wheels/'example.whl'
    with ZipFile(wheel,'w') as z:z.writestr('wheel.dll',b'official wheel')
    (packaging/'requirements-build.txt').write_text('example==1.0 --hash=sha256:'+hashlib.sha256(wheel.read_bytes()).hexdigest())
    class Dist:
        version='1.0'
        @property
        def files(self):raise AssertionError('Installed RECORD is not an authentication source')
        def locate_file(self,name):return tmp_path/'installed'/name
    monkeypatch.setattr(audit,'distribution',lambda name:Dist())
    monkeypatch.setattr(audit.sys,'base_prefix',str(runtime))
    owners=audit.wheel_owners(tmp_path,wheels,archive)
    assert set(owners)=={(runtime/'python314.dll').resolve(),(tmp_path/'installed/wheel.dll').resolve()}
