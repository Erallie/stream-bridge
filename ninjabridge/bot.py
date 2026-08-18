from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from ninjabridge.database import ConfigStore, GuildConfig
from ninjabridge.direct import DirectHub
from ninjabridge.kick import KickGateway
from ninjabridge.messages import DEFAULT_DIRECT_RELAY_TEMPLATE, to_relay_text, to_ssn_message, validate_direct_relay_template
from ninjabridge.ssn import SsnClient

load_dotenv()


def parse_list(value: str | None) -> list[str]:
    return list(dict.fromkeys(x.strip().lower() for x in (value or "").split(",") if x.strip()))


class NinjaBridge(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, application_id=int(os.environ["DISCORD_CLIENT_ID"]))
        self.store = ConfigStore(os.getenv("DATABASE_PATH", "./data/bot.sqlite"))
        self.kick = KickGateway(self.store, self.handle_kick_event, self.handle_kick_authorized)
        self.ssn_clients: dict[int, SsnClient] = {}
        self.direct_hubs: dict[int, DirectHub] = {}
        self.webhooks: dict[int, discord.Webhook] = {}
        self.history_task: asyncio.Task[None] | None = None
        self.ssn_url = os.getenv("SSN_WEBSOCKET_URL", "wss://io.socialstream.ninja")

    async def setup_hook(self) -> None:
        await self.kick.start()
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        logging.info("NinjaBridge ready as %s", self.user)
        if not self.history_task or self.history_task.done():
            self.history_task = asyncio.create_task(self.maintain_history(), name="history-maintenance")
        for guild_id in self.store.guild_ids():
            config = self.store.get(guild_id)
            if config and config.session_id:
                self.get_ssn(int(guild_id), config)
            self.get_direct(int(guild_id))

    async def maintain_history(self) -> None:
        try:
            retention = max(1, int(os.getenv("HISTORY_RETENTION_DAYS", "30")))
        except ValueError:
            retention = 30
            logging.warning("Invalid HISTORY_RETENTION_DAYS; using 30 days")
        while True:
            try:
                events, deliveries = self.store.prune_history(retention)
                logging.info("Pruned %d old events and %d old delivery records", events, deliveries)
            except Exception:
                logging.exception("History maintenance failed; it will retry tomorrow")
            await asyncio.sleep(24 * 60 * 60)

    async def reset_ssn(self, guild_id: int) -> None:
        client = self.ssn_clients.pop(guild_id, None)
        if client:
            await client.close()

    def get_ssn(self, guild_id: int, config: GuildConfig) -> SsnClient:
        if guild_id not in self.ssn_clients:
            async def received(data: dict[str, Any]) -> None:
                await self.handle_ssn(guild_id, data)
            async def status(connected: bool) -> None:
                await self.transport_status(guild_id, connected)
            logger = logging.LoggerAdapter(logging.getLogger("ninjabridge.ssn"), {"guild_id": guild_id})
            password = str(self.store.get_setting(str(guild_id), "ssn_password", ""))
            self.ssn_clients[guild_id] = SsnClient(self.ssn_url, config.session_id or "", config.relay_targets, logger, received, status, password)
            self.ssn_clients[guild_id].start()
        return self.ssn_clients[guild_id]

    def get_direct(self, guild_id: int) -> DirectHub:
        if guild_id not in self.direct_hubs:
            async def received(data: dict[str, Any]) -> None:
                client = self.ssn_clients.get(guild_id)
                if not client or not client.connected:
                    await self.handle_direct(guild_id, data)
            guild = str(guild_id)
            hub = DirectHub(
                received,
                str(self.store.get_setting(guild, "direct_twitch_channel", "")),
                str(self.store.get_setting(guild, "direct_youtube_live_chat_id", "")),
            )
            self.direct_hubs[guild_id] = hub
            hub.start()
        return self.direct_hubs[guild_id]

    async def reset_direct(self, guild_id: int) -> None:
        hub = self.direct_hubs.pop(guild_id, None)
        if hub:
            await hub.close()
        self.get_direct(guild_id)

    async def handle_kick_event(self, guild_id: int, data: dict[str, Any]) -> None:
        client = self.ssn_clients.get(guild_id)
        if not client or not client.connected:
            await self.handle_direct(guild_id, data)

    async def handle_kick_authorized(self, guild_id: int, username: str) -> None:
        logging.info("Discord guild %s authorized Kick channel %s", guild_id, username)

    async def send_direct(self, guild_id: int, text: str, exclude: str = "") -> None:
        tasks = [self.get_direct(guild_id).send(text, exclude)]
        if exclude != "kick" and self.kick.connected(guild_id):
            tasks.append(self.kick.send(guild_id, text))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logging.error("Direct relay send failed: %s", result)

    async def transport_status(self, guild_id: int, connected: bool) -> None:
        if not self.store.get_setting(str(guild_id), "transport_announcements", True):
            return
        config = self.store.get(str(guild_id))
        if not config:
            return
        channel_ids = set(config.channel_ids)
        if config.discord_relay_channel_id:
            channel_ids.add(config.discord_relay_channel_id)
        text = "NinjaBridge switched to Social Stream Ninja transport." if connected else "NinjaBridge lost SSN and switched to direct platform connections."
        guild = self.get_guild(guild_id)
        for channel_id in channel_ids:
            channel = guild.get_channel(int(channel_id)) if guild else None
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                try:
                    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    logging.exception("Could not announce transport switch in %s", channel_id)

    async def handle_ssn(self, guild_id: int, data: dict[str, Any]) -> bool:
        message_text = str(data.get("chatmessage") or "")
        content_image = str(data.get("contentimg") or "")
        if data.get("reflection") or data.get("bot") or not data.get("chatname") or not (message_text or content_image):
            return False
        platform = str(data.get("type", "unknown")).lower()
        user_id = str(data.get("userid") or data.get("chatname", ""))
        key = self.store.claim_event(str(guild_id), platform, str(data.get("id", "")), user_id, message_text or content_image, data.get("timestamp", int(time.time())))
        if not key:
            return False
        config = self.store.get(str(guild_id))
        if config and config.discord_relay_channel_id and self.store.claim_delivery(str(guild_id), key, "discord"):
            await self.send_webhook(guild_id, int(config.discord_relay_channel_id), str(data["chatname"]), str(data.get("chatimg", "")), platform, message_text or content_image)
        return True

    async def handle_direct(self, guild_id: int, data: dict[str, Any]) -> None:
        accepted = await self.handle_ssn(guild_id, data)
        if accepted:
            template = str(self.store.get_setting(str(guild_id), "direct_relay_template", DEFAULT_DIRECT_RELAY_TEMPLATE))
            await self.send_direct(guild_id, to_relay_text(data, template), str(data.get("type", "")))

    async def send_webhook(self, guild_id: int, channel_id: int, display_name: str, avatar_url: str, platform: str, content: str) -> None:
        guild = self.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            return
        hook = self.webhooks.get(channel_id)
        if not hook:
            hooks = await channel.webhooks()
            hook = next((item for item in hooks if item.name == "NinjaBridge"), None)
            if not hook:
                hook = await channel.create_webhook(name="NinjaBridge", reason="Cross-platform relay")
            self.webhooks[channel_id] = hook
        try:
            await hook.send(content, username=f"{display_name} ({platform.title()})"[:80], avatar_url=avatar_url or None, allowed_mentions=discord.AllowedMentions.none(), wait=True)
        except discord.NotFound:
            self.webhooks.pop(channel_id, None)
            raise

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id or not message.guild:
            return
        guild_id = str(message.guild.id)
        config = self.store.get(guild_id)
        if not config or str(message.channel.id) not in config.channel_ids:
            return
        payload = to_ssn_message(message)
        if not (payload["chatmessage"] or payload["contentimg"]):
            return
        key = self.store.claim_event(guild_id, "discord", str(message.id), str(message.author.id), payload["chatmessage"], int(message.created_at.timestamp()))
        if not key:
            return
        ssn = self.get_ssn(message.guild.id, config) if config.session_id else None
        if ssn and ssn.connected:
            await ssn.inject(payload)
            for target in config.relay_targets:
                if self.store.claim_delivery(guild_id, key, target):
                    await ssn.send_chat(target, to_relay_text(payload))
        else:
            template = str(self.store.get_setting(guild_id, "direct_relay_template", DEFAULT_DIRECT_RELAY_TEMPLATE))
            await self.send_direct(message.guild.id, to_relay_text(payload, template))

    async def close(self) -> None:
        if self.history_task:
            self.history_task.cancel()
            await asyncio.gather(self.history_task, return_exceptions=True)
        await asyncio.gather(*(client.close() for client in self.ssn_clients.values()), return_exceptions=True)
        await asyncio.gather(*(hub.close() for hub in self.direct_hubs.values()), return_exceptions=True)
        await self.kick.close()
        self.store.close()
        await super().close()


bot = NinjaBridge()
admin = app_commands.default_permissions(administrator=True)


@bot.tree.command(name="setup", description="Connect this server to Social Stream Ninja")
@admin
@app_commands.describe(
    session_id="The SSN session ID that NinjaBridge should join",
    relay_targets="Comma-separated platforms SSN should relay messages to",
    password="The SSN session password, if the session is protected",
)
async def setup(i: discord.Interaction, session_id: str, relay_targets: str = "twitch,youtube,kick,tiktok", password: str = "") -> None:
    assert i.guild_id
    bot.store.set_session(str(i.guild_id), session_id.strip(), parse_list(relay_targets))
    bot.store.set_setting(str(i.guild_id), "ssn_password", password)
    await bot.reset_ssn(i.guild_id)
    config = bot.store.get(str(i.guild_id))
    if config:
        bot.get_ssn(i.guild_id, config)
    await i.response.send_message("SSN session and relay targets saved.", ephemeral=True)


forward_group = app_commands.Group(name="forward", description="Choose Discord channels whose messages are sent to streaming chats", default_permissions=discord.Permissions(administrator=True))


@forward_group.command(name="add", description="Add a Discord text channel or voice-channel chat as a relay source")
@app_commands.describe(channel="The text channel or voice-channel side chat to forward from")
async def channel_add(i: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert i.guild_id
    changed = bot.store.add_channel(str(i.guild_id), str(channel.id))
    await i.response.send_message("Discord channel will now be forwarded to SSN." if changed else "That channel is already forwarded to SSN.", ephemeral=True)


@forward_group.command(name="remove", description="Stop forwarding messages from one Discord channel")
@app_commands.describe(channel="The configured text channel or voice-channel side chat to remove")
async def channel_remove(i: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert i.guild_id
    changed = bot.store.remove_channel(str(i.guild_id), str(channel.id))
    await i.response.send_message("Discord channel will no longer be forwarded to SSN." if changed else "That channel was not being forwarded.", ephemeral=True)


@forward_group.command(name="clear", description="Remove every configured Discord forwarding channel")
async def channel_clear(i: discord.Interaction) -> None:
    assert i.guild_id
    await i.response.send_message(f"Stopped forwarding {bot.store.clear_channels(str(i.guild_id))} Discord channel(s) to SSN.", ephemeral=True)


bot.tree.add_command(forward_group)
receive_group = app_commands.Group(name="receive", description="Choose where Discord receives messages from streaming platforms", default_permissions=discord.Permissions(administrator=True))


@receive_group.command(name="set", description="Choose the Discord channel that receives streaming chat messages")
@app_commands.describe(channel="The text channel or voice-channel side chat that should receive messages")
async def receive_set(i: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "discord_relay_channel_id", str(channel.id))
    await i.response.send_message(f"SSN platform messages will now be mirrored to {channel.mention}.", ephemeral=True)


@receive_group.command(name="clear", description="Stop sending streaming chat messages into Discord")
async def receive_clear(i: discord.Interaction) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "discord_relay_channel_id", None)
    await i.response.send_message("SSN-to-Discord mirroring disabled.", ephemeral=True)


bot.tree.add_command(receive_group)

direct_group = app_commands.Group(name="direct", description="Configure direct platform connections", default_permissions=discord.Permissions(administrator=True))


@direct_group.command(name="twitch", description="Connect directly to a Twitch channel when SSN is unavailable")
@app_commands.describe(channel="The Twitch channel name, with or without the leading #")
async def direct_twitch(i: discord.Interaction, channel: str) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "direct_twitch_channel", channel.lstrip("#"))
    await bot.reset_direct(i.guild_id)
    await i.response.send_message("Direct Twitch channel saved. Credentials are read from .env.", ephemeral=True)


@direct_group.command(name="youtube", description="Connect directly to one YouTube livestream chat")
@app_commands.describe(live_chat_id="The broadcast's activeLiveChatId, not its video ID")
async def direct_youtube(i: discord.Interaction, live_chat_id: str) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "direct_youtube_live_chat_id", live_chat_id)
    await bot.reset_direct(i.guild_id)
    await i.response.send_message("Direct YouTube live-chat ID saved. OAuth is read from .env.", ephemeral=True)


@direct_group.command(name="kick", description="Privately authorize this server's broadcaster account with Kick")
async def direct_kick(i: discord.Interaction) -> None:
    assert i.guild_id
    try:
        url = bot.kick.authorization_url(i.guild_id, i.user.id)
    except RuntimeError as error:
        await i.response.send_message(str(error), ephemeral=True)
        return
    await i.response.send_message(f"[Authorize this server's Kick channel]({url})\nThis private link expires in 10 minutes.", ephemeral=True)


@direct_group.command(name="disable", description="Disable one direct streaming-platform connection")
@app_commands.describe(platform="The direct connection to disable: twitch, youtube, or kick")
async def direct_disable(i: discord.Interaction, platform: str) -> None:
    assert i.guild_id
    platform = platform.casefold()
    if platform not in {"twitch", "youtube", "kick"}:
        await i.response.send_message("Platform must be twitch, youtube, or kick.", ephemeral=True)
        return
    if platform == "kick":
        await bot.kick.disable(i.guild_id)
    else:
        suffix = {"twitch": "channel", "youtube": "live_chat_id"}[platform]
        bot.store.set_setting(str(i.guild_id), f"direct_{platform}_{suffix}", "")
    await bot.reset_direct(i.guild_id)
    await i.response.send_message(f"Direct {platform.title()} disabled.", ephemeral=True)


@direct_group.command(name="message", description="Set the message format used for direct relays when SSN is unavailable")
@app_commands.describe(template="Format using {name}, {message}, and optionally {platform}; leave blank to reset")
async def direct_message(i: discord.Interaction, template: str = "") -> None:
    assert i.guild_id
    try:
        checked = validate_direct_relay_template(template)
    except ValueError as error:
        await i.response.send_message(str(error), ephemeral=True)
        return
    bot.store.set_setting(str(i.guild_id), "direct_relay_template", checked)
    example = to_relay_text({"chatname": "Alex", "chatmessage": "Hello!", "type": "twitch"}, checked)
    await i.response.send_message(f"Direct relay message saved. Example:\n{example}", ephemeral=True)


bot.tree.add_command(direct_group)


@bot.tree.command(name="switchmessages", description="Enable or disable transport-switch messages")
@admin
@app_commands.describe(enabled="Whether Discord should announce switches between SSN and direct mode")
async def switch_messages(i: discord.Interaction, enabled: bool) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "transport_announcements", enabled)
    await i.response.send_message(f"Transport-switch messages: {enabled}.", ephemeral=True)
@bot.tree.command(name="status", description="Show this server's NinjaBridge connections and relay configuration")
@admin
async def status(i: discord.Interaction) -> None:
    assert i.guild_id
    c = bot.store.get(str(i.guild_id))
    session = c.session_id[:3] + "••••••" if c and c.session_id else "not set"
    channels = ", ".join(f"<#{x}>" for x in c.channel_ids) if c else "none"
    mirror = f"<#{c.discord_relay_channel_id}>" if c and c.discord_relay_channel_id else "off"
    ssn_state = "connected" if i.guild_id in bot.ssn_clients and bot.ssn_clients[i.guild_id].connected else "disconnected"
    hub = bot.direct_hubs.get(i.guild_id)
    direct_platforms = list(hub.adapters if hub else [])
    if bot.kick.connected(i.guild_id):
        direct_platforms.append(f"kick ({bot.kick.username(i.guild_id)})")
    direct = ", ".join(direct_platforms) or "none"
    template = str(bot.store.get_setting(str(i.guild_id), "direct_relay_template", DEFAULT_DIRECT_RELAY_TEMPLATE))
    await i.response.send_message(f"Discord channels forwarded: {channels}\nSSN session: {session} ({ssn_state})\nDirect platforms: {direct}\nDirect relay message: `{template}`\nPlatform messages received in Discord: {mirror}", ephemeral=True)


@bot.tree.command(name="disable", description="Disconnect this server from SSN without removing direct connections")
@admin
async def disable(i: discord.Interaction) -> None:
    assert i.guild_id
    bot.store.clear_session(str(i.guild_id))
    await bot.reset_ssn(i.guild_id)
    await i.response.send_message("SSN forwarding disabled.", ephemeral=True)


def main() -> None:
    missing = [x for x in ("DISCORD_TOKEN", "DISCORD_CLIENT_ID") if not os.getenv(x)]
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing))
    logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    bot.run(os.environ["DISCORD_TOKEN"], log_handler=None)
