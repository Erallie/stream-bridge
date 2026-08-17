import "dotenv/config";
import process from "node:process";
import { resolve } from "node:path";
import { ChannelType, Client, GatewayIntentBits, PermissionFlagsBits, REST, Routes, SlashCommandBuilder } from "discord.js";
import pino from "pino";
import { ConfigStore } from "./config-store.js";
import { toSsnMessage } from "./message.js";
import { SsnClient } from "./ssn-client.js";

const missing = ["DISCORD_TOKEN", "DISCORD_CLIENT_ID"].filter(name => !process.env[name]);
if (missing.length) throw new Error(`Missing required environment variables: ${missing.join(", ")}`);
const logger = pino({ level: process.env.LOG_LEVEL || "info" });
const store = new ConfigStore(resolve(process.env.DATABASE_PATH || "./data/bot.sqlite"), logger);
const ssnClients = new Map();

const adminCommand = command => command.setDefaultMemberPermissions(PermissionFlagsBits.Administrator);
const commands = [
    adminCommand(new SlashCommandBuilder().setName("setup").setDescription("Connect this server to Social Stream Ninja")
        .addStringOption(option => option.setName("session-id").setDescription("Session value from your SSN URL").setRequired(true).setMinLength(3).setMaxLength(128))
        .addStringOption(option => option.setName("relay-targets").setDescription("Optional comma list, such as twitch,youtube,kick").setMaxLength(256))),
    adminCommand(new SlashCommandBuilder().setName("channel").setDescription("Manage channels forwarded to Social Stream Ninja")
        .addSubcommand(sub => sub.setName("add").setDescription("Add a channel")
            .addChannelOption(option => option.setName("channel").setDescription("Text channel or voice-channel side chat")
                .addChannelTypes(ChannelType.GuildText, ChannelType.GuildVoice).setRequired(true)))
        .addSubcommand(sub => sub.setName("remove").setDescription("Remove a channel")
            .addChannelOption(option => option.setName("channel").setDescription("Configured text or voice channel")
                .addChannelTypes(ChannelType.GuildText, ChannelType.GuildVoice).setRequired(true)))
        .addSubcommand(sub => sub.setName("clear").setDescription("Remove all configured channels"))),
    adminCommand(new SlashCommandBuilder().setName("status").setDescription("Show this server's SSN configuration")),
    adminCommand(new SlashCommandBuilder().setName("disable").setDescription("Remove this server's SSN session and stop forwarding"))
];

const rest = new REST({ version: "10" }).setToken(process.env.DISCORD_TOKEN);
const route = process.env.DISCORD_GUILD_ID
    ? Routes.applicationGuildCommands(process.env.DISCORD_CLIENT_ID, process.env.DISCORD_GUILD_ID)
    : Routes.applicationCommands(process.env.DISCORD_CLIENT_ID);
await rest.put(route, { body: commands.map(command => command.toJSON()) });
logger.info({ scope: process.env.DISCORD_GUILD_ID ? "guild" : "global" }, "Slash command registered");

function parseRelayTargets(value) {
    return [...new Set((value || "").split(",").map(item => item.trim().toLowerCase())
        .filter(item => /^[a-z0-9_-]+$/.test(item) && item !== "discord"))];
}

function resetSsnClient(guildId) {
    ssnClients.get(guildId)?.close();
    ssnClients.delete(guildId);
}

function getSsnClient(guildId, config) {
    if (!ssnClients.has(guildId)) {
        const ssn = new SsnClient({ url: process.env.SSN_WEBSOCKET_URL || "wss://io.socialstream.ninja",
            sessionId: config.sessionId, relayTargets: config.relayTargets, logger: logger.child({ guildId }) });
        ssn.connect();
        ssnClients.set(guildId, ssn);
    }
    return ssnClients.get(guildId);
}

const client = new Client({ intents: [GatewayIntentBits.Guilds, GatewayIntentBits.GuildMessages, GatewayIntentBits.MessageContent] });
client.once("ready", readyClient => logger.info({ bot: readyClient.user.tag }, "Discord bot ready"));

client.on("interactionCreate", async interaction => {
    if (!interaction.isChatInputCommand() || !interaction.guildId || !["setup", "channel", "status", "disable"].includes(interaction.commandName)) return;
    try {
        if (interaction.commandName === "setup") {
            const sessionId = interaction.options.getString("session-id", true).trim();
            const relayTargets = parseRelayTargets(interaction.options.getString("relay-targets"));
            store.setSession(interaction.guildId, sessionId, relayTargets);
            resetSsnClient(interaction.guildId);
            await interaction.reply({ content: `SSN session saved. Relay fallback: ${relayTargets.join(", ") || "off"}.`, ephemeral: true });
        } else if (interaction.commandName === "channel") {
            const action = interaction.options.getSubcommand();
            if (action === "clear") {
                const count = store.clearChannels(interaction.guildId);
                await interaction.reply({ content: `Removed ${count} configured channel${count === 1 ? "" : "s"}.`, ephemeral: true });
                return;
            }
            const channel = interaction.options.getChannel("channel", true);
            const changed = action === "add" ? store.addChannel(interaction.guildId, channel.id) : store.removeChannel(interaction.guildId, channel.id);
            const content = action === "add"
                ? (changed ? `Added ${channel}. Messages from it will be forwarded to SSN.` : `${channel} is already configured.`)
                : (changed ? `Removed ${channel}.` : `${channel} was not configured.`);
            await interaction.reply({ content, ephemeral: true });
        } else if (interaction.commandName === "disable") {
            store.clearSession(interaction.guildId);
            resetSsnClient(interaction.guildId);
            await interaction.reply({ content: "SSN forwarding is disabled for this server.", ephemeral: true });
        } else {
            const config = store.get(interaction.guildId);
            const maskedSession = config?.sessionId ? `${config.sessionId.slice(0, 3)}${"•".repeat(Math.min(8, Math.max(0, config.sessionId.length - 3)))}` : "not set";
            const channels = config?.channelIds.length ? config.channelIds.map(id => `<#${id}>`).join(", ") : "none";
            await interaction.reply({ content: `Channels: ${channels}\nSession: ${maskedSession}\nRelay fallback: ${config?.relayTargets.join(", ") || "off"}`, ephemeral: true });
        }
    } catch (error) {
        logger.error({ err: error, guildId: interaction.guildId }, "Slash command failed");
        const response = { content: "That configuration change failed. Check the bot logs.", ephemeral: true };
        if (interaction.replied || interaction.deferred) await interaction.followUp(response).catch(() => {});
        else await interaction.reply(response).catch(() => {});
    }
});

client.on("messageCreate", message => {
    if (!message.guildId || message.author.bot || message.webhookId) return;
    const config = store.get(message.guildId);
    if (!config?.sessionId || !config.channelIds.includes(message.channelId)) return;
    const payload = toSsnMessage(message);
    if (!payload.chatmessage && !payload.contentimg) return;
    getSsnClient(message.guildId, config).publish(payload);
    logger.info({ guildId: message.guildId, channelId: message.channelId, messageId: message.id }, "Forwarded Discord message to SSN");
});
client.on("error", error => logger.error({ err: error }, "Discord client error"));
client.on("warn", warning => logger.warn({ warning }, "Discord client warning"));

function shutdown(signal) {
    logger.info({ signal }, "Shutting down");
    for (const ssn of ssnClients.values()) ssn.close();
    client.destroy();
    store.close();
    process.exit(0);
}
process.once("SIGINT", () => shutdown("SIGINT"));
process.once("SIGTERM", () => shutdown("SIGTERM"));
await client.login(process.env.DISCORD_TOKEN);
