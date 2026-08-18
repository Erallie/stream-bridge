from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class GuildConfig:
    guild_id: str
    channel_ids: tuple[str, ...]
    session_id: str | None
    relay_targets: tuple[str, ...]
    discord_relay_channel_id: str | None = None


class ConfigStore:
    def __init__(self, path: str) -> None:
        database = Path(path)
        database.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database, timeout=10)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS guild_config(
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT,
                ssn_session_id TEXT,
                relay_targets TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_channels(
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, channel_id)
            );
            INSERT OR IGNORE INTO guild_channels
                SELECT guild_id, channel_id, updated_at FROM guild_config WHERE channel_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS guild_settings(
                guild_id TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                PRIMARY KEY(guild_id, key)
            );
            CREATE TABLE IF NOT EXISTS processed_events(
                guild_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                platform TEXT NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                fingerprint TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, event_key)
            );
            CREATE TABLE IF NOT EXISTS deliveries(
                guild_id TEXT NOT NULL,
                event_key TEXT NOT NULL,
                destination TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY(guild_id, event_key, destination)
            );
            CREATE INDEX IF NOT EXISTS processed_events_created_at ON processed_events(created_at);
            CREATE INDEX IF NOT EXISTS deliveries_created_at ON deliveries(created_at);
        """)
        self.connection.commit()

    def _ensure(self, guild_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO guild_config VALUES(?, NULL, NULL, '', ?)",
            (guild_id, now()),
        )

    def get(self, guild_id: str) -> GuildConfig | None:
        row = self.connection.execute("SELECT * FROM guild_config WHERE guild_id=?", (guild_id,)).fetchone()
        if not row:
            return None
        channels = tuple(
            item[0]
            for item in self.connection.execute(
                "SELECT channel_id FROM guild_channels WHERE guild_id=? ORDER BY created_at, channel_id",
                (guild_id,),
            )
        )
        return GuildConfig(
            guild_id,
            channels,
            row["ssn_session_id"],
            tuple(filter(None, row["relay_targets"].split(","))),
            self.get_setting(guild_id, "discord_relay_channel_id"),
        )

    def guild_ids(self) -> list[str]:
        return [row[0] for row in self.connection.execute("SELECT guild_id FROM guild_config")]

    def set_session(self, guild_id: str, session_id: str, targets: list[str]) -> None:
        self._ensure(guild_id)
        self.connection.execute(
            "UPDATE guild_config SET ssn_session_id=?, relay_targets=?, updated_at=? WHERE guild_id=?",
            (session_id, ",".join(targets), now(), guild_id),
        )
        self.connection.commit()

    def clear_session(self, guild_id: str) -> None:
        self.connection.execute(
            "UPDATE guild_config SET ssn_session_id=NULL, relay_targets='', updated_at=? WHERE guild_id=?",
            (now(), guild_id),
        )
        self.connection.commit()

    def add_channel(self, guild_id: str, channel_id: str) -> bool:
        self._ensure(guild_id)
        result = self.connection.execute(
            "INSERT OR IGNORE INTO guild_channels VALUES(?, ?, ?)",
            (guild_id, channel_id, now()),
        )
        self.connection.commit()
        return result.rowcount > 0

    def remove_channel(self, guild_id: str, channel_id: str) -> bool:
        result = self.connection.execute(
            "DELETE FROM guild_channels WHERE guild_id=? AND channel_id=?",
            (guild_id, channel_id),
        )
        self.connection.commit()
        return result.rowcount > 0

    def clear_channels(self, guild_id: str) -> int:
        result = self.connection.execute("DELETE FROM guild_channels WHERE guild_id=?", (guild_id,))
        self.connection.commit()
        return result.rowcount

    def set_setting(self, guild_id: str, key: str, value: Any) -> None:
        self._ensure(guild_id)
        self.connection.execute(
            "INSERT INTO guild_settings VALUES(?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, json.dumps(value)),
        )
        self.connection.commit()

    def get_setting(self, guild_id: str, key: str, default: Any = None) -> Any:
        row = self.connection.execute(
            "SELECT value FROM guild_settings WHERE guild_id=? AND key=?",
            (guild_id, key),
        ).fetchone()
        return json.loads(row[0]) if row else default

    @staticmethod
    def event_key(platform: str, message_id: str, user_id: str, text: str, timestamp: int | str) -> tuple[str, str]:
        normalized = " ".join(text.casefold().split())
        fingerprint = hashlib.sha256(f"{platform}|{user_id}|{normalized}".encode()).hexdigest()
        source = f"{platform}|{message_id}" if message_id else f"{fingerprint}|{str(timestamp)[:10]}"
        return hashlib.sha256(source.encode()).hexdigest(), fingerprint

    def claim_event(self, guild_id: str, platform: str, message_id: str, user_id: str, text: str, timestamp: int | str) -> str | None:
        key, fingerprint = self.event_key(platform, message_id, user_id, text, timestamp)
        result = self.connection.execute(
            "INSERT OR IGNORE INTO processed_events VALUES(?, ?, ?, ?, ?, ?)",
            (guild_id, key, platform, message_id, fingerprint, now()),
        )
        self.connection.commit()
        return key if result.rowcount else None

    def claim_delivery(self, guild_id: str, key: str, destination: str) -> bool:
        result = self.connection.execute(
            "INSERT OR IGNORE INTO deliveries VALUES(?, ?, ?, ?, ?)",
            (guild_id, key, destination, "sent", now()),
        )
        self.connection.commit()
        return result.rowcount > 0

    def prune_history(self, retention_days: int = 30) -> tuple[int, int]:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))).isoformat()
        deliveries = self.connection.execute("DELETE FROM deliveries WHERE created_at < ?", (cutoff,)).rowcount
        events = self.connection.execute("DELETE FROM processed_events WHERE created_at < ?", (cutoff,)).rowcount
        self.connection.commit()
        return events, deliveries

    def close(self) -> None:
        self.connection.close()
