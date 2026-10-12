"""Async NDJSON transport. No automatic retries; no raw protocol logging."""
from __future__ import annotations

from .limits import merge_limit_update

import asyncio
import contextlib
import json
import os
import subprocess
from collections.abc import Sequence
from typing import Any


class ConnectionLost(RuntimeError):
    """Transport unavailable; a submitted operation may have run."""


class RpcError(RuntimeError):
    def __init__(self, method: str, code: int | None):
        self.method = method
        self.code = code
        super().__init__(f"Codex RPC {method} failed (code={code}); no automatic retry")


class RpcClient:
    def __init__(self, command: Sequence[str], *, timeout: float = 30,
                 cwd: str | None = None):
        self.command = list(command)
        self.timeout = timeout
        self.cwd = cwd
        self.process: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future] = {}
        self.initialization: dict[str, Any] = {}
        self._events: asyncio.Queue = asyncio.Queue(maxsize=4096)
        self._write_lock = asyncio.Lock()
        self._counter = 0
        self.rate_limit_snapshot = None
        self._tasks: list[asyncio.Task] = []
        self._failure: ConnectionLost | None = None

    async def __aenter__(self):
        try:
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            from .safety import codex_environment
            self.process = await asyncio.create_subprocess_exec(
                *self.command, cwd=self.cwd, creationflags=flags,env=codex_environment(),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, limit=8 * 1024 * 1024)
            self._tasks = [asyncio.create_task(self._read()),
                           asyncio.create_task(self._drain_stderr())]
            self.initialization = await self.request("initialize", {
                "clientInfo": {"name": "codex_mission_control",
                               "title": "Codex Mission Control", "version": "0.1.0"}})
            await self._send({"method": "initialized", "params": {}})
            return self
        except BaseException:
            await self.close()
            raise

    async def __aexit__(self, *_):
        await self.close()

    async def _send(self, message: dict, *, before_send=None):
        if self._failure:
            raise self._failure
        if not self.process or self.process.returncode is not None:
            raise ConnectionLost("Codex process is not running")
        try:
            async with self._write_lock:
                # Keep the policy OS lease through write; release before drain awaits.
                with before_send() if before_send is not None else contextlib.nullcontext():
                    self.process.stdin.write(
                        (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
                await self.process.stdin.drain()
        except (BrokenPipeError, ConnectionError, OSError) as exc:
            raise ConnectionLost("Codex stdin closed") from exc

    async def request(self, method: str, params: dict | None = None,
                      *, timeout: float | None = None, before_send=None) -> dict:
        self._counter += 1
        rid = self._counter
        future = asyncio.get_running_loop().create_future()
        self.pending[rid] = future
        try:
            async with asyncio.timeout(self.timeout if timeout is None else timeout):
                await self._send({"id": rid, "method": method, "params": params or {}}, before_send=before_send)
                response = await future
            if "error" in response:
                raise RpcError(method, response["error"].get("code"))
            return response["result"]
        finally:
            self.pending.pop(rid, None)
            if not future.done():
                future.cancel()

    def _fail(self, reason: str):
        if self._failure:
            return
        self._failure = ConnectionLost(reason)
        for future in self.pending.values():
            if not future.done():
                future.set_exception(self._failure)
        # Replace backlog on terminal failure: never claim incomplete turns succeeded.
        while not self._events.empty():
            self._events.get_nowait()
        self._events.put_nowait(self._failure)

    async def _read(self):
        try:
            while line := await self.process.stdout.readline():
                message = json.loads(line)
                if not isinstance(message, dict):
                    raise ValueError("Expected object")
                if "method" in message:
                    if "id" in message:
                        # Stage 1 never grants approval, supplies credentials, or runs tools.
                        await self._send({"id": message["id"], "error": {
                            "code": -32601, "message": "Unsupported client request"}})
                    else:
                        if message["method"] == "account/rateLimits/updated":
                            self.rate_limit_snapshot = merge_limit_update(
                                self.rate_limit_snapshot, message.get("params", {}))
                        self._events.put_nowait(message)
                elif "id" in message and ("result" in message or "error" in message):
                    future = self.pending.get(message["id"])
                    if future is not None and not future.done():
                        future.set_result(message)
                else:
                    raise ValueError("Invalid response envelope")
            self._fail("Codex stdout closed; outcome may be unknown")
        except asyncio.CancelledError:
            raise
        except (ValueError, UnicodeError, asyncio.QueueFull, ConnectionLost, OSError):
            self._fail("Codex transport failed or notification backlog exceeded")

    async def _drain_stderr(self):
        # Drain continuously to avoid child-process deadlocks. Never persist secrets.
        while await self.process.stderr.read(8192):
            pass

    async def next_event(self) -> dict:
        if self._failure:
            raise self._failure
        event = await self._events.get()
        if isinstance(event, Exception):
            raise event
        return event

    async def close(self):
        if self.process:
            if self.process.stdin:
                with contextlib.suppress(OSError):
                    self.process.stdin.close()
            if self.process.returncode is None:
                try:
                    await asyncio.wait_for(self.process.wait(), 2)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        self.process.terminate()
                    try:
                        await asyncio.wait_for(self.process.wait(), 2)
                    except TimeoutError:
                        with contextlib.suppress(ProcessLookupError):
                            self.process.kill()
                        await self.process.wait()
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._fail("Codex client closed")
