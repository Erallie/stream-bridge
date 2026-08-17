from __future__ import annotations

import asyncio
import json
import logging
import random
from typing import Any

import websockets

from ninjabridge.messages import to_relay_text


class SsnClient:
    def __init__(self, url: str, session_id: str, relay_targets: tuple[str, ...], logger: logging.LoggerAdapter) -> None:
        self.url = url
        self.session_id = session_id
        self.relay_targets = relay_targets
        self.logger = logger
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self.stopping = False
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._run(), name=f"ssn-{self.session_id[:4]}")

    async def publish(self, payload: dict[str, Any]) -> None:
        await self._enqueue({"action": "extContent", "value": json.dumps(payload, separators=(",", ":"))})
        for target in self.relay_targets:
            await self._enqueue({"action": "sendChat", "target": target, "value": to_relay_text(payload)})

    async def _enqueue(self, command: dict[str, Any]) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.queue.task_done()
            self.logger.warning("SSN queue full; discarded oldest command")
        await self.queue.put(command)

    async def _run(self) -> None:
        attempt = 0
        while not self.stopping:
            try:
                self.logger.info("Connecting to Social Stream Ninja")
                async with websockets.connect(
                    self.url,
                    open_timeout=15,
                    ping_interval=25,
                    ping_timeout=15,
                    close_timeout=5,
                ) as socket:
                    await socket.send(json.dumps({"join": self.session_id, "in": 0, "out": 1}))
                    self.logger.info("Connected to Social Stream Ninja")
                    attempt = 0
                    while not self.stopping:
                        command = await self.queue.get()
                        try:
                            await socket.send(json.dumps(command, separators=(",", ":")))
                        except Exception:
                            await self._requeue(command)
                            raise
                        else:
                            self.queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                delay = min(30, 2**attempt) + random.random() * 0.5
                attempt += 1
                self.logger.exception("SSN connection failed; reconnecting in %.1f seconds", delay)
                await asyncio.sleep(delay)

    async def _requeue(self, command: dict[str, Any]) -> None:
        self.queue.task_done()
        if self.queue.full():
            self.queue.get_nowait()
            self.queue.task_done()
        await self.queue.put(command)

    async def close(self) -> None:
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
