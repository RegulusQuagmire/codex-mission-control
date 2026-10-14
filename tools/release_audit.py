"""Local release inventory and fail-closed payload gates. Never submits work."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import types
from zipfile import ZipFile
from importlib.metadata import distribution


def clean_environment(python_root, cache):
    env=dict(os.environ)
    for name in ('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','QT_PLUGIN_PATH','QML2_IMPORT_PATH','QML_IMPORT_PATH'):
        env.pop(name,None)
    windows=Path(env.get('SystemRoot','C:/Windows'))
    env.update(PATH=os.pathsep.join(map(str,[windows/'System32',windows,Path(python_root),Path(python_root)/'DLLs'])),
               PYTHONNOUSERSITE='1',PYTHONSAFEPATH='1',PYTHONHASHSEED='0',
               SOURCE_DATE_EPOCH='1791936000',PYTHONPYCACHEPREFIX=str(cache))
    return env


def verify_archive(archive, destination, checksum):
    archive=Path(archive);destination=Path(destination).resolve()
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=checksum:raise ValueError('Runtime archive hash mismatch')
    with ZipFile(archive) as zipfile:
        for name in zipfile.namelist():
            if name.endswith('/'):continue
            target=destination/name
            if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Invalid runtime archive path')
            if any(p.is_symlink() or p.is_junction() for p in [target,*target.parents]):raise ValueError('Linked runtime input')
            if not target.is_file() or target.read_bytes()!=zipfile.read(name):raise ValueError('Runtime file mismatch: '+name)


def verify_runtime(root, archive):
    lock=json.loads((Path(root)/'packaging/python-runtime.json').read_text())
    if archive is None:raise ValueError('Verified Python runtime archive required')
    verify_archive(archive,Path(sys.base_prefix),lock['sha256'])
    return lock


def wheel_owners(root, wheelhouse, runtime_archive):
    """Ownership comes from authenticated archives, never installed RECORD claims."""
    root=Path(root);owners={}
    lock=json.loads((root/'packaging/python-runtime.json').read_text(encoding='utf-8'))
    runtime_archive=Path(runtime_archive)
    if hashlib.sha256(runtime_archive.read_bytes()).hexdigest()!=lock['sha256']:
        raise ValueError('Runtime archive hash mismatch')
    with ZipFile(runtime_archive) as archive:
        for name in archive.namelist():
            if name.endswith(('/', '.pyc')):continue
            if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('Unsafe runtime member')
            target=(Path(sys.base_prefix)/name).resolve()
            owners[target]=('CPython',lock['version'],name,hashlib.sha256(archive.read(name)).hexdigest())
    wheels={hashlib.sha256(p.read_bytes()).hexdigest():p for p in Path(wheelhouse).glob('*.whl')}
    for line in (root/'packaging/requirements-build.txt').read_text(encoding='utf-8').splitlines():
        if not line or line.startswith('#'):continue
        requirement,checksum=line.split(' --hash=sha256:');name,version=requirement.split('==')
        dist=distribution(name)
        if checksum not in wheels or dist.version!=version:raise ValueError('Unverified wheel provider: '+name)
        with ZipFile(wheels[checksum]) as archive:
            for member in archive.namelist():
                if member.endswith(('/', '.pyc', '.dist-info/RECORD')):continue
                if Path(member).is_absolute() or '..' in Path(member).parts or '.data/' in member:
                    raise ValueError('Unsupported wheel layout: '+name)
                target=Path(dist.locate_file(member)).resolve()
                owners[target]=(name,version,member,hashlib.sha256(archive.read(member)).hexdigest())
    return owners


def binary_provenance(entries, python_root, owners):
    result=[];python_root=Path(python_root).resolve()
    for destination,source,kind in entries:
        source=Path(source)
        if any(p.is_symlink() or p.is_junction() for p in [source,*source.parents]):raise ValueError('Linked native input')
        source=source.resolve()
        if source not in owners:raise ValueError('Unpinned native input: '+destination)
        provider,version,relative,expected=owners[source]
        if hashlib.sha256(source.read_bytes()).hexdigest()!=expected:
            raise ValueError('Native input hash mismatch: '+destination)
        result.append({'path':destination.replace('\\','/'),'provider':provider,'version':version,
                       'source':relative,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()})
    return sorted(result,key=lambda item:item['path'])

PRIVATE_NAMES = {'auth.json', 'credentials.json', 'cookies.txt', '.git', '.codex', '.local', '.venv'}
PRIVATE_SUFFIXES = {'.sqlite', '.sqlite3', '.db', '.cmc', '.pem', '.key', '.pfx', '.p12', '.log'}
QT_DLLS = {'qt6core.dll', 'qt6gui.dll', 'qt6widgets.dll', 'qt6network.dll',
           'qt6opengl.dll', 'qt6dbus.dll', 'qt6svg.dll'}
SECRET = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{30,}')
TOKEN = re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{30,}')
KEY_BLOCK = re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----\r?\n(?:[A-Za-z0-9+/=]{40,}\r?\n){2,}')


def inventory(folder):
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink(): raise ValueError('Expected a real payload directory')
    result = []
    for path in sorted(folder.rglob('*')):
        name = path.relative_to(folder).as_posix()
        parts = {part.lower() for part in Path(name).parts}
        if path.is_symlink() or path.is_junction(): raise ValueError('Linked payload: '+name)
        if parts & PRIVATE_NAMES or any(p == '.env' or p.startswith('.env.') for p in parts):
            raise ValueError('Private payload: '+name)
        if not path.is_file(): continue
        low = path.name.lower()
        if low=='opengl32sw.dll' or ('imageformats' in parts and low.endswith('.dll') and low!='qsvg.dll'):
            raise ValueError('Retired native component: '+name)
        if path.suffix.lower() in PRIVATE_SUFFIXES or low.endswith(('.sqlite3-wal', '.sqlite3-shm', '.db-wal', '.db-shm')):
            raise ValueError('Private payload: '+name)
        if low.endswith('.exe') and low != 'missioncontrol.exe': raise ValueError('Unexpected executable: '+name)
        if low.startswith('qt6') and low.endswith('.dll') and low not in QT_DLLS:
            raise ValueError('Unreviewed Qt module: '+name)
        data = path.read_bytes()
        # Crypto DLLs legitimately contain PEM delimiter strings as format constants.
        # Text payloads reject even a delimiter; binaries require key body evidence.
        sensitive = SECRET.search(data) if path.suffix.lower() in {'.txt','.md','.json','.py','.toml'} else TOKEN.search(data) or KEY_BLOCK.search(data)
        if sensitive: raise ValueError('Sensitive content: '+name)
        result.append({'path': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    return result


def environment(root, wheelhouse, runtime_archive=None):
    """Verify pinned build wheels; no absolute paths or account information in receipt."""
    root = Path(root)
    if sys.version_info[:3] != (3, 14, 8) or sys.platform != 'win32':
        raise ValueError('Release build requires CPython 3.14.8 on Windows x64')
    import struct
    if struct.calcsize('P') != 8: raise ValueError('Release build requires x64 Python')
    runtime=verify_runtime(root,runtime_archive)
    wheels_by_hash={hashlib.sha256(p.read_bytes()).hexdigest():p for p in Path(wheelhouse).glob('*.whl')}
    dependencies = []
    for line in (root/'packaging/requirements-build.txt').read_text().splitlines():
        if not line or line.startswith('#'): continue
        requirement, checksum = line.split(' --hash=sha256:')
        name, version = requirement.split('==')
        dist = distribution(name)
        if len(checksum) != 64 or dist.version != version:
            raise ValueError('Build dependency mismatch: '+name)
        wheel=wheels_by_hash.get(checksum)
        if wheel is None: raise ValueError('Missing hash-verified wheel: '+name)
        with ZipFile(wheel) as archive:
            for entry in archive.namelist():
                # pip regenerates wheel-supplied bytecode for its installation path.
                # It is derived data, never an authenticated build input: the
                # builder uses a fresh PYTHONPYCACHEPREFIX for compilation/audit.
                if entry.endswith(('/', '.pyc', '.dist-info/RECORD')): continue
                if '..' in Path(entry).parts or '.data/' in entry: raise ValueError('Unsupported wheel layout: '+name)
                installed = Path(dist.locate_file(entry))
                if not installed.is_file() or installed.is_symlink() or installed.read_bytes() != archive.read(entry):
                    raise ValueError('Installed build file mismatch: '+name+'/'+entry)
        dependencies.append({'name': name, 'version': version, 'wheelSha256': checksum})
    if len(dependencies) != 12: raise ValueError('Incomplete build lock')
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=root).decode().split('\0')
    sources = []
    for name in sorted(set(tracked)-{''}):
        path = root/name
        if path.is_symlink() or not path.is_file(): raise ValueError('Unexpected source entry: '+name)
        sources.append({'path': name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'schema': 1, 'python': '3.14.8', 'runtime':runtime,'platform': 'windows-x64',
            'dependencies': dependencies, 'sourceFiles': sources}


def audit(folder):
    files = inventory(folder)
    names = {f['path'].lower() for f in files}
    required = {'missioncontrol.exe', '_internal/license', '_internal/third_party_notices.md', '_internal/installer_license.txt',
                '_internal/source-distributions.json', '_internal/licenses/third-party/rust/third_party_notices.txt',
                '_internal/licenses/third-party/qt/third_party_notices.txt', '_internal/licenses/third-party/runtime/third_party_notices.txt',
                '_internal/mission_control/desktop/translations.json', '_internal/licenses/python/license.txt',
                '_internal/licenses/third-party/qt/lgpl-3.0-only.txt',
                '_internal/licenses/third-party/qt/gpl-3.0-only.txt'}
    if not required <= names: raise ValueError('Incomplete release payload: '+str(sorted(required-names)))
    for name in ('Qt6Core.dll', 'Qt6Gui.dll', 'Qt6Widgets.dll'):
        if not any(p.endswith('/'+name.lower()) for p in names): raise ValueError('Missing replaceable Qt library: '+name)
    from PyInstaller.archive.readers import CArchiveReader
    archive=CArchiveReader(str(Path(folder)/'MissionControl.exe'))
    pyz=archive.open_embedded_archive('PYZ.pyz')
    modules=sorted(pyz.toc)
    required_modules={'mission_control.queue','mission_control.managed','mission_control.adapter',
                      'mission_control.pause','mission_control.orchestration',
                      'mission_control.model_policy','mission_control.credit_policy'}
    if not required_modules <= set(modules): raise ValueError('Missing protected execution modules')
    def inspect_code(code,module):
        if isinstance(code,types.CodeType):
            filename=code.co_filename.replace('\\','/').lower()
            if '/users/' in filename:
                raise ValueError('Private build path in application module: '+module)
            for value in code.co_consts:inspect_code(value,module)
        elif isinstance(code,(str,bytes)):
            value=code.encode('utf-8') if isinstance(code,str) else code
            if TOKEN.search(value) or KEY_BLOCK.search(value): raise ValueError('Sensitive archived content: '+module)
    for module in modules:inspect_code(pyz.extract(module),module)
    return {'schema': 1, 'files': files, 'pythonModules':modules, 'publicationAuthorized': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['environment', 'bundle'])
    parser.add_argument('folder', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--wheelhouse', type=Path)
    parser.add_argument('--runtime-archive',type=Path)
    args = parser.parse_args()
    if args.operation == 'environment' and not args.wheelhouse: parser.error('--wheelhouse is required')
    report = environment(args.folder,args.wheelhouse,args.runtime_archive) if args.operation == 'environment' else audit(args.folder)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')


if __name__ == '__main__': main()
