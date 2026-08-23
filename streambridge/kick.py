from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any, TypeAlias

import aiohttp
from aiohttp import web
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from streambridge.database import ConfigStore
from streambridge.oauth import OAuthToken
from streambridge.relay import ReflectionTracker

RuntimeKey: TypeAlias = int | str
KickHandler = Callable[[RuntimeKey, dict[str, Any]], Awaitable[None]]
KICK_BOT_USER_ID = "124763980"


def kick_chat_payload(text: str) -> dict[str, str]:
    return {"content": text[:500], "type": "bot"}


def broadcaster_id(event: dict[str, Any]) -> str:
    return str((event.get("broadcaster") or {}).get("user_id", ""))


class KickAccount:
    def __init__(self, gateway: "KickGateway", key: RuntimeKey, user_id: str,
                 username: str, refresh_token: str) -> None:
        self.gateway = gateway
        self.key = key
        self.user_id = user_id
        self.username = username
        self.token = OAuthToken(
            "KICK", "https://id.kick.com/oauth/token", refresh_token=refresh_token,
            client_id=gateway.client_id, client_secret=gateway.client_secret,
            on_refresh=self.save_rotated_token,
        )

    def save_rotated_token(self, refresh_token: str) -> None:
        assert self.gateway.fernet
        encrypted = self.gateway.fernet.encrypt(refresh_token.encode()).decode()
        self.gateway.store.update_dashboard_refresh_token("kick", self.user_id, encrypted)

    async def send(self, text: str) -> None:
        session = await self.gateway.get_session()
        for attempt in range(2):
            token = await self.token.get(force_refresh=attempt == 1)
            async with session.post(
                "https://api.kick.com/public/v1/chat",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=kick_chat_payload(text),
            ) as response:
                if response.status != 401 or attempt:
                    if response.status >= 400:
                        detail = await response.text()
                        raise RuntimeError(f"Kick send failed: HTTP {response.status}: {detail[:200]}")
                    return


class KickGateway:
    """Kick chat runtime; account authorization is owned by the dashboard."""

    def __init__(self, store: ConfigStore, handler: KickHandler) -> None:
        self.store = store
        self.handler = handler
        self.client_id = os.getenv("KICK_CLIENT_ID", "")
        self.client_secret = os.getenv("KICK_CLIENT_SECRET", "")
        encryption_key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
        self.fernet = Fernet(encryption_key.encode()) if encryption_key else None
        self.accounts: dict[RuntimeKey, KickAccount] = {}
        self.keys_by_broadcaster: dict[str, set[RuntimeKey]] = defaultdict(set)
        self.reflections: dict[RuntimeKey, ReflectionTracker] = defaultdict(ReflectionTracker)
        self.public_key: Any = None
        self.session: aiohttp.ClientSession | None = None
        self.start_task: asyncio.Task[None] | None = None

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def start(self) -> None:
        if self.client_id:
            self.start_task = asyncio.create_task(self.load_public_key(), name="kick-public-key")

    async def load_public_key(self) -> None:
        while True:
            try:
                session = await self.get_session()
                async with session.get("https://api.kick.com/public/v1/public-key") as response:
                    body = await response.json(content_type=None)
                    pem = body.get("data", {}).get("public_key") or body.get("public_key") or body.get("data")
                    if response.status >= 400 or not isinstance(pem, str):
                        raise RuntimeError(f"Could not load Kick public key (HTTP {response.status})")
                self.public_key = serialization.load_pem_public_key(pem.encode())
                logging.info("Loaded Kick webhook verification key")
                return
            except asyncio.CancelledError:
                return
            except Exception:
                logging.exception("Kick public key could not be loaded; retrying in 30 seconds")
                await asyncio.sleep(30)

    def register_account(self, key: RuntimeKey, user_id: str, username: str, refresh_token: str) -> None:
        if not self.fernet:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
        self.unregister_account(key)
        self.accounts[key] = KickAccount(self, key, user_id, username, refresh_token)
        self.keys_by_broadcaster[user_id].add(key)

    def unregister_account(self, key: RuntimeKey) -> None:
        account = self.accounts.pop(key, None)
        if account:
            self.keys_by_broadcaster[account.user_id].discard(key)
        self.reflections.pop(key, None)

    async def ensure_chat_subscription(self, access_token: str) -> None:
        session = await self.get_session()
        headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
        async with session.get("https://api.kick.com/public/v1/events/subscriptions", headers=headers) as response:
            body = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"Kick subscription lookup failed: HTTP {response.status}")
            if any(item.get("event") == "chat.message.sent" and item.get("version") == 1 for item in body.get("data", [])):
                return
        payload = {"events": [{"name": "chat.message.sent", "version": 1}], "method": "webhook"}
        async with session.post("https://api.kick.com/public/v1/events/subscriptions", headers=headers, json=payload) as response:
            if response.status >= 400:
                detail = await response.text()
                raise RuntimeError(f"Kick chat subscription failed: HTTP {response.status}: {detail[:200]}")

    async def webhook(self, request: web.Request) -> web.Response:
        if not self.public_key:
            return web.Response(status=503, text="Kick webhook verification is not ready")
        raw = await request.read()
        message_id = request.headers.get("Kick-Event-Message-Id", "")
        timestamp = request.headers.get("Kick-Event-Message-Timestamp", "")
        signature = request.headers.get("Kick-Event-Signature", "")
        try:
            self.public_key.verify(
                base64.b64decode(signature), f"{message_id}.{timestamp}.".encode() + raw,
                padding.PKCS1v15(), hashes.SHA256(),
            )
            event = json.loads(raw)
        except Exception:
            logging.warning("Rejected a Kick webhook with an invalid signature")
            return web.Response(status=401, text="invalid signature")
        if request.headers.get("Kick-Event-Type", "") != "chat.message.sent":
            return web.Response(status=204)
        sender = event.get("sender", {})
        identity = sender.get("identity") or {}
        data = {
            "type": "kick", "id": event.get("message_id", message_id),
            "userid": sender.get("user_id", ""), "chatname": sender.get("username", ""),
            "username": sender.get("username", ""), "chatmessage": event.get("content", ""),
            "chatimg": sender.get("profile_picture", ""), "nameColor": identity.get("username_color", ""),
            "source": "direct",
        }
        sender_id = str(sender.get("user_id", ""))
        for key in tuple(self.keys_by_broadcaster.get(broadcaster_id(event), ())):
            if sender_id == KICK_BOT_USER_ID:
                logging.debug("Suppressed message from StreamBridge's Kick relay account")
                continue
            if self.reflections[key].consume("kick", str(data["chatmessage"])):
                continue
            await self.handler(key, dict(data))
        return web.Response(status=204)

    async def send(self, key: RuntimeKey, text: str) -> None:
        account = self.accounts.get(key)
        if not account:
            return
        outbound = text[:500]
        self.reflections[key].add("kick", outbound)
        try:
            await account.send(outbound)
        except Exception:
            self.reflections[key].discard("kick", outbound)
            raise

    def connected(self, key: RuntimeKey) -> bool:
        return key in self.accounts

    def username(self, key: RuntimeKey) -> str:
        account = self.accounts.get(key)
        return account.username if account else ""

    async def close(self) -> None:
        if self.start_task:
            self.start_task.cancel()
            await asyncio.gather(self.start_task, return_exceptions=True)
        if self.session and not self.session.closed:
            await self.session.close()
