import { mkdirSync } from "node:fs";
import { dirname } from "node:path";
import Database from "better-sqlite3";

export class ConfigStore {
    constructor(path, logger) {
        mkdirSync(dirname(path), { recursive: true });
        this.db = new Database(path);
        this.db.pragma("journal_mode = WAL");
        this.db.exec(`CREATE TABLE IF NOT EXISTS guild_config (
            guild_id TEXT PRIMARY KEY, channel_id TEXT, ssn_session_id TEXT,
            relay_targets TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS guild_channels (
            guild_id TEXT NOT NULL, channel_id TEXT NOT NULL,
            created_at TEXT NOT NULL, PRIMARY KEY (guild_id, channel_id)
        );
        INSERT OR IGNORE INTO guild_channels (guild_id, channel_id, created_at)
            SELECT guild_id, channel_id, updated_at FROM guild_config WHERE channel_id IS NOT NULL`);
        this.getStatement = this.db.prepare("SELECT * FROM guild_config WHERE guild_id = ?");
        this.sessionStatement = this.db.prepare(`INSERT INTO guild_config
            (guild_id, channel_id, ssn_session_id, relay_targets, updated_at)
            VALUES (?, NULL, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET ssn_session_id = excluded.ssn_session_id,
                relay_targets = excluded.relay_targets, updated_at = excluded.updated_at`);
        logger.info({ path }, "SQLite configuration database ready");
    }

    get(guildId) {
        const row = this.getStatement.get(guildId);
        if (!row) return null;
        const channelIds = this.db.prepare("SELECT channel_id FROM guild_channels WHERE guild_id = ? ORDER BY created_at").all(guildId)
            .map(channel => channel.channel_id);
        return { guildId: row.guild_id, channelIds, sessionId: row.ssn_session_id,
            relayTargets: row.relay_targets.split(",").filter(Boolean) };
    }

    addChannel(guildId, channelId) {
        this.ensureGuild(guildId);
        return this.db.prepare("INSERT OR IGNORE INTO guild_channels (guild_id, channel_id, created_at) VALUES (?, ?, ?)")
            .run(guildId, channelId, new Date().toISOString()).changes > 0;
    }

    removeChannel(guildId, channelId) {
        return this.db.prepare("DELETE FROM guild_channels WHERE guild_id = ? AND channel_id = ?").run(guildId, channelId).changes > 0;
    }

    clearChannels(guildId) {
        return this.db.prepare("DELETE FROM guild_channels WHERE guild_id = ?").run(guildId).changes;
    }

    setSession(guildId, sessionId, relayTargets) {
        this.sessionStatement.run(guildId, sessionId, relayTargets.join(","), new Date().toISOString());
    }

    ensureGuild(guildId) {
        this.db.prepare(`INSERT OR IGNORE INTO guild_config
            (guild_id, channel_id, ssn_session_id, relay_targets, updated_at) VALUES (?, NULL, NULL, '', ?)`)
            .run(guildId, new Date().toISOString());
    }

    clearSession(guildId) {
        this.db.prepare("UPDATE guild_config SET ssn_session_id = NULL, relay_targets = '', updated_at = ? WHERE guild_id = ?").run(new Date().toISOString(), guildId);
    }

    close() {
        this.db.close();
    }
}
