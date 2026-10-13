"""Mission queue controls; only queue-run starts Codex."""
from contextlib import asynccontextmanager
from pathlib import Path
import shutil
from .adapter import CodexAdapter
from .queue import MissionQueue, QueueWorker
from .rpc import RpcClient
from .state import StateError, load_state, state_lock


def report(data):
    jobs=list(data['missions'].values())
    stage='paused' if data['paused'] else 'waiting' if data['active'] else 'blocked' if any(j['status'] in {'pending','failed','needs_attention','paused'} for j in jobs) else 'completed'
    result={'stage':stage,'active':data['active'],'paused':data['paused'],'executionOrder':data['executionOrder'],'missions':[]}
    for job in jobs:
        value={k:job.get(k) for k in ('id','title','project','priority','dependsOn','status','runPath','model','result')}
        value['attempts']=[{'phase':a['phase'],'turnId':a.get('turnId'),'decision':a['decision'],
                            'passed':a.get('validation',{}).get('passed')} for a in job['attempts']]
        checks=job.get('checks',{})
        value['checks']={'passed':checks.get('passed'),'changes':checks.get('changes',[]),
                         'commands':[{k:c.get(k) for k in ('name','kind','exitCode','timedOut')} for c in checks.get('commands',[])]}
        result['missions'].append(value)
    return result


async def execute_queue(args):
    q=MissionQueue(args.queue)
    if args.command=='queue-migrate':
        from .migration import migrate
        if args.legacy_queue is None:raise StateError('--legacy-queue is required')
        data=migrate(args.legacy_queue,q.path)
    elif args.command=='queue-configure':
        from .safety import configure
        configure(q,args.allow_root);data=q.read()
    elif args.command=='queue-approve':
        from .safety import approve
        approve(q,args.mission_id);data=q.read()
    elif args.command in {'queue-review-result','queue-approve-result'}:
        from .validator import review_result,approve_result
        from .queue import worker_lease_path
        with state_lock(worker_lease_path()),state_lock(q.path),q.storage():
            data=q.read();job=data['missions'].get(args.mission_id)
            if not job or job['status']!='waiting_approval' or not job.get('runPath'):
                raise StateError('Mission must await result approval')
            root=Path(job['runPath']).parent
            review=review_result(root) if args.command=='queue-review-result' else approve_result(root,args.review_id,accept_user_rights=args.accept_user_rights)
        return {'stage':'waiting_approval','workspace':str(root/'workspace'),'diff':str(root/'result.diff'),'review':review}
    elif args.command=='queue-backup':
        if args.destination is None:raise StateError('--destination is required')
        with state_lock(q.path):q.journal().backup(args.destination)
        return {'stage':'completed','backup':str(args.destination.resolve())}
    elif args.command=='queue-checkpoint-export':
        from .safety import settings
        from .checkpoints import export
        if args.destination is None:raise StateError('--destination is required')
        from .queue import worker_lease_path
        with state_lock(worker_lease_path()),state_lock(q.path),q.storage():
            data=q.read();job=data['missions'].get(args.mission_id)
            if not job or not job.get('runPath') or job['type']!='project':raise StateError('Project checkpoint required')
            root=Path(job['runPath']).parent
            destination=args.destination.resolve()
            if destination==q.path or destination.is_relative_to(q.journal().run_root):raise StateError('Export cannot replace controller state')
            export(root,load_state(root/'snapshot.json'),destination,settings(q)['allowedRoots'])
        return {'stage':'completed','export':str(destination)}
    elif args.command=='queue-add':
        if args.mission is None:raise StateError('queue-add requires --mission JSON file')
        data=q.add(load_state(args.mission))
    elif args.command=='queue-list':
        with state_lock(q.path):data=q.read()
    elif args.command=='queue-run':
        if q.path.suffix!='.sqlite3':raise StateError('Legacy JSON automation is disabled; use queue-migrate, configure roots and approve missions')
        if args.model or args.effort or args.task or args.task_file or args.thread_id:
            raise StateError('Queue execution uses saved mission definitions and SmartRouter')
        executable=shutil.which(args.codex)
        if not executable:raise StateError('Codex executable not found')
        def factory_for_cwd(cwd):
            @asynccontextmanager
            async def factory():
                async with RpcClient([executable,'app-server','--listen','stdio://'],cwd=str(cwd),timeout=args.rpc_timeout) as rpc:
                    yield CodexAdapter(rpc)
            return factory
        data=await QueueWorker(q,factory_for_cwd).run(max_wait=args.max_wait)
    else:
        data=q.control(args.command.removeprefix('queue-'),args.mission_id,priority=args.priority,acknowledge_uncertain=args.acknowledge_uncertain_result,expected_turn_id=args.pause_turn_id)
    return report(data)
