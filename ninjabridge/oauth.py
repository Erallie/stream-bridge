from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from pathlib import Path

import aiohttp

_state_lock = threading.Lock()


def _oauth_state_path() -> Path:
    return Path(os.getenv("OAUTH_STATE_PATH", "./data/oauth_tokens.json"))


def _read_state() -> dict[str, dict[str, str]]:
    path = _oauth_state_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {key: value for key, value in data.items() if isinstance(key, str) and isinstance(value, dict)}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _persist_rotated_token(prefix: str, previous: str, current: str) -> None:
    path = _oauth_state_path()
    with _state_lock:
        state = _read_state()
        state[prefix] = {"refresh_token": current, "supersedes": previous}
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        try:
            temporary.chmod(0o600)
        except OSError:
            pass
        temporary.replace(path)


class OAuthToken:
    """An access token that refreshes itself without logging secrets."""

    def __init__(self, prefix: str, token_url: str) -> None:
        self.prefix = prefix
        self.token_url = token_url
        self.access_token = os.getenv(f"{prefix}_ACCESS_TOKEN", "").removeprefix("oauth:")
        configured_refresh = os.getenv(f"{prefix}_REFRESH_TOKEN", "")
        saved = _read_state().get(prefix, {})
        if configured_refresh and configured_refresh in {saved.get("supersedes"), saved.get("refresh_token")}:
            self.refresh_token = saved.get("refresh_token", configured_refresh)
        else:
            self.refresh_token = configured_refresh
        self.client_id = os.getenv(f"{prefix}_CLIENT_ID", "")
        self.client_secret = os.getenv(f"{prefix}_CLIENT_SECRET", "")
        self.expires_at = 0.0
        self.lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.access_token or (self.refresh_token and self.client_id and self.client_secret))

    async def get(self, force_refresh: bool = False) -> str:
        if self.access_token and not force_refresh and (not self.expires_at or time.time() < self.expires_at - 120):
            return self.access_token
        if not (self.refresh_token and self.client_id and self.client_secret):
            if self.access_token:
                return self.access_token
            raise RuntimeError(f"{self.prefix} OAuth credentials are not configured")
        async with self.lock:
            if self.access_token and not force_refresh and self.expires_at and time.time() < self.expires_at - 120:
                return self.access_token
            form = {"client_id": self.client_id, "client_secret": self.client_secret, "grant_type": "refresh_token", "refresh_token": self.refresh_token}
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(self.token_url, data=form) as response:
                    body = await response.json(content_type=None)
                    if response.status >= 400:
                        raise RuntimeError(f"{self.prefix} token refresh failed (HTTP {response.status})")
            self.access_token = str(body["access_token"])
            if body.get("refresh_token"):
                previous = self.refresh_token
                self.refresh_token = str(body["refresh_token"])
                if self.refresh_token != previous:
                    _persist_rotated_token(self.prefix, previous, self.refresh_token)
                    logging.info("Persisted rotated %s refresh token", self.prefix)
            self.expires_at = time.time() + int(body.get("expires_in", 3600))
            logging.info("Refreshed %s access token", self.prefix)
            return self.access_token
