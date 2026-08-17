from __future__ import annotations

import asyncio
import logging
import os
import random
from collections.abc import Awaitable, Callable
from typing import Any

import aiohttp
import websockets

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class TwitchAdapter:
    def __init__(self, channel: str, handler: Handler) -> None:
        self.channel = channel.lstrip("#").lower()
        self.handler = handler
        self.task: asyncio.Task[None] | None = None
        self.socket: Any = None
        self.queue: asyncio.Queue[str] = asyncio.Queue(maxsize=200)

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name=f"twitch-{self.channel}")

    async def send(self, text: str) -> None:
        await self.queue.put(text[:500])

    async def run(self) -> None:
        token = os.getenv("TWITCH_OAUTH_TOKEN", "").removeprefix("oauth:")
        username = os.getenv("TWITCH_BOT_USERNAME", "").lower()
        if not token or not username:
            logging.error("Direct Twitch requires TWITCH_OAUTH_TOKEN and TWITCH_BOT_USERNAME")
            return
        attempt = 0
        while True:
            try:
                async with websockets.connect("wss://irc-ws.chat.twitch.tv:443", ping_interval=25, ping_timeout=15) as socket:
                    self.socket = socket
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
        while True:
            text = await self.queue.get()
            await socket.send(f"PRIVMSG #{self.channel} :{text}")
            self.queue.task_done()

    async def parse_message(self, line: str) -> None:
        tags_text, rest = line.split(" ", 1) if line.startswith("@") else ("", line)
        tags = dict(item.split("=", 1) for item in tags_text[1:].split(";") if "=" in item)
        prefix, text = rest.split(" PRIVMSG ", 1)
        _, message = text.split(" :", 1)
        login = prefix.split("!", 1)[0].lstrip(":")
        await self.handler({
            "type": "twitch", "id": tags.get("id", ""), "userid": tags.get("user-id", login),
            "chatname": tags.get("display-name", login), "username": login,
            "chatmessage": message, "chatimg": "", "source": "direct",
        })

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

    def start(self) -> None:
        self.task = asyncio.create_task(self.run(), name="youtube-live-chat")

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {os.getenv('YOUTUBE_ACCESS_TOKEN', '')}", "Content-Type": "application/json"}

    async def run(self) -> None:
        if not os.getenv("YOUTUBE_ACCESS_TOKEN"):
            logging.error("Direct YouTube requires YOUTUBE_ACCESS_TOKEN")
            return
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    params = {"liveChatId": self.live_chat_id, "part": "id,snippet,authorDetails", "maxResults": 200}
                    if self.page_token:
                        params["pageToken"] = self.page_token
                    async with session.get("https://www.googleapis.com/youtube/v3/liveChat/messages", params=params, headers=self.headers) as response:
                        body = await response.json(content_type=None)
                        if response.status >= 400:
                            raise RuntimeError(f"YouTube HTTP {response.status}: {body}")
                    initial = not self.page_token
                    self.page_token = body.get("nextPageToken", self.page_token)
                    if not initial:
                        for item in body.get("items", []):
                            snippet = item.get("snippet", {})
                            author = item.get("authorDetails", {})
                            if snippet.get("type") == "textMessageEvent":
                                await self.handler({
                                    "type": "youtube", "id": item.get("id", ""),
                                    "userid": author.get("channelId", ""), "chatname": author.get("displayName", ""),
                                    "username": author.get("displayName", ""), "chatmessage": snippet.get("displayMessage", ""),
                                    "chatimg": author.get("profileImageUrl", ""), "source": "direct",
                                })
                    await asyncio.sleep(max(1, int(body.get("pollingIntervalMillis", 5000)) / 1000))
                except asyncio.CancelledError:
                    return
                except Exception:
                    logging.exception("Direct YouTube polling failed; retrying")
                    await asyncio.sleep(15)

    async def send(self, text: str) -> None:
        payload = {"snippet": {"liveChatId": self.live_chat_id, "type": "textMessageEvent", "textMessageDetails": {"messageText": text[:200]}}}
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.post("https://www.googleapis.com/youtube/v3/liveChat/messages", params={"part": "snippet"}, headers=self.headers, json=payload) as response:
                if response.status >= 400:
                    raise RuntimeError(f"YouTube send failed: {response.status} {await response.text()}")

    async def close(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)


class DirectHub:
    def __init__(self, handler: Handler, twitch_channel: str = "", youtube_live_chat_id: str = "") -> None:
        self.adapters: dict[str, Any] = {}
        if twitch_channel:
            self.adapters["twitch"] = TwitchAdapter(twitch_channel, handler)
        if youtube_live_chat_id:
            self.adapters["youtube"] = YouTubeAdapter(youtube_live_chat_id, handler)

    def start(self) -> None:
        for adapter in self.adapters.values():
            adapter.start()

    async def send(self, text: str, exclude: str = "") -> None:
        results = await asyncio.gather(*(adapter.send(text) for platform, adapter in self.adapters.items() if platform != exclude), return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logging.error("Direct platform send failed: %s", result)

    async def close(self) -> None:
        await asyncio.gather(*(adapter.close() for adapter in self.adapters.values()), return_exceptions=True)
