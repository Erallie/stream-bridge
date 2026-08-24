import asyncio
import logging
import unittest

from streambridge.ssn import SsnClient


class SsnReloadTests(unittest.TestCase):
    def test_reload_baseline_suppresses_only_an_unchanged_connection(self) -> None:
        changes: list[bool] = []

        async def status(connected: bool) -> None:
            changes.append(connected)

        async def exercise() -> None:
            logger = logging.LoggerAdapter(logging.getLogger("test.ssn.reload"), {})
            still_connected = SsnClient(
                "wss://example.invalid",
                "session",
                (),
                logger,
                on_status=status,
                reported_connected=True,
            )
            await still_connected._set_connected(True)
            self.assertEqual(changes, [])

            disconnected_during_reload = SsnClient(
                "wss://example.invalid",
                "session",
                (),
                logger,
                on_status=status,
                reported_connected=True,
            )
            await disconnected_during_reload._set_connected(False)
            await disconnected_during_reload._set_connected(True)

        asyncio.run(exercise())
        self.assertEqual(changes, [False, True])
