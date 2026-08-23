import unittest

from streambridge.oauth import OAuthToken


class OAuthTokenTests(unittest.TestCase):
    def test_requires_explicit_dashboard_credentials(self) -> None:
        token = OAuthToken(
            "TWITCH",
            "https://id.twitch.tv/oauth2/token",
            refresh_token="linked-refresh",
            client_id="client",
            client_secret="secret",
        )
        self.assertEqual(token.access_token, "")
        self.assertEqual(token.refresh_token, "linked-refresh")
        self.assertTrue(token.configured)


if __name__ == "__main__":
    unittest.main()
