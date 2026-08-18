from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import aiohttp
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
    ) -> None:
        self.url = url
        self.http_api_url = self._default_http_api_url(url, session_id)
        self.session_id = session_id
        self.relay_targets = relay_targets
        self.logger = logger
        self.on_message = on_message
        self.on_status = on_status
        self.connected = False
        self.queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self.stopping = False
        self.task: asyncio.Task[None] | None = None
        self.host_wait_logged = False

    @staticmethod
    def _default_http_api_url(url: str, session_id: str) -> str:
        parts = urlsplit(url)
        scheme = "https" if parts.scheme == "wss" else "http"
        return urlunsplit((scheme, parts.netloc, "/" + quote(session_id, safe=""), "", ""))

    async def _set_connected(self, connected: bool) -> None:
        if self.connected == connected:
            return
        self.connected = connected
        if connected:
            self.host_wait_logged = False
            self.logger.info("SSN host responded; using SSN transport")
        else:
            self.logger.warning("SSN host stopped responding; using direct transport")
        if self.on_status:
            await self.on_status(connected)

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

    async def _probe_host(self) -> None:
        interval = max(5.0, float(os.getenv("SSN_HOST_PROBE_INTERVAL", "15")))
        timeout = max(3.0, float(os.getenv("SSN_HOST_PROBE_TIMEOUT", "10")))
        client_timeout = aiohttp.ClientTimeout(total=timeout)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            while not self.stopping:
                payload: dict[str, Any] = {"action": "getHype", "get": "ninjabridge-presence"}
                host_available = False
                try:
                    async with session.post(self.http_api_url, json=payload) as response:
                        result = await response.json(content_type=None)
                        host_available = response.status < 400 and isinstance(result, dict)
                except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError):
                    host_available = False
                await self._set_connected(host_available)
                if not host_available and not self.host_wait_logged:
                    self.logger.warning(
                        "SSN relay is reachable, but the SSN host did not answer; using direct transport and continuing to check"
                    )
                    self.host_wait_logged = True
                await asyncio.sleep(interval)

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
                    await socket.send(json.dumps(join))
                    attempt = 0
                    self.logger.info("Connected to SSN relay; waiting for the SSN host")
                    sender = asyncio.create_task(self._sender(socket), name="ssn-sender")
                    receiver = asyncio.create_task(self._receiver(socket), name="ssn-receiver")
                    probe = asyncio.create_task(self._probe_host(), name="ssn-host-probe")
                    done, pending = await asyncio.wait((sender, receiver, probe), return_when=asyncio.FIRST_COMPLETED)
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
                await self._set_connected(False)

    async def close(self) -> None:
        self.stopping = True
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
