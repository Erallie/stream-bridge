from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
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
            CREATE TABLE IF NOT EXISTS dashboard_users(
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboard_identities(
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
                display_name TEXT NOT NULL,
                avatar_url TEXT NOT NULL DEFAULT '',
                access_token TEXT NOT NULL DEFAULT '',
                refresh_token TEXT NOT NULL DEFAULT '',
                scopes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(provider, provider_user_id)
            );
            CREATE TABLE IF NOT EXISTS dashboard_sessions(
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS dashboard_oauth_states(
                state TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                mode TEXT NOT NULL,
                user_id TEXT,
                verifier TEXT NOT NULL DEFAULT '',
                return_to TEXT NOT NULL,
                expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bridge_workspaces(
                id TEXT PRIMARY KEY,
                owner_user_id TEXT NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
                discord_guild_id TEXT,
                ssn_session_id TEXT,
                ssn_targets TEXT NOT NULL DEFAULT '',
                relay_template TEXT NOT NULL DEFAULT '{name}: {message} (from {platform})',
                transport_announcements INTEGER NOT NULL DEFAULT 1,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS workspace_connections(
                workspace_id TEXT NOT NULL REFERENCES bridge_workspaces(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                provider_user_id TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                settings TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY(workspace_id, provider)
            );
            CREATE INDEX IF NOT EXISTS dashboard_identities_user ON dashboard_identities(user_id);
            CREATE INDEX IF NOT EXISTS dashboard_sessions_user ON dashboard_sessions(user_id);
            CREATE INDEX IF NOT EXISTS bridge_workspaces_owner ON bridge_workspaces(owner_user_id);
        """)
        self.connection.commit()
        self._migrate_schema()

    def _columns(self, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in self.connection.execute(f"PRAGMA table_info({table})")
        }

    def _migrate_schema(self) -> None:
        """Remove obsolete columns while preserving all active configuration."""
        guild_columns = self._columns("guild_config")
        workspace_columns = self._columns("bridge_workspaces")
        migrate_guilds = "channel_id" in guild_columns
        migrate_workspaces = bool({"name", "ssn_password"} & workspace_columns)
        if not migrate_guilds and not migrate_workspaces:
            return

        self.connection.execute("PRAGMA foreign_keys=OFF")
        try:
            with self.connection:
                if migrate_guilds:
                    self.connection.execute(
                        "INSERT OR IGNORE INTO guild_channels "
                        "SELECT guild_id, channel_id, updated_at FROM guild_config "
                        "WHERE channel_id IS NOT NULL"
                    )
                    self.connection.execute("DROP TABLE IF EXISTS guild_config_migrated")
                    self.connection.execute(
                        """CREATE TABLE guild_config_migrated(
                               guild_id TEXT PRIMARY KEY,
                               ssn_session_id TEXT,
                               relay_targets TEXT NOT NULL DEFAULT '',
                               updated_at TEXT NOT NULL
                           )"""
                    )
                    self.connection.execute(
                        "INSERT INTO guild_config_migrated "
                        "SELECT guild_id, ssn_session_id, relay_targets, updated_at FROM guild_config"
                    )
                    self.connection.execute("DROP TABLE guild_config")
                    self.connection.execute(
                        "ALTER TABLE guild_config_migrated RENAME TO guild_config"
                    )

                if migrate_workspaces:
                    self.connection.execute("DROP TABLE IF EXISTS bridge_workspaces_migrated")
                    self.connection.execute(
                        """CREATE TABLE bridge_workspaces_migrated(
                               id TEXT PRIMARY KEY,
                               owner_user_id TEXT NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
                               discord_guild_id TEXT,
                               ssn_session_id TEXT,
                               ssn_targets TEXT NOT NULL DEFAULT '',
                               relay_template TEXT NOT NULL DEFAULT '{name}: {message} (from {platform})',
                               transport_announcements INTEGER NOT NULL DEFAULT 1,
                               enabled INTEGER NOT NULL DEFAULT 1,
                               created_at TEXT NOT NULL,
                               updated_at TEXT NOT NULL
                           )"""
                    )
                    self.connection.execute(
                        """INSERT INTO bridge_workspaces_migrated
                               (id, owner_user_id, discord_guild_id, ssn_session_id,
                                ssn_targets, relay_template, transport_announcements,
                                enabled, created_at, updated_at)
                           SELECT id, owner_user_id, discord_guild_id, ssn_session_id,
                                  ssn_targets, relay_template, transport_announcements,
                                  enabled, created_at, updated_at
                           FROM bridge_workspaces"""
                    )
                    self.connection.execute("DROP TABLE bridge_workspaces")
                    self.connection.execute(
                        "ALTER TABLE bridge_workspaces_migrated RENAME TO bridge_workspaces"
                    )
                    self.connection.execute(
                        "CREATE INDEX IF NOT EXISTS bridge_workspaces_owner "
                        "ON bridge_workspaces(owner_user_id)"
                    )
        finally:
            self.connection.execute("PRAGMA foreign_keys=ON")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """Commit a group of configuration changes together or roll them all back."""
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self.connection.rollback()
            raise
        else:
            self.connection.commit()

    def _ensure(self, guild_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO guild_config "
            "(guild_id, ssn_session_id, relay_targets, updated_at) VALUES(?, NULL, '', ?)",
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

    def set_session(
        self,
        guild_id: str,
        session_id: str,
        targets: list[str],
        *,
        commit: bool = True,
    ) -> None:
        self._ensure(guild_id)
        self.connection.execute(
            "UPDATE guild_config SET ssn_session_id=?, relay_targets=?, updated_at=? WHERE guild_id=?",
            (session_id, ",".join(targets), now(), guild_id),
        )
        if commit:
            self.connection.commit()

    def clear_session(self, guild_id: str, *, commit: bool = True) -> None:
        self.connection.execute(
            "UPDATE guild_config SET ssn_session_id=NULL, relay_targets='', updated_at=? WHERE guild_id=?",
            (now(), guild_id),
        )
        if commit:
            self.connection.commit()

    def add_channel(self, guild_id: str, channel_id: str, *, commit: bool = True) -> bool:
        self._ensure(guild_id)
        result = self.connection.execute(
            "INSERT OR IGNORE INTO guild_channels VALUES(?, ?, ?)",
            (guild_id, channel_id, now()),
        )
        if commit:
            self.connection.commit()
        return result.rowcount > 0

    def clear_channels(self, guild_id: str, *, commit: bool = True) -> int:
        result = self.connection.execute("DELETE FROM guild_channels WHERE guild_id=?", (guild_id,))
        if commit:
            self.connection.commit()
        return result.rowcount

    def set_setting(
        self,
        guild_id: str,
        key: str,
        value: Any,
        *,
        commit: bool = True,
    ) -> None:
        self._ensure(guild_id)
        self.connection.execute(
            "INSERT INTO guild_settings VALUES(?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, json.dumps(value)),
        )
        if commit:
            self.connection.commit()

    def set_settings(
        self,
        guild_id: str,
        values: dict[str, Any],
        *,
        commit: bool = True,
    ) -> None:
        self._ensure(guild_id)
        self.connection.executemany(
            "INSERT INTO guild_settings VALUES(?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (
                (guild_id, key, json.dumps(value))
                for key, value in values.items()
            ),
        )
        if commit:
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

    def dashboard_user_for_identity(self, provider: str, provider_user_id: str) -> str | None:
        row = self.connection.execute(
            "SELECT user_id FROM dashboard_identities WHERE provider=? AND provider_user_id=?",
            (provider, provider_user_id),
        ).fetchone()
        return str(row[0]) if row else None

    def create_dashboard_user(self) -> str:
        user_id = str(uuid.uuid4())
        stamp = now()
        self.connection.execute("INSERT INTO dashboard_users VALUES(?, ?, ?)", (user_id, stamp, stamp))
        self.connection.commit()
        return user_id

    def save_dashboard_identity(self, user_id: str, identity: dict[str, Any]) -> None:
        provider = str(identity["provider"])
        provider_user_id = str(identity["provider_user_id"])
        existing = self.dashboard_user_for_identity(provider, provider_user_id)
        if existing and existing != user_id:
            raise ValueError("That account is already linked to another StreamBridge account")
        stamp = now()
        self.connection.execute(
            """INSERT INTO dashboard_identities
               (provider, provider_user_id, user_id, display_name, avatar_url, access_token,
                refresh_token, scopes, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(provider, provider_user_id) DO UPDATE SET
                   display_name=excluded.display_name, avatar_url=excluded.avatar_url,
                   access_token=excluded.access_token,
                   refresh_token=CASE WHEN excluded.refresh_token='' THEN dashboard_identities.refresh_token ELSE excluded.refresh_token END,
                   scopes=excluded.scopes, updated_at=excluded.updated_at""",
            (provider, provider_user_id, user_id, str(identity.get("display_name", "")),
             str(identity.get("avatar_url", "")), str(identity.get("access_token", "")),
             str(identity.get("refresh_token", "")), str(identity.get("scopes", "")), stamp, stamp),
        )
        self.connection.execute("UPDATE dashboard_users SET updated_at=? WHERE id=?", (stamp, user_id))
        self.connection.commit()

    def dashboard_identities(self, user_id: str, include_tokens: bool = False) -> list[dict[str, Any]]:
        columns = "*" if include_tokens else "provider, provider_user_id, display_name, avatar_url, scopes, updated_at"
        return [dict(row) for row in self.connection.execute(
            f"SELECT {columns} FROM dashboard_identities WHERE user_id=? ORDER BY provider", (user_id,)
        )]

    def unlink_dashboard_identity(self, user_id: str, provider: str) -> list[str]:
        """Remove a linked identity and relay assignments that depend on it.

        The caller must wrap this operation in ``transaction()``.
        """
        identity = self.connection.execute(
            "SELECT provider_user_id FROM dashboard_identities WHERE user_id=? AND provider=?",
            (user_id, provider),
        ).fetchone()
        if not identity:
            return []
        identity_count = self.connection.execute(
            "SELECT COUNT(*) FROM dashboard_identities WHERE user_id=?",
            (user_id,),
        ).fetchone()[0]
        if identity_count <= 1:
            raise ValueError(
                "Link another account before disconnecting your only sign-in method"
            )

        workspace_rows = self.connection.execute(
            "SELECT id, discord_guild_id FROM bridge_workspaces WHERE owner_user_id=?",
            (user_id,),
        ).fetchall()
        affected_workspace_ids: set[str] = set()

        if provider == "discord":
            for workspace in workspace_rows:
                guild_id = str(workspace["discord_guild_id"] or "")
                if not guild_id:
                    continue
                self.set_setting(guild_id, "discord_enabled", False, commit=False)
                affected_workspace_ids.add(str(workspace["id"]))
        else:
            connection_provider = "youtube" if provider == "google" else provider
            matching_rows = self.connection.execute(
                """SELECT workspace_id FROM workspace_connections
                   WHERE workspace_id IN (
                       SELECT id FROM bridge_workspaces WHERE owner_user_id=?
                   ) AND provider=? AND provider_user_id=?""",
                (user_id, connection_provider, str(identity["provider_user_id"])),
            ).fetchall()
            affected_workspace_ids.update(str(row["workspace_id"]) for row in matching_rows)
            self.connection.execute(
                """DELETE FROM workspace_connections
                   WHERE workspace_id IN (
                       SELECT id FROM bridge_workspaces WHERE owner_user_id=?
                   ) AND provider=? AND provider_user_id=?""",
                (user_id, connection_provider, str(identity["provider_user_id"])),
            )

        self.connection.execute(
            "DELETE FROM dashboard_identities WHERE user_id=? AND provider=? AND provider_user_id=?",
            (user_id, provider, str(identity["provider_user_id"])),
        )
        self.connection.execute(
            "UPDATE dashboard_users SET updated_at=? WHERE id=?",
            (now(), user_id),
        )
        return sorted(affected_workspace_ids)

    def update_dashboard_refresh_token(self, provider: str, provider_user_id: str, encrypted_token: str) -> None:
        self.connection.execute(
            "UPDATE dashboard_identities SET refresh_token=?, updated_at=? WHERE provider=? AND provider_user_id=?",
            (encrypted_token, now(), provider, provider_user_id),
        )
        self.connection.commit()

    def update_dashboard_tokens(
        self,
        provider: str,
        provider_user_id: str,
        encrypted_access_token: str,
        encrypted_refresh_token: str = "",
    ) -> None:
        self.connection.execute(
            """UPDATE dashboard_identities SET access_token=?,
               refresh_token=CASE WHEN ?='' THEN refresh_token ELSE ? END,
               updated_at=? WHERE provider=? AND provider_user_id=?""",
            (
                encrypted_access_token,
                encrypted_refresh_token,
                encrypted_refresh_token,
                now(),
                provider,
                provider_user_id,
            ),
        )
        self.connection.commit()

    def save_dashboard_session(self, token_hash: str, user_id: str, expires_at: str) -> None:
        self.connection.execute("INSERT INTO dashboard_sessions VALUES(?, ?, ?, ?)", (token_hash, user_id, expires_at, now()))
        self.connection.commit()

    def dashboard_session_user(self, token_hash: str) -> str | None:
        self.connection.execute("DELETE FROM dashboard_sessions WHERE expires_at < ?", (now(),))
        row = self.connection.execute(
            "SELECT user_id FROM dashboard_sessions WHERE token_hash=? AND expires_at>=?", (token_hash, now())
        ).fetchone()
        self.connection.commit()
        return str(row[0]) if row else None

    def delete_dashboard_session(self, token_hash: str) -> None:
        self.connection.execute("DELETE FROM dashboard_sessions WHERE token_hash=?", (token_hash,))
        self.connection.commit()

    def save_oauth_state(self, state: str, provider: str, mode: str, user_id: str | None,
                         verifier: str, return_to: str, expires_at: str) -> None:
        self.connection.execute("INSERT INTO dashboard_oauth_states VALUES(?, ?, ?, ?, ?, ?, ?)",
                                (state, provider, mode, user_id, verifier, return_to, expires_at))
        self.connection.commit()

    def pop_oauth_state(self, state: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM dashboard_oauth_states WHERE state=? AND expires_at>=?", (state, now())
        ).fetchone()
        self.connection.execute("DELETE FROM dashboard_oauth_states WHERE state=? OR expires_at<?", (state, now()))
        self.connection.commit()
        return dict(row) if row else None

    def workspaces(self, user_id: str | None = None) -> list[dict[str, Any]]:
        query = "SELECT * FROM bridge_workspaces"
        parameters: tuple[Any, ...] = ()
        if user_id:
            query += " WHERE owner_user_id=?"
            parameters = (user_id,)
        query += " ORDER BY created_at"
        result: list[dict[str, Any]] = []
        for row in self.connection.execute(query, parameters):
            item = dict(row)
            item["ssn_targets"] = list(filter(None, str(item["ssn_targets"]).split(",")))
            item["transport_announcements"] = bool(item["transport_announcements"])
            item["enabled"] = bool(item["enabled"])
            item["connections"] = [dict(connection) for connection in self.connection.execute(
                "SELECT provider, provider_user_id, enabled, settings FROM workspace_connections WHERE workspace_id=?",
                (item["id"],),
            )]
            for connection in item["connections"]:
                connection["enabled"] = bool(connection["enabled"])
                connection["settings"] = json.loads(connection["settings"])
            result.append(item)
        return result

    def save_workspace(
        self,
        user_id: str,
        data: dict[str, Any],
        workspace_id: str | None = None,
        *,
        commit: bool = True,
    ) -> str:
        if workspace_id is None:
            existing_workspace = self.connection.execute(
                "SELECT id FROM bridge_workspaces WHERE owner_user_id=? LIMIT 1",
                (user_id,),
            ).fetchone()
            if existing_workspace:
                raise ValueError("This account already has a bridge")
        workspace_id = workspace_id or str(uuid.uuid4())
        existing = self.connection.execute("SELECT owner_user_id, created_at FROM bridge_workspaces WHERE id=?", (workspace_id,)).fetchone()
        if existing and existing["owner_user_id"] != user_id:
            raise PermissionError("Workspace does not belong to this account")
        discord_guild_id = data.get("discord_guild_id") or None
        if discord_guild_id:
            conflict = self.connection.execute(
                "SELECT id FROM bridge_workspaces WHERE discord_guild_id=? AND id<>?",
                (str(discord_guild_id), workspace_id),
            ).fetchone()
            if conflict:
                raise ValueError("That Discord server is already assigned to another bridge")
        stamp = now()
        created = str(existing["created_at"]) if existing else stamp
        targets = ",".join(dict.fromkeys(str(value).lower() for value in data.get("ssn_targets", []) if value))
        self.connection.execute(
            """INSERT INTO bridge_workspaces
               (id, owner_user_id, discord_guild_id, ssn_session_id, ssn_targets,
                relay_template, transport_announcements, enabled, created_at, updated_at)
               VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET discord_guild_id=excluded.discord_guild_id,
               ssn_session_id=excluded.ssn_session_id,
               ssn_targets=excluded.ssn_targets, relay_template=excluded.relay_template,
               transport_announcements=excluded.transport_announcements, enabled=excluded.enabled,
               updated_at=excluded.updated_at""",
            (workspace_id, user_id, discord_guild_id,
             data.get("ssn_session_id") or None, targets,
             str(data.get("relay_template", "{name}: {message} (from {platform})")),
             int(bool(data.get("transport_announcements", True))), int(bool(data.get("enabled", True))), created, stamp),
        )
        if commit:
            self.connection.commit()
        return workspace_id

    def update_workspace_ssn_for_guild(self, guild_id: str, session_id: str | None,
                                       targets: list[str] | tuple[str, ...]) -> None:
        self.connection.execute(
            "UPDATE bridge_workspaces SET ssn_session_id=?, ssn_targets=?, updated_at=? WHERE discord_guild_id=?",
            (session_id, ",".join(targets), now(), guild_id),
        )
        self.connection.commit()

    def update_workspace_announcements_for_guild(self, guild_id: str, enabled: bool) -> None:
        self.connection.execute(
            "UPDATE bridge_workspaces SET transport_announcements=?, updated_at=? WHERE discord_guild_id=?",
            (int(enabled), now(), guild_id),
        )
        self.connection.commit()

    def set_workspace_connection(
        self,
        user_id: str,
        workspace_id: str,
        provider: str,
        provider_user_id: str,
        enabled: bool,
        settings: dict[str, Any],
        *,
        commit: bool = True,
    ) -> None:
        owned = self.connection.execute("SELECT 1 FROM bridge_workspaces WHERE id=? AND owner_user_id=?", (workspace_id, user_id)).fetchone()
        identity_provider = "google" if provider == "youtube" else provider
        linked = self.connection.execute(
            "SELECT 1 FROM dashboard_identities WHERE user_id=? AND provider=? AND provider_user_id=?",
            (user_id, identity_provider, provider_user_id),
        ).fetchone()
        if not owned or not linked:
            raise PermissionError("Workspace or linked account is unavailable")
        self.connection.execute(
            """INSERT INTO workspace_connections VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(workspace_id, provider) DO UPDATE SET
               provider_user_id=excluded.provider_user_id, enabled=excluded.enabled, settings=excluded.settings""",
            (workspace_id, provider, provider_user_id, int(enabled), json.dumps(settings)),
        )
        if commit:
            self.connection.commit()

    def set_workspace_connection_enabled(
        self,
        workspace_id: str,
        provider: str,
        enabled: bool,
        *,
        commit: bool = True,
    ) -> bool:
        result = self.connection.execute(
            "UPDATE workspace_connections SET enabled=? WHERE workspace_id=? AND provider=?",
            (int(enabled), workspace_id, provider),
        )
        if commit:
            self.connection.commit()
        return result.rowcount > 0
