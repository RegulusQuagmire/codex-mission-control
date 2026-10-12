import json
import os
from pathlib import Path
import sqlite3
import pytest
from mission_control.storage import JournalStore, journal_context
from mission_control.state import load_state, save_state, state_exists, StateError


def test_queue_and_session_receipts_share_one_sqlite_database(tmp_path):
    db=tmp_path/'q.sqlite3';store=JournalStore(db)
    managed=store.run_root/'one'/'0'/'managed.json'
    with journal_context(store):
        save_state(db,{'version':1,'kind':'mission-queue'})
        save_state(managed,{'threadId':'saved-thread','stage':'submitted','task':'private text'})
        assert state_exists(managed) and load_state(managed)['threadId']=='saved-thread'
    assert not managed.exists()
    with journal_context(JournalStore(db)):
        assert load_state(managed)['stage']=='submitted'
    with sqlite3.connect(db) as c:
        assert c.execute('select count(*) from documents').fetchone()[0]==2
    if os.name=='nt':assert b'private text' not in db.read_bytes()


def test_sqlite_transaction_rollback_and_unknown_schema_are_fail_closed(tmp_path):
    db=tmp_path/'q.sqlite3';store=JournalStore(db);store.save('queue',{'value':1})
    with pytest.raises(RuntimeError):
        with store.transaction() as c:
            store.write(c,'queue',{'value':2})
            raise RuntimeError('simulated crash')
    assert store.load('queue')=={'value':1}
    with sqlite3.connect(db) as c:c.execute('pragma user_version=999')
    with pytest.raises(StateError):store.load('queue')


def test_corrupt_database_is_not_recreated(tmp_path):
    db=tmp_path/'q.sqlite3';db.write_bytes(b'not a database')
    before=db.read_bytes()
    with pytest.raises(StateError):JournalStore(db).load('queue')
    assert db.read_bytes()==before


def test_document_tamper_is_not_interpreted_as_empty_queue(tmp_path):
    db=tmp_path/'q.sqlite3';store=JournalStore(db);store.save('queue',{'value':1})
    with sqlite3.connect(db) as c:c.execute("update documents set payload=x'010203' where key='queue'")
    with pytest.raises(StateError):store.load('queue')


def test_new_file_backup_is_consistent_and_never_overwrites(tmp_path):
    db=tmp_path/'q.sqlite3';store=JournalStore(db);store.save('queue',{'value':1})
    copy=tmp_path/'backup.sqlite3';store.backup(copy)
    assert JournalStore(copy).load('queue')=={'value':1}
    store.save('queue',{'value':2})
    with pytest.raises(StateError):store.backup(copy)
    assert JournalStore(copy).load('queue')=={'value':1}


def test_context_cannot_route_state_outside_queue_namespace(tmp_path):
    db=tmp_path/'q.sqlite3';store=JournalStore(db);other=tmp_path/'report.json'
    with journal_context(store):save_state(other,{'report':True})
    assert other.exists() and json.loads(other.read_text())=={'report':True}


def test_forced_exit_mid_transaction_keeps_previous_document(tmp_path):
    import subprocess,sys
    path=tmp_path/'q.sqlite3';store=JournalStore(path);store.save('queue',{'phase':'before'})
    code="from mission_control.storage import JournalStore; import os,sys; s=JournalStore(sys.argv[1]); c=s.transaction(); db=c.__enter__(); s.write(db,'queue',{'phase':'after'}); os._exit(94)"
    result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,timeout=15)
    assert result.returncode==94,result.stderr
    assert JournalStore(path).load('queue')=={'phase':'before'}


def test_known_database_disappearance_is_not_empty_or_recreated(tmp_path):
    store=JournalStore(tmp_path/'q.sqlite3');store.save('queue',{'active':'a'})
    store.path.unlink()
    with pytest.raises(StateError):store.exists('queue')
    with pytest.raises(StateError):store.save('queue',{'active':None})
    assert not store.path.exists()


def test_protection_failure_never_falls_back_to_plaintext(tmp_path,monkeypatch):
    import os
    if os.name!='nt':return # DPAPI integration is Windows-specific.
    import mission_control.storage as storage
    store=JournalStore(tmp_path/'q.sqlite3');store.save('queue',{'phase':'before'})
    def unavailable(*args):raise StateError('Protection unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(storage,'_crypt',unavailable)
        with pytest.raises(StateError):store.save('queue',{'secret':'no-plaintext-fallback-123456'})
    assert b'no-plaintext-fallback-123456' not in store.path.read_bytes()
    assert store.load('queue')=={'phase':'before'}


def test_unmarked_copy_or_interrupted_backup_cannot_become_executable(tmp_path):
    import shutil,sqlite3
    source=tmp_path/'q.sqlite3';store=JournalStore(source);store.save('queue',{'active':None})
    copy=tmp_path/'copy.sqlite3';shutil.copyfile(source,copy)
    with pytest.raises(StateError):JournalStore(copy)
    archive=tmp_path/'backup.sqlite3';store.backup(archive)
    with sqlite3.connect(archive) as c:c.execute("delete from metadata where key='backup'")
    with pytest.raises(StateError):JournalStore(archive)
