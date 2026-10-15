"""Release-only gates use synthetic inputs; never a user database or Codex."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from zipfile import ZipFile
import pytest

ROOT=Path(__file__).resolve().parents[1]


def module():
    spec=importlib.util.spec_from_file_location('sqlite_release',ROOT/'tools/sqlite_release.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def fixture(tmp_path):
    root=tmp_path/'repo';(root/'packaging').mkdir(parents=True)
    data=bytearray(160);data[:2]=b'MZ';data[60:64]=(128).to_bytes(4,'little')
    data[128:132]=b'PE\x00\x00';data[132:134]=(0x8664).to_bytes(2,'little')
    archive=tmp_path/'sqlite.zip'
    with ZipFile(archive,'w') as z:
        z.writestr('sqlite3.dll',bytes(data))
        z.writestr('sqlite3.def','EXPORTS\n')
    raw=archive.read_bytes()
    lock={'version':'3.54.0','archive':{'sha256':hashlib.sha256(raw).hexdigest(),
         'sha3_256':hashlib.sha3_256(raw).hexdigest()},
         'dll':{'member':'sqlite3.dll','sha256':hashlib.sha256(data).hexdigest()}}
    (root/'packaging/sqlite-runtime.json').write_text(json.dumps(lock),encoding='utf-8')
    return root,archive,lock


def test_sqlite_override_rejects_changed_archive(tmp_path):
    root,archive,_=fixture(tmp_path);archive.write_bytes(archive.read_bytes()+b'tamper')
    with pytest.raises(ValueError,match='SQLite archive hash mismatch'):
        module().verify(root,archive)


def test_sqlite_override_authenticates_one_target_without_modifying_python(tmp_path):
    root,archive,lock=fixture(tmp_path);original=tmp_path/'python/sqlite3.dll'
    original.parent.mkdir();original.write_bytes(b'original Python bytes')
    entries=[('sqlite3.dll',str(original),'BINARY'),('unrelated.dll','untouched','BINARY')]
    result,owners=module().replace(entries,root,archive,tmp_path/'isolated')
    assert original.read_bytes()==b'original Python bytes'
    assert result[1]==entries[1] and result[0][0]=='sqlite3.dll'
    target=Path(result[0][1]);assert target!=original
    assert hashlib.sha256(target.read_bytes()).hexdigest()==lock['dll']['sha256']
    assert owners[target.resolve()]==('SQLite','3.54.0','sqlite3.dll',lock['dll']['sha256'])


@pytest.mark.parametrize('count',[0,2])
def test_sqlite_override_never_silently_uses_an_old_or_ambiguous_dll(tmp_path,count):
    root,archive,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='Exactly one SQLite DLL'):
        module().replace([('sqlite3.dll','old','BINARY')]*count,root,archive,tmp_path/'isolated')
    assert not (tmp_path/'isolated').exists()


def test_sqlite_runtime_qa_reports_actual_loaded_library():
    if sys.platform!='win32':pytest.skip('Windows DLL provenance')
    import sqlite3
    from mission_control.desktop.runtime_qa import sqlite_runtime
    value=sqlite_runtime()
    assert value['version']==sqlite3.sqlite_version
    assert value['threadSafety']>0 and value['sourceId']
    loaded=Path(value['loadedDll'])
    assert loaded.name.lower()=='sqlite3.dll'
    assert hashlib.sha256(loaded.read_bytes()).hexdigest()==value['loadedDllSha256']


def assets_module():
    sys.path.insert(0,str(ROOT/'tools'))
    spec=importlib.util.spec_from_file_location('release_assets',ROOT/'tools/release_assets.py')
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    return value


def test_release_sources_are_explicit_and_fail_on_changed_archive(tmp_path):
    asset=assets_module();archive=tmp_path/'qt-source.tar.gz';archive.write_bytes(b'original')
    catalogue={'sources':[{'path':archive.name,'sha256':hashlib.sha256(b'original').hexdigest()}],'rustCrates':[]}
    private=tmp_path/'private.db';private.write_bytes(b'never distribute')
    entries=asset.source_files(catalogue,[tmp_path])
    assert entries==[('upstream/qt-source.tar.gz',archive)]
    archive.write_bytes(b'changed')
    with pytest.raises(ValueError,match='Missing or changed corresponding source'):
        asset.source_files(catalogue,[tmp_path])


def test_release_zip_is_repeatable_and_rejects_traversal(tmp_path):
    asset=assets_module();source=tmp_path/'notice.txt';source.write_text('synthetic')
    a=tmp_path/'a.zip';b=tmp_path/'b.zip'
    asset.zip_files(a,[('notice.txt',source)]);asset.zip_files(b,[('notice.txt',source)])
    assert a.read_bytes()==b.read_bytes()
    with pytest.raises(ValueError,match='Unsafe or duplicate'):
        asset.zip_files(tmp_path/'bad.zip',[('../secret',source)])


@pytest.mark.parametrize('changed',['source','checkout','missing','extra'])
def test_release_assets_bind_source_and_companion_files_to_candidate(tmp_path,changed):
    asset=assets_module();p=tmp_path/'src/module.py';p.parent.mkdir();p.write_bytes(b'reviewed')
    expected=hashlib.sha256(b'reviewed').hexdigest()
    receipt={'sourceFiles':[{'path':'src/module.py','sha256':expected}]}
    source={'files':[{'path':'src/module.py','sha256':expected}]}
    if changed=='source':source['files'][0]['sha256']='0'*64
    if changed=='checkout':p.write_bytes(b'changed after build')
    if changed=='missing':source['files']=[]
    if changed=='extra':source['files'].append({'path':'src/unreviewed.py','sha256':expected})
    with pytest.raises(ValueError,match='candidate'):
        asset.bind_source(tmp_path,receipt,source)


def test_new_checkout_license_file_never_enters_release_sources(tmp_path):
    asset=assets_module();directory=tmp_path/'packaging/licenses/Example';directory.mkdir(parents=True)
    notice=directory/'LICENSE.txt';notice.write_bytes(b'reviewed notice')
    private=directory/'auth.json';private.write_bytes(b'private data added after build')
    receipt={'sourceFiles':[{'path':'packaging/licenses/Example/LICENSE.txt','sha256':hashlib.sha256(notice.read_bytes()).hexdigest()}]}
    assert asset.license_files(tmp_path,receipt)==[('licenses/Example/LICENSE.txt',notice)]
