"""Trusted argv checks with bounded output and lifetime of their process tree."""
import asyncio
import time
import ctypes
import os
import signal
import subprocess
import threading


def _windows_job():
    from ctypes import wintypes as w
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    class Basic(ctypes.Structure):
        _fields_=[('perProcess',ctypes.c_int64),('perJob',ctypes.c_int64),('flags',w.DWORD),
                  ('minWS',ctypes.c_size_t),('maxWS',ctypes.c_size_t),('active',w.DWORD),
                  ('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
    class IO(ctypes.Structure):
        _fields_=[(name,ctypes.c_uint64) for name in ('readOps','writeOps','otherOps','readBytes','writeBytes','otherBytes')]
    class Extended(ctypes.Structure):
        _fields_=[('basic',Basic),('io',IO),('processMemory',ctypes.c_size_t),
                  ('jobMemory',ctypes.c_size_t),('peakProcess',ctypes.c_size_t),('peakJob',ctypes.c_size_t)]
    k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];k.CreateJobObjectW.restype=w.HANDLE
    k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
    k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE]
    k.CloseHandle.argtypes=[w.HANDLE]
    handle=k.CreateJobObjectW(None,None)
    if not handle:raise OSError('Cannot create check process job')
    limits=Extended();limits.basic.flags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not k.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):
        k.CloseHandle(handle);raise OSError('Cannot set check process lifetime')
    return k,handle


def run_command(argv, cwd, timeout, cancel_event=None):
    process=None;job=None;output=bytearray();timed_out=False
    def drain():
        while chunk:=process.stdout.read(4096):
            if len(output)<8192:output.extend(chunk[:8192-len(output)])
    try:
        kwargs={'cwd':str(cwd),'stdin':subprocess.DEVNULL,'stdout':subprocess.PIPE,'stderr':subprocess.STDOUT,'shell':False}
        from .safety import process_environment
        kwargs['env']=process_environment()
        if os.name=='nt':
            job=_windows_job()
            kwargs['creationflags']=subprocess.CREATE_NO_WINDOW | 0x4 # CREATE_SUSPENDED
        else:kwargs['start_new_session']=True
        process=subprocess.Popen(argv,**kwargs)
        if job:
            k,handle=job
            if not k.AssignProcessToJobObject(handle,int(process._handle)):
                raise OSError('Cannot contain check process')
            resume=ctypes.WinDLL('ntdll').NtResumeProcess
            resume.argtypes=[ctypes.c_void_p];resume.restype=ctypes.c_long
            if resume(int(process._handle)) != 0:raise OSError('Cannot start contained check')
        reader=threading.Thread(target=drain,daemon=True);reader.start()
        deadline=time.monotonic()+timeout
        while process.poll() is None:
            if cancel_event and cancel_event.is_set():break
            remaining=deadline-time.monotonic()
            if remaining<=0:timed_out=True;break
            try:process.wait(timeout=min(0.1,remaining))
            except subprocess.TimeoutExpired:pass
    finally:
        if job:job[0].CloseHandle(job[1])
        elif process:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        if process:
            if process.poll() is None:process.kill()
            process.wait()
            if 'reader' in locals():reader.join(timeout=2)
            process.stdout.close()
    return {'exitCode':process.returncode,'timedOut':timed_out,
            'output':bytes(output).decode('utf-8',errors='replace')}


async def run_check(argv,cwd,timeout):
    cancel=threading.Event()
    task=asyncio.create_task(asyncio.to_thread(run_command,argv,cwd,timeout,cancel))
    try:return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        await asyncio.shield(task)
        raise
