"""CLI entry points for metadata-only limits and durable text execution."""
from contextlib import asynccontextmanager
from pathlib import Path
import shutil

from .adapter import CodexAdapter
from .limits import inspect_limits, LimitPolicy, number
from .managed import ManagedRunner
from .routing import Task, Mode, RoutingBlocked
from .rpc import RpcClient
from .state import load_state


async def execute_managed(args):
    if args.model is not None or args.effort is not None:
        raise RoutingBlocked("Managed commands use SmartRouter configuration")
    if args.max_wait is not None and (not number(args.max_wait) or args.max_wait < 0):
        raise RoutingBlocked("--max-wait must be finite and nonnegative")
    if args.command == "managed-resume":
        if args.task is not None or args.task_file is not None or args.expect is not None or args.thread_id is not None:
            raise RoutingBlocked("Resume uses the saved task/validator/thread; do not supply replacements")
        saved=load_state(args.state)
        if args.output and args.output.resolve()==Path(saved.get("historyPath",args.history)).resolve():
            raise RoutingBlocked("Report output must differ from saved history")
    task=None
    if args.command == "managed-run":
        text=args.task_file.read_text(encoding="utf-8-sig") if args.task_file else args.task
        if text is None or args.expect is None:
            raise RoutingBlocked("managed-run requires --task/--task-file and --expect")
        task=Task(text,operation=args.operation,estimated_files=args.files,risk=args.risk,previous_errors=args.previous_errors)
    executable=shutil.which(args.codex)
    cwd=args.cwd.resolve()
    if not executable or not cwd.is_dir():
        raise RoutingBlocked("Codex executable and existing workspace required")
    @asynccontextmanager
    async def factory():
        async with RpcClient([executable,"app-server","--listen","stdio://"],cwd=str(cwd),timeout=args.rpc_timeout) as rpc:
            yield CodexAdapter(rpc)
    if args.command == "limits":
        async with factory() as adapter:
            limits=await adapter.rate_limits()
            return {"stage":"limits","inferenceStarted":False,"limits":inspect_limits(limits),"snapshot":limits}
    runner=ManagedRunner(factory,args.state,cwd=cwd)
    if args.command == "managed-resume":
        return await runner.resume(max_wait=args.max_wait)
    return await runner.run(task,expected=args.expect,mode=Mode(args.mode),
                            policy=LimitPolicy(args.limit_policy,args.limit_threshold),history_path=args.history,
                            excluded=args.exclude_model,thread_id=args.thread_id,max_attempts=args.max_attempts,
                            turn_timeout=args.turn_timeout,max_wait=args.max_wait)
