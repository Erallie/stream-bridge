# StreamBridge

StreamBridge connects your Discord server’s conversations with livestream chats across Twitch, YouTube, Kick, and platforms supported through Social Stream Ninja.

Messages can travel in both directions:

- Send messages from selected Discord channels to your streaming chats.
- Display messages from streaming platforms inside a selected Discord channel.
- Relay messages between connected streaming platforms.
- Use normal Discord text channels or the text chat attached to a voice channel.

StreamBridge can connect directly to Twitch, YouTube, and Kick. It can also integrate with Social Stream Ninja for additional platform support, including TikTok.

## Main features

- **Cross-platform chat relay** — Relay messages between Discord, Twitch, YouTube, and Kick, with additional platforms such as TikTok available through Social Stream Ninja.

- **Two-way Discord integration** — Send messages from Discord to streaming chats and display streaming-platform messages in Discord.

- **Multiple forwarding channels** — Configure any number of Discord channels as message sources.

- **Native-looking Discord messages** — Messages received from streaming platforms use webhooks to display the chatter’s name, source platform, and profile image when available.

- **Social Stream Ninja integration** — Connect StreamBridge to an SSN session for additional platforms.

- **Automatic transport switching** — Prefer Social Stream Ninja when it is available and return to direct platform connections when SSN goes offline.

- **Custom relay templates** — Customize direct relay messages using `{name}`, `{message}`, and `{platform}` placeholders.

- **Discord custom-emote support** — Render Discord custom emotes through Social Stream Ninja and convert them into readable emote names for direct platform relay.

- **Duplicate and echo prevention** — Track message IDs, delivery history, and recently relayed messages to reduce duplicate posts, reflections, and relay loops.

### Cross-platform chat relay

StreamBridge can relay conversations between:

- Discord
- Twitch
- YouTube
- Kick
- Other platforms supported by your Social Stream Ninja session

When direct connections are active, messages received from one streaming platform can be forwarded to the other enabled platforms and Discord.

### Discord-to-stream forwarding

Administrators can select one or more Discord channels whose messages should be forwarded to streaming chats.

Both of these channel types are supported:

- Normal Discord text channels
- Voice-channel side chats

Adding a forwarding channel does not require you to receive streaming messages in that channel.

### Stream-to-Discord messages

Administrators can choose a Discord channel where Twitch, YouTube, Kick, and Social Stream Ninja messages appear.

Messages use Discord webhooks so that each message can display the original chatter’s:

- Display name
- Platform
- Profile image, when available
- Message content

The receiving channel may also be one of the channels used for forwarding.

### Direct connections and SSN support

StreamBridge supports two relay methods:

- **Direct mode:** StreamBridge connects directly to Twitch, YouTube, and Kick.
- **Social Stream Ninja mode:** StreamBridge sends messages through a configured Social Stream Ninja session.

If Social Stream Ninja becomes available, StreamBridge can switch to SSN automatically. If SSN goes offline, StreamBridge switches back to its configured direct connections.

### Duplicate and loop prevention

StreamBridge tracks sent and received messages to prevent relayed messages from repeatedly bouncing between Discord and streaming platforms.

### Discord custom emotes

When Social Stream Ninja is connected, Discord custom emotes can be sent to SSN as rendered emotes.

When StreamBridge uses direct platform connections, Discord custom emotes are converted into readable names. For example:

```text
<:erallieHeart:1529884213434777742>
```

becomes:

```text
erallieHeart
```

### Custom relay messages

Administrators can customize how messages appear when StreamBridge is using direct platform connections.

Available placeholders are:

- `{name}` — the original sender’s name
- `{message}` — the message
- `{platform}` — the source platform

For example:

```text
[{platform}] {name}: {message}
```

could produce:

```text
[Discord] Erika: Hello, everyone!
```

## Adding StreamBridge to your server

Use the official StreamBridge invitation link:

[Invite StreamBridge to Discord](https://discord.com/oauth2/authorize?client_id=1538972596165419069)

When inviting StreamBridge, select the server where you have permission to add bots.

StreamBridge should have these permissions in the channels it uses:

- View Channels
- Send Messages
- Read Message History
- Manage Webhooks
- Embed Links
- Attach Files

The **Manage Webhooks** permission is needed in the receiving channel so that streaming messages can retain their original names, platforms, and profile pictures.

StreamBridge’s configuration commands require the Discord **Administrator** permission.

## Recommended initial setup

A typical setup takes four steps:

1. Choose one or more Discord channels that send messages to streaming platforms.
2. Choose the Discord channel that receives streaming messages.
3. Open the StreamBridge dashboard, link your platform accounts once, and assign them to this server's bridge.
4. Run `/status` to verify everything.

For example:

```text
/forward add channel:#stream-chat
/receive set channel:#stream-chat
/direct setup
/status
```

You may use the same Discord channel for both `/forward add` and `/receive set`.

## Commands

All configuration responses and dashboard links are visible only to the administrator who ran the command.

### `/forward add`

Adds a Discord channel as a source for messages sent to streaming platforms.

```text
/forward add channel:#channel
```

You can run this command multiple times to forward more than one channel.

Supported channel types:

- Text channels
- Voice-channel side chats

Example:

```text
/forward add channel:#stream-chat
```

### `/forward remove`

Stops forwarding messages from one Discord channel.

```text
/forward remove channel:#channel
```

This does not affect other forwarding channels or messages received from streaming platforms.

### `/forward clear`

Removes every configured Discord forwarding channel.

```text
/forward clear
```

Afterward, streaming messages can still be received in Discord if a receiving channel is configured, but Discord messages will not be sent to the streaming platforms.

### `/receive set`

Chooses the Discord channel that receives messages from streaming platforms.

```text
/receive set channel:#channel
```

The selected channel may be a normal text channel or a voice-channel side chat.

It may also be one of the channels configured with `/forward add`.

### `/receive clear`

Stops sending streaming-platform messages into Discord.

```text
/receive clear
```

This does not disable platform connections or Discord-to-platform forwarding.

### `/direct setup`

Opens the dashboard, where you can link Twitch, Google/YouTube, or Kick and choose every direct connection for this server's bridge.

```text
/direct setup
```

Each platform is authorized once on its own website. The linked identity supplies the channel, posting identity, and renewable OAuth authorization.

### `/direct disable`

Opens the dashboard so you can disable or change direct platform connections.

```text
/direct disable
```

Disable the platform in the bridge's **Direct platform connections** section. Disabling one platform does not affect the others.

### `/direct message`

Opens the dashboard so you can change the format used for direct relay messages.

```text
/direct message
```

Available placeholders:

```text
{name}
{message}
{platform}
```

The dashboard template must contain all three placeholders.

The default format is:

```text
{name} said: {message}
```

### `/ssn connect`

Connects the Discord server to a Social Stream Ninja session.

```text
/ssn connect session_id:SESSION_ID relay_targets:PLATFORMS
```

`relay_targets` is a comma-separated list. For example:

```text
/ssn connect session_id:your-session-id relay_targets:twitch,youtube,kick,tiktok
```

If `relay_targets` is omitted, the default is:

```text
twitch,youtube,kick,tiktok
```

The Social Stream Ninja overlay-room password is not required. StreamBridge uses the SSN session ID.

The SSN session must be configured correctly by whoever operates that Social Stream Ninja session.

### `/ssn disconnect`

Disconnects the server from Social Stream Ninja.

```text
/ssn disconnect
```

This does not delete or disable direct Twitch, YouTube, or Kick connections. StreamBridge can resume direct relay using any direct platforms that remain configured.

### `/switchmessages`

Controls whether StreamBridge posts notices when it switches between SSN and direct mode.

Enable notices:

```text
/switchmessages enabled:true
```

Disable notices:

```text
/switchmessages enabled:false
```

If direct mode becomes active but no direct platform connections are configured, StreamBridge warns that messages will not be relayed.

### `/status`

Shows the server’s current StreamBridge configuration.

```text
/status
```

The status includes:

- Discord channels being forwarded
- Whether an SSN session is configured and connected
- Platforms assigned to SSN
- Directly connected platforms and accounts
- The current direct relay message template
- The Discord channel receiving platform messages

The SSN session ID is masked for privacy.

## Understanding forwarding and receiving

Forwarding and receiving are independent.

### Forwarding only

If you configure `/forward add` but not `/receive set`:

- Discord messages can be sent to streaming platforms.
- Streaming messages will not be displayed in Discord.

### Receiving only

If you configure `/receive set` but do not add forwarding channels:

- Streaming messages can appear in Discord.
- Discord messages will not be sent to streaming platforms.

### Both directions

If you configure both:

- Messages from selected Discord channels can be sent to streaming platforms.
- Messages from streaming platforms can appear in Discord.
- The same Discord channel may be used for both.

## Direct mode versus Social Stream Ninja

### Direct mode supports

- Twitch
- YouTube
- Kick

Direct mode continues working even when the computer running Social Stream Ninja is offline.

### Social Stream Ninja mode supports

- Twitch
- YouTube
- Kick
- Other platforms supported by the connected SSN session

When StreamBridge detects an active SSN host, it can let SSN handle the platform relay. When the SSN host stops responding, StreamBridge returns to direct mode.

The exact platforms available through SSN depend on the connected Social Stream Ninja setup.

## Web dashboard

The StreamBridge dashboard is the full configuration surface. People can manage Discord forwarding and receiving channels, SSN sessions and arbitrary SSN targets, transport announcements, direct relay templates, linked direct accounts, and Discord-backed or standalone workspaces. Settings changed with Discord commands appear automatically in the open dashboard. A standalone workspace does not require StreamBridge to be installed in a Discord server.

The public Svelte site contains no OAuth secrets. Authentication callbacks, encrypted tokens, sessions, workspace settings, and relay processes remain in this Pi-hosted StreamBridge service. Expose the existing local listener through Cloudflare Tunnel and configure:

```ini
DASHBOARD_SITE_URL=https://YOUR_SITE
DASHBOARD_ALLOWED_ORIGINS=https://YOUR_SITE
DASHBOARD_API_PUBLIC_URL=https://YOUR_STREAMBRIDGE_API_HOST
```

Register the following callbacks with their providers:

- `/dashboard/auth/discord/callback`
- `/dashboard/auth/google/callback`
- `/dashboard/auth/twitch/callback`
- `/dashboard/auth/kick/callback`

Prefix each path with `DASHBOARD_API_PUBLIC_URL`. These are the only OAuth callbacks StreamBridge uses. Discord dashboard sign-in also needs `DISCORD_CLIENT_SECRET`; Google reuses the YouTube client; Twitch and Kick reuse their existing application credentials. `TOKEN_ENCRYPTION_KEY` is required before any dashboard account can be linked.

## Privacy and authorization

Each platform account is authorized once through the dashboard and may then be assigned to bridges owned by the same dashboard account. Discord-backed bridges can only select servers where the signed-in Discord user has the Administrator permission or is the server owner.

Only authorize accounts you own or are permitted to manage.

StreamBridge does not need your Discord, Google, YouTube, Twitch, or Kick password. Authentication occurs on each platform's own website.

## Troubleshooting

### A command is not visible

Make sure:

- StreamBridge has been invited with the `applications.commands` authorization scope.
- You have the Discord Administrator permission.
- Discord has finished synchronizing the bot’s commands.

### StreamBridge cannot post in a channel

Check that it has:

- View Channel
- Send Messages
- Read Message History

For messages received from platforms, also grant:

- Manage Webhooks
- Embed Links
- Attach Files

### Streaming messages do not appear in Discord

Run:

```text
/status
```

Then verify:

- A receiving channel is shown.
- The desired direct platform is connected, or SSN is connected.
- StreamBridge has permission to view and post in the receiving channel.
- StreamBridge has permission to manage webhooks there.

### Discord messages are not sent to streaming platforms

Verify:

- The Discord channel was added with `/forward add`.
- At least one direct platform is connected, or SSN is connected.
- The message was not sent by another bot or by StreamBridge’s own webhook.
- StreamBridge can read the channel.

### YouTube is connected but no messages appear

The authorized YouTube channel must have an active livestream with live chat enabled. StreamBridge automatically waits for and discovers the active chat.

### The wrong platform account appears

Sign out of that platform in your browser, open a private/incognito window, sign into the intended broadcaster account, and link it again from the dashboard.

## Support

If you encounter a problem, include the following when requesting help:

- The command you ran
- The response StreamBridge displayed
- The output of `/status`
- The source and destination platforms involved
- Whether StreamBridge was using direct mode or Social Stream Ninja

Never share authorization links, access tokens, refresh tokens, client secrets, Discord bot tokens, or complete SSN session credentials in a public support channel.
