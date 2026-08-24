from __future__ import annotations

import string
import html
import re
from html.parser import HTMLParser
from typing import Any

import discord

DEFAULT_DIRECT_RELAY_TEMPLATE = "{name}: {message} (from {platform})"
DIRECT_RELAY_FIELDS = frozenset({"name", "message", "platform"})
DISCORD_TOKEN = re.compile(r"<(?:(a?):([A-Za-z0-9_]+):(\d+)|@!?([0-9]+)|@&([0-9]+)|#([0-9]+))>")


class _SsnTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.ignored_depth += 1
        elif self.ignored_depth == 0 and tag == "img":
            attributes = dict(attrs)
            self.parts.append(attributes.get("alt") or attributes.get("title") or "")
        elif self.ignored_depth == 0 and tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.ignored_depth:
            self.ignored_depth -= 1

    def handle_data(self, data: str) -> None:
        if self.ignored_depth == 0:
            self.parts.append(data)


def ssn_to_plain_text(value: str) -> str:
    """Decode SSN's HTML entities and retain readable custom-emote alt text."""
    parser = _SsnTextParser()
    try:
        parser.feed(value)
        parser.close()
    except Exception:
        return html.unescape(value)
    return "".join(parser.parts)


def render_discord_content(
    content: str,
    users: dict[str, str] | None = None,
    roles: dict[str, str] | None = None,
    channels: dict[str, str] | None = None,
) -> tuple[str, bool]:
    """Convert Discord custom emojis to SSN-safe image markup."""
    users, roles, channels = users or {}, roles or {}, channels or {}
    output: list[str] = []
    cursor = 0
    has_custom_emote = False
    for match in DISCORD_TOKEN.finditer(content):
        output.append(html.escape(content[cursor:match.start()]))
        animated, emote_name, emote_id, user_id, role_id, channel_id = match.groups()
        if emote_id:
            has_custom_emote = True
            extension = "gif" if animated else "png"
            safe_name = html.escape(emote_name, quote=True)
            url = f"https://cdn.discordapp.com/emojis/{emote_id}.{extension}?size=128&quality=lossless"
            output.append(f'<img class="regular-emote" src="{html.escape(url, quote=True)}" alt=":{safe_name}:" title=":{safe_name}:">')
        elif user_id:
            output.append(html.escape("@" + users.get(user_id, user_id)))
        elif role_id:
            output.append(html.escape("@" + roles.get(role_id, role_id)))
        else:
            output.append(html.escape("#" + channels.get(channel_id or "", channel_id or "")))
        cursor = match.end()
    output.append(html.escape(content[cursor:]))
    return "".join(output), has_custom_emote


def discord_to_plain_content(
    content: str,
    users: dict[str, str] | None = None,
    roles: dict[str, str] | None = None,
    channels: dict[str, str] | None = None,
) -> str:
    """Convert Discord markup to portable chat text, using bare custom-emote names."""
    users, roles, channels = users or {}, roles or {}, channels or {}
    output: list[str] = []
    cursor = 0
    for match in DISCORD_TOKEN.finditer(content):
        output.append(content[cursor:match.start()])
        _, emote_name, emote_id, user_id, role_id, channel_id = match.groups()
        if emote_id:
            output.append(emote_name)
        elif user_id:
            output.append("@" + users.get(user_id, user_id))
        elif role_id:
            output.append("@" + roles.get(role_id, role_id))
        else:
            output.append("#" + channels.get(channel_id or "", channel_id or ""))
        cursor = match.end()
    output.append(content[cursor:])
    return "".join(output)


def to_ssn_message(message: discord.Message) -> dict[str, Any]:
    display_name = message.author.display_name
    image = next(
        (item.url for item in message.attachments if item.content_type and item.content_type.startswith("image/")),
        "",
    )
    name_color = ""
    if isinstance(message.author, discord.Member) and message.author.color.value:
        name_color = str(message.author.color)
    users = {str(user.id): user.display_name for user in message.mentions}
    roles = {str(role.id): role.name for role in message.role_mentions}
    channels = {str(channel.id): channel.name for channel in message.channel_mentions}
    rendered, has_custom_emote = render_discord_content(message.content or "", users, roles, channels)
    plain_text = discord_to_plain_content(message.content or "", users, roles, channels)

    return {
        "id": f"discord-{message.id}",
        "chatname": display_name,
        "chatbadges": "",
        "backgroundColor": "",
        "textColor": "",
        "chatmessage": rendered if has_custom_emote else plain_text,
        "plainText": plain_text,
        "chatimg": message.author.display_avatar.replace(size=128, format="png").url,
        "nameColor": name_color,
        "hasDonation": "",
        "membership": "",
        "contentimg": image,
        "textonly": not has_custom_emote,
        "type": "discord",
        "userid": str(message.author.id),
        "sourceName": message.guild.name if message.guild else "Discord",
        "timestamp": int(message.created_at.timestamp()),
    }


def validate_direct_relay_template(template: str) -> str:
    template = template.strip()
    if not template:
        return DEFAULT_DIRECT_RELAY_TEMPLATE
    if len(template) > 400:
        raise ValueError("The template cannot exceed 400 characters.")
    fields: set[str] = set()
    try:
        for _, field, spec, conversion in string.Formatter().parse(template):
            if field is None:
                continue
            if field not in DIRECT_RELAY_FIELDS:
                raise ValueError(f"Unsupported placeholder: {{{field}}}.")
            if spec or conversion:
                raise ValueError("Placeholder formatting and conversions are not supported.")
            fields.add(field)
    except ValueError as error:
        if str(error).startswith(("Unsupported", "Placeholder")):
            raise
        raise ValueError("The template contains unmatched braces.") from error
    if "message" not in fields:
        raise ValueError("The template must contain {message}.")
    return template


def to_relay_text(payload: dict[str, Any], template: str = DEFAULT_DIRECT_RELAY_TEMPLATE) -> str:
    template = validate_direct_relay_template(template)
    values = {
        "name": str(payload.get("chatname") or payload.get("username") or "Unknown"),
        "message": str(payload.get("plainText") or payload.get("chatmessage") or "shared an image"),
        "platform": str(payload.get("type") or "unknown").title(),
    }
    return template.format_map(values)


def to_ssn_relay_text(payload: dict[str, Any]) -> str:
    """Format an SSN-connected relay the same way StreamBridge historically did."""
    name = str(payload.get("chatname") or payload.get("username") or "Unknown")
    message = str(
        payload.get("plainText")
        or ssn_to_plain_text(str(payload.get("chatmessage") or ""))
        or "shared an image"
    )
    return f"{name} said: {message}"
