import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streambridge.database import ConfigStore
from streambridge.kick import KickGateway
from streambridge.web import WebGateway
from streambridge.youtube import YouTubeGateway


async def ignore_event(guild_id: int, data: dict) -> None:
    return


async def ignore_authorized(guild_id: int, name: str) -> None:
    return


class WebGatewayTests(unittest.TestCase):
    def test_youtube_callback_exists_when_kick_is_not_configured(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            with patch.dict(os.environ, {}, clear=True):
                store = ConfigStore(str(Path(directory) / "bot.sqlite"))
                youtube = YouTubeGateway(store, ignore_authorized)
                kick = KickGateway(store, ignore_event, ignore_authorized)
                gateway = WebGateway(kick, youtube)
                routes = {(route.method, route.resource.canonical) for route in gateway.create_app().router.routes()}

                self.assertIn(("GET", "/youtube/oauth/callback"), routes)
                self.assertIn(("POST", "/kick/webhook"), routes)
                self.assertFalse(kick.client_id)
                store.close()


if __name__ == "__main__":
    unittest.main()
