from __future__ import annotations

import os
from typing import TypeAlias

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.oauth import OAuthToken

RuntimeKey: TypeAlias = int | str


class YouTubeAccount:
    def __init__(self, gateway: "YouTubeGateway", key: RuntimeKey, channel_id: str,
                 title: str, refresh_token: str) -> None:
        self.gateway = gateway
        self.key = key
        self.channel_id = channel_id
        self.title = title
        self.token = OAuthToken(
            "YOUTUBE", "https://oauth2.googleapis.com/token",
            refresh_token=refresh_token, client_id=gateway.client_id,
            client_secret=gateway.client_secret, on_refresh=self.save_rotated_token,
        )

    def save_rotated_token(self, refresh_token: str) -> None:
        encrypted = self.gateway.fernet.encrypt(refresh_token.encode()).decode()
        self.gateway.store.update_dashboard_refresh_token("google", self.channel_id, encrypted)


class YouTubeGateway:
    """Runtime YouTube accounts authorized exclusively through the dashboard."""

    def __init__(self, store: ConfigStore) -> None:
        self.store = store
        self.client_id = os.getenv("YOUTUBE_CLIENT_ID", "")
        self.client_secret = os.getenv("YOUTUBE_CLIENT_SECRET", "")
        key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
        self.fernet = Fernet(key.encode()) if key else None
        self.accounts: dict[RuntimeKey, YouTubeAccount] = {}

    def register_account(self, key: RuntimeKey, channel_id: str, title: str, refresh_token: str) -> None:
        if not self.fernet:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required")
        self.accounts[key] = YouTubeAccount(self, key, channel_id, title, refresh_token)

    def unregister_account(self, key: RuntimeKey) -> None:
        self.accounts.pop(key, None)

    def token(self, key: RuntimeKey) -> OAuthToken | None:
        account = self.accounts.get(key)
        return account.token if account else None

    def username(self, key: RuntimeKey) -> str:
        account = self.accounts.get(key)
        return account.title if account else ""
