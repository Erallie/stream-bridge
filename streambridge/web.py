from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web

from streambridge.kick import KickGateway
from streambridge.dashboard import DashboardAPI


class WebGateway:
    """Shared local HTTP receiver for platform webhooks and OAuth callbacks."""

    def __init__(self, kick: KickGateway, dashboard: DashboardAPI | None = None) -> None:
        self.kick = kick
        self.dashboard = dashboard
        self.runner: web.AppRunner | None = None
        self.start_task: asyncio.Task[None] | None = None
        self.listener_ready = False

    def create_app(self) -> web.Application:
        app = web.Application(client_max_size=1024 * 1024)
        app.router.add_post(os.getenv("KICK_WEBHOOK_PATH", "/kick/webhook"), self.kick.webhook)
        if self.dashboard:
            self.dashboard.register(app)
        return app

    async def start(self) -> None:
        self.start_task = asyncio.create_task(self.run_listener(), name="web-gateway")

    async def run_listener(self) -> None:
        while True:
            try:
                self.runner = web.AppRunner(self.create_app(), access_log=logging.getLogger("streambridge.web.http"))
                await self.runner.setup()
                await web.TCPSite(
                    self.runner,
                    os.getenv("WEBHOOK_HOST", "127.0.0.1"),
                    int(os.getenv("WEBHOOK_PORT", "8765")),
                ).start()
                self.listener_ready = True
                logging.info("Webhook and OAuth receiver listening on the loopback interface")
                return
            except asyncio.CancelledError:
                return
            except Exception:
                logging.exception("Webhook/OAuth receiver could not start; retrying in 30 seconds")
                if self.runner:
                    await self.runner.cleanup()
                    self.runner = None
                self.listener_ready = False
                await asyncio.sleep(30)

    async def close(self) -> None:
        self.listener_ready = False
        if self.start_task:
            self.start_task.cancel()
            await asyncio.gather(self.start_task, return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()
        if self.dashboard:
            await self.dashboard.close()
