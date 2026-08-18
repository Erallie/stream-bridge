from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import websockets
from aiohttp import web
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from ninjabridge.oauth import OAuthToken
from ninjabridge.relay import ReflectionTracker

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class TwitchAdapter:
    def __init__(self, channel: str, handler: Handler) -> None:
        self.channel = channel.lstrip("#").lower()
        self.handler = handler
        self.task: asyncio.Task[None] | None = None
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)
        self.oauth = OAuthToken("TWITCH", "https://id.twitch.tv/oauth2/token")

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name=f"twitch-{self.channel}")

    async def send(self, text: str) -> None:
        if self.queue.full():
            self.queue.get_nowait()
            self.queue.task_done()
            logging.warning("Twitch send queue full; discarded oldest message")
        await self.queue.put(text[:500])

    async def run(self) -> None:
        username = os.getenv("TWITCH_BOT_USERNAME", "").lower()
        if not self.oauth.configured or not username:
            logging.error("Direct Twitch requires TWITCH_BOT_USERNAME and Twitch OAuth credentials")
            return
        attempt = 0
        while True:
            try:
                token = await self.oauth.get(force_refresh=attempt > 0)
                async with websockets.connect("wss://irc-ws.chat.twitch.tv:443", ping_interval=25, ping_timeout=15) as socket:
                    await socket.send("CAP REQ :twitch.tv/tags twitch.tv/commands")
                    await socket.send(f"PASS oauth:{token}")
                    await socket.send(f"NICK {username}")
                    await socket.send(f"JOIN #{self.channel}")
                    attempt = 0
                    sender = asyncio.create_task(self.sender(socket))
                    try:
                        async for raw in socket:
                            for line in raw.split("\r\n"):
                                if line.startswith("PING"):
                                    await socket.send("PONG :tmi.twitch.tv")
                                elif "Login authentication failed" in line:
                                    raise RuntimeError("Twitch rejected the OAuth token")
                                elif " PRIVMSG " in line:
                                    await self.parse_message(line)
                    finally:
                        sender.cancel()
            except asyncio.CancelledError:
                return
            except Exception:
                delay = min(30, 2 ** attempt) + random.random()
                attempt += 1
                logging.exception("Direct Twitch connection failed; retrying in %.1fs", delay)
                await asyncio.sleep(delay)

    async def sender(self, socket: Any) -> None:
        last_send = 0.0
        while True:
            text = await self.queue.get()
            try:
                delay = 1.5 - (asyncio.get_running_loop().time() - last_send)
                if delay > 0:
                    await asyncio.sleep(delay)
                await socket.send(f"PRIVMSG #{self.channel} :{text}")
                last_send = asyncio.get_running_loop().time()
            finally:
                self.queue.task_done()

    async def parse_message(self, line: str) -> None:
        tags_text, rest = line.split(" ", 1) if line.startswith("@") else ("", line)
        tags = dict(item.split("=", 1) for item in tags_text[1:].split(";") if "=" in item)
        prefix, text = rest.split(" PRIVMSG ", 1)
        _, message = text.split(" :", 1)
        login = prefix.split("!", 1)[0].lstrip(":")
        await self.handler({"type": "twitch", "id": tags.get("id", ""), "userid": tags.get("user-id", login), "chatname": tags.get("display-name", login), "username": login, "chatmessage": message, "chatimg": "", "nameColor": tags.get("color", ""), "source": "direct"})

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class YouTubeAdapter:
    def __init__(self, live_chat_id: str, handler: Handler) -> None:
        self.live_chat_id = live_chat_id
        self.handler = handler
        self.task: asyncio.Task[None] | None = None
        self.page_token = ""
        self.oauth = OAuthToken("YOUTUBE", "https://oauth2.googleapis.com/token")
        self.session: aiohttp.ClientSession | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="youtube-live-chat")

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def request(self, session: aiohttp.ClientSession, method: str, url: str, **kwargs: Any) -> tuple[int, Any]:
        for attempt in range(2):
            token = await self.oauth.get(force_refresh=attempt == 1)
            kwargs["headers"] = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
            async with session.request(method, url, **kwargs) as response:
                body = await response.json(content_type=None)
                if response.status != 401 or attempt:
                    return response.status, body
        raise RuntimeError("YouTube request retry failed")

    async def run(self) -> None:
        if not self.oauth.configured:
            logging.error("Direct YouTube requires YouTube OAuth credentials")
            return
        session = await self.get_session()
        while True:
            try:
                params = {"liveChatId": self.live_chat_id, "part": "id,snippet,authorDetails", "maxResults": 200}
                if self.page_token:
                    params["pageToken"] = self.page_token
                status, body = await self.request(session, "GET", "https://www.googleapis.com/youtube/v3/liveChat/messages", params=params)
                if status >= 400:
                    raise RuntimeError(f"YouTube HTTP {status}: {body}")
                initial = not self.page_token
                self.page_token = body.get("nextPageToken", self.page_token)
                if not initial:
                    for item in body.get("items", []):
                        snippet, author = item.get("snippet", {}), item.get("authorDetails", {})
                        if snippet.get("type") == "textMessageEvent":
                            await self.handler({"type": "youtube", "id": item.get("id", ""), "userid": author.get("channelId", ""), "chatname": author.get("displayName", ""), "username": author.get("displayName", ""), "chatmessage": snippet.get("displayMessage", ""), "chatimg": author.get("profileImageUrl", ""), "source": "direct"})
                await asyncio.sleep(max(1, int(body.get("pollingIntervalMillis", 5000)) / 1000))
            except asyncio.CancelledError:
                return
            except Exception:
                logging.exception("Direct YouTube polling failed; retrying")
                await asyncio.sleep(15)

    async def send(self, text: str) -> None:
        payload = {"snippet": {"liveChatId": self.live_chat_id, "type": "textMessageEvent", "textMessageDetails": {"messageText": text[:200]}}}
        session = await self.get_session()
        status, body = await self.request(session, "POST", "https://www.googleapis.com/youtube/v3/liveChat/messages", params={"part": "snippet"}, json=payload)
        if status >= 400:
            raise RuntimeError(f"YouTube send failed: HTTP {status}: {body}")

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.session and not self.session.closed:
            await self.session.close()


class KickAdapter:
    def __init__(self, broadcaster_user_id: str, handler: Handler) -> None:
        self.broadcaster_user_id = broadcaster_user_id
        self.handler = handler
        self.oauth = OAuthToken("KICK", "https://id.kick.com/oauth/token")
        self.runner: web.AppRunner | None = None
        self.public_key: Any = None
        self.task: asyncio.Task[None] | None = None
        self.session: aiohttp.ClientSession | None = None

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="kick-webhook")

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def run(self) -> None:
        if not self.oauth.configured:
            logging.error("Direct Kick requires Kick OAuth credentials")
            return
        try:
            session = await self.get_session()
            async with session.get("https://api.kick.com/public/v1/public-key") as response:
                body = await response.json(content_type=None)
                pem = body.get("data", {}).get("public_key") or body.get("public_key") or body.get("data")
                if response.status >= 400 or not isinstance(pem, str):
                    raise RuntimeError(f"Could not load Kick public key (HTTP {response.status})")
            self.public_key = serialization.load_pem_public_key(pem.encode())
            app = web.Application(client_max_size=1024 * 1024)
            app.router.add_post(os.getenv("KICK_WEBHOOK_PATH", "/kick/webhook"), self.webhook)
            self.runner = web.AppRunner(app, access_log=logging.getLogger("ninjabridge.kick.http"))
            await self.runner.setup()
            await web.TCPSite(self.runner, os.getenv("KICK_WEBHOOK_HOST", "127.0.0.1"), int(os.getenv("KICK_WEBHOOK_PORT", "8765"))).start()
            logging.info("Kick webhook receiver listening on the loopback interface")
        except Exception:
            logging.exception("Direct Kick webhook receiver could not start")

    async def webhook(self, request: web.Request) -> web.Response:
        raw = await request.read()
        message_id = request.headers.get("Kick-Event-Message-Id", "")
        timestamp = request.headers.get("Kick-Event-Message-Timestamp", "")
        signature = request.headers.get("Kick-Event-Signature", "")
        try:
            signed = f"{message_id}.{timestamp}.".encode() + raw
            self.public_key.verify(base64.b64decode(signature), signed, padding.PKCS1v15(), hashes.SHA256())
            event = json.loads(raw)
        except Exception:
            logging.warning("Rejected a Kick webhook with an invalid signature")
            return web.Response(status=401, text="invalid signature")
        if request.headers.get("Kick-Event-Type", "") == "chat.message.sent":
            sender = event.get("sender", {})
            identity = sender.get("identity") or {}
            await self.handler({"type": "kick", "id": event.get("message_id", message_id), "userid": sender.get("user_id", ""), "chatname": sender.get("username", ""), "username": sender.get("username", ""), "chatmessage": event.get("content", ""), "chatimg": sender.get("profile_picture", ""), "nameColor": identity.get("username_color", ""), "source": "direct"})
        return web.Response(status=204)

    async def send(self, text: str) -> None:
        payload: dict[str, Any] = {"content": text[:500], "type": "user"}
        if self.broadcaster_user_id:
            payload["broadcaster_user_id"] = int(self.broadcaster_user_id)
        session = await self.get_session()
        for attempt in range(2):
            token = await self.oauth.get(force_refresh=attempt == 1)
            async with session.post("https://api.kick.com/public/v1/chat", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=payload) as response:
                if response.status != 401 or attempt:
                    if response.status >= 400:
                        raise RuntimeError(f"Kick send failed: HTTP {response.status}")
                    return

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.runner:
            await self.runner.cleanup()
        if self.session and not self.session.closed:
            await self.session.close()


class DirectHub:
    def __init__(self, handler: Handler, twitch_channel: str = "", youtube_live_chat_id: str = "", kick_broadcaster_user_id: str = "") -> None:
        self.adapters: dict[str, Any] = {}
        self.reflections = ReflectionTracker()

        def platform_handler(platform: str) -> Handler:
            async def received(data: dict[str, Any]) -> None:
                if self.reflections.consume(platform, str(data.get("chatmessage", ""))):
                    logging.debug("Suppressed reflected %s relay message", platform)
                    return
                await handler(data)
            return received

        if twitch_channel:
            self.adapters["twitch"] = TwitchAdapter(twitch_channel, platform_handler("twitch"))
        if youtube_live_chat_id:
            self.adapters["youtube"] = YouTubeAdapter(youtube_live_chat_id, platform_handler("youtube"))
        if kick_broadcaster_user_id:
            self.adapters["kick"] = KickAdapter(kick_broadcaster_user_id, platform_handler("kick"))

    def start(self) -> None:
        for adapter in self.adapters.values():
            adapter.start()

    async def send(self, text: str, exclude: str = "") -> None:
        destinations = [(platform, adapter) for platform, adapter in self.adapters.items() if platform != exclude]
        for platform, _ in destinations:
            self.reflections.add(platform, text)
        results = await asyncio.gather(*(adapter.send(text) for _, adapter in destinations), return_exceptions=True)
        for (platform, _), result in zip(destinations, results, strict=True):
            if isinstance(result, Exception):
                self.reflections.discard(platform, text)
                logging.error("Direct %s send failed: %s", platform, result)

    async def close(self) -> None:
        await asyncio.gather(*(adapter.close() for adapter in self.adapters.values()), return_exceptions=True)
