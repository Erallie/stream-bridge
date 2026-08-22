from streambridge.oauth import OAuthToken


def test_oauth_token_requires_explicit_dashboard_credentials() -> None:
    token = OAuthToken(
        "TWITCH", "https://id.twitch.tv/oauth2/token",
        refresh_token="linked-refresh", client_id="client", client_secret="secret",
    )
    assert token.access_token == ""
    assert token.refresh_token == "linked-refresh"
    assert token.configured
