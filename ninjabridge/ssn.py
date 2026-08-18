from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import websockets

from ninjabridge.messages import to_relay_text

MessageHandler = Callable[[dict[str, Any]], Awaitable[None]]
StatusHandler = Callable[[bool], Awaitable[None]]


class SsnClient:
    def __init__(
        self,
        url: str,
        session_id: str,
        relay_targets: tuple[str, ...],
        logger: logging.LoggerAdapter,
        on_message: MessageHandler | None = None,
        on_status: StatusHandler | None = None,
        password: str = "",
    ) -> None:
        self.url = url
        self.session_id = session_id
        self.relay_targets = relay_targets
        self.logger = logger
        self.on_message = on_message
        self.on_status = on_status
        self.password = password
        self.connected = False
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self.stopping = False
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self.task or self.task.done():
            self.task = asyncio.create_task(self._run(), name=f"ssn-{self.session_id[:4]}")

    async def inject(self, payload: dict[str, Any]) -> None:
        await self._enqueue({"action": "extContent", "value": json.dumps(payload, separators=(",", ":"))})

    async def send_chat(self, target: str, text: str) -> None:
        await self._enqueue({"action": "sendChat", "target": target, "value": text})

    async def publish_discord(self, payload: dict[str, Any]) -> None:
        await self.inject(payload)
        for target in self.relay_targets:
            await self.send_chat(target, to_relay_text(payload))

    async def _enqueue(self, command: dict[str, Any]) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.queue.task_done()
            self.logger.warning("SSN queue full; discarded oldest command")
        self.queue.put_nowait(command)

    async def _sender(self, socket: Any) -> None:
        while not self.stopping:
            command = await self.queue.get()
            try:
                await socket.send(json.dumps(command, separators=(",", ":")))
            except Exception:
                await self._enqueue(command)
                raise
            finally:
                self.queue.task_done()

    async def _receiver(self, socket: Any) -> None:
        async for raw in socket:
            try:
                data = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if self.on_message and isinstance(data, dict):
                try:
                    await self.on_message(data)
                except Exception:
                    self.logger.exception("Failed to process SSN message")

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
                    join: dict[str, Any] = {"join": self.session_id, "in": 4, "out": 1}
                    if self.password:
                        join["password"] = self.password
                    await socket.send(json.dumps(join))
                    attempt = 0
                    self.connected = True
                    self.logger.info("Connected to SSN channels 4→1")
                    if self.on_status:
                        await self.on_status(True)
                    sender = asyncio.create_task(self._sender(socket), name="ssn-sender")
                    receiver = asyncio.create_task(self._receiver(socket), name="ssn-receiver")
                    done, pending = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
                    for task in pending:
                        task.cancel()
                    results = await asyncio.gather(*done, *pending, return_exceptions=True)
                    for result in results:
                        if isinstance(result, Exception) and not isinstance(result, asyncio.CancelledError):
                            raise result
            except asyncio.CancelledError:
                break
            except Exception:
                delay = min(30, 2 ** attempt) + random.random() * 0.5
                attempt += 1
                self.logger.exception("SSN connection failed; retrying in %.1fs", delay)
                await asyncio.sleep(delay)
            finally:
                if self.connected:
                    self.connected = False
                    if self.on_status:
                        await self.on_status(False)

    async def close(self) -> None:
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
