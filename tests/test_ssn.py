import asyncio
import logging
import unittest

from streambridge.ssn import SsnClient


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

    def test_transient_probe_failures_do_not_disconnect_ssn(self) -> None:
        changes: list[bool] = []

        async def status(connected: bool) -> None:
            changes.append(connected)

        async def exercise() -> None:
            client = self.make_client(status)
            failures = await client._record_probe_result(True, 0, 3)
            failures = await client._record_probe_result(False, failures, 3)
            failures = await client._record_probe_result(False, failures, 3)
            self.assertTrue(client.connected)
            self.assertEqual(changes, [True])

            failures = await client._record_probe_result(False, failures, 3)
            self.assertFalse(client.connected)
            self.assertEqual(changes, [True, False])

            failures = await client._record_probe_result(True, failures, 3)
            self.assertEqual(failures, 0)
            self.assertTrue(client.connected)
            self.assertEqual(changes, [True, False, True])

        asyncio.run(exercise())
