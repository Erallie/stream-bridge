import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streambridge.oauth import OAuthToken, _persist_rotated_token


class OAuthStateTests(unittest.TestCase):
    def test_rotated_refresh_token_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            state_path = Path(directory) / "oauth.json"
            environment = {
                "OAUTH_STATE_PATH": str(state_path),
                "TWITCH_REFRESH_TOKEN": "original",
                "TWITCH_CLIENT_ID": "client",
                "TWITCH_CLIENT_SECRET": "secret",
            }
            with patch.dict(os.environ, environment, clear=True):
                _persist_rotated_token("TWITCH", "original", "rotated")
                token = OAuthToken("TWITCH", "https://example.invalid/token")

            self.assertEqual(token.refresh_token, "rotated")
            self.assertEqual(json.loads(state_path.read_text(encoding="utf-8"))["TWITCH"]["supersedes"], "original")

    def test_explicitly_changed_environment_token_wins(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            state_path = Path(directory) / "oauth.json"
            state_path.write_text('{"TWITCH":{"refresh_token":"rotated","supersedes":"old"}}', encoding="utf-8")
            with patch.dict(os.environ, {"OAUTH_STATE_PATH": str(state_path), "TWITCH_REFRESH_TOKEN": "new"}, clear=True):
                token = OAuthToken("TWITCH", "https://example.invalid/token")

            self.assertEqual(token.refresh_token, "new")

    def test_per_account_token_does_not_reuse_global_access_token(self) -> None:
        with patch.dict(os.environ, {"KICK_ACCESS_TOKEN": "wrong-account"}, clear=True):
            token = OAuthToken(
                "KICK",
                "https://id.kick.com/oauth/token",
                refresh_token="per-guild-refresh",
                client_id="client",
                client_secret="secret",
            )

        self.assertEqual(token.access_token, "")
        self.assertEqual(token.refresh_token, "per-guild-refresh")


if __name__ == "__main__":
    unittest.main()
