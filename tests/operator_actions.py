"""Explicit operator confirmations for trusted test fixtures, never a gate bypass.

Security regression tests use the raw runners and verify the unapproved boundary.
Existing execution tests use these helpers to approve each observed result and
then retain their assertions on actual subprocesses, repairs and receipts.
"""
from pathlib import Path
from mission_control import validator as v
from mission_control.queue import QueueWorker
from mission_control.mission_run import ProjectRunner


def confirm(root):
    review=v.review_result(root)
    v.approve_result(root,review['reviewId'],accept_user_rights=True)


async def validate_with_confirmation(*args,**kwargs):
    result=await v.validate(*args,**kwargs)
    if result['kind']=='execution_approval_required':
        confirm(args[0]);result=await v.validate(*args,**kwargs)
    return result


class ConfirmedQueueWorker(QueueWorker):
    async def run(self,**kwargs):
        for _ in range(20):
            result=await super().run(**kwargs)
            if result['active'] is None:return result
            job=result['missions'][result['active']]
            if job['status']!='waiting_approval':return result
            with self.queue.storage():confirm(Path(job['runPath']).parent)
        raise AssertionError('Fixture confirmation budget exhausted')


class ConfirmedProjectRunner(ProjectRunner):
    async def run_project(self,*args,**kwargs):
        return await self._confirm_until_done(await super().run_project(*args,**kwargs))

    async def resume(self,**kwargs):
        return await self._confirm_until_done(await super().resume(**kwargs))

    async def _confirm_until_done(self,result):
        for _ in range(8):
            if result['stage']!='waiting_approval':return result
            confirm(self.root);result=await super().resume()
        raise AssertionError('Fixture confirmation budget exhausted')
