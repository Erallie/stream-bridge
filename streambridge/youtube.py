from __future__ import annotations

import logging
import os
import secrets
import time
import urllib.parse
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web
from cryptography.fernet import Fernet, InvalidToken

from streambridge.database import ConfigStore
from streambridge.oauth import OAuthToken

AuthorizedHandler = Callable[[int, str], Awaitable[None]]


@dataclass
class PendingAuthorization:
    guild_id: int
    expires_at: float


class YouTubeAccount:
    def __init__(self, gateway: "YouTubeGateway", guild_id: int, channel_id: str, title: str, refresh_token: str) -> None:
        self.gateway = gateway
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.title = title
        self.token = OAuthToken(
            "YOUTUBE",
            "https://oauth2.googleapis.com/token",
            refresh_token=refresh_token,
            client_id=gateway.client_id,
            client_secret=gateway.client_secret,
            on_refresh=self.save_rotated_token,
        )

    def save_rotated_token(self, refresh_token: str) -> None:
        self.gateway.save_account(self.guild_id, self.channel_id, self.title, refresh_token)


class YouTubeGateway:
    """Per-Discord-server YouTube OAuth accounts sharing one callback route."""

    def __init__(self, store: ConfigStore, on_authorized: AuthorizedHandler) -> None:
        self.store = store
        self.on_authorized = on_authorized
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
        self.redirect_uri = os.getenv("YOUTUBE_OAUTH_REDIRECT_URI", "")
        key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
        try:
            self.fernet = Fernet(key.encode("ascii")) if key else None
        except (ValueError, TypeError):
            logging.error("TOKEN_ENCRYPTION_KEY is not a valid Fernet key")
            self.fernet = None
        self.accounts: dict[int, YouTubeAccount] = {}
        self.pending: dict[str, PendingAuthorization] = {}
        self.session: aiohttp.ClientSession | None = None

    def load_accounts(self) -> None:
        if not self.fernet:
            return
        for guild_text in self.store.guild_ids():
            saved = self.store.get_setting(guild_text, "youtube_authorization", {})
            if not isinstance(saved, dict) or not saved.get("refresh_token"):
                continue
            try:
                refresh = self.fernet.decrypt(str(saved["refresh_token"]).encode("ascii")).decode("utf-8")
                self.register_account(int(guild_text), str(saved["channel_id"]), str(saved.get("title", "YouTube channel")), refresh)
            except (InvalidToken, KeyError, ValueError, UnicodeError):
                logging.error("Could not decrypt YouTube authorization for Discord guild %s", guild_text)

    def register_account(self, guild_id: int, channel_id: str, title: str, refresh_token: str) -> None:
        self.accounts[guild_id] = YouTubeAccount(self, guild_id, channel_id, title, refresh_token)

    def save_account(self, guild_id: int, channel_id: str, title: str, refresh_token: str) -> None:
        if not self.fernet:
            raise RuntimeError("Token encryption is not configured")
        encrypted = self.fernet.encrypt(refresh_token.encode()).decode("ascii")
        if isinstance(guild_id, str) and guild_id.startswith("workspace:"):
            self.store.update_dashboard_refresh_token("google", channel_id, encrypted)
            return
        self.store.set_setting(str(guild_id), "youtube_authorization", {
            "channel_id": channel_id,
            "title": title,
            "refresh_token": encrypted,
        })

    def authorization_url(self, guild_id: int, listener_ready: bool) -> str:
        if not (self.client_id and self.client_secret and self.redirect_uri and self.fernet):
            raise RuntimeError("YouTube authorization has not been configured by the StreamBridge owner.")
        if not listener_ready:
            raise RuntimeError("The authorization receiver is still starting. Try again in a moment.")
        now = time.monotonic()
        self.pending = {key: value for key, value in self.pending.items() if value.expires_at >= now}
        state = secrets.token_urlsafe(32)
        self.pending[state] = PendingAuthorization(guild_id, now + 600)
        query = urllib.parse.urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/youtube.force-ssl",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    async def get_session(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    async def oauth_callback(self, request: web.Request) -> web.Response:
        pending = self.pending.pop(request.query.get("state", ""), None)
        if not pending or pending.expires_at < time.monotonic():
            return web.Response(status=400, text="This StreamBridge YouTube authorization link is invalid or expired.")
        if request.query.get("error"):
            return web.Response(status=400, text=f"YouTube authorization was declined: {request.query['error']}")
        code = request.query.get("code", "")
        if not code:
            return web.Response(status=400, text="Google did not provide an authorization code.")
        try:
            session = await self.get_session()
            async with session.post("https://oauth2.googleapis.com/token", data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.redirect_uri,
            }) as response:
                body = await response.json(content_type=None)
                if response.status >= 400 or not body.get("refresh_token"):
                    raise RuntimeError(f"YouTube token exchange failed: HTTP {response.status}")
            access_token = str(body["access_token"])
            async with session.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id,snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"},
            ) as response:
                channel_body = await response.json(content_type=None)
                items = channel_body.get("items", [])
                if response.status >= 400 or not items:
                    raise RuntimeError(f"YouTube channel lookup failed: HTTP {response.status}")
            channel_id = str(items[0]["id"])
            title = str(items[0].get("snippet", {}).get("title", "YouTube channel"))
            refresh_token = str(body["refresh_token"])
            self.save_account(pending.guild_id, channel_id, title, refresh_token)
            self.register_account(pending.guild_id, channel_id, title, refresh_token)
            await self.on_authorized(pending.guild_id, title)
        except Exception:
            logging.exception("YouTube OAuth callback failed for guild %s", pending.guild_id)
            return web.Response(status=500, text="StreamBridge could not finish YouTube authorization. Check its logs.")
        return web.Response(text=f"YouTube channel {title} is now connected to StreamBridge. You may close this tab.")

    def token(self, guild_id: int) -> OAuthToken | None:
        account = self.accounts.get(guild_id)
        return account.token if account else None

    def connected(self, guild_id: int) -> bool:
        return guild_id in self.accounts

    def username(self, guild_id: int) -> str:
        account = self.accounts.get(guild_id)
        return account.title if account else ""

    async def disable(self, guild_id: int) -> None:
        self.accounts.pop(guild_id, None)
        self.store.remove_setting(str(guild_id), "youtube_authorization")

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
