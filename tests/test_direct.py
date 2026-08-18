import asyncio
import unittest

from ninjabridge.direct import TwitchAdapter
from ninjabridge.kick import broadcaster_id, kick_chat_payload


class DirectAdapterTests(unittest.TestCase):
    def test_twitch_messages_include_the_looked_up_avatar(self) -> None:
        received = []

        async def handler(payload):
            received.append(payload)

        async def exercise() -> None:
            adapter = TwitchAdapter("channel", handler)

            async def avatar(user_id: str, login: str) -> str:
                self.assertEqual((user_id, login), ("42", "alex"))
                return "https://example.test/alex.png"

            adapter.get_avatar = avatar
            await adapter.parse_message(
                "@id=message-1;user-id=42;display-name=Alex;color=#9146FF :alex!alex@alex.tmi.twitch.tv PRIVMSG #channel :hello"
            )

        asyncio.run(exercise())
        self.assertEqual(received[0]["chatimg"], "https://example.test/alex.png")

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
