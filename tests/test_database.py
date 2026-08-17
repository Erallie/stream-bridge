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
            store.close()


if __name__ == "__main__":
    unittest.main()
