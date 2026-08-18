from __future__ import annotations

import string
from typing import Any

import discord

DEFAULT_DIRECT_RELAY_TEMPLATE = "{name} said: {message}"
DIRECT_RELAY_FIELDS = frozenset({"name", "message", "platform"})


def to_ssn_message(message: discord.Message) -> dict[str, Any]:
    display_name = message.author.display_name
    image = next(
        (item.url for item in message.attachments if item.content_type and item.content_type.startswith("image/")),
        "",
    )
    name_color = ""
    if isinstance(message.author, discord.Member) and message.author.color.value:
        name_color = str(message.author.color)

    return {
        "id": f"discord-{message.id}",
        "chatname": display_name,
        "chatbadges": "",
        "backgroundColor": "",
        "textColor": "",
        "chatmessage": message.clean_content or message.content or "",
        "chatimg": message.author.display_avatar.replace(size=128, format="png").url,
        "nameColor": name_color,
        "hasDonation": "",
        "membership": "",
        "contentimg": image,
        "textonly": True,
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
        "message": str(payload.get("chatmessage") or "shared an image"),
        "platform": str(payload.get("type") or "unknown").title(),
    }
    return template.format_map(values)
