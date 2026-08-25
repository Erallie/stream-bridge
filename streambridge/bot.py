from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Literal

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from streambridge.database import ConfigStore, GuildConfig
from streambridge.dashboard import DashboardAPI
from streambridge.direct import DirectHub
from streambridge.kick import KickGateway
from streambridge.messages import DEFAULT_DIRECT_RELAY_TEMPLATE, ssn_to_plain_text, to_relay_text, to_ssn_message, to_ssn_relay_text, validate_direct_relay_template
from streambridge.oauth import OAuthToken
from streambridge.relay import ReflectionTracker
from streambridge.ssn import SsnClient
from streambridge.youtube import YouTubeGateway
from streambridge.web import WebGateway

load_dotenv()


def parse_list(value: str | None) -> list[str]:
    return list(dict.fromkeys(x.strip().lower() for x in (value or "").split(",") if x.strip()))


def platform_display_name(display_name: str, platform: str) -> str:
    return display_name.removeprefix("@") if platform.lower() == "youtube" else display_name


def webhook_username(display_name: str, platform: str) -> str:
    name = display_name.strip() or "Unknown user"
    combined = f"{name} ({platform.title()})"
    combined = re.sub("discord", "Dis-cord", combined, flags=re.IGNORECASE)
    combined = re.sub("clyde", "C-lyde", combined, flags=re.IGNORECASE)
    return combined[:80]


def dashboard_url() -> str:
    return f"{os.getenv('DASHBOARD_SITE_URL', 'https://streambridge.gozarproductions.com').rstrip('/')}/dashboard"


def format_status(discord: str, session: str, ssn_state: str, ssn_targets: str, direct: str, template: str) -> str:
    return (
        f"**Discord relay channel:** {discord}\n"
        f"**SSN session:** {session} ({ssn_state})\n"
        f"**SSN Platforms:** {ssn_targets}\n"
        f"**Direct platforms:** {direct}\n"
        f"**Direct relay message:** `{template}`"
    )


def format_discord_status(channel_id: str | None, enabled: bool, forward: bool, receive: bool) -> str:
    if not enabled or not channel_id or not (forward or receive):
        return "Disabled"
    if forward and receive:
        direction = "forwarding/receiving"
    elif forward:
        direction = "forwarding only"
    else:
        direction = "receiving only"
    return f"<#{channel_id}> ({direction})"


class StreamBridge(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents, application_id=int(os.environ["DISCORD_CLIENT_ID"]))
        self.store = ConfigStore(os.getenv("DATABASE_PATH", "./data/bot.sqlite"))
        self.youtube = YouTubeGateway(self.store)
        self.kick = KickGateway(self.store, self.handle_kick_event)
        self.dashboard = DashboardAPI(
            self.store,
            self.reload_workspace,
            self.handle_dashboard_identity,
            self.dashboard_discord_channels,
            self.dashboard_runtime_status,
        )
        self.web = WebGateway(self.kick, self.dashboard)
        self.ssn_clients: dict[int | str, SsnClient] = {}
        self.direct_hubs: dict[int | str, DirectHub] = {}
        self.workspace_runtime_keys: dict[str, int | str] = {}
        self.webhooks: dict[int, discord.Webhook] = {}
        self.ssn_reflections: dict[int, ReflectionTracker] = {}
        self.history_task: asyncio.Task[None] | None = None
        self.ssn_url = os.getenv("SSN_WEBSOCKET_URL", "wss://io.socialstream.ninja")

    async def handle_dashboard_identity(self, provider: str, identity: dict[str, str]) -> None:
        if provider == "kick":
            await self.kick.ensure_chat_subscription(identity["access_token"])

    async def dashboard_discord_channels(self, guild_id: str) -> list[dict[str, str]]:
        guild = self.get_guild(int(guild_id))
        if not guild:
            return []
        channels: list[dict[str, str]] = []
        for channel in guild.channels:
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                channels.append({
                    "id": str(channel.id),
                    "name": channel.name,
                    "type": "voice" if isinstance(channel, discord.VoiceChannel) else "text",
                })
        return sorted(channels, key=lambda item: (item["type"], item["name"].casefold()))

    async def dashboard_runtime_status(self, guild_id: str) -> dict[str, Any]:
        key = int(guild_id)
        ssn = self.ssn_clients.get(key)
        return {
            "ssn": "connected" if ssn and ssn.connected else "disconnected",
            "direct_platforms": self.direct_platforms(key),
        }

    async def setup_hook(self) -> None:
        await self.kick.start()
        await self.web.start()
        await self.load_workspaces()
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def load_workspaces(self) -> None:
        """Start every dashboard-configured bridge, including Discord-backed bridges."""
        for workspace in self.store.workspaces():
            if workspace["enabled"]:
                await self.start_workspace(workspace)

    @staticmethod
    def workspace_key(workspace: dict[str, Any]) -> int | str:
        return int(workspace["discord_guild_id"]) if workspace["discord_guild_id"] else f"workspace:{workspace['id']}"

    def workspace_for_guild(self, guild_id: int) -> dict[str, Any] | None:
        return next(
            (
                workspace for workspace in self.store.workspaces()
                if workspace["enabled"] and str(workspace["discord_guild_id"] or "") == str(guild_id)
            ),
            None,
        )

    def direct_template(self, guild_id: int) -> str:
        workspace = self.workspace_for_guild(guild_id)
        if workspace:
            return str(workspace["relay_template"])
        return str(self.store.get_setting(str(guild_id), "direct_relay_template", DEFAULT_DIRECT_RELAY_TEMPLATE))

    def workspace_identity(self, workspace: dict[str, Any], provider: str) -> dict[str, Any] | None:
        connection = next((item for item in workspace["connections"] if item["provider"] == provider and item["enabled"]), None)
        if not connection:
            return None
        identity_provider = "google" if provider == "youtube" else provider
        identities = self.store.dashboard_identities(str(workspace["owner_user_id"]), include_tokens=True)
        return next((item for item in identities if item["provider"] == identity_provider and item["provider_user_id"] == connection["provider_user_id"]), None)

    async def start_workspace(
        self,
        workspace: dict[str, Any],
        ssn_reported_connected: bool = False,
    ) -> None:
        key = self.workspace_key(workspace)
        self.workspace_runtime_keys[str(workspace["id"])] = key
        ssn = None
        if workspace["ssn_session_id"]:
            ssn = self.get_workspace_ssn(workspace, ssn_reported_connected)
        youtube = self.workspace_identity(workspace, "youtube")
        kick = self.workspace_identity(workspace, "kick")
        twitch = self.workspace_identity(workspace, "twitch")
        if youtube:
            self.youtube.register_account(key, str(youtube["provider_user_id"]), str(youtube["display_name"]), self.dashboard.decrypt(str(youtube["refresh_token"])))
        if kick:
            self.kick.register_account(key, str(kick["provider_user_id"]), str(kick["display_name"]), self.dashboard.decrypt(str(kick["refresh_token"])))
        twitch_oauth = None
        twitch_channel = ""
        twitch_username = ""
        if twitch:
            twitch_channel = str(twitch["display_name"]).lstrip("#").lower()
            twitch_username = twitch_channel
            twitch_oauth = OAuthToken(
                "TWITCH", "https://id.twitch.tv/oauth2/token",
                refresh_token=self.dashboard.decrypt(str(twitch["refresh_token"])),
                client_id=os.getenv("TWITCH_CLIENT_ID", ""), client_secret=os.getenv("TWITCH_CLIENT_SECRET", ""),
                on_refresh=lambda token, user_id=str(twitch["provider_user_id"]):
                    self.store.update_dashboard_refresh_token("twitch", user_id, self.dashboard.encrypt(token)),
            )
        if twitch_oauth or youtube:
            async def received(data: dict[str, Any]) -> None:
                ssn = self.ssn_clients.get(key)
                if not ssn or not ssn.connected:
                    if isinstance(key, int):
                        await self.handle_direct(key, data)
                    else:
                        await self.handle_workspace_direct(workspace, data)
            async def youtube_broadcast_detected() -> None:
                if isinstance(key, int):
                    await self.announce_youtube_broadcast(key)
            hub = DirectHub(
                received, twitch_channel, self.youtube.token(key), twitch_oauth,
                twitch_username, youtube_broadcast_detected,
            )
            self.direct_hubs[key] = hub
            hub.start(
                youtube_polling_enabled=not bool(
                    ssn and (ssn.connected or ssn_reported_connected)
                )
            )

    async def handle_workspace_direct(self, workspace: dict[str, Any], data: dict[str, Any]) -> None:
        key = self.workspace_key(workspace)
        message = ssn_to_plain_text(str(data.get("plainText") or data.get("chatmessage") or ""))
        if not message:
            return
        event = self.store.claim_event(key, str(data.get("type", "unknown")), str(data.get("id", "")),
                                       str(data.get("userid") or data.get("chatname", "")), message,
                                       data.get("timestamp", int(time.time())))
        if not event:
            return
        relay_text = to_relay_text(data, str(workspace["relay_template"]))
        source = str(data.get("type", ""))
        hub = self.direct_hubs.get(key)
        tasks: list[Any] = [hub.send(relay_text, source)] if hub else []
        if source != "kick" and self.kick.connected(key):
            tasks.append(self.kick.send(key, relay_text))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def get_workspace_ssn(
        self,
        workspace: dict[str, Any],
        reported_connected: bool = False,
    ) -> SsnClient:
        key = self.workspace_key(workspace)
        if key not in self.ssn_clients:
            async def received(data: dict[str, Any]) -> None:
                if isinstance(key, int):
                    await self.handle_ssn(key, data)
                else:
                    await self.handle_workspace_message(str(workspace["id"]), data)
            async def status(connected: bool) -> None:
                hub = self.direct_hubs.get(key)
                if hub:
                    await hub.set_youtube_polling_enabled(not connected)
                if isinstance(key, int):
                    await self.transport_status(key, connected)
            logger = logging.LoggerAdapter(logging.getLogger("streambridge.ssn"), {"workspace_id": workspace["id"]})
            self.ssn_clients[key] = SsnClient(
                self.ssn_url, str(workspace["ssn_session_id"]), tuple(workspace["ssn_targets"]),
                logger, received, status,
                reported_connected,
            )
            self.ssn_clients[key].start()
        return self.ssn_clients[key]

    async def handle_workspace_message(self, workspace_id: str, data: dict[str, Any]) -> None:
        """Deduplicate standalone SSN traffic; SSN itself performs configured platform relaying."""
        text = ssn_to_plain_text(str(data.get("plainText") or data.get("chatmessage") or ""))
        if data.get("reflection") or data.get("bot") or not text:
            return
        self.store.claim_event(
            f"workspace:{workspace_id}", str(data.get("type", "unknown")), str(data.get("id", "")),
            str(data.get("userid") or data.get("chatname", "")), text,
            data.get("timestamp", int(time.time())),
        )

    async def reload_workspace(self, workspace_id: str) -> None:
        key = self.workspace_runtime_keys.pop(workspace_id, f"workspace:{workspace_id}")
        existing = self.ssn_clients.pop(key, None)
        reported_connected = bool(existing and existing.reported_connected)
        if existing:
            existing.on_status = None
            await existing.close()
        direct = self.direct_hubs.pop(key, None)
        if direct:
            await direct.close()
        self.youtube.unregister_account(key)
        self.kick.unregister_account(key)
        workspace = next((item for item in self.store.workspaces() if item["id"] == workspace_id), None)
        if workspace and workspace["enabled"]:
            await self.start_workspace(workspace, reported_connected)

    async def on_ready(self) -> None:
        logging.info("StreamBridge ready as %s", self.user)
        if not self.history_task or self.history_task.done():
            self.history_task = asyncio.create_task(self.maintain_history(), name="history-maintenance")
        for guild_id in self.store.guild_ids():
            config = self.store.get(guild_id)
            if config and config.session_id and not self.workspace_for_guild(int(guild_id)):
                self.get_ssn(int(guild_id), config)

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
                hub = self.direct_hubs.get(guild_id)
                if hub:
                    await hub.set_youtube_polling_enabled(not connected)
                await self.transport_status(guild_id, connected)
            logger = logging.LoggerAdapter(logging.getLogger("streambridge.ssn"), {"guild_id": guild_id})
            self.ssn_clients[guild_id] = SsnClient(self.ssn_url, config.session_id or "", config.relay_targets, logger, received, status)
            self.ssn_clients[guild_id].start()
        return self.ssn_clients[guild_id]

    async def handle_kick_event(self, guild_id: int | str, data: dict[str, Any]) -> None:
        if isinstance(guild_id, str) and guild_id.startswith("workspace:"):
            workspace_id = guild_id.removeprefix("workspace:")
            workspace = next((item for item in self.store.workspaces() if item["id"] == workspace_id), None)
            if workspace:
                ssn = self.ssn_clients.get(guild_id)
                if not ssn or not ssn.connected:
                    await self.handle_workspace_direct(workspace, data)
            return
        client = self.ssn_clients.get(guild_id)
        if not client or not client.connected:
            await self.handle_direct(guild_id, data)

    async def send_direct(self, guild_id: int, text: str, exclude: str = "") -> None:
        hub = self.direct_hubs.get(guild_id)
        tasks = [hub.send(text, exclude)] if hub else []
        if exclude != "kick" and self.kick.connected(guild_id):
            tasks.append(self.kick.send(guild_id, text))
        results = await asyncio.gather(*tasks, return_exceptions=True) if tasks else []
        for result in results:
            if isinstance(result, Exception):
                logging.error("Direct relay send failed: %s", result)

    def direct_platforms(self, guild_id: int) -> list[str]:
        hub = self.direct_hubs.get(guild_id)
        platforms = list(hub.adapters) if hub else []
        if self.kick.connected(guild_id):
            platforms.append("kick")
        return platforms

    async def announce_youtube_broadcast(self, guild_id: int) -> None:
        if not self.store.get_setting(str(guild_id), "youtube_live_notifications", True):
            return
        if not self.store.get_setting(str(guild_id), "discord_enabled", True):
            return
        config = self.store.get(str(guild_id))
        if not config or not config.discord_relay_channel_id:
            return
        guild = self.get_guild(guild_id)
        channel = guild.get_channel(int(config.discord_relay_channel_id)) if guild else None
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            return
        try:
            await channel.send(
                "-# YouTube live broadcast detected. Messages will now be relayed.",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            logging.exception("Could not announce the detected YouTube broadcast in %s", channel.id)

    async def transport_status(self, guild_id: int, connected: bool) -> None:
        if not self.store.get_setting(str(guild_id), "transport_announcements", True):
            return
        config = self.store.get(str(guild_id))
        if not config:
            return
        channel_ids = set(config.channel_ids)
        if config.discord_relay_channel_id:
            channel_ids.add(config.discord_relay_channel_id)
        text = "-# StreamBridge switched to Social Stream Ninja transport." if connected else "-# StreamBridge lost SSN and switched to direct platform connections."
        if not connected and not self.direct_platforms(guild_id):
            text += "\n-# No platforms have been set up for direct connection. Messages will not be relayed."
        guild = self.get_guild(guild_id)
        for channel_id in channel_ids:
            channel = guild.get_channel(int(channel_id)) if guild else None
            if isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
                try:
                    await channel.send(text, allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    logging.exception("Could not announce transport switch in %s", channel_id)

    async def handle_ssn(self, guild_id: int, data: dict[str, Any]) -> bool:
        message_text = ssn_to_plain_text(str(data.get("plainText") or data.get("chatmessage") or ""))
        display_name = ssn_to_plain_text(str(data.get("chatname") or ""))
        platform = str(data.get("type", "unknown")).lower()
        display_name = platform_display_name(display_name, platform)
        data["chatmessage"] = message_text
        data["plainText"] = message_text
        data["chatname"] = display_name
        content_image = str(data.get("contentimg") or "")
        if data.get("reflection") or data.get("bot") or not display_name or not (message_text or content_image):
            return False
        tracker = self.ssn_reflections.get(guild_id)
        if tracker and message_text and tracker.consume(platform, message_text):
            logging.info("Suppressed a returning SSN relay echo from %s", platform)
            return False
        user_id = str(data.get("userid") or data.get("chatname", ""))
        key = self.store.claim_event(str(guild_id), platform, str(data.get("id", "")), user_id, message_text or content_image, data.get("timestamp", int(time.time())))
        if not key:
            return False
        config = self.store.get(str(guild_id))
        if (
            config
            and config.discord_relay_channel_id
            and self.store.get_setting(str(guild_id), "discord_enabled", True)
            and self.store.get_setting(str(guild_id), "discord_receive_enabled", True)
            and self.store.claim_delivery(str(guild_id), key, "discord")
        ):
            await self.send_webhook(guild_id, int(config.discord_relay_channel_id), display_name, str(data.get("chatimg", "")), platform, message_text or content_image)
        return True

    async def handle_direct(self, guild_id: int, data: dict[str, Any]) -> None:
        accepted = await self.handle_ssn(guild_id, data)
        if accepted:
            await self.send_direct(guild_id, to_relay_text(data, self.direct_template(guild_id)), str(data.get("type", "")))

    async def send_webhook(self, guild_id: int, channel_id: int, display_name: str, avatar_url: str, platform: str, content: str) -> None:
        guild = self.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if not isinstance(channel, (discord.TextChannel, discord.VoiceChannel)):
            return
        hook = self.webhooks.get(channel_id)
        if not hook:
            hooks = await channel.webhooks()
            hook = next((item for item in hooks if item.name == "StreamBridge"), None)
            if not hook:
                hook = await channel.create_webhook(name="StreamBridge", reason="Cross-platform relay")
            self.webhooks[channel_id] = hook
        try:
            await hook.send(content, username=webhook_username(display_name, platform), avatar_url=avatar_url or None, allowed_mentions=discord.AllowedMentions.none(), wait=True)
        except discord.NotFound:
            self.webhooks.pop(channel_id, None)
            raise

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id or not message.guild:
            return
        guild_id = str(message.guild.id)
        config = self.store.get(guild_id)
        if (
            not config
            or not self.store.get_setting(guild_id, "discord_enabled", True)
            or not self.store.get_setting(guild_id, "discord_forward_enabled", True)
            or str(message.channel.id) not in config.channel_ids
        ):
            return
        payload = to_ssn_message(message)
        if not (payload["chatmessage"] or payload["contentimg"]):
            return
        key = self.store.claim_event(guild_id, "discord", str(payload["id"]), str(message.author.id), payload["chatmessage"], int(message.created_at.timestamp()))
        if not key:
            return
        ssn = self.get_ssn(message.guild.id, config) if config.session_id else None
        if ssn and ssn.connected:
            await ssn.inject(payload)
            relay_text = to_ssn_relay_text(payload)
            for target in config.relay_targets:
                if self.store.claim_delivery(guild_id, key, target):
                    self.ssn_reflections.setdefault(
                        message.guild.id,
                        ReflectionTracker(),
                    ).add(target, relay_text)
                    await ssn.send_chat(target, relay_text)
        else:
            await self.send_direct(message.guild.id, to_relay_text(payload, self.direct_template(message.guild.id)))

    async def close(self) -> None:
        if self.history_task:
            self.history_task.cancel()
            await asyncio.gather(self.history_task, return_exceptions=True)
        await asyncio.gather(*(client.close() for client in self.ssn_clients.values()), return_exceptions=True)
        await asyncio.gather(*(hub.close() for hub in self.direct_hubs.values()), return_exceptions=True)
        await self.web.close()
        await self.kick.close()
        self.store.close()
        await super().close()


bot = StreamBridge()
admin = app_commands.default_permissions(administrator=True)
ssn_group = app_commands.Group(
    name="ssn",
    description="Configure the optional Social Stream Ninja connection",
    default_permissions=discord.Permissions(administrator=True),
)


@ssn_group.command(name="connect", description="Connect this server to a Social Stream Ninja session")
@app_commands.describe(
    session_id="The SSN session ID that StreamBridge should join",
    relay_targets="Comma-separated platforms SSN should relay messages to",
)
async def ssn_connect(i: discord.Interaction, session_id: str, relay_targets: str = "twitch,youtube,kick,tiktok") -> None:
    assert i.guild_id
    targets = parse_list(relay_targets)
    bot.store.set_session(str(i.guild_id), session_id.strip(), targets)
    bot.store.update_workspace_ssn_for_guild(str(i.guild_id), session_id.strip(), targets)
    await bot.reset_ssn(i.guild_id)
    config = bot.store.get(str(i.guild_id))
    if config:
        bot.get_ssn(i.guild_id, config)
    await i.response.send_message("SSN session and relay targets saved.", ephemeral=True)


@ssn_group.command(name="disconnect", description="Disconnect SSN without removing direct platform connections")
async def ssn_disconnect(i: discord.Interaction) -> None:
    assert i.guild_id
    bot.store.clear_session(str(i.guild_id))
    bot.store.update_workspace_ssn_for_guild(str(i.guild_id), None, [])
    await bot.reset_ssn(i.guild_id)
    await i.response.send_message("SSN disconnected.", ephemeral=True)


bot.tree.add_command(ssn_group)


channel_group = app_commands.Group(name="channel", description="Configure the shared Discord relay channel", default_permissions=discord.Permissions(administrator=True))


@channel_group.command(name="set", description="Choose the Discord relay channel and its relay directions")
@app_commands.describe(
    channel="The text channel or voice-channel side chat used for Discord relay",
    forward="Forward messages from this Discord channel to streaming platforms",
    receive="Send streaming-platform messages to this Discord channel",
)
async def channel_set(
    i: discord.Interaction,
    channel: discord.TextChannel | discord.VoiceChannel,
    forward: bool,
    receive: bool,
) -> None:
    assert i.guild_id
    guild_id = str(i.guild_id)
    bot.store.clear_channels(guild_id)
    bot.store.add_channel(guild_id, str(channel.id))
    bot.store.set_setting(guild_id, "discord_relay_channel_id", str(channel.id))
    bot.store.set_setting(guild_id, "discord_enabled", forward or receive)
    bot.store.set_setting(guild_id, "discord_forward_enabled", forward)
    bot.store.set_setting(guild_id, "discord_receive_enabled", receive)
    await i.response.send_message(
        f"Discord relay channel set to {channel.mention}. "
        f"Forwarding: {'`enabled`' if forward else '`disabled`'}. "
        f"Receiving: {'`enabled`' if receive else '`disabled`'}.",
        ephemeral=True,
    )


@channel_group.command(name="remove", description="Disable Discord relay without clearing its saved channel or directions")
async def channel_remove(i: discord.Interaction) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "discord_enabled", False)
    await i.response.send_message(
        "Discord relay is disabled. The saved channel and relay directions were retained.",
        ephemeral=True,
    )


bot.tree.add_command(channel_group)

direct_group = app_commands.Group(name="direct", description="Configure direct platform connections", default_permissions=discord.Permissions(administrator=True))


@direct_group.command(
    name="setup",
    description="Open the dashboard to configure direct platform connections",
)
async def direct_setup(i: discord.Interaction) -> None:
    await i.response.send_message(
        f"[Open the StreamBridge dashboard]({dashboard_url()}) to configure "
        "direct platform connections. Sign in, edit your bridge settings, "
        "and link platform accounts there.",
        ephemeral=True,
    )

async def set_direct_connection_enabled(
    i: discord.Interaction,
    platform: Literal["twitch", "youtube", "kick"],
    enabled: bool,
) -> None:
    assert i.guild_id
    workspace = bot.workspace_for_guild(i.guild_id)
    connection = next(
        (item for item in workspace["connections"] if item["provider"] == platform),
        None,
    ) if workspace else None
    if not workspace or not connection:
        if enabled:
            message = f"You must first connect your {platform.title()} account using `/direct setup`."
        else:
            message = f"Direct {platform.title()} is already disabled."
        await i.response.send_message(message, ephemeral=True)
        return
    if bool(connection["enabled"]) == enabled:
        state = "enabled" if enabled else "disabled"
        await i.response.send_message(f"Direct {platform.title()} is already {state}.", ephemeral=True)
        return
    if enabled:
        try:
            bot.store.set_workspace_connection(
                str(workspace["owner_user_id"]),
                str(workspace["id"]),
                platform,
                str(connection["provider_user_id"]),
                True,
                dict(connection["settings"]),
            )
        except PermissionError:
            await i.response.send_message(
                f"You must first connect your {platform.title()} account using `/direct setup`.",
                ephemeral=True,
            )
            return
    else:
        bot.store.set_workspace_connection_enabled(str(workspace["id"]), platform, False)
    await bot.reload_workspace(str(workspace["id"]))
    state = "enabled" if enabled else "disabled"
    await i.response.send_message(
        f"Direct {platform.title()} {state}.{' Its linked account was retained.' if not enabled else '' }",
        ephemeral=True,
    )


@direct_group.command(name="enable", description="Enable a previously linked direct platform connection")
@app_commands.describe(platform="The direct platform connection to enable")
async def direct_enable(i: discord.Interaction, platform: Literal["twitch", "youtube", "kick"]) -> None:
    await set_direct_connection_enabled(i, platform, True)


@direct_group.command(name="disable", description="Disable one direct platform connection without unlinking its account")
@app_commands.describe(platform="The direct platform connection to disable")
async def direct_disable(i: discord.Interaction, platform: Literal["twitch", "youtube", "kick"]) -> None:
    await set_direct_connection_enabled(i, platform, False)


@direct_group.command(name="message", description="Set the message format used for direct relays when SSN is unavailable")
@app_commands.describe(template="Use {name}, {message}, and {platform}; leave blank to restore the default")
async def direct_message(i: discord.Interaction, template: str = "") -> None:
    assert i.guild_id
    try:
        checked = validate_direct_relay_template(template)
    except ValueError as error:
        await i.response.send_message(str(error), ephemeral=True)
        return
    guild_id = str(i.guild_id)
    bot.store.set_setting(guild_id, "direct_relay_template", checked)
    workspace = bot.workspace_for_guild(i.guild_id)
    if workspace:
        workspace["relay_template"] = checked
        bot.store.save_workspace(
            str(workspace["owner_user_id"]),
            workspace,
            str(workspace["id"]),
        )
    example = to_relay_text(
        {"chatname": "Alex", "chatmessage": "Hello!", "type": "twitch"},
        checked,
    )
    await i.response.send_message(
        f"Direct relay message saved. Example:\n{example}",
        ephemeral=True,
    )


@direct_group.command(name="youtubenotif", description="Enable or disable YouTube live-broadcast notifications")
@app_commands.describe(enabled="Whether the bot posts when it detects an active YouTube live broadcast")
async def direct_youtube_notifications(i: discord.Interaction, enabled: bool) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "youtube_live_notifications", enabled)
    state = "enabled" if enabled else "disabled"
    await i.response.send_message(
        f"YouTube live-broadcast notifications {state}.",
        ephemeral=True,
    )


bot.tree.add_command(direct_group)


@bot.tree.command(name="switchmessages", description="Enable or disable transport-switch messages")
@admin
@app_commands.describe(enabled="Whether Discord should announce switches between SSN and direct mode")
async def switch_messages(i: discord.Interaction, enabled: bool) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "transport_announcements", enabled)
    bot.store.update_workspace_announcements_for_guild(str(i.guild_id), enabled)
    await i.response.send_message(f"Transport-switch messages: {enabled}.", ephemeral=True)
@bot.tree.command(name="status", description="Show this server's StreamBridge connections and relay configuration")
@admin
async def status(i: discord.Interaction) -> None:
    assert i.guild_id
    c = bot.store.get(str(i.guild_id))
    session = c.session_id[:3] + "••••••" if c and c.session_id else "not set"
    channel_id = c.channel_ids[0] if c and c.channel_ids else c.discord_relay_channel_id if c else None
    discord_enabled = bool(bot.store.get_setting(str(i.guild_id), "discord_enabled", True))
    forward = bool(bot.store.get_setting(str(i.guild_id), "discord_forward_enabled", True))
    receive = bool(bot.store.get_setting(str(i.guild_id), "discord_receive_enabled", True))
    discord_status = format_discord_status(channel_id, discord_enabled, forward, receive)
    ssn_state = "connected" if i.guild_id in bot.ssn_clients and bot.ssn_clients[i.guild_id].connected else "disconnected"
    ssn_targets = ", ".join(c.relay_targets) if c and c.relay_targets else "none"
    direct_platforms = []
    for platform in bot.direct_platforms(i.guild_id):
        if platform == "twitch":
            hub = bot.direct_hubs.get(i.guild_id)
            adapter = hub.adapters.get("twitch") if hub else None
            twitch_channel = getattr(adapter, "channel", "")
            direct_platforms.append(f"twitch ({twitch_channel})" if twitch_channel else "twitch")
        elif platform == "youtube":
            direct_platforms.append(f"youtube ({bot.youtube.username(i.guild_id)})")
        elif platform == "kick":
            direct_platforms.append(f"kick ({bot.kick.username(i.guild_id)})")
    direct = ", ".join(direct_platforms) or "none"
    template = bot.direct_template(i.guild_id)
    await i.response.send_message(format_status(discord_status, session, ssn_state, ssn_targets, direct, template), ephemeral=True)
def main() -> None:
    missing = [x for x in ("DISCORD_TOKEN", "DISCORD_CLIENT_ID") if not os.getenv(x)]
    if missing:
        raise RuntimeError("Missing: " + ", ".join(missing))
    logging.basicConfig(level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO), format="%(asctime)s %(levelname)s %(name)s %(message)s")
    bot.run(os.environ["DISCORD_TOKEN"], log_handler=None)
