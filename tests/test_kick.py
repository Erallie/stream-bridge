import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.kick import KickGateway


async def ignore_event(key: int | str, data: dict) -> None:
    return None


class KickGatewayTests(unittest.TestCase):
    def test_dashboard_account_is_registered_by_runtime_key(self) -> None:
        environment = {
            "KICK_CLIENT_ID": "client",
            "KICK_CLIENT_SECRET": "secret",
            "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, environment, clear=True
        ):
            store = ConfigStore(str(Path(directory) / "bot.sqlite"))
            gateway = KickGateway(store, ignore_event)
            gateway.register_account(42, "kick-1", "Alice", "refresh")
            self.assertTrue(gateway.connected(42))
            self.assertEqual(gateway.username(42), "Alice")
            gateway.unregister_account(42)
            self.assertFalse(gateway.connected(42))
            store.close()

    def test_send_tracks_ssn_formatted_reflection_alias(self) -> None:
        class Account:
            async def send(self, text: str) -> None:
                return None

        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(str(Path(directory) / "bot.sqlite"))
            gateway = KickGateway(store, ignore_event)
            gateway.accounts[42] = Account()

            async def exercise() -> None:
                await gateway.send(
                    42,
                    "Alice: hello (from Discord)",
                    ("Alice said: hello",),
                )

            asyncio.run(exercise())
            self.assertTrue(gateway.reflections[42].consume("kick", "Alice said: hello"))
            store.close()


if __name__ == "__main__":
    unittest.main()
