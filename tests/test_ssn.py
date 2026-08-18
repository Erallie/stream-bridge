import asyncio
import logging
import unittest

from ninjabridge.ssn import SsnClient


class SsnClientTests(unittest.TestCase):
    def make_client(self, on_status=None) -> SsnClient:
        logger = logging.LoggerAdapter(logging.getLogger("test.ssn"), {})
        return SsnClient("wss://example.invalid", "session", (), logger, on_status=on_status)

    def test_default_http_api_url_uses_the_session(self) -> None:
        self.assertEqual(
            SsnClient._default_http_api_url("wss://io.socialstream.ninja", "my session"),
            "https://io.socialstream.ninja/my%20session",
        )

    def test_status_handler_runs_only_when_transport_changes(self) -> None:
        changes: list[bool] = []

        async def status(connected: bool) -> None:
            changes.append(connected)

        async def exercise() -> None:
            client = self.make_client(status)
            await client._set_connected(True)
            await client._set_connected(True)
            await client._set_connected(False)
            await client._set_connected(False)

        asyncio.run(exercise())
        self.assertEqual(changes, [True, False])
