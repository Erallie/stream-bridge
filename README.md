# NinjaBridge

NinjaBridge connects Discord to Social Stream Ninja (SSN) and mirrors SSN platform chat into Discord with identity-aware webhook names and avatars. It contains no LLM and can run independently of any AI service.

## Install

Requires Python 3.11 or newer.

```powershell
python -m venv bot-env
bot-env\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
python -m ninjabridge
```

Enable Discord's **Message Content** and **Server Members** privileged intents. Invite with `bot` and `applications.commands`. Grant **View Channels**, **Read Message History**, **Add Reactions**, and **Send Messages** in configured Discord source channels. Grant **Manage Webhooks** in the platform-mirror channel.

In SSN enable:

1. **Enable remote API control of extension**.
2. **Send chat messages to API server** so NinjaBridge receives normalized chat on channel 4.
3. SSN's built-in relay if platform-to-platform relay is wanted.
4. Reflection/reply hiding if relayed copies should not appear again in the overlay.

Do not run a second independent relay system. SSN owns platform-to-platform relay; NinjaBridge explicitly relays Discord-originated messages through SSN because API-injected Discord messages have no captured browser tab.

## Core commands

- `/setup session_id relay_targets` connects SSN and sets destinations for Discord-originated messages.
- `/channel add|remove|clear` manages normal text channels and voice-channel side chats forwarded from Discord.
- `/relay-channel set|clear` selects the Discord text channel receiving identity-aware platform webhook messages.
- `/identity link|list` maps stable platform user IDs to a canonical name, avatar, and owner flag.
- `/status` shows the current configuration with a masked session ID.
- `/disable` disconnects SSN while retaining other settings.

## Optional NinjaMind companion

Run the separate **NinjaMind** project for local AI responses, per-person memory, mention handling, reactions, and ambient chatter. NinjaMind can use Discord by itself or optionally listen to the same SSN session.

## Relay and duplicate behavior

- Discord user messages are injected into the SSN overlay once, then sent to configured platforms using SSN's normal `Name said: message` relay format.
- Platform messages are relayed between platforms by SSN and mirrored to Discord by a `NinjaBridge` webhook using `Canonical Name (Platform)` and the canonical avatar.
- SSN messages marked `reflection` and bot messages are ignored by NinjaBridge.
- Processed events are unique by platform/message ID, with a content fingerprint fallback.
- Deliveries are unique by event/destination, preventing reconnects and retries from sending twice.
- Discord webhook messages and bot messages are ignored by the Discord listener.

Native Twitch, YouTube, Kick, and TikTok chats always display the connected relay account's avatar; those platforms do not permit per-message impersonation. Canonical per-person avatars are supported in Discord webhooks and can be used by a custom SSN overlay.

## Test

```powershell
python -m unittest discover -s tests -v
```

The SQLite migrations preserve the prior NinjaBridge database and migrate legacy single-channel entries automatically.
