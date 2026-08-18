# StreamBridge Privacy Policy
  
**Last updated:** August 18, 2026

This Privacy Policy explains how StreamBridge (“StreamBridge,” “we,” “us,” or “the Bot”), operated by **Gozar Productions LLC**, accesses, processes, stores, shares, and deletes information when it is added to a Discord server or connected to Twitch, YouTube, Kick, or Social Stream Ninja.

Contact us with privacy questions or deletion requests at **contact@gozarproductions.com**.

## 1. Scope

This Privacy Policy applies to:

- The StreamBridge Discord bot
- StreamBridge’s OAuth authorization pages and callback endpoints
- Direct Twitch, YouTube, and Kick integrations
- Optional Social Stream Ninja integrations
- Messages processed or relayed by StreamBridge

It does not govern Discord, Twitch, Google, YouTube, Kick, Social Stream Ninja, Cloudflare, or any other third-party service. Those services process information according to their own privacy policies.

## 2. How StreamBridge works

StreamBridge relays chat messages between configured Discord channels and enabled streaming platforms.

Depending on a server administrator’s configuration, StreamBridge may:

- Read messages sent in specifically configured Discord channels
- Forward those messages to Twitch, YouTube, Kick, or Social Stream Ninja
- Receive public livestream chat messages from connected platforms
- Repost those messages in a configured Discord channel
- Relay messages from one streaming platform to other connected platforms
- Connect to a Social Stream Ninja session
- Automatically switch between Social Stream Ninja and direct platform connections
- Suppress duplicate messages and relay loops

StreamBridge does not use artificial intelligence or language models to analyze messages.

## 3. Information StreamBridge accesses and processes

### 3.1 Discord server information

StreamBridge may access or store:

- Discord server IDs
- IDs of configured forwarding channels
- The ID of the configured receiving channel
- Discord server names while constructing relay messages
- Server-specific relay settings
- Whether transport-switch notices are enabled
- The direct relay message template selected by an administrator

Discord IDs are numeric identifiers assigned by Discord.

### 3.2 Discord message information

StreamBridge processes messages only when they are sent in channels selected with `/forward add`.

For those messages, StreamBridge may process:

- Message ID
- Message text
- Message timestamp
- Author’s Discord user ID
- Author’s display name
- Author’s display avatar URL
- Author’s displayed role color
- Custom Discord emote names and image URLs
- Resolved user, role, and channel mentions
- The URL of the first attached image, when applicable
- Discord server name
- Source channel ID

StreamBridge ignores messages sent by bots and webhooks for forwarding purposes.

Message content is processed so it can be relayed to destinations selected by the Discord server’s administrators. StreamBridge does not intentionally write the full Discord message body to its configuration database.

A copy of the message may be stored by Discord or by each destination platform after StreamBridge posts it there. Those copies are controlled by the relevant platform and server or channel owner.

### 3.3 Streaming-platform chat information

For Twitch, YouTube, Kick, and messages received through Social Stream Ninja, StreamBridge may process:

- Platform name
- Platform message ID
- Chatter’s platform user or channel ID
- Username or display name
- Message text
- Profile image URL
- Username color, when supplied by the platform
- Message timestamp
- Broadcaster or channel information
- Whether the message appears to be a bot message, reflection, or duplicate

This information is used to display and relay the message and to prevent duplicates.

StreamBridge does not intentionally create permanent archives of complete livestream chat messages. Copies posted into Discord or other streaming chats remain subject to those platforms’ retention and deletion systems.

### 3.4 Social Stream Ninja information

When an administrator uses `/ssn connect`, StreamBridge stores:

- The Social Stream Ninja session ID
- The selected relay-target platforms
- Connection and transport state while the Bot is operating

The session ID is masked when displayed through `/status`.

StreamBridge does not require or store the separate password used for password-protected Social Stream Ninja overlay or VDO rooms.

Messages routed through Social Stream Ninja may be processed by Social Stream Ninja’s infrastructure according to its own practices.

### 3.5 YouTube authorization information

When an administrator authorizes YouTube, StreamBridge stores:

- Discord server ID associated with the authorization
- Authorized YouTube channel ID
- YouTube channel title
- An encrypted OAuth refresh token

StreamBridge requests the following Google OAuth scope:

```text
https://www.googleapis.com/auth/youtube.force-ssl
```

This scope can permit broad YouTube account actions. StreamBridge’s current implementation uses it only to:

- Identify the authorized YouTube channel
- Discover that channel’s active livestream
- Read messages from its active live chat
- Post relayed messages into its active live chat
- Refresh the authorization token as needed

StreamBridge does not use this permission to upload, edit, or delete videos; manage playlists; read viewing history; access private messages; or obtain the Google account password.

StreamBridge never receives or stores the user’s Google password. Authentication occurs directly on Google’s website.

StreamBridge uses YouTube API Services. Its use and transfer of information received from Google APIs adheres to the [Google API Services User Data Policy](https://developers.google.com/terms/api-services-user-data-policy), including its Limited Use requirements.

Use of YouTube features is also subject to the [Google Privacy Policy](https://policies.google.com/privacy), [YouTube Terms of Service](https://www.youtube.com/t/terms), and [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies).

### 3.6 Kick authorization information

When an administrator authorizes Kick, StreamBridge stores:

- Discord server ID associated with the authorization
- Kick broadcaster user ID
- Kick broadcaster username
- An encrypted OAuth refresh token

StreamBridge requests these Kick permissions:

```text
user:read
chat:write
events:subscribe
```

They are used to:

- Identify the authorized broadcaster
- Subscribe to that broadcaster’s chat-message events
- Receive public chat messages
- Post relayed messages using the StreamBridge Kick bot

Although Kick may make additional user information available under an authorized scope, StreamBridge’s current implementation extracts and stores only the broadcaster ID, username, and authorization token needed for these functions. It does not intentionally store the broadcaster’s email address.

StreamBridge never receives or stores the user’s Kick password. Authentication occurs directly on Kick’s website.

### 3.7 Twitch information

StreamBridge uses a centrally configured Twitch bot account to join channels selected by server administrators.

For Twitch chat, StreamBridge may process:

- Channel name
- Message ID
- Chatter’s Twitch user ID
- Login name and display name
- Message text
- Profile image URL
- Username color

A short-lived in-memory cache may retain Twitch user IDs or login names and profile-image URLs to reduce repeated API lookups:

- Successful avatar lookups may be cached for approximately 24 hours.
- Failed avatar lookups may be cached for approximately 5 minutes.
- The cache is held in memory and is lost when StreamBridge restarts.
- The cache is periodically pruned and bounded in size.

Individual Discord servers do not receive or control the central Twitch bot account’s OAuth credentials.

### 3.8 OAuth state and temporary authorization data

YouTube and Kick authorization links use random state values to associate an OAuth response with the correct Discord server.

Pending authorization data:

- Is stored temporarily in memory
- Is associated with a Discord server ID
- Expires after approximately ten minutes
- Is removed after use or expiration
- Does not include a user’s platform password

Kick authorization also uses PKCE verification data, which is stored temporarily in memory until the authorization completes or expires.

### 3.9 Duplicate-prevention and delivery history

To prevent duplicate deliveries and relay loops, StreamBridge stores limited event and delivery records containing:

- Discord server ID
- A generated event key
- Source platform
- Original platform message ID, when available
- A SHA-256 fingerprint derived from the platform, user identifier, and normalized message text
- Destination identifier
- Delivery status
- Creation timestamp

The fingerprint is a one-way hash rather than a stored copy of the message. However, it is still associated with platform and server records.

Duplicate-prevention and delivery records are retained for approximately **30 days** and are removed during scheduled maintenance.

StreamBridge also keeps a short-lived, in-memory reflection tracker for messages it recently sent. Those entries normally expire after approximately two minutes and are not written to the database.

### 3.10 Logs

StreamBridge creates operational logs that may include:

- Timestamps
- Platform names
- Discord server or channel IDs
- Connected channel names
- Connection and retry events
- Command or API errors
- Delivery failures

StreamBridge is designed not to log OAuth access tokens, refresh tokens, client secrets, Discord bot tokens, or account passwords.

Unexpected errors returned by third-party platforms may include limited response details. Log retention depends on the operator’s server configuration and is not currently controlled by StreamBridge itself.

## 4. Information StreamBridge does not intentionally collect

StreamBridge does not intentionally collect or use:

- Discord account passwords
- Google account passwords
- Twitch account passwords
- Kick account passwords
- Payment-card information
- Precise location
- Contact lists
- Browsing history
- Private Discord messages outside configured server channels
- Messages from Discord channels not selected for forwarding
- Voice or video content
- Biometric information
- Data for advertising profiles
- Data for training artificial-intelligence models

## 5. How information is used

StreamBridge uses information only as reasonably necessary to:

- Provide cross-platform chat relay
- Display streaming messages in Discord
- Send Discord messages to configured platforms
- Authenticate authorized YouTube and Kick accounts
- Find active YouTube livestream chats
- Subscribe to Kick chat events
- Look up Twitch profile images
- Maintain server-specific settings
- Detect duplicates and prevent relay loops
- Diagnose failures, secure the service, and maintain reliability
- Comply with legal obligations and platform rules

StreamBridge does not sell personal information or use it for targeted advertising.

## 6. How information is shared

StreamBridge shares information only as needed to provide the configured relay service.

### 6.1 Administrator-selected destinations

A message sent in a configured forwarding channel may be sent to:

- Twitch
- YouTube
- Kick
- Social Stream Ninja
- Other platforms selected through Social Stream Ninja
- A configured Discord receiving channel

Relaying necessarily makes the sender’s display name, source platform, message, and potentially avatar visible to users of those destinations.

Server administrators are responsible for telling their communities when a channel is connected to StreamBridge.

### 6.2 Service providers and infrastructure

Information may pass through infrastructure used to operate StreamBridge, including:

- Discord
- Google and YouTube
- Twitch
- Kick
- Social Stream Ninja
- Cloudflare, for secure OAuth callbacks and Kick webhooks
- The server or hosting provider running StreamBridge

These providers process information according to their own terms and privacy policies.

### 6.3 Legal and safety disclosures

We may disclose information if reasonably necessary to:

- Comply with law, regulation, subpoena, court order, or valid legal process
- Protect the safety, rights, or property of users, the public, StreamBridge, or its operator
- Investigate abuse, fraud, security incidents, or violations of the Terms of Service
- Enforce agreements or platform requirements

### 6.4 Business transfers

If StreamBridge or its operation is transferred to another owner, information necessary to operate the service may be transferred as part of that transaction. Users will be notified through an appropriate public notice if this materially changes the handling of their information.

## 7. Data retention

StreamBridge generally retains information as follows:

- **Server configuration:** Until changed, cleared, or deleted at an administrator’s request
- **YouTube and Kick authorization records:** Until the connection is disabled, the authorization becomes unusable, or deletion is requested
- **Duplicate and delivery history:** Approximately 30 days
- **Pending OAuth state:** Approximately ten minutes
- **Reflection tracking:** Approximately two minutes in memory
- **Twitch avatar cache:** Approximately 24 hours for successful lookups or five minutes for failed lookups
- **Operational logs:** According to the operator’s server and logging configuration
- **Message content:** Processed in transit and not intentionally stored as full message text in StreamBridge’s database

Removing StreamBridge from a Discord server does not necessarily delete all stored server configuration automatically. A server owner or authorized administrator should contact **contact@gozarproductions.com** to request complete deletion.

Backups, if maintained, may retain deleted records temporarily until they are overwritten through the normal backup cycle.

## 8. Security

StreamBridge uses reasonable technical measures designed to protect information, including:

- Encryption of stored per-server YouTube and Kick refresh tokens using Fernet symmetric encryption
- HTTPS for OAuth callbacks
- TLS-protected connections to supported platform APIs
- Signed-webhook verification for Kick events
- PKCE for Kick OAuth authorization
- Random, expiring OAuth state values
- Private Discord responses for OAuth authorization links
- Restricted server-side storage for credentials and tokens
- Avoidance of secrets in normal application logs

No system can guarantee absolute security. Users should immediately contact **contact@gozarproductions.com** if they believe an account or authorization has been compromised.

## 9. User and administrator choices

Discord server administrators can limit StreamBridge’s access by:

- Adding only specific forwarding channels
- Removing a forwarding channel with `/forward remove`
- Removing every forwarding channel with `/forward clear`
- Disabling Discord receiving with `/receive clear`
- Disconnecting Social Stream Ninja with `/ssn disconnect`
- Disabling a direct connection with `/direct disable`
- Removing StreamBridge from the Discord server

Disabling YouTube or Kick removes the locally stored authorization record for that Discord server. It does not necessarily revoke the grant at the platform itself.

### Revoke Google or YouTube access

Users can review or revoke StreamBridge’s Google authorization from their [Google Account connections page](https://myaccount.google.com/connections).

### Revoke Kick access

Users may revoke access through Kick’s account or connected-application settings when available. They may also contact **eds.gozar@gmail.com** for assistance deleting StreamBridge’s stored Kick authorization.

### Request deletion

A Discord server owner, authorized server administrator, or authorized platform-account owner may request access to or deletion of applicable stored information by emailing:

**eds.gozar@gmail.com**

Please include:

- The Discord server ID
- Your Discord user ID
- The connected platform
- Enough information to confirm that you are authorized to make the request

Do not include passwords, bot tokens, OAuth tokens, or client secrets.

We may need to verify the requester’s authority before disclosing or deleting server-level records.

## 10. Legal rights

Depending on where you live, you may have rights regarding personal information, including the right to:

- Request access
- Request correction
- Request deletion
- Object to or restrict certain processing
- Withdraw consent
- Receive a portable copy of certain information
- Lodge a complaint with a data-protection authority

To exercise an applicable right, contact **eds.gozar@gmail.com**.

## 11. Children’s privacy

StreamBridge is not directed to children under 13 or under the minimum age required by Discord or a connected platform in their jurisdiction.

We do not knowingly collect personal information from children in violation of applicable law. If you believe a child’s information has been processed improperly, contact **eds.gozar@gmail.com**.

## 12. International processing

StreamBridge and its service providers may process information in countries other than the user’s country of residence. Those countries may have different data-protection laws.

Where required, the operator will use appropriate safeguards for international transfers.

## 13. Third-party services

Use of StreamBridge may involve third-party services governed by separate terms and privacy policies, including:

- [Discord Privacy Policy](https://discord.com/privacy)
- [Google Privacy Policy](https://policies.google.com/privacy)
- [YouTube Terms of Service](https://www.youtube.com/t/terms)
- [Twitch Privacy Notice](https://www.twitch.tv/p/en/legal/privacy-notice/)
- [Kick Privacy Policy](https://kick.com/privacy-policy)
- [Social Stream Ninja](https://socialstream.ninja/)

StreamBridge does not control these third parties.

## 14. Changes to this Privacy Policy

We may update this Privacy Policy when StreamBridge’s features, data practices, platform integrations, or legal obligations change.

The updated policy will show a new “Last updated” date. If a change materially expands how authorized Google or YouTube data is accessed, used, stored, or shared, affected users may be asked to review or accept the updated policy as required by applicable platform policies.

## 15. Contact

For privacy questions, requests, or complaints:

**Operator:** Gozar Productions LLC 
**Email:** contact@gozarproductions.com