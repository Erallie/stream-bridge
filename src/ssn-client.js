import WebSocket from "ws";
import { toRelayText } from "./message.js";

export class SsnClient {
    constructor({ url, sessionId, relayTargets, logger }) {
        Object.assign(this, { url, sessionId, relayTargets, logger });
        this.queue = [];
        this.attempt = 0;
        this.stopping = false;
    }

    connect() {
        if (this.stopping || [WebSocket.CONNECTING, WebSocket.OPEN].includes(this.socket?.readyState)) return;
        this.logger.info({ url: this.url }, "Connecting to Social Stream Ninja");
        const socket = new WebSocket(this.url, { handshakeTimeout: 15000 });
        this.socket = socket;
        socket.on("open", () => {
            this.attempt = 0;
            socket.send(JSON.stringify({ join: this.sessionId, in: 0, out: 1 }));
            this.logger.info("Connected to Social Stream Ninja");
            this.flush();
            this.heartbeat = setInterval(() => socket.readyState === WebSocket.OPEN && socket.ping(), 25000);
        });
        socket.on("message", raw => this.logger.debug({ response: raw.toString().slice(0, 1000) }, "SSN response"));
        socket.on("error", error => this.logger.error({ err: error }, "SSN WebSocket error"));
        socket.on("close", (code, reason) => {
            clearInterval(this.heartbeat);
            this.logger.warn({ code, reason: reason.toString() }, "SSN disconnected");
            this.scheduleReconnect();
        });
    }

    publish(payload) {
        this.enqueue({ action: "extContent", value: JSON.stringify(payload) });
        for (const target of this.relayTargets) {
            this.enqueue({ action: "sendChat", target, value: toRelayText(payload) });
        }
    }

    enqueue(command) {
        this.queue.push(command);
        if (this.queue.length > 1000) {
            this.queue.shift();
            this.logger.warn("SSN queue full; discarded oldest command");
        }
        this.flush();
    }

    flush() {
        while (this.socket?.readyState === WebSocket.OPEN && this.queue.length) {
            this.socket.send(JSON.stringify(this.queue.shift()));
        }
    }

    scheduleReconnect() {
        if (this.stopping || this.reconnectTimer) return;
        const delay = Math.min(30000, 1000 * (2 ** this.attempt++)) + Math.floor(Math.random() * 500);
        this.logger.info({ delayMs: delay }, "Scheduling SSN reconnect");
        this.reconnectTimer = setTimeout(() => {
            this.reconnectTimer = null;
            this.connect();
        }, delay);
    }

    close() {
        this.stopping = true;
        clearTimeout(this.reconnectTimer);
        clearInterval(this.heartbeat);
        this.socket?.close(1000, "Bot shutting down");
    }
}
