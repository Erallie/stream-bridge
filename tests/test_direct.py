import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from streambridge.direct import DirectHub, TwitchAdapter, YouTubeAdapter, youtube_error_reasons
from streambridge.kick import broadcaster_id, kick_chat_payload


class DirectAdapterTests(unittest.TestCase):
    def test_twitch_messages_include_the_looked_up_avatar(self) -> None:
        received = []

        async def handler(payload):
            received.append(payload)

        async def exercise() -> None:
            adapter = TwitchAdapter("channel", handler, Mock(), "linked-account")

            async def avatar(user_id: str, login: str) -> str:
                self.assertEqual((user_id, login), ("42", "alex"))
                return "https://example.test/alex.png"

            adapter.get_avatar = avatar
            await adapter.parse_message(
                "@id=message-1;user-id=42;display-name=Alex;color=#9146FF :alex!alex@alex.tmi.twitch.tv PRIVMSG #channel :hello"
            )

        asyncio.run(exercise())
        self.assertEqual(received[0]["chatimg"], "https://example.test/alex.png")

    def test_youtube_announces_each_new_broadcast_once(self) -> None:
        async def handler(payload):
            pass

        async def exercise() -> None:
            detected = AsyncMock()
            adapter = YouTubeAdapter(handler, Mock(), detected)
            chats = iter(("first-chat", "first-chat", "second-chat"))

            async def request(session, method, url, **kwargs):
                return 200, {"items": [{"snippet": {"liveChatId": next(chats)}}]}

            adapter.request = request
            adapter.get_session = lambda: asyncio.sleep(0, result=object())
            await adapter.discover_live_chat()
            adapter.clear_live_broadcast(ended=False)
            await adapter.discover_live_chat()
            await adapter.discover_live_chat()
            self.assertEqual(detected.await_count, 2)

        asyncio.run(exercise())

    def test_youtube_can_announce_again_after_the_broadcast_ends(self) -> None:
        async def handler(payload):
            pass

        async def exercise() -> None:
            detected = AsyncMock()
            adapter = YouTubeAdapter(handler, Mock(), detected)
            responses = iter((
                {"items": [{"id": "broadcast-1", "snippet": {"liveChatId": "chat-1"}}]},
                {"items": []},
                {"items": [{"id": "broadcast-1", "snippet": {"liveChatId": "chat-1"}}]},
            ))

            async def request(session, method, url, **kwargs):
                return 200, next(responses)

            adapter.request = request
            adapter.get_session = lambda: asyncio.sleep(0, result=object())
            await adapter.discover_live_chat()
            await adapter.discover_live_chat()
            await adapter.discover_live_chat()
            self.assertEqual(detected.await_count, 2)

        asyncio.run(exercise())

    def test_direct_hub_does_not_start_youtube_polling_when_ssn_is_connected(self) -> None:
        async def handler(payload):
            pass

        hub = DirectHub(handler)
        youtube = Mock()
        hub.adapters = {"youtube": youtube}

        hub.start(youtube_polling_enabled=False)

        youtube.start.assert_not_called()

    def test_direct_hub_pauses_and_resumes_youtube_with_transport(self) -> None:
        async def handler(payload):
            pass

        async def exercise() -> None:
            hub = DirectHub(handler)
            youtube = Mock()
            youtube.set_polling_enabled = AsyncMock()
            hub.adapters = {"youtube": youtube}

            await hub.set_youtube_polling_enabled(False)
            await hub.set_youtube_polling_enabled(True)

            self.assertEqual(
                youtube.set_polling_enabled.await_args_list,
                [unittest.mock.call(False), unittest.mock.call(True)],
            )

        asyncio.run(exercise())

    def test_twitch_broadcaster_messages_are_not_suppressed(self) -> None:
        received = []

        async def handler(payload):
            received.append(payload)

        async def exercise() -> None:
            adapter = TwitchAdapter("channel", handler, Mock(), "broadcaster")

            async def avatar(user_id: str, login: str) -> str:
                return ""

            adapter.get_avatar = avatar
            await adapter.parse_message(
                "@id=message-1;user-id=42;display-name=Broadcaster;color=#9146FF "
                ":broadcaster!broadcaster@broadcaster.tmi.twitch.tv "
                "PRIVMSG #channel :manual message"
            )

        asyncio.run(exercise())
        self.assertEqual(received[0]["chatmessage"], "manual message")

    def test_kick_messages_use_application_bot_identity(self) -> None:
        payload = kick_chat_payload("x" * 501)

        self.assertEqual(payload["type"], "bot")
        self.assertEqual(len(payload["content"]), 500)
        self.assertNotIn("broadcaster_user_id", payload)

    def test_kick_events_expose_their_broadcaster_for_routing(self) -> None:
        event = {"broadcaster": {"user_id": 12345}}

        self.assertEqual(broadcaster_id(event), "12345")
        self.assertEqual(broadcaster_id({}), "")

    def test_youtube_discovers_the_authorized_accounts_active_chat(self) -> None:
        async def handler(payload):
            pass

        async def exercise() -> None:
            adapter = YouTubeAdapter(handler, Mock())

            async def request(session, method, url, **kwargs):
                self.assertEqual(url, "https://www.googleapis.com/youtube/v3/liveBroadcasts")
                self.assertEqual(kwargs["params"]["broadcastStatus"], "active")
                self.assertNotIn("mine", kwargs["params"])
                return 200, {"items": [{"snippet": {"liveChatId": "discovered-chat"}}]}

            adapter.request = request
            adapter.get_session = lambda: asyncio.sleep(0, result=object())
            self.assertEqual(await adapter.discover_live_chat(), "discovered-chat")
            self.assertEqual(adapter.live_chat_id, "discovered-chat")

        asyncio.run(exercise())

    def test_youtube_recognizes_a_normally_ended_live_chat(self) -> None:
        body = {"error": {"errors": [{"reason": "liveChatEnded"}]}}

        self.assertEqual(youtube_error_reasons(body), {"liveChatEnded"})

    def test_youtube_broadcaster_messages_are_not_suppressed(self) -> None:
        received = []

        async def handler(payload):
            received.append(payload)

        async def exercise() -> None:
            adapter = YouTubeAdapter(handler, Mock())
            await adapter.parse_message(
                {
                    "id": "message-1",
                    "snippet": {
                        "type": "textMessageEvent",
                        "displayMessage": "manual message",
                    },
                    "authorDetails": {
                        "channelId": "channel-1",
                        "displayName": "Broadcaster",
                        "isChatOwner": True,
                    },
                }
            )

        asyncio.run(exercise())
        self.assertEqual(received[0]["chatmessage"], "manual message")

    def test_youtube_removes_leading_at_from_display_name(self) -> None:
        received = []

        async def handler(payload):
            received.append(payload)

        async def exercise() -> None:
            adapter = YouTubeAdapter(handler, Mock())
            await adapter.parse_message(
                {
                    "id": "message-1",
                    "snippet": {
                        "type": "textMessageEvent",
                        "displayMessage": "hello",
                    },
                    "authorDetails": {
                        "channelId": "channel-1",
                        "displayName": "@Broadcaster",
                    },
                }
            )

        asyncio.run(exercise())
        self.assertEqual(received[0]["chatname"], "Broadcaster")
        self.assertEqual(received[0]["username"], "Broadcaster")

    def test_youtube_waits_when_the_authorized_account_is_not_live(self) -> None:
        async def handler(payload):
            pass

        async def exercise() -> None:
            adapter = YouTubeAdapter(handler, Mock())

            async def request(session, method, url, **kwargs):
                return 200, {"items": []}

            adapter.request = request
            adapter.get_session = lambda: asyncio.sleep(0, result=object())
            self.assertEqual(await adapter.discover_live_chat(), "")
            self.assertTrue(adapter.waiting_for_broadcast)

        asyncio.run(exercise())

    def test_reflections_track_the_exact_truncated_platform_message(self) -> None:
        class Adapter:
            def __init__(self) -> None:
                self.sent = []

            async def send(self, text: str) -> None:
                self.sent.append(text)

        async def handler(payload):
            pass

        async def exercise() -> None:
            hub = DirectHub(handler)
            twitch = Adapter()
            youtube = Adapter()
            hub.adapters = {"twitch": twitch, "youtube": youtube}
            await hub.send("x" * 600)

            self.assertEqual(twitch.sent, ["x" * 500])
            self.assertEqual(youtube.sent, ["x" * 200])
            self.assertTrue(hub.reflections.consume("twitch", "x" * 500))
            self.assertTrue(hub.reflections.consume("youtube", "x" * 200))

        asyncio.run(exercise())

    def test_reflections_also_track_ssn_formatted_aliases(self) -> None:
        class Adapter:
            async def send(self, text: str) -> None:
                return None

        async def handler(payload):
            pass

        async def exercise() -> None:
            hub = DirectHub(handler)
            hub.adapters = {"twitch": Adapter(), "youtube": Adapter()}
            alias = "Alice said: " + ("x" * 600)

            succeeded = await hub.send(
                "Alice: hello (from Discord)",
                reflection_aliases=(alias,),
            )

            self.assertEqual(succeeded, {"twitch", "youtube"})
            self.assertTrue(hub.reflections.consume("twitch", alias[:500]))
            self.assertTrue(hub.reflections.consume("youtube", alias[:200]))

        asyncio.run(exercise())


if __name__ == "__main__":
    unittest.main()
