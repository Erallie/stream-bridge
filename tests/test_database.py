import tempfile
import unittest
from pathlib import Path

from ninjabridge.database import ConfigStore, GuildConfig


class ConfigStoreTests(unittest.TestCase):
    def test_persists_independent_multi_channel_configuration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="ninja-bridge-") as directory:
            path = str(Path(directory) / "bot.sqlite")
            store = ConfigStore(path)
            store.set_session("guild-1", "session-one", ["twitch", "youtube"])
            store.add_channel("guild-1", "channel-1")
            store.add_channel("guild-1", "channel-2")
            store.set_session("guild-2", "session-two", [])
            store.close()

            store = ConfigStore(path)
            self.assertEqual(
                store.get("guild-1"),
                GuildConfig("guild-1", ("channel-1", "channel-2"), "session-one", ("twitch", "youtube")),
            )
            self.assertEqual(store.get("guild-2").session_id, "session-two")
            store.link_identity("guild-1", "youtube", "UC123", "Erallie", "https://example/avatar.png", True)
            identity = store.resolve_identity("guild-1", "youtube", "UC123", "fallback")
            self.assertEqual(identity["display_name"], "Erallie")
            self.assertEqual(identity["owner"], 1)
            event = store.claim_event("guild-1", "youtube", "message-1", "UC123", "Hello", 1)
            self.assertIsNotNone(event)
            self.assertIsNone(store.claim_event("guild-1", "youtube", "message-1", "UC123", "Hello", 1))
            self.assertTrue(store.claim_delivery("guild-1", event, "discord"))
            self.assertFalse(store.claim_delivery("guild-1", event, "discord"))
            store.close()


if __name__ == "__main__":
    unittest.main()
