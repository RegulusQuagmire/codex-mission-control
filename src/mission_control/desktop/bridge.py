"""Qt main thread ↔ one asyncio loop in a dedicated QThread."""
import asyncio
import inspect
from PySide6.QtCore import QThread,Signal
from ..queue import MissionQueue
from ..safety import redact
from .service import DesktopService


class BackendBridge(QThread):
    snapshot=Signal(dict)
    result=Signal(str,object)
    error=Signal(str)
    stopped=Signal()
    ready=Signal()

    def __init__(self,path,*,factory_for_cwd=None):
        super().__init__()
        self.path=path;self.factory=factory_for_cwd;self.loop=None;self.service=None
        self._tasks=set();self._closing=False;self._shutdown_scheduled=False

    def run(self):
        self.loop=asyncio.new_event_loop();asyncio.set_event_loop(self.loop)
        try:
            self.service=DesktopService(MissionQueue(self.path),factory_for_cwd=self.factory,changed=self.publish)
            self.service.initialize();self.publish();self.loop.call_soon(self.ready.emit)
            # A close request may arrive before or during initialization. Queue
            # this check before entering the loop; request() also schedules it
            # once the loop is running, with duplicate dispatch suppressed.
            self.loop.call_soon(self._honor_shutdown)
            self.loop.run_forever()
        except Exception as error:self.error.emit(redact(str(error)))
        finally:
            pending=asyncio.all_tasks(self.loop)
            for task in pending:task.cancel()
            if pending:self.loop.run_until_complete(asyncio.gather(*pending,return_exceptions=True))
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.close();self.stopped.emit()

    def publish(self):
        try:self.snapshot.emit(self.service.snapshot())
        except Exception as error:self.error.emit(redact(str(error)))

    def request(self,operation,**values):
        if operation=='shutdown':
            self._closing=True
            if self.loop is not None and self.loop.is_running():
                self.loop.call_soon_threadsafe(self._honor_shutdown)
            return
        if self.loop is None or not self.loop.is_running():
            self._reject_request(operation,values,'Backend ещё не готов. Повторите проверку после запуска.');return
        if self._closing:
            self._reject_request(operation,values,'Backend завершает работу. Перезапустите приложение.');return
        self.loop.call_soon_threadsafe(self._schedule,operation,values)

    def _reject_request(self,action,values,message):
        self.error.emit(message)
        token=values.get('_request_token')
        if token is not None and action in {'probe_connection','complete_setup'}:
            self.result.emit(action,{'status':'error','message':message,'_requestToken':token})

    def _honor_shutdown(self):
        if self._closing:self._schedule('shutdown',{})

    def _schedule(self,action,values):
        if action=='shutdown':
            if self._shutdown_scheduled:return
            self._shutdown_scheduled=True
        elif self._closing:
            self._reject_request(action,values,'Backend завершает работу. Перезапустите приложение.');return
        task=self.loop.create_task(self._dispatch(action,values))
        self._tasks.add(task);task.add_done_callback(self._tasks.discard)

    async def _dispatch(self,action,values):
        values=dict(values);request_token=values.pop('_request_token',None)
        try:
            # Explicit public API allowlist, never arbitrary getattr from UI data.
            methods={name:getattr(self.service,name) for name in (
                'refresh_connection','probe_connection','complete_setup','add','edit','access_review','approve_access','control',
                'review_result','approve_result','result','configure_roots','save_preferences','export_portable','import_portable','inspect_update','start','resume_queue','resume_mission','shutdown')}
            if action not in methods:raise ValueError('Unknown desktop action')
            result=methods[action](**values)
            if inspect.isawaitable(result):result=await result
            if request_token is not None and action in {'probe_connection','complete_setup'}:
                result={**result,'_requestToken':request_token}
            self.result.emit(action,result);self.publish()
        except asyncio.CancelledError:raise
        except Exception as error:
            message=redact(str(error));self.error.emit(message)
            if request_token is not None and action in {'probe_connection','complete_setup'}:
                self.result.emit(action,{'status':'error','message':message,'_requestToken':request_token})
        finally:
            if action=='shutdown':
                for task in tuple(self._tasks):
                    if task is not asyncio.current_task():task.cancel()
                self.loop.call_soon(self.loop.stop)
