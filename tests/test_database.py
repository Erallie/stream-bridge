import sqlite3
import tempfile
import unittest
from pathlib import Path

from streambridge.database import ConfigStore, GuildConfig


class ConfigStoreTests(unittest.TestCase):
    def test_transaction_rolls_back_every_related_setting(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            store = ConfigStore(str(Path(directory) / "bot.sqlite"))
            store.set_setting("guild-1", "discord_enabled", False)

            with self.assertRaises(RuntimeError):
                with store.transaction():
                    store.set_settings(
                        "guild-1",
                        {
                            "discord_enabled": True,
                            "discord_forward_enabled": True,
                        },
                        commit=False,
                    )
                    raise RuntimeError("cancel the save")

            self.assertFalse(store.get_setting("guild-1", "discord_enabled"))
            self.assertIsNone(store.get_setting("guild-1", "discord_forward_enabled"))
            store.close()

    def test_migrates_obsolete_columns_without_losing_configuration(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stream-bridge-") as directory:
            path = str(Path(directory) / "legacy.sqlite")
            legacy = sqlite3.connect(path)
            legacy.executescript(
                """
                CREATE TABLE guild_config(
                    guild_id TEXT PRIMARY KEY,
                    channel_id TEXT,
                    ssn_session_id TEXT,
                    relay_targets TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );
                INSERT INTO guild_config VALUES(
                    'guild-1', 'channel-1', 'session-1', 'twitch,kick',
                    '2026-01-01T00:00:00+00:00'
                );
                CREATE TABLE dashboard_users(
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO dashboard_users VALUES('user-1', 'created', 'updated');
                CREATE TABLE bridge_workspaces(
                    id TEXT PRIMARY KEY,
                    owner_user_id TEXT NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    discord_guild_id TEXT,
                    ssn_session_id TEXT,
                    ssn_password TEXT,
                    ssn_targets TEXT NOT NULL DEFAULT '',
                    relay_template TEXT NOT NULL,
                    transport_announcements INTEGER NOT NULL DEFAULT 1,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO bridge_workspaces VALUES(
                    'workspace-1', 'user-1', 'Old name', 'guild-1', 'session-1',
                    'unused-password', 'twitch,kick', '{message}', 1, 1,
                    'created', 'updated'
                );
                """
            )
            legacy.close()

            store = ConfigStore(path)
            self.assertNotIn("channel_id", store._columns("guild_config"))
            self.assertNotIn("name", store._columns("bridge_workspaces"))
            self.assertNotIn("ssn_password", store._columns("bridge_workspaces"))
            self.assertEqual(store.get("guild-1").channel_ids, ("channel-1",))
            workspace = store.workspaces("user-1")[0]
            self.assertEqual(workspace["ssn_targets"], ["twitch", "kick"])
            self.assertEqual(list(store.connection.execute("PRAGMA foreign_key_check")), [])
            store.close()

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
