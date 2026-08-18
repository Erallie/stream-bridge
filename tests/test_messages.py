import unittest

from streambridge.messages import (
    discord_to_plain_content,
    render_discord_content,
    ssn_to_plain_text,
    to_relay_text,
    validate_direct_relay_template,
)


class MessageTests(unittest.TestCase):
    def test_formats_relay_like_ssn(self) -> None:
        self.assertEqual(to_relay_text({"chatname": "Alex", "chatmessage": "hello"}), "Alex said: hello")

    def test_formats_custom_direct_relay(self) -> None:
        payload = {"chatname": "Alex", "chatmessage": "hello", "type": "youtube"}
        self.assertEqual(to_relay_text(payload, "[{platform}] {name}: {message}"), "[Youtube] Alex: hello")

    def test_template_requires_message_and_rejects_unknown_fields(self) -> None:
        with self.assertRaisesRegex(ValueError, "must contain"):
            validate_direct_relay_template("{name}")
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            validate_direct_relay_template("{name}: {text} {message}")

    def test_empty_template_restores_default(self) -> None:
        self.assertEqual(validate_direct_relay_template(""), "{name} said: {message}")

    def test_discord_static_and_animated_emotes_become_ssn_images(self) -> None:
        rendered, has_emote = render_discord_content("Hi <:wave:123> <a:dance:456>!")
        self.assertTrue(has_emote)
        self.assertIn("https://cdn.discordapp.com/emojis/123.png?size=128&amp;quality=lossless", rendered)
        self.assertIn("https://cdn.discordapp.com/emojis/456.gif?size=128&amp;quality=lossless", rendered)
        self.assertIn('class="regular-emote"', rendered)

    def test_discord_emote_markup_escapes_text_and_resolves_mentions(self) -> None:
        rendered, _ = render_discord_content("<b> <@42> <#7> <:ok:9>", {"42": "Alex"}, channels={"7": "general"})
        self.assertTrue(rendered.startswith("&lt;b&gt; @Alex #general "))
        self.assertNotIn("<b>", rendered)

    def test_direct_relay_uses_plain_text_instead_of_emote_html(self) -> None:
        payload = {"chatname": "Alex", "chatmessage": '<img src="emoji">', "plainText": ":wave:", "type": "discord"}
        self.assertEqual(to_relay_text(payload), "Alex said: :wave:")

    def test_discord_custom_emotes_become_bare_names_for_platform_chat(self) -> None:
        content = "<:erallieHeart:1529884213434777742> and <a:dance:456>"
        self.assertEqual(discord_to_plain_content(content), "erallieHeart and dance")

    def test_discord_emote_only_relay_keeps_the_sender_wrapper(self) -> None:
        content = "<:erallieHeart:1529884213434777742>"
        payload = {
            "chatname": "Erika Gozar",
            "chatmessage": '<img src="emoji">',
            "plainText": discord_to_plain_content(content),
            "type": "discord",
        }

        self.assertEqual(to_relay_text(payload), "Erika Gozar said: erallieHeart")

    def test_text_plus_discord_emote_still_uses_the_relay_template(self) -> None:
        content = "Love this <:erallieHeart:1529884213434777742>"
        payload = {
            "chatname": "Erika Gozar",
            "plainText": discord_to_plain_content(content),
            "type": "discord",
        }

        self.assertEqual(to_relay_text(payload), "Erika Gozar said: Love this erallieHeart")

    def test_ssn_html_entities_are_decoded_for_discord(self) -> None:
        self.assertEqual(ssn_to_plain_text("I&#039;m from Twitch &amp; Kick"), "I'm from Twitch & Kick")

    def test_ssn_emote_html_retains_alt_text(self) -> None:
        self.assertEqual(
            ssn_to_plain_text('Hello <img class="regular-emote" src="emoji.png" alt=":wave:"><br>friend'),
            "Hello :wave:\nfriend",
        )

    def test_ssn_script_and_style_markup_is_not_relayed(self) -> None:
        self.assertEqual(ssn_to_plain_text("hello<script>alert(1)</script><style>x</style> world"), "hello world")


if __name__ == "__main__":
    unittest.main()
