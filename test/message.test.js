import test from "node:test";
import assert from "node:assert/strict";
import { toRelayText, toSsnMessage } from "../src/message.js";

test("creates the native SSN Discord shape", () => {
    const payload = toSsnMessage({ id: "123", content: "hello", cleanContent: "hello", createdTimestamp: 1700000000000,
        attachments: { find: () => undefined }, author: { id: "456", username: "alex", globalName: "Alex", displayAvatarURL: () => "https://cdn.example/a.png" },
        member: { displayName: "Alex Server", displayHexColor: "#FF0000" }, guild: { name: "Test Server" } });
    assert.equal(payload.type, "discord");
    assert.equal(payload.chatname, "Alex Server");
    assert.equal(payload.chatmessage, "hello");
    assert.equal(payload.textonly, true);
    assert.equal(payload.id, "discord-123");
});

test("formats fallback like SSN relay-all", () => {
    assert.equal(toRelayText({ chatname: "Alex", chatmessage: "hello" }), "Alex said: hello");
});
