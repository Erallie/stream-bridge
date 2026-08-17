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

5. It requests only Twitch IRC's `chat:read` and `chat:edit` permissions and writes `data/twitch-oauth.env`. Copy its four lines into `.env`, then delete the temporary file.
6. If authorization was performed on your desktop, securely copy only those generated values into the Pi's `/opt/ninjabridge/.env`.
7. Start NinjaBridge and run `/direct twitch channel:YOUR_CHANNEL` in Discord.

The access token refreshes automatically. The Pi makes an outbound secure WebSocket connection to Twitch; no inbound port or cloud chatbot host is required.

## YouTube OAuth setup

YouTube does not provide a permanent access token. NinjaBridge stores a refresh token and obtains new short-lived access tokens automatically.

1. In [Google Cloud Console](https://console.cloud.google.com/), create or select a project.
2. Enable **YouTube Data API v3**.
3. Configure the OAuth consent screen. For a testing app, add the Google account that owns the posting YouTube channel as a test user.
4. Create an OAuth 2.0 Client ID of type **Desktop app**.
5. Put its client ID and client secret into `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET` in `.env` on a computer with a browser.
6. Run:

   ```bash
   python -m ninjabridge.authorize youtube
   ```

7. Sign into the Google account whose YouTube channel should post. The helper requests `youtube.force-ssl`, saves `data/youtube-oauth.env`, and asks Google for offline access.
8. Copy the four generated lines into the Pi's `.env`, then securely delete the temporary file.
9. Find the broadcast's `activeLiveChatId` through the YouTube Live Streaming API (or an API explorer) and run `/direct youtube live_chat_id:VALUE`.

OAuth apps left in Google's **Testing** publishing status may receive refresh tokens that expire after seven days. Move the consent screen to Production when appropriate; unverified personal apps can still show a warning and have user limits.

## Direct Kick without opening router ports

Kick sends incoming chat as HTTPS webhooks. NinjaBridge listens only on `127.0.0.1:8765`; a named Cloudflare Tunnel makes that one path reachable over Cloudflare's outbound connection. You do not forward port 8765 on the router.

1. Add a domain to Cloudflare.
2. Create a Kick developer application in the [Kick Developer portal](https://kick.com/settings/developer). Its webhook URL will be `https://kick-webhook.YOUR_DOMAIN/kick/webhook`.
3. Give the application the chat read/write and event-subscription permissions Kick requests. Complete Kick OAuth for the broadcaster/bot account and place its access token, refresh token, client ID, and client secret in the corresponding `KICK_...` `.env` values.
4. Subscribe the app to Kick's `chat.message.sent` event for the broadcaster. Kick delivers subscribed events to the webhook URL registered for the app.
5. Install `cloudflared` on the Pi using Cloudflare's current Debian/Raspberry Pi instructions, then authenticate and create a named tunnel:

   ```bash
   cloudflared tunnel login
   cloudflared tunnel create ninjabridge
   cloudflared tunnel route dns ninjabridge kick-webhook.YOUR_DOMAIN
   ```

6. Copy `deploy/cloudflared-config.yml.example` to `~/.cloudflared/config.yml`. Replace the tunnel UUID, Linux username, and hostname.
7. Install the tunnel service:

   ```bash
   sudo cloudflared --config /home/YOUR_PI_USER/.cloudflared/config.yml service install
   sudo systemctl enable --now cloudflared
   sudo systemctl status cloudflared
   ```

8. Start NinjaBridge and run `/direct kick broadcaster_user_id:KICK_NUMERIC_ID`.

NinjaBridge downloads Kick's official public key and rejects webhooks whose `Kick-Event-Signature` is invalid. Keep Cloudflare's catch-all `http_status:404` rule so the tunnel does not expose anything else. A named tunnel is required for a stable webhook URL; a quick tunnel changes its address after a restart.

## Optional Social Stream Ninja

Run `/setup session_id:YOUR_SESSION relay_targets:twitch,youtube,kick,tiktok`. If the SSN room is protected, also fill in the command's optional `password` field. The command response is private to the administrator, and the password is stored in the local SQLite database.

In SSN enable remote API control and the option that routes API chat to normal dock/overlay connections. Enable SSN's built-in relay when SSN should own platform-to-platform relay. NinjaBridge ignores reflections, bot messages, its Discord webhook messages, and already-processed event IDs to prevent loops.

When SSN is connected, NinjaBridge routes through SSN and ignores direct inbound copies. When it disconnects, the direct Twitch, YouTube, and Kick adapters resume ownership. TikTok remains SSN-only because TikTok does not offer a general public LIVE-chat read/write API for this use.

## Commands

- `/setup` saves an SSN session and relay targets.
- `/forward add`, `/forward remove`, `/forward clear` manage Discord → streaming chat channels.
- `/receive set`, `/receive clear` manage streaming chats → Discord.
- `/direct twitch`, `/direct youtube`, `/direct kick` configure direct adapters.
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
