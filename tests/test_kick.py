import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.kick import KickGateway


async def ignore_event(guild_id: int, data: dict) -> None:
    return


async def ignore_authorized(guild_id: int, username: str) -> None:
    return


class KickGatewayTests(unittest.TestCase):
    def test_authorizations_are_encrypted_and_isolated_by_guild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            key = Fernet.generate_key().decode("ascii")
            environment = {
                "KICK_CLIENT_ID": "client",
                "KICK_CLIENT_SECRET": "secret",
                "KICK_OAUTH_REDIRECT_URI": "https://example.com/kick/oauth/callback",
                "TOKEN_ENCRYPTION_KEY": key,
            }
            with patch.dict(os.environ, environment, clear=True):
                store = ConfigStore(str(Path(directory) / "bot.sqlite"))
                gateway = KickGateway(store, ignore_event, ignore_authorized)
                gateway.save_account(1, "111", "alice", "alice-refresh")
                gateway.save_account(2, "222", "bob", "bob-refresh")
                saved = store.get_setting("1", "kick_authorization")

                self.assertNotIn("alice-refresh", saved["refresh_token"])

                restored = KickGateway(store, ignore_event, ignore_authorized)
                restored.load_accounts()
                self.assertEqual(restored.accounts[1].user_id, "111")
                self.assertEqual(restored.accounts[1].token.refresh_token, "alice-refresh")
                self.assertEqual(restored.accounts[2].user_id, "222")
                store.close()

    def test_authorization_state_is_bound_to_one_guild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            environment = {
                "KICK_CLIENT_ID": "client",
                "KICK_CLIENT_SECRET": "secret",
                "KICK_OAUTH_REDIRECT_URI": "https://example.com/kick/oauth/callback",
                "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
            }
            with patch.dict(os.environ, environment, clear=True):
                store = ConfigStore(str(Path(directory) / "bot.sqlite"))
                gateway = KickGateway(store, ignore_event, ignore_authorized)
                gateway.listener_ready = True
                url = gateway.authorization_url(42, True)

                self.assertEqual(len(gateway.pending), 1)
                pending = next(iter(gateway.pending.values()))
                self.assertEqual(pending.guild_id, 42)
                self.assertIn("code_challenge_method=S256", url)
                store.close()


if __name__ == "__main__":
    unittest.main()
