"""Handle-pinned paths and durable replacement. Not a process sandbox.

Windows directory handles deny rename/delete while an operation is in flight.
POSIX traversal uses directory descriptors and O_NOFOLLOW. Writes replace the
directory entry, never truncate an existing inode (including a raced hard link).
"""
from contextlib import contextmanager, ExitStack
import ctypes
import os
from pathlib import Path
import stat
import uuid
from .state import StateError


def _regular(info):
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or getattr(info,'st_file_attributes',0)&0x400:
        raise StateError('Linked or non-regular files are unsupported')


def _win_api():
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.CreateFileW.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.c_void_p,w.DWORD,w.DWORD,w.HANDLE]
    k.CreateFileW.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
    k.GetFileInformationByHandle.argtypes=[w.HANDLE,ctypes.c_void_p];k.GetFileInformationByHandle.restype=w.BOOL
    k.MoveFileExW.argtypes=[w.LPCWSTR,w.LPCWSTR,w.DWORD];k.MoveFileExW.restype=w.BOOL
    return k


def _win_open(path,directory,*,writable=False,share_write=False):
    from ctypes import wintypes as w
    class Info(ctypes.Structure):
        _fields_=[('attrs',w.DWORD),('created',w.FILETIME),('accessed',w.FILETIME),('written',w.FILETIME),
                  ('volume',w.DWORD),('sizeHigh',w.DWORD),('sizeLow',w.DWORD),('links',w.DWORD),
                  ('indexHigh',w.DWORD),('indexLow',w.DWORD)]
    k=_win_api()
    # OPEN_REPARSE_POINT: inspect the opened object, never follow a leaf link.
    handle=k.CreateFileW(str(path),0x80 if directory else (0xC0000000 if writable else 0x80000000),3 if directory or share_write else 1,
                         None,3,0x02200000,None)
    if handle==ctypes.c_void_p(-1).value:
        code=ctypes.get_last_error()
        if code in (2,3):raise FileNotFoundError(code,'Secure file missing')
        raise OSError(code,'Secure file open failed')
    info=Info()
    if (not k.GetFileInformationByHandle(handle,ctypes.byref(info)) or info.attrs&0x400
            or bool(info.attrs&0x10)!=directory or (not directory and info.links!=1)):
        k.CloseHandle(handle);raise StateError('Linked or unexpected file object')
    return k,handle


@contextmanager
def parent_handle(path,*,create=False):
    path=Path(os.path.abspath(path))
    if path.name in {'','.','..'}:raise StateError('File name required')
    with ExitStack() as stack:
        if os.name=='nt':
            current=Path(path.anchor)
            k,h=_win_open(current,True);stack.callback(k.CloseHandle,h)
            for part in path.parent.parts[1:]:
                current=current/part
                if create:
                    try:current.mkdir()
                    except FileExistsError:pass
                k,h=_win_open(current,True);stack.callback(k.CloseHandle,h)
            yield path,None
        else:
            fd=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);stack.callback(os.close,fd)
            for part in path.parent.parts[1:]:
                if create:
                    try:os.mkdir(part,mode=0o700,dir_fd=fd)
                    except FileExistsError:pass
                fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);stack.callback(os.close,fd)
            yield path,fd


def _read_file(path,*,limit):
    with parent_handle(path) as (path,fd):
        try:
            if os.name=='nt':
                import msvcrt
                k,h=_win_open(path,False)
                try:raw=msvcrt.open_osfhandle(h,os.O_RDONLY|os.O_BINARY)
                except BaseException:k.CloseHandle(h);raise
            else:raw=os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=fd)
        except (FileNotFoundError,):return None
        except OSError as error:
            if os.name=='nt' and getattr(error,'errno',None) in (2,3):return None
            raise
        with os.fdopen(raw,'rb') as f:
            info=os.fstat(f.fileno());_regular(info)
            if info.st_size>limit:raise StateError('File exceeds bounded limit')
            data=f.read(limit+1)
            if len(data)>limit:raise StateError('File exceeds bounded limit')
            return data


def read_file(path,*,limit):
    try:return _read_file(path,limit=limit)
    except FileNotFoundError:return None


def write_file(path,data,*,new=False):
    with parent_handle(path,create=True) as (path,fd):
        temp='.'+path.name+'.'+uuid.uuid4().hex+'.tmp'
        temporary=path.with_name(temp)
        try:
            try:
                info=path.lstat() if fd is None else os.stat(path.name,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:info=None
            if info is not None:
                _regular(info)
                if new:raise StateError('Destination must be new')
            raw=os.open(temporary if fd is None else temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,
                        0o600,**({} if fd is None else {'dir_fd':fd}))
            with os.fdopen(raw,'wb') as f:
                f.write(data);f.flush();os.fsync(f.fileno())
            if os.name=='nt':
                # REPLACE_EXISTING (unless new) | WRITE_THROUGH. Ancestors remain pinned.
                k=_win_api()
                if not k.MoveFileExW(str(temporary),str(path),8 | (0 if new else 1)):
                    raise OSError(ctypes.get_last_error(),'Durable file replacement failed')
            else:
                if new:
                    os.link(temp,path.name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
                    os.unlink(temp,dir_fd=fd)
                else:os.replace(temp,path.name,src_dir_fd=fd,dst_dir_fd=fd)
                os.fsync(fd)
        finally:
            try:
                if fd is None:temporary.unlink()
                else:os.unlink(temp,dir_fd=fd)
            except FileNotFoundError:pass


def sync_file(path):
    # Flush existing approved check outputs before committing their success receipt.
    with parent_handle(path) as (path,fd):
        if os.name=='nt':
            import msvcrt
            k=_win_api();h=k.CreateFileW(str(path),0xC0000000,1,None,3,0x02200000,None)
            if h==ctypes.c_void_p(-1).value:raise StateError('Cannot flush result file')
            raw=msvcrt.open_osfhandle(h,os.O_RDWR|os.O_BINARY)
        else:raw=os.open(path.name,os.O_RDWR|os.O_NOFOLLOW,dir_fd=fd)
        with os.fdopen(raw,'r+b') as f:_regular(os.fstat(f.fileno()));os.fsync(f.fileno())


@contextmanager
def open_file(path,*,writable=False,share_write=False):
    """Pin a regular file and its ancestors; disallow path replacement on Windows."""
    with parent_handle(path) as (path,fd):
        if os.name=='nt':
            import msvcrt
            k,h=_win_open(path,False,writable=writable,share_write=share_write)
            try:raw=msvcrt.open_osfhandle(h,(os.O_RDWR if writable else os.O_RDONLY)|os.O_BINARY)
            except BaseException:k.CloseHandle(h);raise
        else:raw=os.open(path.name,(os.O_RDWR if writable else os.O_RDONLY)|os.O_NOFOLLOW,dir_fd=fd)
        with os.fdopen(raw,'r+b' if writable else 'rb') as stream:
            _regular(os.fstat(stream.fileno()))
            yield stream
