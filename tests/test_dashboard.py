from __future__ import annotations

from streambridge.database import ConfigStore


def test_dashboard_accounts_sessions_and_standalone_workspace(tmp_path) -> None:
    store = ConfigStore(str(tmp_path / "dashboard.sqlite"))
    user_id = store.create_dashboard_user()
    store.save_dashboard_identity(user_id, {
        "provider": "google",
        "provider_user_id": "google-1",
        "display_name": "Streamer",
        "avatar_url": "https://example.test/avatar.png",
        "access_token": "encrypted-access",
        "refresh_token": "encrypted-refresh",
        "scopes": "openid youtube.force-ssl",
    })
    assert store.dashboard_user_for_identity("google", "google-1") == user_id
    assert "access_token" not in store.dashboard_identities(user_id)[0]

    store.save_dashboard_session("hash", user_id, "2999-01-01T00:00:00+00:00")
    assert store.dashboard_session_user("hash") == user_id

    workspace_id = store.save_workspace(user_id, {
        "name": "Standalone stream",
        "ssn_session_id": "session123",
        "ssn_targets": ["twitch", "youtube"],
        "relay_template": "{name} ({platform}) said: {message}",
        "enabled": True,
    })
    store.set_workspace_connection(user_id, workspace_id, "youtube", "google-1", True, {})
    workspace = store.workspaces(user_id)[0]
    assert workspace["discord_guild_id"] is None
    assert workspace["ssn_targets"] == ["twitch", "youtube"]
    assert workspace["connections"][0]["provider"] == "youtube"


def test_dashboard_identity_cannot_be_linked_to_two_users(tmp_path) -> None:
    store = ConfigStore(str(tmp_path / "dashboard.sqlite"))
    first = store.create_dashboard_user()
    second = store.create_dashboard_user()
    identity = {"provider": "discord", "provider_user_id": "123", "display_name": "A"}
    store.save_dashboard_identity(first, identity)
    try:
        store.save_dashboard_identity(second, identity)
    except ValueError as error:
        assert "already linked" in str(error)
    else:
        raise AssertionError("Expected an account-link collision")


def test_discord_server_can_only_belong_to_one_workspace(tmp_path) -> None:
    store = ConfigStore(str(tmp_path / "dashboard.sqlite"))
    user_id = store.create_dashboard_user()
    body = {
        "name": "Server bridge",
        "discord_guild_id": "123",
        "ssn_targets": [],
        "relay_template": "{name} ({platform}) said: {message}",
    }
    store.save_workspace(user_id, body)
    try:
        store.save_workspace(user_id, body)
    except ValueError as error:
        assert "already assigned" in str(error)
    else:
        raise AssertionError("Expected a duplicate Discord server assignment to be rejected")
