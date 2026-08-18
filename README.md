# NinjaBridge

NinjaBridge connects Discord with Twitch, YouTube, and Kick even when Social Stream Ninja is offline. If a configured SSN session becomes available, NinjaBridge automatically prefers SSN, which adds TikTok and SSN's wider platform support. It announces transport changes unless `/switchmessages enabled:false` is set.

NinjaBridge contains no LLM or identity-linking system. Those features live in the optional NinjaMind companion.

## What you need

- A Raspberry Pi or another always-on computer with Python 3.11+
- A Discord bot application
- A separate Twitch account for the visible bot identity (recommended)
- A Google Cloud OAuth client for the YouTube channel that will post
- A Kick developer application and a domain on Cloudflare if direct Kick receiving is wanted
- Optionally, an SSN session ID

The Twitch code runs on your Pi. It is therefore a locally hosted chat client, not a centrally hosted “cloud bot.” The bot account itself is still an ordinary Twitch account.

## Install on a Raspberry Pi

Replace `YOUR_GITHUB_NAME` and the repository name if necessary.

```bash
sudo apt update
sudo apt install -y git python3 python3-venv python3-pip
sudo mkdir -p /opt/ninjabridge
sudo chown "$USER":"$USER" /opt/ninjabridge
git clone https://github.com/YOUR_GITHUB_NAME/NinjaBridge.git /opt/ninjabridge
cd /opt/ninjabridge
python3 -m venv bot-env
bot-env/bin/python -m pip install --upgrade pip
bot-env/bin/python -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Never commit `.env`, `data/`, OAuth tokens, Discord tokens, tunnel credentials, or logs. They are excluded by `.gitignore`.

NinjaBridge automatically saves rotated platform refresh tokens in `data/oauth_tokens.json`, so a provider-issued replacement survives a restart. Keep the original refresh token in `.env`; if you deliberately replace it there, the new value takes precedence. Processed-event and delivery history is retained for 30 days by default and cleaned at startup and every 24 hours while the bot remains online. Advanced installations can change `HISTORY_RETENTION_DAYS`.

For a first foreground run:

```bash
cd /opt/ninjabridge
bot-env/bin/python -m ninjabridge
```

### Start NinjaBridge automatically

Edit `deploy/ninjabridge.service` and replace both `CHANGE_ME` values with the Pi Linux username. Then:

```bash
sudo cp deploy/ninjabridge.service /etc/systemd/system/ninjabridge.service
sudo systemctl daemon-reload
sudo systemctl enable --now ninjabridge
sudo systemctl status ninjabridge
```

Follow its logs with:

```bash
journalctl -u ninjabridge -f
```

This replaces the old `nohup` command. The service restarts after a crash or reboot.

## Discord setup

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application and bot.
2. Copy the bot token to `DISCORD_TOKEN` and the application's numeric Application ID to `DISCORD_CLIENT_ID` in `.env`.
3. On the Bot page, enable **Message Content Intent**. NinjaBridge does not currently need Server Members Intent.
4. In OAuth2 → URL Generator, choose `bot` and `applications.commands`.
5. Grant **View Channels**, **Send Messages**, **Read Message History**, and **Manage Webhooks**. Add **Attach Files** and **Embed Links** if you want rich content preserved.
6. Open the generated URL and invite the bot.

Configure Discord after it starts:

- `/forward add channel` adds a normal text channel or a voice channel's side chat as Discord → platforms.
- `/receive set channel` chooses a normal text channel or voice side chat for platforms → Discord.
- The same channel may be used for both directions.
- `/status` shows the active transport and configured channels.

## Twitch bot setup

Use a separate Twitch account if you want messages to appear under a bot name. Enable two-factor authentication on the developer account, then:

1. Sign into the [Twitch Developer Console](https://dev.twitch.tv/console/apps) and register an application.
2. Set its OAuth redirect URL to `http://localhost:8787/callback` and choose an appropriate chat-bot/application category.
3. Put the Client ID and generated Client Secret in `.env` as `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET`.
4. Run the authorization assistant on a computer with a browser while signed into the separate Twitch bot account:

   ```bash
   python -m ninjabridge.authorize twitch
   ```

5. It requests only Twitch IRC's `chat:read` and `chat:edit` permissions and writes `data/twitch-oauth.env`. Copy its three lines into `.env`, then delete the temporary file.
6. If authorization was performed on your desktop, securely copy only those generated values into the Pi's `/opt/ninjabridge/.env`.
7. Start NinjaBridge and run `/direct twitch channel:YOUR_CHANNEL` in Discord.

The access token refreshes automatically. The Pi makes an outbound secure WebSocket connection to Twitch; no inbound port or cloud chatbot host is required.

## YouTube OAuth setup

Create one Google OAuth application for NinjaBridge. Each Discord server then privately authorizes its own YouTube channel with `/direct youtube`; encrypted refresh tokens are stored separately in the database.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth audience as **External**, complete the app branding, and publish the app **In production** so any Google account can authorize it.
4. Create an OAuth 2.0 Client ID of type **Web application**.
5. Add `https://ninjabridge-webhook.YOUR_DOMAIN/youtube/oauth/callback` as an authorized redirect URI. It must exactly match `YOUTUBE_OAUTH_REDIRECT_URI` in `.env`.
6. Put only the app's client ID, client secret, and redirect URI in `.env`. Do not put a YouTube refresh token there.
7. Add the `youtube.force-ssl` scope under **Data Access**, then submit the production app for Google OAuth verification. This scope is required to read and post live-chat messages. Before verification is approved, users may see Google's unverified-app warning and the project is subject to Google's new-user cap.
8. Restart NinjaBridge. In each Discord server, an administrator runs `/direct youtube` and opens the private link while signed into the YouTube account whose channel should be connected.

NinjaBridge automatically discovers that account's active livestream chat. Authorization can be completed before going live; NinjaBridge keeps checking until an active chat exists.

Do not leave the public NinjaBridge app in **Testing** or maintain a test-user allowlist. Production publishing makes it available to any Google account; verification removes the unverified-app warning and new-user cap for the requested scope.

## Direct Kick without opening router ports

Kick sends incoming chat as HTTPS webhooks. Kick and YouTube return each user's OAuth authorization through HTTPS. By default, NinjaBridge listens only on `127.0.0.1:8765`; a named Cloudflare Tunnel carries those routes over an outbound connection. You do not forward a router port. If that local port is already occupied, set `KICK_WEBHOOK_PORT` to a free port in `.env` and use that same port in the Cloudflare tunnel configuration.

1. Add a domain to Cloudflare.
2. Create one Kick developer application in the [Kick Developer portal](https://kick.com/settings/developer). Select **Create a bot for this app**. Set its OAuth redirect URL to `https://ninjabridge-webhook.YOUR_DOMAIN/kick/oauth/callback` and its separate webhook URL to `https://ninjabridge-webhook.YOUR_DOMAIN/kick/webhook`.
3. Select only **Read user information**, **Write to Chat feed**, and **Subscribe to events**. Put the application's `KICK_CLIENT_ID`, `KICK_CLIENT_SECRET`, and exact `KICK_OAUTH_REDIRECT_URI` in `.env`. Do not put a broadcaster refresh token or broadcaster ID in `.env`.
4. Generate one database-encryption key and place the printed value in `TOKEN_ENCRYPTION_KEY` in `.env`. It protects both Kick and YouTube per-server authorizations:

   ```bash
   cd /opt/ninjabridge
   bot-env/bin/python -m ninjabridge.keygen
   ```

   Back up this key securely. Changing or losing it makes saved Kick and YouTube authorizations unreadable.
5. Install `cloudflared` outside `bot-env` using Cloudflare's current Debian/Raspberry Pi instructions, then authenticate and create a named tunnel:

   ```bash
   cloudflared tunnel login
   cloudflared tunnel create ninjabridge
   cloudflared tunnel route dns ninjabridge ninjabridge-webhook.YOUR_DOMAIN
   ```

6. Copy `deploy/cloudflared-config.yml.example` to `~/.cloudflared/config.yml`. Replace the tunnel UUID, Linux username, and hostname. The single hostname rule intentionally routes `/kick/webhook`, `/kick/oauth/callback`, and `/youtube/oauth/callback` to NinjaBridge. If `KICK_WEBHOOK_PORT` is `8766`, change `8765` to `8766` in this file too.
7. Validate the configuration, then install the tunnel service:

   ```bash
   cloudflared tunnel ingress validate
   sudo cloudflared --config /home/YOUR_PI_USER/.cloudflared/config.yml service install
   sudo systemctl enable --now cloudflared
   sudo systemctl status cloudflared --no-pager -l
   ```

8. Restart NinjaBridge. Confirm that its listener is running, then test the public callback route. A `400` response saying the authorization link is invalid or expired is expected here—it proves Cloudflare reached NinjaBridge without a real OAuth request:

   ```bash
   curl -i http://127.0.0.1:8765/kick/oauth/callback
   curl -i https://ninjabridge-webhook.YOUR_DOMAIN/kick/oauth/callback
   ```

   Use your configured local port in the first command.
9. In each Discord server, an administrator runs `/direct kick` and follows the private authorization link while signed into the Kick account that owns that server's channel. NinjaBridge discovers the broadcaster ID, subscribes to `chat.message.sent`, encrypts the refresh token, and stores that authorization separately for the Discord server.

NinjaBridge uses one shared local listener and routes each signed event by broadcaster ID. It downloads Kick's official public key and rejects invalid signatures. `/direct disable platform:kick` removes only the current Discord server's saved authorization. Keep Cloudflare's catch-all `http_status:404` rule so the tunnel exposes nothing else.

## Optional Social Stream Ninja

Run `/setup session_id:YOUR_SESSION relay_targets:twitch,youtube,kick,tiktok`. If the SSN room is protected, also fill in the command's optional `password` field. The command response is private to the administrator, and the password is stored in the local SQLite database.

In SSN enable remote API control and the option that routes API chat to normal dock/overlay connections. Enable SSN's built-in relay when SSN should own platform-to-platform relay. NinjaBridge ignores reflections, bot messages, its Discord webhook messages, and already-processed event IDs to prevent loops.

When SSN is connected, NinjaBridge routes through SSN and ignores direct inbound copies. NinjaBridge verifies that the SSN extension/app itself is responding, rather than treating an otherwise empty cloud room as connected. If the host closes or stops responding, direct Twitch, YouTube, and Kick adapters resume ownership automatically; the default detection window is about 25 seconds and can be tuned with `SSN_HOST_PROBE_INTERVAL` and `SSN_HOST_PROBE_TIMEOUT`. TikTok remains SSN-only because TikTok does not offer a general public LIVE-chat read/write API for this use.

## Commands

- `/setup` saves an SSN session and relay targets.
- `/forward add`, `/forward remove`, `/forward clear` manage Discord → streaming chat channels.
- `/receive set`, `/receive clear` manage streaming chats → Discord.
- `/direct twitch` chooses the channel joined by the shared Twitch bot account. `/direct youtube` privately authorizes this server's YouTube channel and automatically follows its active livestream. `/direct kick` privately authorizes this server's Kick broadcaster.
- `/direct message` customizes direct relay text with `{name}`, `{message}`, and `{platform}`. An empty value restores `{name} said: {message}`.
- `/direct disable platform` disables one direct adapter.
- `/switchmessages` controls transport-switch notices.
- `/status` displays configuration with the SSN session masked.
- `/disable` disconnects SSN without deleting direct settings.

## Updating and testing

```bash
cd /opt/ninjabridge
git pull --ff-only
bot-env/bin/python -m pip install -r requirements.txt
bot-env/bin/python -m unittest discover -s tests -v
sudo systemctl restart ninjabridge
```

The SQLite migrations preserve existing configuration. Direct and SSN messages use platform/message IDs plus delivery records to suppress duplicate forwards.

While SSN is disconnected, every accepted Twitch, YouTube, or Kick message is sent to the configured Discord receive channel and relayed to every other enabled direct platform. Messages in configured Discord forward channels are relayed to every enabled direct platform. The source platform is excluded from its own fan-out, preventing an immediate echo.

Discord role colors and platform-provided username colors are retained as `nameColor` metadata. Twitch, YouTube, and Kick do not render arbitrary HTML or allow a relay bot to color only part of a native chat message, so NinjaBridge sends plain text there instead of exposing markup. SSN can use the Discord role color in its overlay when SSN is connected.

Discord custom emojis are injected into SSN as safe `<img class="regular-emote">` markup backed by Discord's CDN. Animated custom emojis use GIF URLs. NinjaBridge marks those messages `textonly: false`, allowing SSN's dock, overlays, and emote wall to render them. Ordinary text is HTML-escaped, and direct native-platform relays use the separate plain-text form such as `:emote_name:`.
