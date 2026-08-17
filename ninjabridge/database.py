from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GuildConfig:
    guild_id: str
    channel_ids: tuple[str, ...]
    session_id: str | None
    relay_targets: tuple[str, ...]


class ConfigStore:
    def __init__(self, path: str) -> None:
        database_path = Path(path)
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode = WAL")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS guild_config (
                guild_id TEXT PRIMARY KEY,
                channel_id TEXT,
                ssn_session_id TEXT,
                relay_targets TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS guild_channels (
                guild_id TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (guild_id, channel_id)
            );
            INSERT OR IGNORE INTO guild_channels (guild_id, channel_id, created_at)
                SELECT guild_id, channel_id, updated_at
                FROM guild_config WHERE channel_id IS NOT NULL;
        """)
        self.connection.commit()

    def get(self, guild_id: str) -> GuildConfig | None:
        row = self.connection.execute(
            "SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)
        ).fetchone()
        if not row:
            return None
        channels = self.connection.execute(
            "SELECT channel_id FROM guild_channels WHERE guild_id = ? ORDER BY created_at, channel_id",
            (guild_id,),
        ).fetchall()
        return GuildConfig(
            guild_id=guild_id,
            channel_ids=tuple(item["channel_id"] for item in channels),
            session_id=row["ssn_session_id"],
            relay_targets=tuple(item for item in row["relay_targets"].split(",") if item),
        )

    def _ensure_guild(self, guild_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO guild_config VALUES (?, NULL, NULL, '', datetime('now'))",
            (guild_id,),
        )

    def set_session(self, guild_id: str, session_id: str, relay_targets: list[str]) -> None:
        self._ensure_guild(guild_id)
        self.connection.execute(
            "UPDATE guild_config SET ssn_session_id = ?, relay_targets = ?, updated_at = datetime('now') WHERE guild_id = ?",
            (session_id, ",".join(relay_targets), guild_id),
        )
        self.connection.commit()

    def add_channel(self, guild_id: str, channel_id: str) -> bool:
        self._ensure_guild(guild_id)
        cursor = self.connection.execute(
            "INSERT OR IGNORE INTO guild_channels VALUES (?, ?, datetime('now'))",
            (guild_id, channel_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def remove_channel(self, guild_id: str, channel_id: str) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM guild_channels WHERE guild_id = ? AND channel_id = ?",
            (guild_id, channel_id),
        )
        self.connection.commit()
        return cursor.rowcount > 0

    def clear_channels(self, guild_id: str) -> int:
        cursor = self.connection.execute("DELETE FROM guild_channels WHERE guild_id = ?", (guild_id,))
        self.connection.commit()
        return cursor.rowcount

    def clear_session(self, guild_id: str) -> None:
        self.connection.execute(
            "UPDATE guild_config SET ssn_session_id = NULL, relay_targets = '', updated_at = datetime('now') WHERE guild_id = ?",
            (guild_id,),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
