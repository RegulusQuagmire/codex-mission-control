"""Atomic compatibility JSON, SQLite journal routing and OS leases."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import tempfile


class StateError(ValueError):
    """Local state validation/locking error safe to display."""


def save_state(path: Path, data: dict) -> None:
    from .storage import store_for
    store=store_for(path)
    if store is not None:
        store.save(store.key(path),data)
        return
    from .secure_files import write_file
    write_file(path,(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode('utf-8'))


def load_state(path: Path) -> dict:
    from .storage import store_for
    store=store_for(path)
    if store is not None:return store.load(store.key(path))
    from .secure_files import read_file
    raw=read_file(path,limit=64*1024*1024)
    if raw is None:raise StateError('Required state file missing')
    data=json.loads(raw)
    if not isinstance(data, dict):
        raise StateError("Expected a state object")
    return data



@contextmanager
def state_lock(path: Path):
    """Nonblocking OS lease; released automatically even when the process dies.

    Keep the lock file: unlinking it creates races between separate file handles.
    """
    from .storage import guard_path
    path = guard_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path=guard_path(path.with_name(path.name + ".lock"))
    from .secure_files import write_file,open_file
    if not lock_path.exists():
        try:write_file(lock_path,b'0',new=True)
        except (StateError,OSError):
            if not lock_path.exists():raise
    with open_file(lock_path,writable=True,share_write=True) as stream:
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.lockf(stream, fcntl.LOCK_EX | fcntl.LOCK_NB, 1)
        except OSError:
            raise StateError("Another integration check is using this state file") from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.lockf(stream, fcntl.LOCK_UN, 1)


def state_exists(path: Path) -> bool:
    from .storage import store_for
    store=store_for(path)
    return store.exists(store.key(path)) if store is not None else Path(path).exists()
