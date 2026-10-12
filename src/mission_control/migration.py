"""Explicit, transactional legacy import. Originals remain available for inspection."""
import hashlib
from pathlib import Path
from .state import StateError, load_state, save_state, state_lock
from .storage import JournalStore, guard_path, journal_context
from .queue import MissionQueue
from . import queue as queue_module


def migrate(source,destination):
    source=guard_path(source);destination=guard_path(destination)
    if source.suffix!='.json' or destination.suffix!='.sqlite3' or source.parent!=destination.parent:
        raise StateError('Migration requires JSON source and new SQLite destination in the same directory')
    with state_lock(queue_module.worker_lease_path()),state_lock(source),state_lock(destination):
        if not source.exists():raise StateError('Legacy queue missing')
        marker=source.with_name(source.name+'.migration.json')
        handoff={'source':str(source),'destination':str(destination)}
        if marker.exists():
            if load_state(marker)!=handoff:raise StateError('Legacy source already handed off to a different database')
        else:
            # Durable before destination creation: crash recovery can only retry this destination.
            save_state(marker,handoff)
        old=MissionQueue(source);data=old.read()
        if not source.exists():raise StateError('Legacy queue missing')
        identity={'source':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
        store=JournalStore(destination)
        if store.backup_only:raise StateError('Archival backup cannot receive migration handoff')
        if destination.exists():
            if not store.exists('migration') or store.load('migration')!=identity:
                raise StateError('Existing database is not this legacy import; no overwrite')
        else:
            store.run_root=source.parent/(source.name+'.runs')
            store.history_path=source.parent/(source.name+'.history.json')
            documents={'queue':data,'migration':identity,'migration-checkpoints':{'complete':False}}
            if store.history_path.exists():documents['history']=load_state(store.history_path)
            for job in data['missions'].values():
                paths=[Path(a['path']) for a in job['archives']]
                if job.get('runPath'):paths.append(Path(job['runPath']))
                for path in paths:
                    if not path.is_relative_to(store.run_root):raise StateError('Legacy journal outside queue namespace')
                    guard_path(path)
                    if not path.exists():
                        if job.get('dispatchStarted'):raise StateError('Dispatched legacy journal missing; cannot migrate as idle')
                        continue
                    for journal in [path,path.parent/'snapshot.json',path.parent/'checkpoint.json',*sorted((path.parent/'checks').glob('*.json'))]:
                        guard_path(journal)
                        if journal.exists():documents[store.key(journal)]=load_state(journal)
            with store.transaction() as c:
                for key,value in documents.items():store.write(c,key,value)
        if store.exists('migration-checkpoints') and not store.load('migration-checkpoints').get('complete'):
            from .checkpoints import create
            with journal_context(store):
                for job in data['missions'].values():
                    if job['type']=='project':
                        paths=[Path(a['path']) for a in job['archives']]
                        if job.get('runPath'):paths.append(Path(job['runPath']))
                        for path in paths:
                            if store.exists(store.key(path)):
                                create(path.parent,load_state(path.parent/'snapshot.json'))
            store.save('migration-checkpoints',{'complete':True})
        reservation=queue_module.worker_lease_path()
        if reservation.exists():
            saved=load_state(reservation)
            if saved.get('queuePath') not in {None,str(source),str(destination)}:
                raise StateError('Another queue is reserved; imported database retained, retry migration after resolving it')
            if saved.get('queuePath')==str(source):save_state(reservation,{'queuePath':str(destination)})
    return MissionQueue(destination).read()
