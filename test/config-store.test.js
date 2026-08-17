import test from "node:test";
import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { ConfigStore } from "../src/config-store.js";

test("persists independent configuration for each Discord server", async () => {
    const directory = await mkdtemp(join(tmpdir(), "ninja-bridge-"));
    const logger = { info() {} };
    try {
        let store = new ConfigStore(join(directory, "bot.sqlite"), logger);
        store.setSession("guild-1", "session-one", ["twitch", "youtube"]);
        store.addChannel("guild-1", "channel-1");
        store.addChannel("guild-1", "channel-2");
        store.setSession("guild-2", "session-two", []);
        store.close();

        store = new ConfigStore(join(directory, "bot.sqlite"), logger);
        assert.deepEqual(store.get("guild-1"), {
            guildId: "guild-1", channelIds: ["channel-1", "channel-2"], sessionId: "session-one", relayTargets: ["twitch", "youtube"]
        });
        assert.equal(store.get("guild-2").sessionId, "session-two");
        store.close();
    } finally {
        await rm(directory, { recursive: true, force: true, maxRetries: 2, retryDelay: 100 }).catch(() => {});
    }
});
