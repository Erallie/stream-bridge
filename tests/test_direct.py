import unittest

from ninjabridge.kick import broadcaster_id, kick_chat_payload


class DirectAdapterTests(unittest.TestCase):
    def test_kick_messages_use_application_bot_identity(self) -> None:
        payload = kick_chat_payload("x" * 501)

        self.assertEqual(payload["type"], "bot")
        self.assertEqual(len(payload["content"]), 500)
        self.assertNotIn("broadcaster_user_id", payload)

    def test_kick_events_expose_their_broadcaster_for_routing(self) -> None:
        event = {"broadcaster": {"user_id": 12345}}

        self.assertEqual(broadcaster_id(event), "12345")
        self.assertEqual(broadcaster_id({}), "")


if __name__ == "__main__":
    unittest.main()
