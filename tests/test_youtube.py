import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.youtube import YouTubeGateway


def test_dashboard_youtube_account_is_registered_by_runtime_key(tmp_path) -> None:
    environment = {
        "YOUTUBE_CLIENT_ID": "client",
        "YOUTUBE_CLIENT_SECRET": "secret",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    with patch.dict(os.environ, environment, clear=True):
        store = ConfigStore(str(tmp_path / "bot.sqlite"))
        gateway = YouTubeGateway(store)
        gateway.register_account("workspace:one", "google-1", "Alice", "refresh")
        assert gateway.connected("workspace:one")
        assert gateway.username("workspace:one") == "Alice"
        gateway.unregister_account("workspace:one")
        assert not gateway.connected("workspace:one")
