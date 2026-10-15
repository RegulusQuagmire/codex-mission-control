"""Inspect a source distribution without extracting or running its contents."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tarfile


def audit(archive):
    files=[]
    with tarfile.open(archive) as source:
        for member in source.getmembers():
            parts=PurePosixPath(member.name).parts
            if not parts or member.name.startswith('/') or '..' in parts or member.issym() or member.islnk():
                raise ValueError('Unsafe source path')
            name='/'.join(parts[1:]);low=name.lower()
            if any(p.lower() in {'.git','.venv','.codex','.local','__pycache__','auth.json','credentials.json','cookies.txt'} or p.startswith('.env') for p in parts):
                raise ValueError('Private source: '+name)
            if low.endswith(('.exe','.dll','.pyd','.pyc','.sqlite','.sqlite3','.db','.cmc','.pem','.key','.pfx','.p12','.log')):
                raise ValueError('Private source or binary: '+name)
            if not member.isfile():continue
            data=source.extractfile(member).read()
            if re.search(rb'gh[pousr]_[A-Za-z0-9]{30,}|sk-proj-[A-Za-z0-9_-]{30,}',data):
                raise ValueError('Sensitive source: '+name)
            files.append({'path':name,'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)})
    names={f['path'] for f in files}
    required={'LICENSE','THIRD_PARTY_NOTICES.md','packaging/requirements-build.txt',
              'packaging/python-runtime.json','packaging/INSTALLER_LICENSE.txt',
              'packaging/source-distributions.json','tools/build_release.py',
              'tools/release_audit.py','src/mission_control/pause.py',
              'src/mission_control/orchestration.py','src/mission_control/desktop/translations.json'}
    if not required<=names:raise ValueError('Missing source build inputs: '+str(sorted(required-names)))
    return {'schema':1,'archiveSha256':hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
            'files':files,'publicationAuthorized':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path);parser.add_argument('report',type=Path)
    args=parser.parse_args()
    args.report.write_text(json.dumps(audit(args.archive),indent=2)+'\n',encoding='utf-8')
