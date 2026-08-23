import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from streambridge.database import ConfigStore
from streambridge.kick import KickGateway
from streambridge.web import WebGateway


async def ignore_event(key: int | str, data: dict) -> None:
    return None


class WebGatewayTests(unittest.TestCase):
    def test_only_dashboard_oauth_callbacks_are_registered(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {}, clear=True
        ):
            store = ConfigStore(str(Path(directory) / "bot.sqlite"))
            gateway = WebGateway(KickGateway(store, ignore_event))
            routes = {
                (route.method, route.resource.canonical)
                for route in gateway.create_app().router.routes()
            }
            self.assertIn(("POST", "/kick/webhook"), routes)
            self.assertNotIn(("GET", "/youtube/oauth/callback"), routes)
            self.assertNotIn(("GET", "/kick/oauth/callback"), routes)
            store.close()


if __name__ == "__main__":
    unittest.main()
