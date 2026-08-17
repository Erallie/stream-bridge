# NinjaBridge

Bridge Discord chat into Social Stream Ninja.

A multi-server Discord bot that forwards an administrator-selected text channel or voice-channel side chat into each server's own Social Stream Ninja (SSN) session.

## Bot-owner setup

1. Install Node.js 20 or newer.
2. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications), enable **Message Content Intent**, and invite it with the `bot` and `applications.commands` scopes.
3. Copy `.env.example` to `.env` and fill in `DISCORD_TOKEN` and `DISCORD_CLIENT_ID`.
4. Run `npm install`, then `npm start`.

`DISCORD_GUILD_ID` is useful during development because commands appear immediately in that server. Remove it for a public bot using global commands.

## Setup for each Discord server

Only administrators can use these commands, and every response is private:

- `/setup session-id:YOUR_SESSION_ID` saves that server's SSN session. Optionally provide `relay-targets:twitch,youtube,kick`.
- `/channel add channel:#your-channel` adds a normal text channel or voice-channel side chat. Run it again to add more channels.
- `/channel remove channel:#your-channel` removes one configured channel.
- `/channel clear` removes all configured channels.
- `/status` shows every configured channel, a masked session ID, and current relay settings.
- `/disable` removes the session ID and stops forwarding while retaining the channel list.

In SSN, enable **remote API control** and open the matching dock/overlay in server mode, such as `?session=YOUR_ID&server`.

Configuration is stored in `data/bot.sqlite`, a SQLite database excluded from Git. It holds Discord server IDs, selected channel IDs, SSN session IDs, and relay target names.

## Why there is no password command

SSN has an optional password for its peer-to-peer VDO.Ninja transport. The documented SSN server/WebSocket API used by this bot joins with the session ID and has no password field. Asking for and storing that password would therefore add risk without authenticating this integration. Treat the session ID as a secret because the SSN API currently relies on it.

## Relay-chat behavior

SSN API `extContent` reaches overlays, but SSN's current `relayall` path requires a captured source browser tab. API-injected Discord messages have no source tab. If relay is wanted, administrators can set `relay-targets` during `/ssn setup`; the bot issues SSN `sendChat` commands to those SSN-connected platforms and stores no platform credentials.

## Reliability and verification

- Uses native-looking SSN Discord message fields through `extContent`.
- Uses one reconnecting SSN connection per active Discord server, heartbeat pings, exponential backoff, and bounded queues.
- Ignores bot and webhook messages to prevent loops.
- Run `npm run check` and `npm test` before deployment.

Sources: [SSN API](https://github.com/steveseguin/social_stream/blob/main/api.md), [Discord adapter](https://github.com/steveseguin/social_stream/blob/main/sources/discord.js), and [message/relay processing](https://github.com/steveseguin/social_stream/blob/main/background.js).
