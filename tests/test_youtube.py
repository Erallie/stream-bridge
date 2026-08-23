import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet

from streambridge.database import ConfigStore
from streambridge.youtube import YouTubeGateway


class YouTubeGatewayTests(unittest.TestCase):
    def test_dashboard_account_is_registered_by_runtime_key(self) -> None:
        environment = {
            "YOUTUBE_CLIENT_ID": "client",
            "YOUTUBE_CLIENT_SECRET": "secret",
            "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(),
        }
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, environment, clear=True
        ):
            store = ConfigStore(str(Path(directory) / "bot.sqlite"))
            gateway = YouTubeGateway(store)
            gateway.register_account("workspace:one", "google-1", "Alice", "refresh")
            self.assertEqual(gateway.username("workspace:one"), "Alice")
            gateway.unregister_account("workspace:one")
            self.assertEqual(gateway.username("workspace:one"), "")
            store.close()


if __name__ == "__main__":
    unittest.main()
