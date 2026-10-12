"""Persistent sequential missions with protected SQLite journals and explicit approvals."""
from __future__ import annotations
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from dataclasses import asdict
import re
from pathlib import Path
import tempfile
import time
import asyncio

from .execution import exact_output, timestamp
from .limits import LimitPolicy, number
from .managed import ManagedRunner, TERMINAL
from .mission_run import ProjectRunner
from .routing import Task, Mode
from .state import state_exists, StateError, load_state, save_state, state_lock
from . import validator

STATUSES={'pending','running','paused','completed','failed','cancelled','needs_attention',
          'waiting_approval','waiting_limit','waiting_credit','waiting_network','waiting_active','waiting_model','auth_required','limits_unsupported'}


def worker_lease_path():
    # Conservative per-user/temp-scope serialisation, even across queue/project paths.
    return Path(tempfile.gettempdir())/'codex-mission-control'/'mission-worker'


@contextmanager
def worker_claim(queue):
    path=worker_lease_path()
    with state_lock(path):
        if path.exists():
            saved=load_state(path)
            if saved.get('queuePath')==str(queue.path) and not queue.path.exists():
                raise StateError('Reserved queue journal is missing; cannot infer idle')
            if saved.get('queuePath') not in {None,str(queue.path)}:
                raise StateError('Another queue retains an unfinished mission; resume that queue first')
        save_state(path,{'queuePath':str(queue.path)})
        try:yield
        finally:
            # Retain reservation across process exit while any mission is unresolved.
            # Missing/corrupt journals must not clear a prior reservation.
            try:
                if queue.read()['active'] is None:save_state(path,{'queuePath':None})
            except (StateError,OSError,ValueError):pass


class MissionQueue:
    def __init__(self,path):
        from .storage import guard_path
        self.path=guard_path(path);self._journal=None

    def journal(self):
        from .storage import JournalStore
        if self.path.suffix!='.sqlite3':raise StateError('SQLite queue required')
        if self._journal is None:self._journal=JournalStore(self.path)
        return self._journal

    def storage(self):
        from .storage import journal_context
        return journal_context(self.journal()) if self.path.suffix=='.sqlite3' else nullcontext()


    def run_path(self,job):
        root=self.journal().run_root if self.path.suffix=='.sqlite3' else self.path.parent/(self.path.name+'.runs')
        return root/job['id']/str(job['generation'])/'managed.json'

    def _definition(self,job,*,check_workspace=True):
        if not isinstance(job,dict) or not isinstance(job.get('id'),str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}',job['id']):
            raise StateError('Mission ID must be lowercase letters/digits/hyphen/underscore, at most 64')
        validator.relative(job['id'])
        if not isinstance(job.get('title'),str) or not job['title'].strip():raise StateError('Mission title required')
        Task(**job['task']);Mode(job.get('mode','balanced'))
        if 'manual' in job:
            from .routing import check_manual
            check_manual(job['manual'])
        if not Path(job.get('project','')).is_absolute() or (check_workspace and not Path(job['project']).is_dir()):raise StateError('Existing absolute project required')
        if type(job.get('priority',0)) is not int:raise StateError('Priority must be an integer')
        deps=job.get('dependsOn',[])
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps) or len(set(deps))!=len(deps):
            raise StateError('Unique dependency IDs required')
        if type(job.get('maxAttempts',3)) is not int or not 1<=job.get('maxAttempts',3)<=8:raise StateError('Attempt budget must be 1..8')
        timeout=job.get('turnTimeout',120)
        if not number(timeout) or timeout<=0:raise StateError('Positive finite turn timeout required')
        LimitPolicy(**job.get('policy',{}))
        if job.get('type')=='text':exact_output(job.get('expected'))
        elif job.get('type')=='project':
            validator.check_spec(job['criteria'],check_workspace=check_workspace)
            if Path(job['criteria']['project']).resolve()!=Path(job['project']).resolve():raise StateError('Criteria project differs')
        else:raise StateError('Mission type must be text or project')

    def read(self):
        with self.storage():return self._read()

    def _read(self):
        if self.path.suffix=='.sqlite3' and self.path.exists() and not state_exists(self.path):
            raise StateError('SQLite queue document missing; never assume idle')
        if not state_exists(self.path):return {'version':1,'kind':'mission-queue','paused':False,'active':None,'missions':{},'executionOrder':[]}
        data=load_state(self.path)
        try:
            if data.get('version')!=1 or data.get('kind')!='mission-queue' or type(data.get('paused')) is not bool or not isinstance(data.get('missions'),dict):
                raise StateError('Invalid queue journal')
            jobs=data['missions']
            for identity,job in jobs.items():
                self._definition(job,check_workspace=False)
                if identity!=job['id'] or job.get('status') not in STATUSES or type(job.get('generation')) is not int or job['generation']<0:
                    raise StateError('Invalid mission identity/status/generation')
                if job.get('runPath') and Path(job['runPath']).resolve()!=self.run_path(job):raise StateError('Mission journal path changed')
            if data.get('active') is not None and data['active'] not in jobs:raise StateError('Unknown active mission')
            visiting=set();visited=set()
            def visit(identity):
                if identity in visiting:raise StateError('Dependency cycle')
                if identity in visited:return
                if identity not in jobs:raise StateError('Missing dependency')
                visiting.add(identity)
                for dep in jobs[identity]['dependsOn']:visit(dep)
                visiting.remove(identity);visited.add(identity)
            for identity in jobs:visit(identity)
            return data
        except (KeyError,TypeError,ValueError) as error:
            if isinstance(error,StateError):raise
            raise StateError('Incomplete queue/mission journal') from error

    def _save(self,data):data['updatedAt']=timestamp();save_state(self.path,data)

    def add(self,definition):
        job=deepcopy(definition);self._definition(job)
        if self.path.suffix=='.sqlite3':
            from .safety import reject_secrets
            reject_secrets(job)
        with state_lock(self.path), self.storage():
            data=self.read()
            if job['id'] in data['missions']:raise StateError('Mission ID already exists')
            if any(dep not in data['missions'] for dep in job.get('dependsOn',[])) or job['id'] in job.get('dependsOn',[]):
                raise StateError('Dependencies must already exist and cannot include self')
            job.update(status='pending',generation=0,sequence=len(data['missions']),pauseRequested=False,
                       cancelRequested=False,archives=[],attempts=[],dispatchStarted=False,createdAt=timestamp())
            job.setdefault('priority',0);job.setdefault('dependsOn',[]);job.setdefault('mode','balanced');job.setdefault('maxAttempts',3)
            data['missions'][job['id']]=job;self._save(data)
        return data

    def control(self,action,identity=None,*,priority=None,acknowledge_uncertain=False):
        with state_lock(self.path), self.storage():
            data=self.read()
            if identity is None:
                if action not in {'pause','resume'}:raise StateError('Mission ID required')
                data['paused']=action=='pause';self._save(data);return data
            if identity not in data['missions']:raise StateError('Unknown mission ID')
            job=data['missions'][identity];active=data['active']==identity
            if action=='priority':
                if type(priority) is not int:raise StateError('Integer priority required')
                job['priority']=priority
            elif action=='pause':
                if job['status'] in {'completed','cancelled','failed','needs_attention'}:raise StateError('Terminal mission cannot pause')
                job['pauseRequested']=True
                if not active:job['status']='paused'
            elif action=='resume':
                if job['cancelRequested'] or job['status'] in {'completed','cancelled','failed','needs_attention'}:raise StateError('Mission cannot resume')
                job['pauseRequested']=False
                if job['status']=='paused':job['status']='running' if active else 'pending'
            elif action=='cancel':
                if job['status'] in {'completed','failed','needs_attention'}:raise StateError('Terminal mission cannot cancel')
                job['cancelRequested']=True;job['pauseRequested']=False
                if not active:job['status']='cancelled'
            elif action=='retry':
                if active or job['status']!='failed':raise StateError('Only known terminal failed missions may retry')
                saved=load_state(Path(job['runPath']))
                attempts=saved['attempts']
                if not attempts or attempts[-1]['phase']!='validated' or attempts[-1]['validation']['passed']:
                    raise StateError('Uncertain/non-validation failures cannot retry')
                if attempts[-1]['validation'].get('kind')=='not_retryable' and acknowledge_uncertain is not True:
                    raise StateError('Unknown side effects require explicit --acknowledge-uncertain-result after reconciliation')
                used=sum(a['count'] for a in job['archives'])+len(attempts)
                if used>=job['maxAttempts']:raise StateError('Cumulative attempt budget exhausted')
                job['archives'].append({'path':job['runPath'],'count':len(attempts),'stage':saved['stage'],'uncertaintyAcknowledged':attempts[-1]['validation'].get('kind')=='not_retryable' and acknowledge_uncertain is True})
                job['generation']+=1;job['status']='pending';job['attempts']=[]
                job.pop('runPath',None);job.pop('result',None);job.pop('checks',None);job.pop('model',None)
                job['dispatchStarted']=False
            else:raise StateError('Unknown queue control')
            self._save(data);return data


class QueueWorker:
    def __init__(self,queue,factory_for_cwd,*,clock=time.time,sleep=asyncio.sleep):
        self.queue=queue;self.factory_for_cwd=factory_for_cwd;self.clock=clock;self.sleep=sleep

    def _stop_requested(self,identity):
        data=self.queue.read();job=data['missions'][identity]
        return data['paused'] or job['pauseRequested'] or job['cancelRequested']

    def _dependencies(self,data,job):
        visited=set();ordered=[]
        def visit(identity):
            if identity in visited:return
            visited.add(identity)
            dep=data['missions'][identity]
            for parent in dep['dependsOn']:visit(parent)
            if dep['type']=='project' and dep['status']=='completed':ordered.append(Path(dep['runPath']).parent)
        for identity in job['dependsOn']:visit(identity)
        return ordered

    async def run(self,*,max_wait=None):
        if max_wait is not None and (not number(max_wait) or max_wait<0):raise StateError('Finite nonnegative max-wait required')
        if self.queue.path.suffix=='.sqlite3' and not self.queue.path.exists():
            raise StateError('Queue database missing; create explicitly or recover saved evidence')
        if self.queue.path.suffix=='.sqlite3' and self.queue.journal().backup_only:
            raise StateError('Backup is archival evidence, not an executable queue; reconcile with the original before recovery')
        if self.queue.path.suffix=='.json' and self.queue.path.with_name(self.queue.path.name+'.migration.json').exists():
            raise StateError('Legacy queue handed off to SQLite; never execute both copies')
        deadline=None if max_wait is None else self.clock()+max_wait
        with worker_claim(self.queue), self.queue.storage():
            with state_lock(self.queue.path):
                saved=self.queue.read()
                for identity,job in saved['missions'].items():
                    if job['type']=='project' and job['status']=='completed':
                        try:validator.verify_completed(Path(job['runPath']).parent)
                        except (StateError,OSError,ValueError):
                            job['status']='needs_attention'
                            job['stopReason']='Completed result missing or changed; restore artifacts, never replay automatically'
                            self.queue._save(saved)
                            return saved
            while True:
                with state_lock(self.queue.path):
                    data=self.queue.read()
                    identity=data['active']
                    cancelling=identity is not None and data['missions'][identity]['cancelRequested']
                    if data['paused'] and not cancelling:return data
                    if identity is None:
                        candidates=[j for j in data['missions'].values() if j['status']=='pending' and not j['pauseRequested']
                                    and all(data['missions'][d]['status']=='completed' for d in j['dependsOn'])]
                        if not candidates:return data
                        job=min(candidates,key=lambda j:(-j['priority'],j['sequence']))
                        if not Path(job['project']).is_dir():
                            job['status']='needs_attention'
                            job['stopReason']='Project folder unavailable; restore it before explicit reconciliation'
                            self.queue._save(data);continue
                        if self.queue.path.suffix=='.sqlite3':
                            from .safety import authorize
                            authorize(self.queue,job)
                        identity=job['id'];data['active']=identity;job['status']='running'
                        job['runPath']=str(self.queue.run_path(job));self.queue._save(data)
                    else:job=data['missions'][identity]
                    if not Path(job['project']).is_dir():
                        job['status']='needs_attention'
                        job['stopReason']='Active project folder unavailable; inspect saved evidence before recovery'
                        self.queue._save(data);return data
                    if job['pauseRequested'] and not job['cancelRequested']:job['status']='paused';self.queue._save(data);return data
                    if job['status']=='needs_attention':return data
                    if self.queue.path.suffix=='.sqlite3':
                        from .safety import authorize
                        authorize(self.queue,job)
                    job=deepcopy(job)
                path=Path(job['runPath']);cwd=Path(job['project']) if job['type']=='text' else path.parent/'workspace'
                runner_cls=ManagedRunner if job['type']=='text' else ProjectRunner
                runner=runner_cls(self.factory_for_cwd(cwd),path,cwd=cwd,clock=self.clock,sleep=self.sleep,
                                  stop_requested=lambda:self._stop_requested(identity))
                if job['type']=='project':runner.require_checkpoint=self.queue.path.suffix=='.sqlite3'
                remaining=None if deadline is None else max(0,deadline-self.clock())
                try:
                    if state_exists(path):result=await runner.resume(max_wait=remaining)
                    else:
                        if job.get('dispatchStarted') or job['attempts'] or job.get('result'):
                            raise StateError('Managed journal missing after dispatch; never replay')
                        # A crash between this marker and initial managed state is deliberately
                        # fail-closed: a missing journal cannot prove no turn was sent.
                        with state_lock(self.queue.path):
                            latest=self.queue.read();latest['missions'][identity]['dispatchStarted']=True
                            self.queue._save(latest)
                        budget=job['maxAttempts']-sum(a['count'] for a in job['archives'])
                        options={'mode':job['mode'],'max_attempts':budget,'turn_timeout':job.get('turnTimeout',120),
                                 'policy':LimitPolicy(**job.get('policy',{})),
                                 'history_path':self.queue.journal().history_path if self.queue.path.suffix=='.sqlite3' else self.queue.path.parent/(self.queue.path.name+'.history.json'),'max_wait':remaining}
                        if 'manual' in job:options['manual']=job['manual']
                        task=Task(**job['task'])
                        if job['type']=='text':result=await runner.run(task,expected=job['expected'],**options)
                        else:result=await runner.run_project(task,job['criteria'],overlays=self._dependencies(data,job),**options)
                except (StateError,OSError,ValueError):
                    with state_lock(self.queue.path):
                        data=self.queue.read();data['missions'][identity]['status']='needs_attention'
                        data['missions'][identity]['stopReason']='Unsafe/missing journal, workspace or check configuration; inspect saved evidence'
                        self.queue._save(data);return data
                with state_lock(self.queue.path):
                    data=self.queue.read();current=data['missions'][identity]
                    current['attempts']=deepcopy(result['attempts']);current['model']=deepcopy(result.get('decision'))
                    current['result']={'stage':result['stage'],'threadId':result.get('threadId'),
                                       'stopReason':result.get('stopReason'),'nextCheckAt':result.get('nextCheckAt')}
                    if result['attempts'] and 'validation' in result['attempts'][-1]:
                        current['checks']=deepcopy(result['attempts'][-1]['validation'])
                    last=result['attempts'][-1] if result['attempts'] else None
                    unresolved=last and last['phase'] in {'submitted','completed_unvalidated'} and result['stage']!='waiting_approval'
                    if current['cancelRequested'] and not unresolved:
                        current['status']='cancelled';data['active']=None
                    elif result['stage']=='completed':
                        current['status']='completed';data['active']=None
                        if identity not in data['executionOrder']:data['executionOrder'].append(identity)
                    elif result['stage'] in {'validation_failed','attempts_exhausted'}:
                        current['status']='failed';data['active']=None
                    elif result['stage'] in TERMINAL:current['status']='needs_attention'
                    elif data['paused'] or current['pauseRequested']:current['status']='paused'
                    else:current['status']=result['stage'] if result['stage'] in STATUSES else 'running'
                    self.queue._save(data)
                    if data['active'] is not None or data['paused']:return data
