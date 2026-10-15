"""Read-only diagnostics for explicit isolated release QA, not normal startup."""
import ctypes
import hashlib
import os
from pathlib import Path
import sqlite3


def loaded_library(name):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetModuleHandleW.argtypes=[ctypes.c_wchar_p];kernel.GetModuleHandleW.restype=ctypes.c_void_p
    kernel.GetModuleFileNameW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_uint]
    handle=kernel.GetModuleHandleW(name);buffer=ctypes.create_unicode_buffer(32768)
    if not handle or not kernel.GetModuleFileNameW(handle,buffer,len(buffer)):
        raise RuntimeError('Cannot identify loaded library: '+name)
    path=Path(buffer.value)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def sqlite_runtime():
    connection=sqlite3.connect(':memory:')
    try:
        source_id=connection.execute('select sqlite_source_id()').fetchone()[0]
        options=[row[0] for row in connection.execute('pragma compile_options')]
    finally:connection.close()
    result={'version':sqlite3.sqlite_version,'sourceId':source_id,
            'threadSafety':sqlite3.threadsafety,'compileOptions':options}
    if os.name=='nt':
        loaded=loaded_library('sqlite3.dll')
        result.update(loadedDll=loaded['path'],loadedDllSha256=loaded['sha256'])
    return result
