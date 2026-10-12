"""Offline helper: crash controller after durable turn acknowledgement."""
import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import sys
from mission_control.adapter import CodexAdapter
import mission_control.queue as queue_module
from mission_control.queue import MissionQueue, QueueWorker
from mission_control.rpc import RpcClient

queue_path=Path(sys.argv[1]);server_path=Path(sys.argv[2]);mode=sys.argv[3]
queue_module.worker_lease_path=lambda:queue_path.parent/'worker'
class Adapter(CodexAdapter):
    async def run_turn(self,*a,on_started=None,**kw):
        def started(identity):
            on_started(identity)
            if mode=='crash':os._exit(93)
        return await super().run_turn(*a,on_started=started,**kw)
def for_cwd(cwd):
    @asynccontextmanager
    async def factory():
        cmd=[sys.executable,str(Path(__file__).with_name('persistent_limit_server.py')),str(server_path),'normal']
        async with RpcClient(cmd,timeout=3) as rpc:yield Adapter(rpc)
    return factory
asyncio.run(QueueWorker(MissionQueue(queue_path),for_cwd).run())
