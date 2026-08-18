import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.youtube import YouTubeGateway


async def ignore_authorized(guild_id: int, title: str) -> None:
    return


class YouTubeGatewayTests(unittest.TestCase):
    def test_authorizations_are_encrypted_and_isolated_by_guild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            environment = {
                "YOUTUBE_CLIENT_ID": "client",
                "YOUTUBE_CLIENT_SECRET": "secret",
                "YOUTUBE_OAUTH_REDIRECT_URI": "https://example.com/youtube/oauth/callback",
                "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
            }
            with patch.dict(os.environ, environment, clear=True):
                store = ConfigStore(str(Path(directory) / "bot.sqlite"))
                gateway = YouTubeGateway(store, ignore_authorized)
                gateway.save_account(1, "channel-1", "Alice", "alice-refresh")
                gateway.save_account(2, "channel-2", "Bob", "bob-refresh")
                saved = store.get_setting("1", "youtube_authorization")
                self.assertNotIn("alice-refresh", saved["refresh_token"])

                restored = YouTubeGateway(store, ignore_authorized)
                restored.load_accounts()
                self.assertEqual(restored.accounts[1].title, "Alice")
                self.assertEqual(restored.accounts[1].token.refresh_token, "alice-refresh")
                self.assertEqual(restored.accounts[2].channel_id, "channel-2")
                store.close()

    def test_authorization_state_is_bound_to_one_guild(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            environment = {
                "YOUTUBE_CLIENT_ID": "client",
                "YOUTUBE_CLIENT_SECRET": "secret",
                "YOUTUBE_OAUTH_REDIRECT_URI": "https://example.com/youtube/oauth/callback",
                "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode("ascii"),
            }
            with patch.dict(os.environ, environment, clear=True):
                store = ConfigStore(str(Path(directory) / "bot.sqlite"))
                gateway = YouTubeGateway(store, ignore_authorized)
                url = gateway.authorization_url(42, True)
                pending = next(iter(gateway.pending.values()))
                self.assertEqual(pending.guild_id, 42)
                self.assertIn("access_type=offline", url)
                store.close()


if __name__ == "__main__":
    unittest.main()
