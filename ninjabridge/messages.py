from __future__ import annotations

from typing import Any

import discord


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


def to_relay_text(payload: dict[str, Any]) -> str:
    return f"{payload['chatname']} said: {payload.get('chatmessage') or 'shared an image'}"
