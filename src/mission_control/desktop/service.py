"""Single-owner GUI facade; execution remains in the existing queue controller."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path
import time

from ..adapter import CodexAdapter
from ..queue import MissionQueue, QueueWorker, worker_lease_path, worker_claim
from ..rpc import RpcClient
from ..state import StateError, state_lock, load_state, state_exists
from ..storage import STATE_OBSERVER
from .. import safety, validator
from ..limits import inspect_limits
from ..secure_files import read_file
from .discovery import resolve_codex, CodexNotFound


DEFAULTS = {'theme':'dark','codex':'codex','mode':'balanced','policy':'balanced',
            'maxAttempts':3,'closeToTray':True,'notifications':True,'overlayPinned':True,
            'overlayCodexOnly':False,'hotkey':'Ctrl+Shift+M','setupComplete':False,
            'resumeOnLaunch':False,'overlayX':None,'overlayY':None,'overlayCompact':False,'reducedMotion':False,
            'modelPolicies':{},
            'creditPolicy':{'mode':'never','fiveHourReserve':10,'weeklyReserve':10,'paidAcknowledged':False}}


class DesktopService:
    def __init__(self, queue: MissionQueue, *, factory_for_cwd=None, changed=None):
        self.queue=queue
        self._custom_factory=factory_for_cwd is not None
        self.factory_for_cwd=factory_for_cwd or self._factory
        self.changed=changed or (lambda:None)
        self.connection={'status':'disconnected','message':'Подключение ещё не проверено'}
        self.models=[];self.limits=inspect_limits(None);self.account={}
        self.worker_task=None;self.closed=False;self._reviewed={};self._access={}
        self._emit_pending=False
        self.limits_observed_at=None;self._last_observation=None

    def initialize(self):
        # A new queue is created explicitly once; missing existing state fails closed.
        with state_lock(self.queue.path),self.queue.storage():
            data=self.queue.read()
            if not self.queue.journal().exists('queue'):self.queue._save(data)
        return self.snapshot()

    def preferences(self):
        store=self.queue.journal()
        saved=store.load('gui-preferences') if store.exists('gui-preferences') else {}
        if set(saved)-set(DEFAULTS):raise StateError('Unknown saved GUI settings; inspect state')
        merged=deepcopy({**DEFAULTS,**saved});self._validate_preferences(merged);return merged

    def save_preferences(self, values):
        if not isinstance(values,dict) or set(values)-set(DEFAULTS):raise StateError('Unknown UI preference')
        with state_lock(self.queue.path):
            current=self.preferences()
            if values.get('setupComplete') and not current['setupComplete']:
                raise StateError('Завершите мастер настройки с проверкой подключения и рабочей папки.')
            merged=deepcopy({**current,**values})
            self._validate_preferences(merged)
            self.queue.journal().save('gui-preferences',merged)
        return merged

    async def export_portable(self,path,passphrase):
        from ..transfer import export_archive
        data=self.snapshot()
        projects=[{'name':Path(root).name,'path':root} for root in data['roots']]
        history=[]
        for job in data['missions']:
            decision=job.get('live',{}).get('decision') or job.get('model') or {}
            history.append({'title':job['title'],'status':job['status'],
                'model':decision.get('model','') if isinstance(decision,dict) else '',
                'effort':decision.get('effort','') if isinstance(decision,dict) else '',
                'attempts':len(job.get('live',{}).get('attempts',[]))})
        store=self.queue.journal()
        if store.exists('portable-import'):
            previous=store.load('portable-import');projects+=previous['projects'];history+=previous['history']
        result=await asyncio.to_thread(export_archive,path,passphrase,preferences=data['preferences'],projects=projects,history=history)
        return {**result,'message':'Защищённый архив создан. Сохраните пароль отдельно.'}

    async def import_portable(self,path,passphrase):
        from ..transfer import import_archive
        if self.closed or self.worker_task is not None:raise StateError('Остановите очередь перед импортом.')
        result=await asyncio.to_thread(import_archive,path,passphrase)
        with state_lock(self.queue.path),self.queue.storage():
            data=self.queue.read();store=self.queue.journal()
            if self.closed or self.worker_task is not None or data['missions'] or data['active'] or store.exists('portable-import'):
                raise StateError('Импорт разрешён только в пустую очередь без прежнего импорта. Текущие данные не заменяются.')
            prefs={**DEFAULTS,**result['preferences']};self._validate_preferences(prefs)
            with store.transaction() as connection:
                store.write(connection,'gui-preferences',prefs)
                store.write(connection,'portable-import',{'projects':result['projects'],'history':result['history'],'trusted':False})
        return {'message':'Данные импортированы как справочные. Перезапустите приложение и пройдите мастер настройки.',
                'projectCount':len(result['projects']),'historyCount':len(result['history'])}

    async def inspect_update(self,path):
        from ..release import inspect_manifest
        return await asyncio.to_thread(inspect_manifest,path)

    @staticmethod
    def _validate_preferences(merged):
        from ..credit_policy import CreditPolicy
        try:CreditPolicy(**merged['creditPolicy'])
        except (ValueError,TypeError) as error:raise StateError('Invalid credit policy') from error
        from ..model_policy import validate_policy
        try:validate_policy(merged['modelPolicies'])
        except ValueError as error:raise StateError(str(error)) from error
        if merged['theme'] not in {'dark','light'} or merged['mode'] not in {'economy','balanced','quality'}:
            raise StateError('Invalid appearance or routing mode')
        if merged['policy'] not in {'balanced','weekly','reserve','stop'}:raise StateError('Invalid limit policy')
        if type(merged['maxAttempts']) is not int or not 1<=merged['maxAttempts']<=8:raise StateError('Attempt budget must be 1..8')
        for key in ('closeToTray','notifications','overlayPinned','overlayCodexOnly','setupComplete','resumeOnLaunch','overlayCompact','reducedMotion'):
            if type(merged[key]) is not bool:raise StateError('Boolean preference required')
        if not isinstance(merged['codex'],str) or not merged['codex'].strip():raise StateError('Codex path required')
        if not isinstance(merged['hotkey'],str) or len(merged['hotkey'])>80:raise StateError('Invalid hotkey')
        if merged['hotkey']:
            from .windows import parse_hotkey
            parse_hotkey(merged['hotkey'])
        for key in ('overlayX','overlayY'):
            if merged[key] is not None and (type(merged[key]) is not int or abs(merged[key])>100000):raise StateError('Invalid overlay position')
        safety.reject_secrets(merged)

    def _factory(self,cwd,codex=None):
        @asynccontextmanager
        async def factory():
            executable=resolve_codex(self.preferences()['codex'] if codex is None else codex)
            async with RpcClient([executable,'app-server','--listen','stdio://'],cwd=str(cwd)) as rpc:
                yield CodexAdapter(rpc)
        return factory

    async def refresh_connection(self,codex=None):
        self.connection={'status':'connecting','message':'Проверка Codex…'};self.changed()
        try:
            factory=(self.factory_for_cwd(self.queue.path.parent) if codex is None or self._custom_factory
                     else self._factory(self.queue.path.parent,codex))
            async with factory() as adapter:
                self.account=await adapter.account()
                self.models=[m for m in await adapter.models() if not m.get('hidden')]
                self.limits=inspect_limits(await adapter.rate_limits())
                self.limits_observed_at=time.time()
            auth=self.account.get('requiresOpenaiAuth') and not self.account.get('type')
            self.connection={'status':'auth_required' if auth else 'connected',
                             'message':'Войдите в Codex' if auth else 'Codex подключён'}
            self._record_limits(self.limits,self.limits_observed_at)
        except Exception as error:
            self.models=[];self.account={};self.limits=inspect_limits(None)
            self.limits_observed_at=None
            self.connection={'status':'error','kind':'executable' if isinstance(error,CodexNotFound) else 'connection',
                             'message':safety.redact(str(error))}
        self.changed()
        return self.connection

    async def probe_connection(self,codex):
        """Read account/model/quota metadata using an unsaved executable choice."""
        return await self.refresh_connection(codex=codex)

    async def complete_setup(self,codex,root):
        # Validate with the same private-workspace and reparse-point checks as
        # execution, before starting a metadata connection or changing state.
        try:safety._root(self.queue,root)
        except (StateError,OSError,ValueError) as error:
            return {'status':'error','kind':'workspace','message':'Рабочая папка: '+safety.redact(str(error))}
        connection=await self.probe_connection(codex)
        if connection['status']!='connected':return connection
        try:
            with state_lock(self.queue.path),self.queue.storage():
                data=self.queue.read()
                if data['active'] is not None:raise StateError('Access settings cannot change while a mission is active')
                path=str(safety._root(self.queue,root))
                preferences={**self.preferences(),'codex':codex,'setupComplete':True}
                self._validate_preferences(preferences)
                store=self.queue.journal()
                with store.transaction() as c:
                    if not store.exists('queue'):store.write(c,'queue',data)
                    store.write(c,'settings',{'version':1,'allowedRoots':[path]})
                    store.write(c,'approvals',{})
                    store.write(c,'gui-preferences',preferences)
        except (StateError,OSError,ValueError) as error:
            return {'status':'error','kind':'workspace','message':'Настройка не сохранена: '+safety.redact(str(error))}
        self.changed()
        return connection

    def configure_roots(self,roots):
        safety.configure(self.queue,roots);self.changed()

    def add(self,definition):
        self.queue.add(definition);self.changed()

    def edit(self,identity,definition):
        """Only undispatched pending definitions; no state replacement or progress loss."""
        self.queue._definition(definition);safety.reject_secrets(definition)
        if definition['id']!=identity:raise StateError('Mission identity cannot change')
        with state_lock(self.queue.path),self.queue.storage():
            data=self.queue.read();old=data['missions'][identity]
            if data['active']==identity or old['status'] not in {'pending','paused'} or old['dispatchStarted']:
                raise StateError('Only undispatched pending missions can be edited')
            keys=('title','type','task','project','criteria','expected','mode','manual','maxAttempts','turnTimeout','policy','dependsOn','priority')
            replacement={k:deepcopy(v) for k,v in old.items() if k not in keys}
            replacement.update(deepcopy(definition));replacement.setdefault('dependsOn',[])
            replacement.setdefault('mode','balanced');replacement.setdefault('priority',0);replacement.setdefault('maxAttempts',3)
            data['missions'][identity]=replacement
            visiting=set();seen=set()
            def visit(key):
                if key in visiting:raise StateError('Dependency cycle')
                if key in seen:return
                if key not in data['missions']:raise StateError('Missing dependency')
                visiting.add(key)
                for dep in data['missions'][key]['dependsOn']:visit(dep)
                visiting.remove(key);seen.add(key)
            for key in data['missions']:visit(key)
            self.queue._save(data)
        self._access.pop(identity,None);self.changed()

    def access_review(self,identity):
        with state_lock(self.queue.path),self.queue.storage():
            job=self.queue.read()['missions'][identity]
            safety.allowed(self.queue,job)
            view=deepcopy(job)
            self._access[identity]=safety.fingerprint(job)
        return safety.sanitize(view)

    def approve_access(self,identity,fingerprint):
        with state_lock(self.queue.path),self.queue.storage():
            job=self.queue.read()['missions'][identity]
            if self._access.get(identity)!=fingerprint or safety.fingerprint(job)!=fingerprint:
                raise StateError('Mission changed; review access again')
        safety.approve(self.queue,identity,expected_fingerprint=fingerprint);self._access.pop(identity,None);self.changed()

    def control(self,action,identity=None,**kwargs):
        result=self.queue.control(action,identity,**kwargs)
        # Known, idle approval waits have no in-flight commands. Acquire the same
        # process-wide lease as QueueWorker before releasing their reservation.
        if action=='cancel' and identity and result['active']==identity and result['missions'][identity]['status']=='waiting_approval':
            with worker_claim(self.queue),state_lock(self.queue.path),self.queue.storage():
                result=self.queue.read();job=result['missions'][identity]
                run=load_state(Path(job['runPath']))
                if (result['active']==identity and job['cancelRequested'] and run['stage']=='waiting_approval'
                        and run['attempts'][-1]['phase']=='completed_unvalidated'):
                    job['status']='cancelled';result['active']=None;self.queue._save(result)
        self.changed();return result

    async def resume_queue(self):
        self.control('resume')
        if self.worker_task is None or self.worker_task.done():return await self.start()
        return self.queue.read()

    async def resume_mission(self,identity):
        self.control('resume',identity)
        if self.worker_task is None or self.worker_task.done():return await self.start()
        return self.queue.read()

    def _result_job(self,identity):
        job=self.queue.read()['missions'].get(identity)
        if not job or job['status']!='waiting_approval' or not job.get('runPath'):
            raise StateError('Mission must await result approval')
        return job

    def review_result(self,identity):
        with state_lock(worker_lease_path()),state_lock(self.queue.path),self.queue.storage():
            job=self._result_job(identity);root=Path(job['runPath']).parent
            review=validator.review_result(root)
            sources={name:validator.read_bytes(validator.safe_path(root/'workspace',name)).decode('utf-8') for name in review['fileHashes']}
            diff=read_file(validator.safe_path(root,'result.diff'),limit=2*validator.MAX_CONTEXT)
            if diff is None:raise StateError('Result diff missing')
            validator.review_result(root)  # Recheck after gathering preview bytes.
            self._reviewed[identity]=review['reviewId']
            return safety.sanitize({'missionId':identity,'review':review,'sources':sources,'diff':diff.decode('utf-8')})

    def approve_result(self,identity,review_id,*,accept_user_rights=False):
        if self._reviewed.get(identity)!=review_id:raise StateError('Review this exact result first')
        with state_lock(worker_lease_path()),state_lock(self.queue.path),self.queue.storage():
            root=Path(self._result_job(identity)['runPath']).parent
            validator.approve_result(root,review_id,accept_user_rights=accept_user_rights)
        self._reviewed.pop(identity,None);self.changed()

    def result(self,identity):
        with self.queue.storage():
            job=self.queue.read()['missions'][identity];result={'mission':job}
            result['previousRuns']=self._previous_runs(job)
            if job.get('runPath'):
                root=Path(job['runPath']).parent
                result['run']=load_state(Path(job['runPath']))
                if job['type']=='project':
                    raw=read_file(validator.safe_path(root,'result.diff'),limit=2*validator.MAX_CONTEXT)
                    result['diff']=None if raw is None else raw.decode('utf-8')
            return safety.sanitize(result)

    def _previous_runs(self,job):
        result=[]
        for generation,item in enumerate(job.get('archives',[])):
            prior={**job,'generation':generation}
            expected=self.queue.run_path(prior)
            if Path(item['path']).resolve()!=expected:raise StateError('Archived run path changed')
            result.append(load_state(expected))
        return result

    def snapshot(self):
        with self.queue.storage():
            data=self.queue.read();jobs=deepcopy(list(data['missions'].values()))
            limits=deepcopy(self.limits)
            observed=self.limits_observed_at
            for job in jobs:
                job['pastAttempts']=[a for run in self._previous_runs(job) for a in run['attempts']]
                if job.get('runPath'):
                    path=Path(job['runPath'])
                    if not state_exists(path):raise StateError('Managed state missing; inspect before recovery')
                    run=load_state(path)
                    job['live']= {k:run.get(k) for k in ('stage','decision','createdAt','updatedAt','waitReason','stopReason','nextCheckAt','attempts')}
                    if data['active']==job['id'] and run.get('limits') and (observed is None or (run.get('limitsObservedAt') or 0)>observed):
                        limits=run['limits'];observed=run.get('limitsObservedAt')
                    job['executionApproved']=False
                    if job['type']=='project' and run.get('stage')=='waiting_approval' and run['attempts']:
                        receipt=load_state(validator.receipt_path(path.parent,run['attempts'][-1]['turnId']))
                        job['executionApproved']=bool(receipt.get('executionApproval') and receipt.get('executionApproval')==receipt.get('reviewId'))
            try:roots=safety.settings(self.queue,check_workspace=False)['allowedRoots']
            except StateError:
                if self.queue.journal().exists('settings'):raise
                roots=[]
            store=self.queue.journal()
            observations=store.load('gui-limit-history').get('observations',[]) if store.exists('gui-limit-history') else []
            return safety.sanitize({'missions':jobs,'paused':data['paused'],'active':data['active'],
                'workerRunning':self.worker_task is not None and not self.worker_task.done(),
                'connection':deepcopy(self.connection),'models':deepcopy(self.models),'account':self.account,
                'limits':limits,'limitsObservedAt':observed,'roots':roots,'preferences':self.preferences(),'limitHistory':observations,
                'portable':store.load('portable-import') if store.exists('portable-import') else None})

    async def start(self):
        if self.closed:raise StateError('Application is shutting down')
        if self.worker_task is not None and not self.worker_task.done():raise StateError('Queue worker already running')
        # Called by the bridge as an owned coroutine. No other execution path exists.
        self.worker_task=asyncio.current_task()
        token=STATE_OBSERVER.set(self._state_changed)
        self.changed()
        try:return await QueueWorker(self.queue,self.factory_for_cwd).run()
        finally:
            STATE_OBSERVER.reset(token);self.worker_task=None;self.changed()

    def _state_changed(self,key):
        if key.startswith('run/') and key.endswith('/managed.json'):
            run=self.queue.journal().load(key)
            if run.get('limitsObservedAt') and self._last_observation!=run['limitsObservedAt']:
                self._last_observation=run['limitsObservedAt'];self._record_limits(run['limits'],run['limitsObservedAt'])
        if self._emit_pending:return
        self._emit_pending=True
        asyncio.get_running_loop().call_later(.1,self._publish)

    def _record_limits(self,limits,at):
        store=self.queue.journal()
        prior=store.load('gui-limit-history').get('observations',[]) if store.exists('gui-limit-history') else []
        store.save('gui-limit-history',{'observations':(prior+[{'at':at,**limits}])[-100:]})

    def _publish(self):
        self._emit_pending=False;self.changed()

    async def shutdown(self):
        self.closed=True
        if self.worker_task is not None and not self.worker_task.done():
            self.control('pause')
            task=self.worker_task;task.cancel()
            try:await task
            except asyncio.CancelledError:pass
