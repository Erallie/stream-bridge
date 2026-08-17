# NinjaBridge

NinjaBridge connects Discord with streaming chats. It can connect directly to Twitch and YouTube without SSN, or automatically prefer Social Stream Ninja when a configured SSN session becomes reachable. SSN adds TikTok and its wider platform catalog. NinjaBridge contains no LLM, AI memory, or cross-platform identity-linking system.

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

SSN is optional. For direct Twitch, put `TWITCH_BOT_USERNAME` and a user OAuth token with chat read/write access in `.env`, then run `/direct twitch channel`. For direct YouTube, put a current OAuth access token with the YouTube scope in `YOUTUBE_ACCESS_TOKEN`, then run `/direct youtube live_chat_id`. Direct YouTube access tokens expire; production deployments should provide a refreshed token before restart.

When SSN connects, NinjaBridge ignores direct inbound copies and routes outbound messages through SSN. If SSN disconnects, direct Twitch/YouTube connections take over. By default the bot announces each switch in configured forward/receive channels; `/switchmessages enabled:false` disables those notices.

Kick's official incoming chat events require webhook delivery to a reachable HTTPS service, so a purely local direct Kick receiver is not included yet. TikTok does not currently provide a general approved LIVE-chat read/write API; TikTok remains SSN-only. NinjaBridge does not use private or scraped platform endpoints.

## Core commands

- `/setup session_id relay_targets` connects SSN and sets destinations for Discord-originated messages.
- `/forward add`, `/forward remove`, and `/forward clear` manage the Discord text channels and voice-channel side chats forwarded into SSN.
- `/receive set` and `/receive clear` select or clear the Discord text channel or voice-channel side chat that receives platform messages from SSN.
- `/direct twitch`, `/direct youtube`, and `/direct disable` configure direct connections used without SSN.
- `/switchmessages` enables or disables announcements when transport changes.
- `/status` shows the current configuration with a masked session ID.
- `/disable` disconnects SSN while retaining other settings.

The direction words describe Discord's role: **forward** means Discord → active streaming transport, while **receive** means streaming platforms → Discord. Both features are optional and may be enabled independently.

The same Discord channel may be configured for both directions. NinjaBridge ignores its own bot and webhook messages, so received SSN messages are not forwarded back into SSN.

## Optional NinjaMind companion

Run the separate **NinjaMind** project for local AI responses, cross-platform identity linking, per-person memory, mention handling, reactions, and ambient chatter. NinjaMind can use Discord by itself or optionally listen to the same SSN session.

## Relay and duplicate behavior

- Discord user messages are injected into the SSN overlay once, then sent to configured platforms using SSN's normal `Name said: message` relay format.
- Platform messages are relayed between platforms by SSN and mirrored to Discord by a `NinjaBridge` webhook using `Platform Name (Platform)` and the platform-provided avatar.
- SSN messages marked `reflection` and bot messages are ignored by NinjaBridge.
- Processed events are unique by platform/message ID, with a content fingerprint fallback.
- Deliveries are unique by event/destination, preventing reconnects and retries from sending twice.
- Discord webhook messages and bot messages are ignored by the Discord listener.

Native Twitch, YouTube, Kick, and TikTok chats always display the connected relay account's avatar; those platforms do not permit per-message impersonation. Canonical identities and shared AI memory are handled exclusively by NinjaMind.

## Test

```powershell
python -m unittest discover -s tests -v
```

The SQLite migrations preserve the prior NinjaBridge database and migrate legacy single-channel entries automatically.
