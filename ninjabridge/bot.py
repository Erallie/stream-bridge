from __future__ import annotations

import asyncio
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from ninjabridge.database import ConfigStore, GuildConfig
from ninjabridge.messages import to_ssn_message
from ninjabridge.ssn import SsnClient

load_dotenv()

def parse_relay_targets(value: str | None) -> list[str]:
    targets: list[str] = []
    for item in (value or "").split(","):
        target = item.strip().lower()
        if target and target != "discord" and target.replace("-", "").replace("_", "").isalnum() and target not in targets:
            targets.append(target)
    return targets


class NinjaBridge(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         application_id=int(os.environ["DISCORD_CLIENT_ID"]))
        self.store = ConfigStore(os.getenv("DATABASE_PATH", "./data/bot.sqlite"))
        self.ssn_clients: dict[int, SsnClient] = {}
        self.ssn_url = os.getenv("SSN_WEBSOCKET_URL", "wss://io.socialstream.ninja")

    async def setup_hook(self) -> None:
        guild_id = os.getenv("DISCORD_GUILD_ID")
        if guild_id:
            guild = discord.Object(id=int(guild_id))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Registered commands in development server %s", guild_id)
        else:
            await self.tree.sync()
            logging.info("Registered global commands")

    async def reset_ssn(self, guild_id: int) -> None:
        client = self.ssn_clients.pop(guild_id, None)
        if client:
            await client.close()

    def get_ssn(self, guild_id: int, config: GuildConfig) -> SsnClient:
        if guild_id not in self.ssn_clients:
            adapter = logging.LoggerAdapter(logging.getLogger("ninjabridge.ssn"), {"guild_id": guild_id})
            client = SsnClient(self.ssn_url, config.session_id or "", config.relay_targets, adapter)
            client.start()
            self.ssn_clients[guild_id] = client
        return self.ssn_clients[guild_id]

    async def close(self) -> None:
        await asyncio.gather(*(client.close() for client in self.ssn_clients.values()), return_exceptions=True)
        self.store.close()
        await super().close()


bot = NinjaBridge()
admin_only = app_commands.default_permissions(administrator=True)


@bot.tree.command(name="setup", description="Connect this server to Social Stream Ninja")
@admin_only
@app_commands.describe(session_id="Session value from your SSN URL", relay_targets="Optional: twitch,youtube,kick")
async def setup(interaction: discord.Interaction, session_id: str, relay_targets: str | None = None) -> None:
    assert interaction.guild_id is not None
    targets = parse_relay_targets(relay_targets)
    bot.store.set_session(str(interaction.guild_id), session_id.strip(), targets)
    await bot.reset_ssn(interaction.guild_id)
    await interaction.response.send_message(
        f"SSN session saved. Relay fallback: {', '.join(targets) or 'off'}.", ephemeral=True
    )


channel_group = app_commands.Group(name="channel", description="Manage channels forwarded to Social Stream Ninja",
                                   default_permissions=discord.Permissions(administrator=True))


@channel_group.command(name="add", description="Add a text channel or voice-channel side chat")
async def channel_add(interaction: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert interaction.guild_id is not None
    changed = bot.store.add_channel(str(interaction.guild_id), str(channel.id))
    text = f"Added {channel.mention}." if changed else f"{channel.mention} is already configured."
    await interaction.response.send_message(text, ephemeral=True)


@channel_group.command(name="remove", description="Remove one configured channel")
async def channel_remove(interaction: discord.Interaction, channel: discord.TextChannel | discord.VoiceChannel) -> None:
    assert interaction.guild_id is not None
    changed = bot.store.remove_channel(str(interaction.guild_id), str(channel.id))
    text = f"Removed {channel.mention}." if changed else f"{channel.mention} was not configured."
    await interaction.response.send_message(text, ephemeral=True)


@channel_group.command(name="clear", description="Remove all configured channels")
async def channel_clear(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    count = bot.store.clear_channels(str(interaction.guild_id))
    await interaction.response.send_message(f"Removed {count} configured channel(s).", ephemeral=True)


bot.tree.add_command(channel_group)


@bot.tree.command(name="status", description="Show this server's NinjaBridge configuration")
@admin_only
async def status(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    config = bot.store.get(str(interaction.guild_id))
    channels = ", ".join(f"<#{channel_id}>" for channel_id in config.channel_ids) if config and config.channel_ids else "none"
    session = "not set"
    if config and config.session_id:
        session = config.session_id[:3] + "•" * min(8, max(0, len(config.session_id) - 3))
    targets = ", ".join(config.relay_targets) if config and config.relay_targets else "off"
    await interaction.response.send_message(
        f"Channels: {channels}\nSession: {session}\nRelay fallback: {targets}", ephemeral=True
    )


@bot.tree.command(name="disable", description="Remove this server's SSN session and stop forwarding")
@admin_only
async def disable(interaction: discord.Interaction) -> None:
    assert interaction.guild_id is not None
    bot.store.clear_session(str(interaction.guild_id))
    await bot.reset_ssn(interaction.guild_id)
    await interaction.response.send_message("SSN forwarding is disabled for this server.", ephemeral=True)


@bot.event
async def on_ready() -> None:
    logging.info("NinjaBridge is ready as %s", bot.user)


@bot.event
async def on_message(message: discord.Message) -> None:
    if not message.guild or message.author.bot or message.webhook_id:
        return
    config = bot.store.get(str(message.guild.id))
    if not config or not config.session_id or str(message.channel.id) not in config.channel_ids:
        return
    payload = to_ssn_message(message)
    if not payload["chatmessage"] and not payload["contentimg"]:
        return
    await bot.get_ssn(message.guild.id, config).publish(payload)
    logging.info("Forwarded Discord message %s from guild %s", message.id, message.guild.id)


def main() -> None:
    missing = [name for name in ("DISCORD_TOKEN", "DISCORD_CLIENT_ID") if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    bot.run(os.environ["DISCORD_TOKEN"], log_handler=None)
