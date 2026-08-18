from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
import urllib.parse
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from streambridge.database import ConfigStore
from streambridge.oauth import OAuthToken
from streambridge.relay import ReflectionTracker

KickHandler = Callable[[int, dict[str, Any]], Awaitable[None]]
AuthorizedHandler = Callable[[int, str], Awaitable[None]]


def kick_chat_payload(text: str) -> dict[str, str]:
    return {"content": text[:500], "type": "bot"}


def broadcaster_id(event: dict[str, Any]) -> str:
    broadcaster = event.get("broadcaster") or {}
    return str(broadcaster.get("user_id", ""))


def create_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


@dataclass
class PendingAuthorization:
    guild_id: int
    verifier: str
    expires_at: float


class KickAccount:
    def __init__(self, gateway: "KickGateway", guild_id: int, user_id: str, username: str, refresh_token: str) -> None:
        self.gateway = gateway
        self.guild_id = guild_id
        self.user_id = user_id
        self.username = username
        self.token = OAuthToken(
            "KICK",
            "https://id.kick.com/oauth/token",
            refresh_token=refresh_token,
            client_id=gateway.client_id,
            client_secret=gateway.client_secret,
            on_refresh=self.save_rotated_token,
        )

    def save_rotated_token(self, refresh_token: str) -> None:
        self.gateway.save_account(self.guild_id, self.user_id, self.username, refresh_token)

    async def send(self, text: str) -> None:
        payload = kick_chat_payload(text)
        session = await self.gateway.get_session()
        for attempt in range(2):
            token = await self.token.get(force_refresh=attempt == 1)
            async with session.post(
                "https://api.kick.com/public/v1/chat",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            ) as response:
                if response.status != 401 or attempt:
                    if response.status >= 400:
                        detail = await response.text()
                        raise RuntimeError(f"Kick send failed: HTTP {response.status}: {detail[:200]}")
                    return


class KickGateway:
    """One webhook/OAuth service with separately authorized Kick accounts per Discord guild."""

    def __init__(self, store: ConfigStore, handler: KickHandler, on_authorized: AuthorizedHandler) -> None:
        self.store = store
        self.handler = handler
        self.on_authorized = on_authorized
        self.client_id = os.getenv("KICK_CLIENT_ID", "")
        self.client_secret = os.getenv("KICK_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("KICK_OAUTH_REDIRECT_URI", "")
        self.fernet = self._load_fernet()
        self.accounts: dict[int, KickAccount] = {}
        self.guilds_by_broadcaster: dict[str, set[int]] = defaultdict(set)
        self.reflections: dict[int, ReflectionTracker] = defaultdict(ReflectionTracker)
        self.pending: dict[str, PendingAuthorization] = {}
        self.public_key: Any = None
        self.session: aiohttp.ClientSession | None = None
        self.start_task: asyncio.Task[None] | None = None

    @staticmethod
    def _load_fernet() -> Fernet | None:
        key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
        if not key:
            return None
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, TypeError):
            logging.error("TOKEN_ENCRYPTION_KEY is not a valid Fernet key")
            return None

    @property
    def authorization_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri and self.fernet)

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def start(self) -> None:
        self.load_accounts()
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

    def load_accounts(self) -> None:
        if not self.fernet:
            return
        for guild_text in self.store.guild_ids():
            saved = self.store.get_setting(guild_text, "kick_authorization", {})
            if not isinstance(saved, dict) or not saved.get("refresh_token"):
                continue
            try:
                token = self.fernet.decrypt(str(saved["refresh_token"]).encode("ascii")).decode("utf-8")
                self.register_account(int(guild_text), str(saved["broadcaster_user_id"]), str(saved.get("username", "")), token)
            except (InvalidToken, KeyError, ValueError, UnicodeError):
                logging.error("Could not decrypt the saved Kick authorization for Discord guild %s", guild_text)

    def register_account(self, guild_id: int, user_id: str, username: str, refresh_token: str) -> None:
        previous = self.accounts.get(guild_id)
        if previous:
            self.guilds_by_broadcaster[previous.user_id].discard(guild_id)
        self.accounts[guild_id] = KickAccount(self, guild_id, user_id, username, refresh_token)
        self.guilds_by_broadcaster[user_id].add(guild_id)

    def save_account(self, guild_id: int, user_id: str, username: str, refresh_token: str) -> None:
        if not self.fernet:
            raise RuntimeError("Kick token encryption is not configured")
        encrypted = self.fernet.encrypt(refresh_token.encode("utf-8")).decode("ascii")
        self.store.set_setting(str(guild_id), "kick_authorization", {
            "broadcaster_user_id": user_id,
            "username": username,
            "refresh_token": encrypted,
        })

    def authorization_url(self, guild_id: int, listener_ready: bool) -> str:
        if not self.authorization_configured:
            raise RuntimeError("Kick authorization has not been configured by the StreamBridge owner.")
        if not listener_ready:
            raise RuntimeError("The authorization receiver is still starting. Try again in a moment.")
        self._prune_pending()
        state = secrets.token_urlsafe(32)
        verifier, challenge = create_pkce_pair()
        self.pending[state] = PendingAuthorization(guild_id, verifier, time.monotonic() + 600)
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "user:read chat:write events:subscribe",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        })
        return f"https://id.kick.com/oauth/authorize?{query}"

    def _prune_pending(self) -> None:
        now = time.monotonic()
        for state in [key for key, pending in self.pending.items() if pending.expires_at < now]:
            self.pending.pop(state, None)

    async def oauth_callback(self, request: web.Request) -> web.Response:
        state = request.query.get("state", "")
        pending = self.pending.pop(state, None)
        if not pending or pending.expires_at < time.monotonic():
            return web.Response(status=400, text="This StreamBridge authorization link is invalid or expired.")
        if request.query.get("error"):
            return web.Response(status=400, text=f"Kick authorization was declined: {request.query['error']}")
        code = request.query.get("code", "")
        if not code:
            return web.Response(status=400, text="Kick did not provide an authorization code.")
        try:
            body = await self.exchange_code(code, pending.verifier)
            access_token = str(body["access_token"])
            refresh_token = str(body["refresh_token"])
            user_id, username = await self.get_authorized_user(access_token)
            await self.ensure_chat_subscription(access_token)
            self.save_account(pending.guild_id, user_id, username, refresh_token)
            self.register_account(pending.guild_id, user_id, username, refresh_token)
            await self.on_authorized(pending.guild_id, username)
        except Exception:
            logging.exception("Kick OAuth callback failed for guild %s", pending.guild_id)
            return web.Response(status=500, text="StreamBridge could not finish Kick authorization. Check its logs.")
        return web.Response(text=f"Kick channel {username} is now connected to StreamBridge. You may close this tab.")

    async def exchange_code(self, code: str, verifier: str) -> dict[str, Any]:
        session = await self.get_session()
        form = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri,
            "code_verifier": verifier,
        }
        async with session.post("https://id.kick.com/oauth/token", data=form) as response:
            body = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"Kick token exchange failed: HTTP {response.status}")
            return body

    async def get_authorized_user(self, access_token: str) -> tuple[str, str]:
        session = await self.get_session()
        async with session.get("https://api.kick.com/public/v1/users", headers={"Authorization": f"Bearer {access_token}"}) as response:
            body = await response.json(content_type=None)
            users = body.get("data", [])
            if response.status >= 400 or not users:
                raise RuntimeError(f"Kick user lookup failed: HTTP {response.status}")
            return str(users[0]["user_id"]), str(users[0].get("name", users[0].get("username", "Kick broadcaster")))

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
            signed = f"{message_id}.{timestamp}.".encode() + raw
            self.public_key.verify(base64.b64decode(signature), signed, padding.PKCS1v15(), hashes.SHA256())
            event = json.loads(raw)
        except Exception:
            logging.warning("Rejected a Kick webhook with an invalid signature")
            return web.Response(status=401, text="invalid signature")
        if request.headers.get("Kick-Event-Type", "") != "chat.message.sent":
            return web.Response(status=204)
        guild_ids = tuple(self.guilds_by_broadcaster.get(broadcaster_id(event), ()))
        sender = event.get("sender", {})
        identity = sender.get("identity") or {}
        data = {"type": "kick", "id": event.get("message_id", message_id), "userid": sender.get("user_id", ""), "chatname": sender.get("username", ""), "username": sender.get("username", ""), "chatmessage": event.get("content", ""), "chatimg": sender.get("profile_picture", ""), "nameColor": identity.get("username_color", ""), "source": "direct"}
        for guild_id in guild_ids:
            if self.reflections[guild_id].consume("kick", str(data["chatmessage"])):
                continue
            await self.handler(guild_id, dict(data))
        return web.Response(status=204)

    async def send(self, guild_id: int, text: str) -> None:
        account = self.accounts.get(guild_id)
        if not account:
            return
        self.reflections[guild_id].add("kick", text)
        try:
            await account.send(text)
        except Exception:
            self.reflections[guild_id].discard("kick", text)
            raise

    def connected(self, guild_id: int) -> bool:
        return guild_id in self.accounts

    def username(self, guild_id: int) -> str:
        account = self.accounts.get(guild_id)
        return account.username if account else ""

    async def disable(self, guild_id: int) -> None:
        account = self.accounts.pop(guild_id, None)
        if account:
            self.guilds_by_broadcaster[account.user_id].discard(guild_id)
        self.reflections.pop(guild_id, None)
        self.store.remove_setting(str(guild_id), "kick_authorization")

    async def close(self) -> None:
        if self.start_task:
            self.start_task.cancel()
            await asyncio.gather(self.start_task, return_exceptions=True)
        if self.session and not self.session.closed:
            await self.session.close()
