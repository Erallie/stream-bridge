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
from ninjabridge.messages import to_relay_text, to_ssn_message
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
        self.ssn_clients: dict[int, SsnClient] = {}
        self.ssn_url = os.getenv("SSN_WEBSOCKET_URL", "wss://io.socialstream.ninja")

    async def setup_hook(self) -> None:
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self) -> None:
        logging.info("NinjaBridge ready as %s", self.user)
        for config in self.store.configured_guilds():
            self.get_ssn(int(config.guild_id), config)

    async def reset_ssn(self, guild_id: int) -> None:
        client = self.ssn_clients.pop(guild_id, None)
        if client:
            await client.close()

    def get_ssn(self, guild_id: int, config: GuildConfig) -> SsnClient:
        if guild_id not in self.ssn_clients:
            async def received(data: dict[str, Any]) -> None:
                await self.handle_ssn(guild_id, data)
            logger = logging.LoggerAdapter(logging.getLogger("ninjabridge.ssn"), {"guild_id": guild_id})
            self.ssn_clients[guild_id] = SsnClient(self.ssn_url, config.session_id or "", config.relay_targets, logger, received)
            self.ssn_clients[guild_id].start()
        return self.ssn_clients[guild_id]

    async def handle_ssn(self, guild_id: int, data: dict[str, Any]) -> None:
        if data.get("reflection") or data.get("bot") or not data.get("chatname") or not data.get("chatmessage"):
            return
        platform = str(data.get("type", "unknown")).lower()
        user_id = str(data.get("userid") or data.get("chatname", ""))
        key = self.store.claim_event(str(guild_id), platform, str(data.get("id", "")), user_id, str(data["chatmessage"]), data.get("timestamp", int(time.time())))
        if not key:
            return
        identity = self.store.resolve_identity(str(guild_id), platform, user_id, str(data["chatname"]), str(data.get("chatimg", "")))
        config = self.store.get(str(guild_id))
        if config and config.discord_relay_channel_id and self.store.claim_delivery(str(guild_id), key, "discord"):
            await self.send_webhook(guild_id, int(config.discord_relay_channel_id), identity, platform, str(data["chatmessage"]))

    async def send_webhook(self, guild_id: int, channel_id: int, identity: dict[str, Any], platform: str, content: str) -> None:
        guild = self.get_guild(guild_id)
        channel = guild.get_channel(channel_id) if guild else None
        if not isinstance(channel, discord.TextChannel):
            return
        hooks = await channel.webhooks()
        hook = next((h for h in hooks if h.name == "NinjaBridge"), None)
        if not hook:
            hook = await channel.create_webhook(name="NinjaBridge", reason="Cross-platform relay")
        await hook.send(content, username=f"{identity['display_name']} ({platform.title()})"[:80], avatar_url=identity.get("avatar_url") or None, allowed_mentions=discord.AllowedMentions.none(), wait=True)

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.webhook_id or not message.guild:
            return
        guild_id = str(message.guild.id)
        config = self.store.get(guild_id)
        if not config or str(message.channel.id) not in config.channel_ids:
            return
        payload = to_ssn_message(message)
        if not config.session_id or not (payload["chatmessage"] or payload["contentimg"]):
            return
        key = self.store.claim_event(guild_id, "discord", str(message.id), str(message.author.id), payload["chatmessage"], int(message.created_at.timestamp()))
        if not key:
            return
        ssn = self.get_ssn(message.guild.id, config)
        await ssn.inject(payload)
        for target in config.relay_targets:
            if self.store.claim_delivery(guild_id, key, target):
                await ssn.send_chat(target, to_relay_text(payload))

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in self.ssn_clients.values()), return_exceptions=True)
        self.store.close()
        await super().close()


bot = NinjaBridge()
admin = app_commands.default_permissions(administrator=True)


@bot.tree.command(name="setup", description="Connect this server to Social Stream Ninja")
@admin
async def setup(i: discord.Interaction, session_id: str, relay_targets: str = "twitch,youtube,kick,tiktok") -> None:
    assert i.guild_id
    bot.store.set_session(str(i.guild_id), session_id.strip(), parse_list(relay_targets))
    await bot.reset_ssn(i.guild_id)
    await i.response.send_message("SSN session and relay targets saved.", ephemeral=True)


forward_group = app_commands.Group(name="forward", description="Choose Discord channels to forward to SSN", default_permissions=discord.Permissions(administrator=True))


@forward_group.command(name="add")
async def channel_add(i: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert i.guild_id
    changed = bot.store.add_channel(str(i.guild_id), str(channel.id))
    await i.response.send_message("Discord channel will now be forwarded to SSN." if changed else "That channel is already forwarded to SSN.", ephemeral=True)


@forward_group.command(name="remove")
async def channel_remove(i: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert i.guild_id
    changed = bot.store.remove_channel(str(i.guild_id), str(channel.id))
    await i.response.send_message("Discord channel will no longer be forwarded to SSN." if changed else "That channel was not being forwarded.", ephemeral=True)


@forward_group.command(name="clear")
async def channel_clear(i: discord.Interaction) -> None:
    assert i.guild_id
    await i.response.send_message(f"Stopped forwarding {bot.store.clear_channels(str(i.guild_id))} Discord channel(s) to SSN.", ephemeral=True)


bot.tree.add_command(forward_group)
receive_group = app_commands.Group(name="receive", description="Choose where Discord receives SSN platform messages", default_permissions=discord.Permissions(administrator=True))


@receive_group.command(name="set")
async def relay_set(i: discord.Interaction, channel: discord.TextChannel) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "discord_relay_channel_id", str(channel.id))
    await i.response.send_message(f"SSN platform messages will now be mirrored to {channel.mention}.", ephemeral=True)


@receive_group.command(name="clear")
async def relay_clear(i: discord.Interaction) -> None:
    assert i.guild_id
    bot.store.set_setting(str(i.guild_id), "discord_relay_channel_id", None)
    await i.response.send_message("SSN-to-Discord mirroring disabled.", ephemeral=True)


bot.tree.add_command(receive_group)
identity_group = app_commands.Group(name="identity", description="Manage cross-platform identities", default_permissions=discord.Permissions(administrator=True))


@identity_group.command(name="link")
async def identity_link(i: discord.Interaction, platform: str, user_id: str, display_name: str, avatar_url: str = "", owner: bool = False, handle: str = "") -> None:
    assert i.guild_id
    bot.store.link_identity(str(i.guild_id), platform, user_id, display_name, avatar_url, owner, handle)
    await i.response.send_message(f"Linked {platform}:{user_id} to {display_name}.", ephemeral=True)


@identity_group.command(name="list")
async def identity_list(i: discord.Interaction) -> None:
    assert i.guild_id
    rows = bot.store.identity_summary(str(i.guild_id))
    text = "\n".join(f"{r['display_name']} ← {r['platform']}:{r['platform_user_id']}" for r in rows) or "No identities."
    await i.response.send_message(text[:1900], ephemeral=True)


bot.tree.add_command(identity_group)


@bot.tree.command(name="status", description="Show NinjaBridge configuration")
@admin
async def status(i: discord.Interaction) -> None:
    assert i.guild_id
    c = bot.store.get(str(i.guild_id))
    session = c.session_id[:3] + "••••••" if c and c.session_id else "not set"
    channels = ", ".join(f"<#{x}>" for x in c.channel_ids) if c else "none"
    mirror = f"<#{c.discord_relay_channel_id}>" if c and c.discord_relay_channel_id else "off"
    await i.response.send_message(f"Discord channels forwarded to SSN: {channels}\nSession: {session}\nSSN platform mirror in Discord: {mirror}", ephemeral=True)


@bot.tree.command(name="disable", description="Disable SSN forwarding")
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
