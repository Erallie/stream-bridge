import os
from unittest.mock import patch

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.kick import KickGateway


async def ignore_event(key: int | str, data: dict) -> None:
    return None


def test_dashboard_kick_account_is_registered_by_runtime_key(tmp_path) -> None:
    environment = {
        "KICK_CLIENT_ID": "client",
        "KICK_CLIENT_SECRET": "secret",
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
    }
    with patch.dict(os.environ, environment, clear=True):
        store = ConfigStore(str(tmp_path / "bot.sqlite"))
        gateway = KickGateway(store, ignore_event)
        gateway.register_account(42, "kick-1", "Alice", "refresh")
        assert gateway.connected(42)
        assert gateway.username(42) == "Alice"
        gateway.unregister_account(42)
        assert not gateway.connected(42)
