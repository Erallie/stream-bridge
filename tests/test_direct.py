import unittest

from ninjabridge.direct import kick_chat_payload


class DirectAdapterTests(unittest.TestCase):
    def test_kick_messages_use_application_bot_identity(self) -> None:
        payload = kick_chat_payload("x" * 501)

        self.assertEqual(payload["type"], "bot")
        self.assertEqual(len(payload["content"]), 500)
        self.assertNotIn("broadcaster_user_id", payload)


if __name__ == "__main__":
    unittest.main()
