# StreamBridge

StreamBridge keeps livestream communities in one conversation by relaying chat between Twitch, YouTube, Kick, Discord, and platforms supported through Social Stream Ninja.

It works as a standalone streaming bridge, so a Discord server is not required. If a community also uses Discord, StreamBridge can optionally connect one Discord channel to the same conversation.

Messages can travel between every enabled destination:

- Relay Twitch, YouTube, and Kick chat directly between platforms.
- Add other platforms, including TikTok, through Social Stream Ninja.
- Optionally send messages from Discord to streaming chats.
- Optionally display streaming chat inside a Discord text channel or voice-channel side chat.

StreamBridge can connect directly to Twitch, YouTube, and Kick. It can also integrate with Social Stream Ninja for additional platform support, including TikTok.

## Main features

- **Cross-platform chat relay** — Relay messages between Twitch, YouTube, and Kick, optionally include Discord, and reach additional platforms such as TikTok through Social Stream Ninja.

- **Standalone streaming bridge** — Relay chat between streaming platforms without installing StreamBridge in a Discord server.

- **Web dashboard** — Link accounts and configure the bridge from one place, whether or not Discord is enabled.

- **Direct platform connections** — Connect Twitch, YouTube, and Kick directly so relay continues without a running Social Stream Ninja host.

- **Social Stream Ninja integration** — Connect an SSN session for additional platforms and destinations.

- **Automatic transport switching** — Prefer Social Stream Ninja when it is available and return to direct platform connections when SSN goes offline.

- **Two-way Discord integration** — Send messages from Discord to streaming chats and display streaming-platform messages in Discord.

- **One shared Discord relay channel** — Use one normal text channel or voice-channel side chat, with forwarding from Discord and receiving into Discord enabled independently.

- **Native-looking Discord messages** — Messages received from streaming platforms use webhooks to display the chatter’s name, source platform, and profile image when available.

- **Custom relay templates** — Customize direct relay messages using `{name}`, `{message}`, and `{platform}` placeholders.

- **Discord custom-emote support** — Render Discord custom emotes through Social Stream Ninja and convert them into readable emote names for direct platform relay.

- **Duplicate and echo prevention** — Track message IDs, delivery history, and recently relayed messages to reduce duplicate posts, reflections, and relay loops.

### Cross-platform chat relay

StreamBridge can relay conversations between:

- Twitch
- YouTube
- Kick
- Discord
- Other platforms supported by your Social Stream Ninja session

When direct connections are active, messages received from one streaming platform can be forwarded to every other enabled streaming platform. Discord participates only when it has been linked and enabled for the bridge.

## Getting started

A typical standalone setup is managed entirely through the StreamBridge dashboard:

1. Open the [StreamBridge dashboard](https://streambridge.gozarproductions.com/dashboard).
2. Sign in with Discord, Google/YouTube, Twitch, or Kick.
3. Link the other platform accounts the bridge should use.
4. Enable Twitch, Kick, and/or YouTube under **Direct Connection**.
5. Optionally connect a Social Stream Ninja session and choose its platform targets.
6. Save the bridge.

Once two or more destinations are enabled, StreamBridge can relay messages between them. Discord is optional and can be linked later without rebuilding the streaming-platform configuration.

Each dashboard account has one bridge. Linked identities can be disconnected later, although another sign-in method must remain linked before the final identity can be disconnected.

## Optional Discord integration

### Discord-to-stream forwarding

Administrators can select one shared Discord relay channel whose messages may be forwarded to streaming chats.

Both of these channel types are supported:

- Normal Discord text channels
- Voice-channel side chats

Forwarding from Discord and receiving into Discord are independent settings. Either direction can be disabled without clearing the selected channel.

### Stream-to-Discord messages

Administrators can use the shared Discord relay channel for Twitch, YouTube, Kick, and Social Stream Ninja messages.

Messages use Discord webhooks so that each message can display the original chatter’s:

- Display name
- Platform
- Profile image, when available
- Message content

The same saved channel is used for both directions when both are enabled.

## Direct connections and SSN support

StreamBridge supports two relay methods:

- **Direct mode:** StreamBridge connects directly to Twitch, YouTube, and Kick.
- **Social Stream Ninja mode:** StreamBridge sends messages through a configured Social Stream Ninja session.

If Social Stream Ninja becomes available, StreamBridge can switch to SSN automatically. If SSN goes offline, StreamBridge switches back to its configured direct connections.

### Duplicate and loop prevention

StreamBridge tracks sent and received messages to prevent relayed messages from repeatedly bouncing between Discord and streaming platforms.

Messages posted through a user-authorized Twitch or YouTube broadcaster account are suppressed only when they match a message StreamBridge recently sent. Manually written broadcaster messages remain eligible for relay. Where a platform provides a distinct StreamBridge bot identity, such as Kick, messages from that bot identity can be suppressed directly.

## Discord emote handling

When Social Stream Ninja is connected, Discord custom emotes can be sent to SSN as rendered emotes.

When StreamBridge uses direct platform connections, Discord custom emotes are converted into readable names. For example:

```text
<:erallieHeart:1529884213434777742>
```

becomes:

```text
erallieHeart
```

## Custom relay messages

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

## Adding StreamBridge to Discord

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

The **Manage Webhooks** permission is needed in the shared relay channel when receiving is enabled so that streaming messages can retain their original names, platforms, and profile pictures.

StreamBridge’s configuration commands require the Discord **Administrator** permission.

### Discord setup example

After completing the dashboard setup, Discord can be added in four steps:

1. Choose the shared Discord relay channel.
2. Enable forwarding from Discord, receiving into Discord, or both.
3. Open the StreamBridge dashboard and enable Discord for the existing bridge.
4. Run `/status` to verify everything.

For example:

```text
/channel set channel:#stream-chat forward:true receive:true
/direct setup
/status
```

`/channel set` selects the shared channel and configures both relay directions at once.

## Discord commands

These commands are available only when StreamBridge is installed in a Discord server. All configuration responses and dashboard links are visible only to the administrator who ran the command. Standalone users can configure the same bridge features through the dashboard without using commands.

### `/channel set`

Chooses the shared Discord relay channel and configures whether messages travel from Discord, to Discord, or both.

```text
/channel set channel:#channel forward:true receive:true
```

Supported channel types:

- Text channels
- Voice-channel side chats

Example:

```text
/channel set channel:#stream-chat forward:true receive:true
```

Parameters:

- `channel` — A normal text channel or voice-channel side chat.
- `forward` — Whether Discord messages should be forwarded to enabled streaming platforms.
- `receive` — Whether streaming-platform messages should be sent to Discord.

Setting both directions to `false` saves the selected channel but leaves Discord relay disabled.

### `/channel remove`

Disables the Discord integration without clearing the saved channel or the saved Forward and Receive choices.

```text
/channel remove
```

Reconfiguring the integration with `/channel set` restores it using the newly selected direction choices.

### `/direct setup`

Opens the dashboard, where you can link Discord, Twitch, Google/YouTube, or Kick and choose direct connections for the bridge.

```text
/direct setup
```

Each platform is authorized once on its own website. Linked identities supply the account and renewable OAuth authorization used by the bridge. Twitch and YouTube currently post through the authorized broadcaster account; Kick posts through StreamBridge's dedicated Kick bot identity.

### `/direct disable`

Immediately disables one direct platform connection without unlinking its account.

```text
/direct disable platform:twitch
```

The `platform` option can be `twitch`, `kick`, or `youtube`. Disabling one platform does not affect the others. You can enable it again through the dashboard without authorizing the account again.

### `/direct message`

Immediately changes the format used for direct relay messages.

```text
/direct message template:{name}: {message} (from {platform})
```

Available placeholders:

```text
{name}
{message}
{platform}
```

The template must contain `{message}`. The `{name}` and `{platform}` placeholders are optional. Leave `template` blank to restore the default format.

The default format is:

```text
{name} ({platform}) said: {message}
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

- The shared Discord relay channel followed by `(forwarding/receiving)`, `(forwarding only)`, or `(receiving only)`; it displays `Disabled` when Discord integration is disabled
- Whether an SSN session is configured and connected
- Platforms assigned to SSN
- Directly connected platforms and accounts
- The current direct relay message template

The SSN session ID is masked for privacy.

## Understanding optional Discord forwarding and receiving

Forwarding and receiving are independent toggles that use the same saved Discord relay channel.

### Forwarding only

If you run `/channel set` with `forward:true` and `receive:false`:

- Discord messages can be sent to streaming platforms.
- Streaming messages will not be displayed in Discord.

### Receiving only

If you run `/channel set` with `forward:false` and `receive:true`:

- Streaming messages can appear in Discord.
- Discord messages will not be sent to streaming platforms.

### Both directions

If you configure both:

- Messages from the shared Discord relay channel can be sent to streaming platforms.
- Messages from streaming platforms can appear in Discord.
- Both directions use the same Discord channel.

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
- TikTok
- Facebook
- Instragram
- X/Twitter
- Many more that I don't even recognize

When StreamBridge detects an active SSN host, it can let SSN handle the platform relay. When the SSN host stops responding, StreamBridge returns to direct mode.

The exact platforms available through SSN depend on the connected Social Stream Ninja setup.

## Using the web dashboard

The [StreamBridge dashboard](https://streambridge.gozarproductions.com/dashboard) is the easiest way to set up and manage your bridge. You can sign in with Discord, Google, Twitch, or Kick, then link your other accounts so they all access the same StreamBridge configuration.

From the dashboard, you can:

- Connect or disconnect Twitch, YouTube, Kick, and Discord accounts.
- Enable direct connections for the platforms you want to relay.
- Connect Social Stream Ninja and choose any SSN-supported destination platforms.
- Choose the Discord channel used for relay, if you want Discord integration.
- Independently enable messages sent from Discord and messages received in Discord.
- Customize the message format used for direct platform relay.
- Choose whether Discord announces switches between SSN and direct relay.
- Use StreamBridge without installing it in a Discord server.

Press **Save** after making configuration changes. Changes made through Discord commands also appear in the dashboard.

### Disconnecting an account

Use the **Disconnect** button beside a linked account to remove it from StreamBridge. Any direct connection that depends on that account will stop working until an account is linked again.

You must keep at least one sign-in method connected so you do not lock yourself out of the dashboard. Disconnecting Discord disables Discord relay but retains the selected server, channel, and relay-direction settings for later use.

Disconnecting an account from StreamBridge removes its saved authorization from StreamBridge, but it may not revoke permission at the platform itself. You can separately revoke StreamBridge through that platform's account settings if desired.

## Privacy and authorization

Each platform account is authorized once through the dashboard and may then be assigned to the bridge owned by that dashboard account. Discord-backed bridges can only select servers where the signed-in Discord user has the Administrator permission or is the server owner.

Only authorize accounts you own or are permitted to manage.

StreamBridge does not need your Discord, Google, YouTube, Twitch, or Kick password. Authentication occurs on each platform's own website.

## Troubleshooting

### Messages are not relayed between streaming platforms

In the dashboard, verify:

- At least two destinations are enabled.
- The relevant Twitch, Google/YouTube, or Kick identities are linked.
- Each desired account is enabled under **Direct Connection**, or an active SSN session is configured.
- The authorized YouTube channel has an active livestream with live chat enabled.
- The broadcaster account has permission to read and post chat on the relevant platform.

If Social Stream Ninja is configured but offline, allow StreamBridge time to detect the unavailable host and switch to direct mode.

### Discord-specific troubleshooting

#### StreamBridge cannot post in a channel

Check that it has:

- View Channel
- Send Messages
- Read Message History

For messages received from platforms, also grant:

- Manage Webhooks
- Embed Links
- Attach Files

#### Streaming messages do not appear in Discord

Run:

```text
/status
```

Then verify:

- A shared Discord relay channel is shown and receiving is enabled.
- The desired direct platform is connected, or SSN is connected.
- StreamBridge has permission to view and post in the shared relay channel.
- StreamBridge has permission to manage webhooks there.

#### Discord messages are not sent to streaming platforms

Verify:

- Forwarding was enabled with `/channel set` or in the dashboard.
- The message was sent in the saved shared Discord relay channel.
- At least one direct platform is connected, or SSN is connected.
- The message was not sent by another bot or by StreamBridge’s own webhook.
- StreamBridge can read the channel.

### YouTube is connected but no messages appear

The authorized YouTube channel must have an active livestream with live chat enabled. StreamBridge automatically waits for and discovers the active chat.

### The wrong platform account appears

Sign out of that platform in your browser, open a private/incognito window, sign into the intended broadcaster account, and link it again from the dashboard.

## Support

Report reproducible bugs and request features through [StreamBridge GitHub Issues](https://github.com/Erallie/stream-bridge/issues).

For setup assistance, troubleshooting, and additional support, join the [Gozar Productions Discord](https://discord.gozarproductions.com).

If you encounter a problem, include the following when requesting help:

- The command you ran
- The response StreamBridge displayed
- The output of `/status`
- The source and destination platforms involved
- Whether StreamBridge was using direct mode or Social Stream Ninja

Never share authorization links, access tokens, refresh tokens, client secrets, Discord bot tokens, or complete SSN session credentials in a public support channel.
