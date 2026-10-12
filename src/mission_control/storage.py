"""SQLite documents preserve durable state transitions without JSON side journals."""
from contextlib import contextmanager, ExitStack
from contextvars import ContextVar
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

from .state import StateError

ACTIVE_STORE=ContextVar('mission_journal_store',default=None)
STATE_OBSERVER=ContextVar('mission_state_observer',default=None)
APP_ID=0x434d4335
MAX_PAYLOAD=64*1024*1024


def guard_path(path):
    path=Path(path).absolute()
    for part in [path,*path.parents]:
        if part.is_symlink() or (part.exists() and (getattr(part.lstat(),'st_file_attributes',0)&0x400 or (part.is_file() and part.stat().st_nlink!=1))):
            raise StateError('Linked state paths are unsupported')
    return path.resolve()


def _crypt(data,key,protect):
    from ctypes import wintypes as w
    class Blob(ctypes.Structure):_fields_=[('size',w.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]
    source_buffer=ctypes.create_string_buffer(data);entropy_buffer=ctypes.create_string_buffer(key.encode())
    source=Blob(len(data),ctypes.cast(source_buffer,ctypes.POINTER(ctypes.c_ubyte)))
    entropy=Blob(len(key.encode()),ctypes.cast(entropy_buffer,ctypes.POINTER(ctypes.c_ubyte)));out=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True)
    local=ctypes.WinDLL('kernel32',use_last_error=True)
    local.LocalFree.argtypes=[ctypes.c_void_p];local.LocalFree.restype=ctypes.c_void_p
    name='CryptProtectData' if protect else 'CryptUnprotectData';fn=getattr(crypt,name)
    fn.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,w.DWORD,ctypes.POINTER(Blob)]
    fn.restype=w.BOOL
    if not fn(ctypes.byref(source),None,ctypes.byref(entropy),None,None,1,ctypes.byref(out)):
        raise StateError('Windows user protection failed; no plaintext fallback')
    try:
        if out.size>MAX_PAYLOAD:raise StateError('Protected state exceeds size limit')
        return ctypes.string_at(out.data,out.size)
    finally:local.LocalFree(out.data)


def _encode(key,data):
    if not isinstance(data,dict):raise StateError('Expected state object')
    raw=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')
    if len(raw)>MAX_PAYLOAD:raise StateError('State document too large')
    codec='dpapi-user-v1' if os.name=='nt' else 'plain-v1'
    payload=_crypt(raw,key,True) if os.name=='nt' else raw
    return codec,payload,hashlib.sha256(payload).hexdigest()


def _decode(key,codec,payload,checksum):
    if not isinstance(payload,bytes) or len(payload)>MAX_PAYLOAD or hashlib.sha256(payload).hexdigest()!=checksum:
        raise StateError('Stored document damaged; no recovery replay')
    expected='dpapi-user-v1' if os.name=='nt' else 'plain-v1'
    if codec!=expected:raise StateError('State protection is unavailable on this OS/profile')
    raw=_crypt(payload,key,False) if os.name=='nt' else payload
    try:data=json.loads(raw)
    except (ValueError,UnicodeError):raise StateError('Stored document invalid') from None
    if not isinstance(data,dict):raise StateError('Stored document is not an object')
    return data


class JournalStore:
    def __init__(self,path):
        self._checked=False;self.backup_only=False
        self.path=guard_path(path);self._known=self.path.exists()
        self.run_root=self.path.parent/(self.path.name+'.runs')
        self.history_path=self.path.parent/(self.path.name+'.history.json')
        if self.path.exists():
            with self._connection(False) as c:
                row=c.execute("select codec,payload,checksum from metadata where key='layout'").fetchone()
                if not row:raise StateError('SQLite layout metadata missing')
                layout=_decode('meta:layout',*row)
                backup=c.execute("select codec,payload,checksum from metadata where key='backup'").fetchone()
                if backup:
                    _decode('meta:backup',*backup);self.backup_only=True
                if not self.backup_only and guard_path(layout['ownerPath'])!=self.path:
                    raise StateError('Database copy cannot execute at another path; use an archival backup')
                self.run_root=guard_path(layout['runRoot']);self.history_path=guard_path(layout['historyPath'])
                if not self.backup_only and (self.run_root.parent!=self.path.parent or not self.run_root.name.endswith('.runs')
                        or self.history_path.parent!=self.path.parent or not self.history_path.name.endswith('.history.json')):
                    raise StateError('SQLite namespace outside queue directory')

    @contextmanager
    def _connection(self,create=False):
        c=None;pins=ExitStack()
        try:
            guard_path(self.path)
            for suffix in ('-journal','-wal','-shm'):guard_path(Path(str(self.path)+suffix))
            exists=self.path.exists()
            if not exists and (self._known or not create):raise StateError('SQLite journal missing; never recreate dispatched state')
            self.path.parent.mkdir(parents=True,exist_ok=True)
            if not exists:
                from .secure_files import write_file
                write_file(self.path,b'',new=True)
            from .secure_files import open_file
            pins.enter_context(open_file(self.path,share_write=True))
            c=sqlite3.connect(self.path.as_uri()+'?mode=rw',uri=True,timeout=3,isolation_level=None)
            c.execute('pragma busy_timeout=3000');c.execute('pragma synchronous=FULL')
            c.execute('pragma secure_delete=ON');c.execute('pragma trusted_schema=OFF')
            if exists:
                if c.execute('pragma application_id').fetchone()[0]!=APP_ID or c.execute('pragma user_version').fetchone()[0]!=1:
                    raise StateError('Unknown SQLite schema; no automatic overwrite')
                if not self._checked:
                    if c.execute('pragma quick_check').fetchone()[0]!='ok':raise StateError('SQLite integrity check failed')
                    self._checked=True
            else:
                c.execute('pragma journal_mode=DELETE')
                c.execute('BEGIN IMMEDIATE')
                c.execute('create table documents (key text primary key,codec text not null,payload blob not null,checksum text not null)')
                c.execute('create table metadata (key text primary key,codec text not null,payload blob not null,checksum text not null)')
                c.execute('create table events (seq integer primary key autoincrement, at real not null, category text not null)')
                codec,payload,checksum=_encode('meta:layout',{'ownerPath':str(self.path),'runRoot':str(self.run_root),'historyPath':str(self.history_path)})
                c.execute('insert into metadata values (?,?,?,?)',('layout',codec,payload,checksum))
                c.execute(f'pragma application_id={APP_ID}');c.execute('pragma user_version=1');c.execute('COMMIT')
            self._known=True
            yield c
        except (sqlite3.Error,KeyError,TypeError,OSError):
            raise StateError('SQLite state unavailable or corrupt; inspect before recovery') from None
        finally:
            if c is not None:c.close()
            pins.close()

    @contextmanager
    def transaction(self):
        if self.backup_only:raise StateError('Archival backup is read-only')
        with self._connection(True) as c:
            c.execute('BEGIN IMMEDIATE')
            try:yield c;c.execute('COMMIT')
            except BaseException:
                c.execute('ROLLBACK');raise

    def key(self,path):
        path=guard_path(path)
        if path==self.path:return 'queue'
        if path==self.history_path:return 'history'
        if path.is_relative_to(self.run_root):
            relative=path.relative_to(self.run_root)
            if relative.suffix=='.json':return 'run/'+relative.as_posix().casefold() if os.name=='nt' else 'run/'+relative.as_posix()
        return None

    def write(self,c,key,data):
        codec,payload,checksum=_encode(key,data)
        c.execute('insert into documents values (?,?,?,?) on conflict(key) do update set codec=excluded.codec,payload=excluded.payload,checksum=excluded.checksum',(key,codec,payload,checksum))
        category='run' if key.startswith('run/') else key if key in {'queue','history','settings','approvals'} else 'state'
        c.execute('insert into events(at,category) values (?,?)',(time.time(),category))
        c.execute('delete from events where seq <= (select coalesce(max(seq),0)-200 from events)')

    def save(self,key,data):
        if self.backup_only:raise StateError('Archival backup is read-only')
        with self.transaction() as c:self.write(c,key,data)
        observer=STATE_OBSERVER.get()
        if observer is not None:observer(key)

    def load(self,key):
        with self._connection() as c:
            row=c.execute('select codec,payload,checksum from documents where key=?',(key,)).fetchone()
            if not row:raise StateError('Required SQLite document missing; no replay')
            return _decode(key,*row)

    def exists(self,key):
        if not self.path.exists():
            if self._known:raise StateError('Known SQLite journal disappeared; no idle fallback')
            return False
        with self._connection() as c:return c.execute('select 1 from documents where key=?',(key,)).fetchone() is not None

    def backup(self,destination):
        from .secure_files import write_file,open_file
        destination=guard_path(destination)
        if destination.exists():raise StateError('Backup destination must be new')
        write_file(destination,b'',new=True)
        with open_file(destination,share_write=True),self._connection() as c:
            target=sqlite3.connect(destination)
            try:
                c.backup(target)
                codec,payload,checksum=_encode('meta:backup',{'source':str(self.path),'createdAt':time.time()})
                target.execute('insert or replace into metadata values (?,?,?,?)',('backup',codec,payload,checksum))
                target.commit()
                if target.execute('pragma integrity_check').fetchone()[0]!='ok':raise StateError('Backup verification failed')
            finally:target.close()



@contextmanager
def journal_context(store):
    token=ACTIVE_STORE.set(store)
    try:yield store
    finally:ACTIVE_STORE.reset(token)


def store_for(path):
    store=ACTIVE_STORE.get()
    if store and store.key(path) is not None:return store
    if Path(path).suffix=='.sqlite3':return JournalStore(path)
    return None
