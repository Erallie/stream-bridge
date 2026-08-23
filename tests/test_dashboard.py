from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from cryptography.fernet import Fernet

from streambridge.dashboard import DashboardAPI
from streambridge.database import ConfigStore


class DashboardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = ConfigStore(str(Path(self.directory.name) / "dashboard.sqlite"))

    def tearDown(self) -> None:
        self.store.close()
        self.directory.cleanup()

    def test_accounts_sessions_and_standalone_workspace(self) -> None:
        user_id = self.store.create_dashboard_user()
        self.store.save_dashboard_identity(
            user_id,
            {
                "provider": "google",
                "provider_user_id": "google-1",
                "display_name": "Streamer",
                "avatar_url": "https://example.test/avatar.png",
                "access_token": "encrypted-access",
                "refresh_token": "encrypted-refresh",
                "scopes": "openid youtube.force-ssl",
            },
        )
        self.assertEqual(
            self.store.dashboard_user_for_identity("google", "google-1"),
            user_id,
        )
        self.assertNotIn("access_token", self.store.dashboard_identities(user_id)[0])
        self.store.save_dashboard_session("hash", user_id, "2999-01-01T00:00:00+00:00")
        self.assertEqual(self.store.dashboard_session_user("hash"), user_id)

        workspace_id = self.store.save_workspace(
            user_id,
            {
                "ssn_session_id": "session123",
                "ssn_targets": ["twitch", "youtube"],
                "relay_template": "{name} ({platform}) said: {message}",
                "enabled": True,
            },
        )
        self.store.set_workspace_connection(
            user_id, workspace_id, "youtube", "google-1", True, {}
        )
        workspace = self.store.workspaces(user_id)[0]
        self.assertIsNone(workspace["discord_guild_id"])
        self.assertEqual(workspace["ssn_targets"], ["twitch", "youtube"])
        self.assertEqual(workspace["connections"][0]["provider"], "youtube")
        self.assertNotIn("name", workspace)
        self.assertNotIn("ssn_password", workspace)

    def test_identity_cannot_be_linked_to_two_users(self) -> None:
        first = self.store.create_dashboard_user()
        second = self.store.create_dashboard_user()
        identity = {
            "provider": "discord",
            "provider_user_id": "123",
            "display_name": "A",
        }
        self.store.save_dashboard_identity(first, identity)
        with self.assertRaisesRegex(ValueError, "already linked"):
            self.store.save_dashboard_identity(second, identity)

    def test_discord_access_is_refreshed_and_server_list_is_cached(self) -> None:
        class Response:
            def __init__(self, status, body):
                self.status = status
                self.body = body

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def json(self, content_type=None):
                return self.body

        class Session:
            def __init__(self):
                self.get_calls = 0
                self.post_calls = 0

            def get(self, url, **kwargs):
                self.get_calls += 1
                if self.get_calls == 1:
                    return Response(401, {"message": "401: Unauthorized"})
                return Response(
                    200,
                    [{"id": "guild-1", "name": "Server", "owner": True}],
                )

            def post(self, url, **kwargs):
                self.post_calls += 1
                return Response(
                    200,
                    {
                        "access_token": "new-access",
                        "refresh_token": "new-refresh",
                        "expires_in": 604800,
                    },
                )

        key = Fernet.generate_key().decode()
        with patch.dict(
            "os.environ",
            {
                "TOKEN_ENCRYPTION_KEY": key,
                "DISCORD_CLIENT_ID": "client-id",
                "DISCORD_CLIENT_SECRET": "client-secret",
            },
        ):
            dashboard = DashboardAPI(self.store)
            user_id = self.store.create_dashboard_user()
            self.store.save_dashboard_identity(
                user_id,
                {
                    "provider": "discord",
                    "provider_user_id": "discord-1",
                    "display_name": "Discord user",
                    "access_token": dashboard.encrypt("expired-access"),
                    "refresh_token": dashboard.encrypt("old-refresh"),
                },
            )
            session = Session()
            dashboard.http = AsyncMock(return_value=session)

            first = asyncio.run(dashboard.available_discord_guilds(user_id))
            second = asyncio.run(dashboard.available_discord_guilds(user_id))

            self.assertEqual(first, [{"id": "guild-1", "name": "Server"}])
            self.assertEqual(second, first)
            self.assertEqual(session.get_calls, 2)
            self.assertEqual(session.post_calls, 1)
            identity = self.store.dashboard_identities(user_id, include_tokens=True)[0]
            self.assertEqual(dashboard.decrypt(identity["access_token"]), "new-access")
            self.assertEqual(dashboard.decrypt(identity["refresh_token"]), "new-refresh")

    def test_unlink_identity_removes_its_connection_atomically(self) -> None:
        user_id = self.store.create_dashboard_user()
        for provider, provider_user_id in (("google", "google-1"), ("twitch", "twitch-1")):
            self.store.save_dashboard_identity(
                user_id,
                {
                    "provider": provider,
                    "provider_user_id": provider_user_id,
                    "display_name": provider.title(),
                },
            )
        workspace_id = self.store.save_workspace(
            user_id,
            {"ssn_targets": [], "relay_template": "{name} ({platform}) said: {message}"},
        )
        self.store.set_workspace_connection(
            user_id, workspace_id, "twitch", "twitch-1", True, {}
        )

        with self.store.transaction():
            affected = self.store.unlink_dashboard_identity(user_id, "twitch")

        self.assertEqual(affected, [workspace_id])
        self.assertEqual(
            [identity["provider"] for identity in self.store.dashboard_identities(user_id)],
            ["google"],
        )
        self.assertEqual(self.store.workspaces(user_id)[0]["connections"], [])

    def test_only_sign_in_identity_cannot_be_disconnected(self) -> None:
        user_id = self.store.create_dashboard_user()
        self.store.save_dashboard_identity(
            user_id,
            {
                "provider": "discord",
                "provider_user_id": "discord-1",
                "display_name": "Discord",
            },
        )

        with self.assertRaisesRegex(ValueError, "only sign-in method"):
            with self.store.transaction():
                self.store.unlink_dashboard_identity(user_id, "discord")

        self.assertEqual(len(self.store.dashboard_identities(user_id)), 1)

    def test_unlink_discord_disables_relay_but_preserves_channel(self) -> None:
        user_id = self.store.create_dashboard_user()
        for provider in ("discord", "twitch"):
            self.store.save_dashboard_identity(
                user_id,
                {
                    "provider": provider,
                    "provider_user_id": f"{provider}-1",
                    "display_name": provider.title(),
                },
            )
        workspace_id = self.store.save_workspace(
            user_id,
            {
                "discord_guild_id": "guild-1",
                "ssn_targets": [],
                "relay_template": "{name} ({platform}) said: {message}",
            },
        )
        self.store.add_channel("guild-1", "channel-1")
        self.store.set_settings(
            "guild-1",
            {"discord_relay_channel_id": "channel-1", "discord_enabled": True},
        )

        with self.store.transaction():
            affected = self.store.unlink_dashboard_identity(user_id, "discord")

        self.assertEqual(affected, [workspace_id])
        self.assertFalse(self.store.get_setting("guild-1", "discord_enabled"))
        self.assertEqual(self.store.get("guild-1").channel_ids, ("channel-1",))

    def test_account_can_only_have_one_workspace(self) -> None:
        user_id = self.store.create_dashboard_user()
        body = {
            "discord_guild_id": "123",
            "ssn_targets": [],
            "relay_template": "{name} ({platform}) said: {message}",
        }
        self.store.save_workspace(user_id, body)
        with self.assertRaisesRegex(ValueError, "already has a bridge"):
            self.store.save_workspace(user_id, body)

    def test_applies_complete_discord_configuration(self) -> None:
        dashboard = DashboardAPI(self.store)
        dashboard.apply_discord_configuration(
            {
                "discord_guild_id": "123",
                "discord_channel_id": "11",
                "discord_enabled": True,
                "discord_forward_enabled": False,
                "discord_receive_enabled": True,
                "transport_announcements": False,
                "ssn_session_id": "session-id",
                "ssn_targets": ["twitch", "tiktok", "future-platform"],
            }
        )
        config = self.store.get("123")
        self.assertIsNotNone(config)
        assert config
        self.assertEqual(config.channel_ids, ("11",))
        self.assertEqual(config.discord_relay_channel_id, "11")
        self.assertEqual(config.session_id, "session-id")
        self.assertEqual(
            config.relay_targets,
            ("twitch", "tiktok", "future-platform"),
        )
        self.assertFalse(self.store.get_setting("123", "transport_announcements"))
        self.assertTrue(self.store.get_setting("123", "discord_enabled"))
        self.assertFalse(self.store.get_setting("123", "discord_forward_enabled"))
        self.assertTrue(self.store.get_setting("123", "discord_receive_enabled"))

    def test_workspace_and_connections_save_with_one_reload(self) -> None:
        user_id = self.store.create_dashboard_user()
        self.store.save_dashboard_identity(
            user_id,
            {
                "provider": "twitch",
                "provider_user_id": "twitch-1",
                "display_name": "Relay bot",
            },
        )
        workspace_id = self.store.save_workspace(
            user_id,
            {
                "ssn_targets": [],
                "relay_template": "{name} ({platform}) said: {message}",
            },
        )
        dashboard = DashboardAPI(self.store)
        dashboard.require_user = Mock(return_value=user_id)
        dashboard.on_workspace_changed = AsyncMock()
        request = Mock()
        request.match_info = {"workspace_id": workspace_id}
        request.json = AsyncMock(
            return_value={
                "discord_guild_id": None,
                "discord_enabled": False,
                "ssn_targets": ["tiktok"],
                "relay_template": "{name} ({platform}) said: {message}",
                "enabled": True,
                "connections": [
                    {
                        "provider": "twitch",
                        "provider_user_id": "twitch-1",
                        "enabled": True,
                        "settings": {},
                    }
                ],
            }
        )

        asyncio.run(dashboard.update_workspace(request))

        workspace = self.store.workspaces(user_id)[0]
        self.assertEqual(workspace["ssn_targets"], ["tiktok"])
        self.assertEqual(workspace["connections"][0]["provider"], "twitch")
        dashboard.on_workspace_changed.assert_awaited_once_with(workspace_id)


if __name__ == "__main__":
    unittest.main()
