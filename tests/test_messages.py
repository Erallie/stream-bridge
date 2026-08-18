import unittest

from ninjabridge.messages import to_relay_text, validate_direct_relay_template


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


if __name__ == "__main__":
    unittest.main()
