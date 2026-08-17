# NinjaBridge

Bridge Discord chat into Social Stream Ninja. NinjaBridge supports multiple Discord servers, multiple configured channels per server, normal text channels, and voice-channel side chats.

## Requirements

- Python 3.11 or newer
- A Discord bot with **Message Content Intent** enabled
- Discord OAuth scopes `bot` and `applications.commands`
- **View Channels** and **Read Message History** in each forwarded channel

## Installation

    python -m venv .venv
    .venv\Scripts\activate
    python -m pip install -r requirements.txt
    copy .env.example .env

Fill in `DISCORD_TOKEN` and `DISCORD_CLIENT_ID`, then run:

    python -m ninjabridge

On macOS or Linux, activate the environment with `source .venv/bin/activate` instead.

## Commands

- `/setup session-id:YOUR_SESSION_ID` saves the server's SSN session. `relay-targets` is optional.
- `/channel add` adds a normal text channel or a voice-channel side chat. Repeat for multiple channels.
- `/channel remove` removes one channel.
- `/channel clear` removes every configured channel.
- `/status` privately displays the current channels, masked session ID, and relay targets.
- `/disable` removes the SSN session and stops forwarding while retaining the channel list.

Only Discord administrators can use these commands. Responses are ephemeral.

In SSN, enable **remote API control** and open the matching dock or overlay in server mode, such as `?session=YOUR_ID&server`.

## Data and passwords

Configuration is stored in `data/bot.sqlite`. The existing Node.js database schema is supported and single-channel entries are migrated automatically.

SSN's WebSocket server API uses the session ID and has no password field. SSN's optional password applies to its peer-to-peer transport, so NinjaBridge does not request or store it. Treat the session ID as a secret.

## Tests

    python -m unittest discover -s tests -v

Sources: [SSN API](https://github.com/steveseguin/social_stream/blob/main/api.md), [Discord adapter](https://github.com/steveseguin/social_stream/blob/main/sources/discord.js), and [message/relay processing](https://github.com/steveseguin/social_stream/blob/main/background.js).
