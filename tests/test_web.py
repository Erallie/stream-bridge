import os
from unittest.mock import patch

from streambridge.database import ConfigStore
from streambridge.kick import KickGateway
from streambridge.web import WebGateway


async def ignore_event(key: int | str, data: dict) -> None:
    return None


def test_only_dashboard_oauth_callbacks_are_registered(tmp_path) -> None:
    with patch.dict(os.environ, {}, clear=True):
        store = ConfigStore(str(tmp_path / "bot.sqlite"))
        gateway = WebGateway(KickGateway(store, ignore_event))
        routes = {(route.method, route.resource.canonical) for route in gateway.create_app().router.routes()}
        assert ("POST", "/kick/webhook") in routes
        assert ("GET", "/youtube/oauth/callback") not in routes
        assert ("GET", "/kick/oauth/callback") not in routes
