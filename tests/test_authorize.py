import base64
import hashlib
import unittest

from ninjabridge.authorize import PROVIDERS, create_pkce_pair


class AuthorizationTests(unittest.TestCase):
    def test_kick_provider_uses_required_scopes(self) -> None:
        self.assertEqual(PROVIDERS["kick"]["token"], "https://id.kick.com/oauth/token")
        self.assertEqual(set(PROVIDERS["kick"]["scope"].split()), {"user:read", "chat:write", "events:subscribe"})

    def test_pkce_challenge_matches_verifier(self) -> None:
        verifier, challenge = create_pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")

        self.assertEqual(challenge, expected)
        self.assertNotIn("=", challenge)
        self.assertGreaterEqual(len(verifier), 43)


if __name__ == "__main__":
    unittest.main()
