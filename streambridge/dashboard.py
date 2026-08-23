from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import aiohttp
from aiohttp import web
from cryptography.fernet import Fernet

from streambridge.database import ConfigStore

WorkspaceChanged = Callable[[str], Awaitable[None]]
IdentityLinked = Callable[[str, dict[str, str]], Awaitable[None]]
DiscordChannels = Callable[[str], Awaitable[list[dict[str, str]]]]
RuntimeStatus = Callable[[str], Awaitable[dict[str, Any]]]


def iso_after(**kwargs: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(**kwargs)).isoformat()


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


class DashboardAPI:
    """Dashboard sessions, linked identities, OAuth, and workspace configuration."""

    providers = ("discord", "google", "twitch", "kick")
    connection_providers = ("youtube", "twitch", "kick")

    def __init__(self, store: ConfigStore, on_workspace_changed: WorkspaceChanged | None = None,
                 on_identity_linked: IdentityLinked | None = None,
                 discord_channels: DiscordChannels | None = None,
                 runtime_status: RuntimeStatus | None = None) -> None:
        self.store = store
        self.on_workspace_changed = on_workspace_changed
        self.on_identity_linked = on_identity_linked
        self.discord_channels_provider = discord_channels
        self.runtime_status_provider = runtime_status
        self.site_url = os.getenv("DASHBOARD_SITE_URL", "http://localhost:5173").rstrip("/")
        self.public_url = os.getenv("DASHBOARD_API_PUBLIC_URL", "http://localhost:8765").rstrip("/")
        self.cookie_name = "streambridge_session"
        self.session: aiohttp.ClientSession | None = None
        key = os.getenv("TOKEN_ENCRYPTION_KEY", "")
        self.fernet = Fernet(key.encode()) if key else None

    def register(self, app: web.Application) -> None:
        app.middlewares.append(self.cors_middleware)
        app.router.add_get("/dashboard/api/health", self.health)
        app.router.add_get("/dashboard/api/me", self.me)
        app.router.add_delete("/dashboard/api/identities/{provider}", self.disconnect_identity)
        app.router.add_get("/dashboard/api/discord/guilds", self.discord_guilds)
        app.router.add_get("/dashboard/api/discord/guilds/{guild_id}/channels", self.discord_channels)
        app.router.add_post("/dashboard/api/logout", self.logout)
        app.router.add_get("/dashboard/api/workspaces", self.list_workspaces)
        app.router.add_patch("/dashboard/api/workspaces/{workspace_id}", self.update_workspace)
        app.router.add_put("/dashboard/api/workspaces/{workspace_id}/connections/{provider}", self.update_connection)
        app.router.add_get("/dashboard/auth/{provider}", self.begin_oauth)
        app.router.add_get("/dashboard/auth/{provider}/callback", self.oauth_callback)
        app.router.add_route("OPTIONS", "/dashboard/api/{tail:.*}", self.preflight)

    @web.middleware
    async def cors_middleware(self, request: web.Request, handler: Any) -> web.StreamResponse:
        try:
            response = await handler(request)
        except web.HTTPException as error:
            response = error
        except Exception:
            logging.exception("Dashboard API request failed")
            response = web.json_response(
                {"error": "The StreamBridge API could not complete the request"},
                status=500,
            )
        origin = request.headers.get("Origin", "")
        allowed = {value.strip().rstrip("/") for value in os.getenv("DASHBOARD_ALLOWED_ORIGINS", self.site_url).split(",") if value.strip()}
        if origin.rstrip("/") in allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
        return response

    async def preflight(self, request: web.Request) -> web.Response:
        return web.Response(headers={
            "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Max-Age": "86400",
        })

    async def http(self) -> aiohttp.ClientSession:
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self.session

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        if not self.fernet:
            raise RuntimeError("TOKEN_ENCRYPTION_KEY is required before dashboard accounts can be linked")
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        if not value or not self.fernet:
            return ""
        return self.fernet.decrypt(value.encode()).decode()

    def current_user(self, request: web.Request) -> str | None:
        token = request.cookies.get(self.cookie_name, "")
        return self.store.dashboard_session_user(hashlib.sha256(token.encode()).hexdigest()) if token else None

    def require_user(self, request: web.Request) -> str:
        user_id = self.current_user(request)
        if not user_id:
            raise web.HTTPUnauthorized(text=json.dumps({"error": "Sign in is required"}), content_type="application/json")
        return user_id

    def issue_session(self, response: web.StreamResponse, user_id: str) -> None:
        token = secrets.token_urlsafe(48)
        self.store.save_dashboard_session(hashlib.sha256(token.encode()).hexdigest(), user_id, iso_after(days=30))
        response.set_cookie(
            self.cookie_name, token, max_age=30 * 86400, httponly=True,
            secure=self.public_url.startswith("https://"), samesite="None" if self.public_url.startswith("https://") else "Lax",
            path="/",
        )

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True, "service": "StreamBridge dashboard API"})

    async def me(self, request: web.Request) -> web.Response:
        user_id = self.current_user(request)
        if not user_id:
            return web.json_response({"authenticated": False, "providers": list(self.providers)})
        return web.json_response({
            "authenticated": True,
            "id": user_id,
            "identities": self.store.dashboard_identities(user_id),
            "providers": list(self.providers),
        })

    async def logout(self, request: web.Request) -> web.Response:
        token = request.cookies.get(self.cookie_name, "")
        if token:
            self.store.delete_dashboard_session(hashlib.sha256(token.encode()).hexdigest())
        response = web.json_response({"ok": True})
        response.del_cookie(self.cookie_name, path="/")
        return response

    async def disconnect_identity(self, request: web.Request) -> web.Response:
        user_id = self.require_user(request)
        provider = request.match_info["provider"]
        if provider not in self.providers:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "Unsupported provider"}),
                content_type="application/json",
            )
        try:
            with self.store.transaction():
                affected_workspace_ids = self.store.unlink_dashboard_identity(
                    user_id, provider
                )
        except ValueError as error:
            raise web.HTTPConflict(
                text=json.dumps({"error": str(error)}),
                content_type="application/json",
            )
        for workspace_id in affected_workspace_ids:
            await self.changed(workspace_id)
        return web.json_response(
            {"ok": True, "affected_workspace_ids": affected_workspace_ids}
        )

    async def list_workspaces(self, request: web.Request) -> web.Response:
        user_id = self.require_user(request)
        workspaces = self.store.workspaces(user_id)
        if not workspaces:
            workspace_id = self.store.save_workspace(user_id, {
                "ssn_targets": ["twitch", "youtube", "kick"],
                "relay_template": "{name} ({platform}) said: {message}",
                "transport_announcements": True,
                "enabled": True,
            })
            await self.changed(workspace_id)
            workspaces = self.store.workspaces(user_id)
        for workspace in workspaces:
            workspace["connections"] = [
                connection
                for connection in workspace["connections"]
                if connection["provider"] in self.connection_providers
            ]
            guild_id = str(workspace.get("discord_guild_id") or "")
            config = self.store.get(guild_id) if guild_id else None
            workspace["discord_channel_id"] = (
                config.discord_relay_channel_id
                if config and config.discord_relay_channel_id
                else config.channel_ids[0] if config and config.channel_ids else None
            )
            workspace["discord_enabled"] = bool(
                self.store.get_setting(guild_id, "discord_enabled", True)
            ) if guild_id else False
            workspace["discord_forward_enabled"] = bool(
                self.store.get_setting(guild_id, "discord_forward_enabled", True)
            ) if guild_id else True
            workspace["discord_receive_enabled"] = bool(
                self.store.get_setting(guild_id, "discord_receive_enabled", True)
            ) if guild_id else True
            if config:
                workspace["ssn_session_id"] = config.session_id
                workspace["ssn_targets"] = list(config.relay_targets)
                workspace["transport_announcements"] = bool(
                    self.store.get_setting(guild_id, "transport_announcements", workspace["transport_announcements"])
                )
            workspace["runtime_status"] = (
                await self.runtime_status_provider(guild_id)
                if guild_id and self.runtime_status_provider
                else {"ssn": "disconnected", "direct_platforms": []}
            )
        return web.json_response({"workspaces": workspaces})

    async def json_body(self, request: web.Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except (json.JSONDecodeError, ValueError):
            raise web.HTTPBadRequest(text=json.dumps({"error": "A JSON request body is required"}), content_type="application/json")
        if not isinstance(body, dict):
            raise web.HTTPBadRequest(text=json.dumps({"error": "The request body must be an object"}), content_type="application/json")
        return body

    async def validate_workspace(self, user_id: str, body: dict[str, Any]) -> None:
        template = str(body.get("relay_template", ""))
        for placeholder in ("{name}", "{message}", "{platform}"):
            if placeholder not in template:
                raise web.HTTPBadRequest(text=json.dumps({"error": f"Relay template must contain {placeholder}"}), content_type="application/json")
        targets = body.get("ssn_targets", [])
        if not isinstance(targets, list) or any(
            not isinstance(value, str) or not value.strip() or len(value) > 40
            for value in targets
        ):
            raise web.HTTPBadRequest(text=json.dumps({"error": "Invalid SSN platform selection"}), content_type="application/json")
        guild_id = str(body.get("discord_guild_id") or "")
        if bool(body.get("discord_enabled", False)) and not guild_id:
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "Select a Discord server or disable Discord"}),
                content_type="application/json",
            )
        if guild_id and guild_id not in {guild["id"] for guild in await self.available_discord_guilds(user_id)}:
            raise web.HTTPForbidden(
                text=json.dumps({"error": "You must administer the selected Discord server"}),
                content_type="application/json",
            )
        if guild_id:
            channels = await self.get_discord_channels(guild_id)
            channel_ids = {channel["id"] for channel in channels}
            discord_channel_id = str(body.get("discord_channel_id") or "")
            if (
                bool(body.get("discord_enabled", False))
                and not discord_channel_id
                and (
                    bool(body.get("discord_forward_enabled", True))
                    or bool(body.get("discord_receive_enabled", True))
                )
            ):
                raise web.HTTPBadRequest(text=json.dumps({"error": "Select a Discord channel or disable both Discord relay directions"}), content_type="application/json")
            if discord_channel_id and discord_channel_id not in channel_ids:
                raise web.HTTPBadRequest(text=json.dumps({"error": "Invalid Discord channel"}), content_type="application/json")

    async def available_discord_guilds(self, user_id: str) -> list[dict[str, str]]:
        identity = next(
            (item for item in self.store.dashboard_identities(user_id, include_tokens=True) if item["provider"] == "discord"),
            None,
        )
        if not identity:
            return []
        access_token = self.decrypt(str(identity["access_token"]))
        if not access_token:
            return []
        session = await self.http()
        async with session.get(
            "https://discord.com/api/v10/users/@me/guilds",
            headers={"Authorization": f"Bearer {access_token}"},
        ) as response:
            body = await response.json(content_type=None)
            if response.status >= 400:
                raise web.HTTPUnauthorized(
                    text=json.dumps({"error": "Reconnect Discord to refresh server access"}),
                    content_type="application/json",
                )
        administrator = 1 << 3
        return [
            {"id": str(guild["id"]), "name": str(guild.get("name", "Discord server"))}
            for guild in body
            if guild.get("owner") or int(guild.get("permissions", "0")) & administrator
        ]

    async def discord_guilds(self, request: web.Request) -> web.Response:
        return web.json_response({"guilds": await self.available_discord_guilds(self.require_user(request))})

    async def get_discord_channels(self, guild_id: str) -> list[dict[str, str]]:
        return await self.discord_channels_provider(guild_id) if self.discord_channels_provider else []

    async def discord_channels(self, request: web.Request) -> web.Response:
        user_id = self.require_user(request)
        guild_id = request.match_info["guild_id"]
        if guild_id not in {guild["id"] for guild in await self.available_discord_guilds(user_id)}:
            raise web.HTTPForbidden(text=json.dumps({"error": "You do not administer that Discord server"}), content_type="application/json")
        return web.json_response({"channels": await self.get_discord_channels(guild_id)})

    def apply_discord_configuration(self, body: dict[str, Any], *, commit: bool = True) -> None:
        guild_id = str(body.get("discord_guild_id") or "")
        if not guild_id:
            return
        channel_id = str(body.get("discord_channel_id") or "")
        self.store.clear_channels(guild_id, commit=commit)
        if channel_id:
            self.store.add_channel(guild_id, channel_id, commit=commit)
        self.store.set_settings(
            guild_id,
            {
                "discord_relay_channel_id": channel_id or None,
                "discord_enabled": bool(body.get("discord_enabled", False)),
                "discord_forward_enabled": bool(body.get("discord_forward_enabled", True)),
                "discord_receive_enabled": bool(body.get("discord_receive_enabled", True)),
                "transport_announcements": bool(body.get("transport_announcements", True)),
            },
            commit=commit,
        )
        session_id = str(body.get("ssn_session_id") or "").strip()
        if session_id:
            self.store.set_session(
                guild_id,
                session_id,
                [str(value).strip().lower() for value in body.get("ssn_targets", [])],
                commit=commit,
            )
        else:
            self.store.clear_session(guild_id, commit=commit)

    async def update_workspace(self, request: web.Request) -> web.Response:
        user_id = self.require_user(request)
        body = await self.json_body(request)
        await self.validate_workspace(user_id, body)
        workspace_id = request.match_info["workspace_id"]
        connections = body.get("connections", [])
        if not isinstance(connections, list):
            raise web.HTTPBadRequest(
                text=json.dumps({"error": "Connections must be a list"}),
                content_type="application/json",
            )
        try:
            with self.store.transaction():
                self.store.save_workspace(user_id, body, workspace_id, commit=False)
                self.apply_discord_configuration(body, commit=False)
                for connection in connections:
                    if not isinstance(connection, dict):
                        raise ValueError("Invalid direct connection")
                    provider = str(connection.get("provider", ""))
                    if provider not in self.connection_providers:
                        raise ValueError(f"Unsupported provider: {provider}")
                    self.store.set_workspace_connection(
                        user_id,
                        workspace_id,
                        provider,
                        str(connection.get("provider_user_id", "")),
                        bool(connection.get("enabled", True)),
                        connection.get("settings", {})
                        if isinstance(connection.get("settings", {}), dict)
                        else {},
                        commit=False,
                    )
        except ValueError as error:
            raise web.HTTPConflict(text=json.dumps({"error": str(error)}), content_type="application/json")
        await self.changed(workspace_id)
        return web.json_response({"ok": True})

    async def update_connection(self, request: web.Request) -> web.Response:
        user_id = self.require_user(request)
        provider = request.match_info["provider"]
        if provider not in self.connection_providers:
            raise web.HTTPBadRequest(text=json.dumps({"error": "Unsupported provider"}), content_type="application/json")
        body = await self.json_body(request)
        self.store.set_workspace_connection(
            user_id, request.match_info["workspace_id"], provider,
            str(body.get("provider_user_id", "")), bool(body.get("enabled", True)),
            body.get("settings", {}) if isinstance(body.get("settings", {}), dict) else {},
        )
        await self.changed(request.match_info["workspace_id"])
        return web.json_response({"ok": True})

    async def changed(self, workspace_id: str) -> None:
        if self.on_workspace_changed:
            await self.on_workspace_changed(workspace_id)

    async def begin_oauth(self, request: web.Request) -> web.Response:
        provider = request.match_info["provider"]
        if provider not in self.providers:
            raise web.HTTPNotFound()
        mode = request.query.get("mode", "login")
        user_id = self.current_user(request)
        if mode == "link" and not user_id:
            raise web.HTTPUnauthorized(text="Sign in before linking another account")
        return_to = request.query.get("return_to", f"{self.site_url}/dashboard")
        if not return_to.startswith(self.site_url):
            return_to = f"{self.site_url}/dashboard"
        state = secrets.token_urlsafe(32)
        verifier, challenge = pkce_pair()
        self.store.save_oauth_state(state, provider, mode, user_id, verifier, return_to, iso_after(minutes=10))
        return web.HTTPFound(self.authorization_url(provider, state, challenge))

    def authorization_url(self, provider: str, state: str, challenge: str) -> str:
        callback = f"{self.public_url}/dashboard/auth/{provider}/callback"
        values: dict[str, str] = {"response_type": "code", "redirect_uri": callback, "state": state}
        if provider == "discord":
            values.update(client_id=os.getenv("DISCORD_CLIENT_ID", ""), scope="identify guilds")
            endpoint = "https://discord.com/oauth2/authorize"
        elif provider == "google":
            values.update(client_id=os.getenv("YOUTUBE_CLIENT_ID", ""), scope="openid profile email https://www.googleapis.com/auth/youtube.force-ssl", access_type="offline", prompt="consent")
            endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
        elif provider == "twitch":
            values.update(client_id=os.getenv("TWITCH_CLIENT_ID", ""), scope="user:read:email chat:read chat:edit", force_verify="true")
            endpoint = "https://id.twitch.tv/oauth2/authorize"
        else:
            values.update(client_id=os.getenv("KICK_CLIENT_ID", ""), scope="user:read chat:write events:subscribe", code_challenge=challenge, code_challenge_method="S256")
            endpoint = "https://id.kick.com/oauth/authorize"
        if not values.get("client_id"):
            raise web.HTTPServiceUnavailable(text=f"{provider.title()} OAuth is not configured")
        return f"{endpoint}?{urllib.parse.urlencode(values)}"

    async def oauth_callback(self, request: web.Request) -> web.Response:
        provider = request.match_info["provider"]
        pending = self.store.pop_oauth_state(request.query.get("state", ""))
        if not pending or pending["provider"] != provider:
            raise web.HTTPBadRequest(text="This sign-in link is invalid or expired")
        if request.query.get("error"):
            return web.HTTPFound(f"{pending['return_to']}?auth_error={urllib.parse.quote(request.query['error'])}")
        try:
            identity = await self.exchange_identity(provider, request.query.get("code", ""), str(pending["verifier"]))
            user_id = str(pending["user_id"] or self.store.dashboard_user_for_identity(provider, identity["provider_user_id"]) or self.store.create_dashboard_user())
            if self.on_identity_linked:
                await self.on_identity_linked(provider, identity)
            identity["access_token"] = self.encrypt(identity.get("access_token", ""))
            identity["refresh_token"] = self.encrypt(identity.get("refresh_token", ""))
            self.store.save_dashboard_identity(user_id, identity)
            response = web.HTTPFound(f"{pending['return_to']}?auth=success")
            self.issue_session(response, user_id)
            return response
        except Exception:
            logging.exception("Dashboard %s OAuth callback failed", provider)
            return web.HTTPFound(f"{pending['return_to']}?auth_error=authorization_failed")

    async def exchange_identity(self, provider: str, code: str, verifier: str) -> dict[str, str]:
        callback = f"{self.public_url}/dashboard/auth/{provider}/callback"
        client_id = os.getenv({"google": "YOUTUBE_CLIENT_ID"}.get(provider, f"{provider.upper()}_CLIENT_ID"), "")
        client_secret = os.getenv({"google": "YOUTUBE_CLIENT_SECRET"}.get(provider, f"{provider.upper()}_CLIENT_SECRET"), "")
        token_urls = {
            "discord": "https://discord.com/api/v10/oauth2/token",
            "google": "https://oauth2.googleapis.com/token",
            "twitch": "https://id.twitch.tv/oauth2/token",
            "kick": "https://id.kick.com/oauth/token",
        }
        form = {"client_id": client_id, "client_secret": client_secret, "code": code, "grant_type": "authorization_code", "redirect_uri": callback}
        if provider == "kick":
            form["code_verifier"] = verifier
        session = await self.http()
        async with session.post(token_urls[provider], data=form) as response:
            token = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"{provider} token exchange failed: HTTP {response.status}")
        access = str(token["access_token"])
        headers = {"Authorization": f"Bearer {access}"}
        if provider == "discord":
            url = "https://discord.com/api/v10/users/@me"
        elif provider == "google":
            url = "https://openidconnect.googleapis.com/v1/userinfo"
        elif provider == "twitch":
            url = "https://api.twitch.tv/helix/users"
            headers["Client-Id"] = client_id
        else:
            url = "https://api.kick.com/public/v1/users"
        async with session.get(url, headers=headers) as response:
            profile = await response.json(content_type=None)
            if response.status >= 400:
                raise RuntimeError(f"{provider} profile lookup failed: HTTP {response.status}")
        if provider == "discord":
            identifier, name = str(profile["id"]), str(profile.get("global_name") or profile["username"])
            avatar = f"https://cdn.discordapp.com/avatars/{identifier}/{profile['avatar']}.png" if profile.get("avatar") else ""
        elif provider == "google":
            identifier, name, avatar = str(profile["sub"]), str(profile.get("name", profile.get("email", "Google user"))), str(profile.get("picture", ""))
        else:
            item = (profile.get("data") or [profile])[0]
            identifier = str(item.get("id", item.get("user_id", "")))
            name = str(item.get("display_name", item.get("name", item.get("login", provider.title()))))
            avatar = str(item.get("profile_image_url", item.get("profile_picture", "")) or "")
        return {
            "provider": provider, "provider_user_id": identifier, "display_name": name,
            "avatar_url": avatar, "access_token": access, "refresh_token": str(token.get("refresh_token", "")),
            "scopes": " ".join(token.get("scope", [])) if isinstance(token.get("scope"), list) else str(token.get("scope", "")),
        }

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()
