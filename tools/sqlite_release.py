"""Authenticated, build-only SQLite override. Never edits the Python runtime."""
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


def verify(root,archive):
    lock=json.loads((Path(root)/'packaging/sqlite-runtime.json').read_text(encoding='utf-8'))
    data=Path(archive).read_bytes()
    if (hashlib.sha256(data).hexdigest()!=lock['archive']['sha256'] or
            hashlib.sha3_256(data).hexdigest()!=lock['archive']['sha3_256']):
        raise ValueError('SQLite archive hash mismatch')
    if tuple(map(int,lock['version'].split('.')))<(3,53,2):raise ValueError('SQLite FTS5 fix required')
    with ZipFile(archive) as z:
        if len(z.namelist())!=2 or set(z.namelist())!={'sqlite3.dll','sqlite3.def'}:
            raise ValueError('Unexpected SQLite archive members')
        dll=z.read(lock['dll']['member'])
    if hashlib.sha256(dll).hexdigest()!=lock['dll']['sha256']:raise ValueError('SQLite DLL hash mismatch')
    offset=int.from_bytes(dll[60:64],'little')
    if (dll[:2]!=b'MZ' or dll[offset:offset+4]!=b'PE\x00\x00' or
            int.from_bytes(dll[offset+4:offset+6],'little')!=0x8664):
        raise ValueError('SQLite Windows x64 PE required')
    return lock,dll


def replace(entries,root,archive,destination):
    matches=[i for i,item in enumerate(entries) if Path(item[0]).name.lower()=='sqlite3.dll']
    if len(matches)!=1:raise ValueError('Exactly one SQLite DLL must be collected')
    lock,dll=verify(root,archive)
    destination=Path(destination)
    if any(p.is_symlink() or p.is_junction() for p in [destination,*destination.parents]):
        raise ValueError('Linked SQLite output')
    destination.mkdir(parents=True,exist_ok=False)
    target=destination/'sqlite3.dll';target.write_bytes(dll)
    result=list(entries);old=result[matches[0]]
    result[matches[0]]=(old[0],str(target),old[2])
    owners={target.resolve():('SQLite',lock['version'],lock['dll']['member'],lock['dll']['sha256'])}
    return result,owners
