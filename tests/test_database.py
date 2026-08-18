import tempfile
import unittest
from pathlib import Path

from streambridge.database import ConfigStore, GuildConfig


class ConfigStoreTests(unittest.TestCase):
    def test_persists_independent_multi_channel_configuration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            path = str(Path(directory) / "bot.sqlite")
            store = ConfigStore(path)
            store.set_session("guild-1", "session-one", ["twitch", "youtube"])
            store.add_channel("guild-1", "channel-1")
            store.add_channel("guild-1", "channel-2")
            store.set_setting("guild-1", "discord_relay_channel_id", "channel-1")
            store.set_session("guild-2", "session-two", [])
            store.close()

            store = ConfigStore(path)
            self.assertEqual(
                store.get("guild-1"),
                GuildConfig("guild-1", ("channel-1", "channel-2"), "session-one", ("twitch", "youtube"), "channel-1"),
            )
            self.assertEqual(store.get("guild-2").session_id, "session-two")
            event = store.claim_event("guild-1", "youtube", "message-1", "UC123", "Hello", 1)
            self.assertIsNotNone(event)
            self.assertIsNone(store.claim_event("guild-1", "youtube", "message-1", "UC123", "Hello", 1))
            self.assertTrue(store.claim_delivery("guild-1", event, "discord"))
            self.assertFalse(store.claim_delivery("guild-1", event, "discord"))
            store.close()

    def test_prunes_old_event_and_delivery_history(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            store = ConfigStore(str(Path(directory) / "bot.sqlite"))
            event = store.claim_event("guild-1", "twitch", "old-message", "user", "Hello", 1)
            self.assertIsNotNone(event)
            self.assertTrue(store.claim_delivery("guild-1", event, "discord"))
            store.connection.execute("UPDATE processed_events SET created_at = '2000-01-01T00:00:00+00:00'")
            store.connection.execute("UPDATE deliveries SET created_at = '2000-01-01T00:00:00+00:00'")
            store.connection.commit()

            self.assertEqual(store.prune_history(30), (1, 1))
            self.assertIsNotNone(store.claim_event("guild-1", "twitch", "old-message", "user", "Hello", 1))
            store.close()


if __name__ == "__main__":
    unittest.main()
