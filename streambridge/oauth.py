from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import aiohttp


class OAuthToken:
    """A dashboard-owned OAuth token that refreshes itself without logging secrets."""

    def __init__(
        self,
        prefix: str,
        token_url: str,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        on_refresh: Callable[[str], None] | None = None,
    ) -> None:
        self.prefix = prefix
        self.token_url = token_url
        self.access_token = ""
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.on_refresh = on_refresh
        self.expires_at = 0.0
        self.lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.refresh_token and self.client_id and self.client_secret)

    async def get(self, force_refresh: bool = False) -> str:
        if self.access_token and not force_refresh and time.time() < self.expires_at - 120:
            return self.access_token
        if not self.configured:
            raise RuntimeError(f"{self.prefix} OAuth credentials are not configured")
        async with self.lock:
            if self.access_token and not force_refresh and time.time() < self.expires_at - 120:
                return self.access_token
            form = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
            }
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(self.token_url, data=form) as response:
                    body = await response.json(content_type=None)
                    if response.status >= 400:
                        raise RuntimeError(f"{self.prefix} token refresh failed (HTTP {response.status})")
            self.access_token = str(body["access_token"])
            rotated = str(body.get("refresh_token", ""))
            if rotated and rotated != self.refresh_token:
                self.refresh_token = rotated
                if not self.on_refresh:
                    raise RuntimeError(f"{self.prefix} returned a rotated token without a persistence handler")
                self.on_refresh(rotated)
                logging.info("Persisted rotated %s refresh token", self.prefix)
            self.expires_at = time.time() + int(body.get("expires_in", 3600))
            logging.info("Refreshed %s access token", self.prefix)
            return self.access_token
