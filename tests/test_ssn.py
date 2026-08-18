import asyncio
import json
import logging
import unittest

from ninjabridge.ssn import SsnClient


class SsnClientTests(unittest.TestCase):
    def make_client(self, on_status=None) -> SsnClient:
        logger = logging.LoggerAdapter(logging.getLogger("test.ssn"), {})
        return SsnClient("wss://example.invalid", "session", (), logger, on_status=on_status)

    def test_probe_response_requires_the_matching_callback_token(self) -> None:
        client = self.make_client()

        self.assertTrue(client._is_probe_response(json.dumps({"callback": {"get": "expected", "result": False}}), "expected"))
        self.assertFalse(client._is_probe_response(json.dumps({"callback": {"get": "other", "result": True}}), "expected"))
        self.assertFalse(client._is_probe_response("not json", "expected"))

    def test_default_api_url_uses_ssn_api_endpoint(self) -> None:
        self.assertEqual(SsnClient._default_api_url("wss://io.socialstream.ninja"), "wss://io.socialstream.ninja/api")
        self.assertEqual(SsnClient._default_api_url("wss://example.test/custom"), "wss://example.test/custom")

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
