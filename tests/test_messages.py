import unittest

from ninjabridge.messages import to_relay_text


class MessageTests(unittest.TestCase):
    def test_formats_relay_like_ssn(self) -> None:
        self.assertEqual(to_relay_text({"chatname": "Alex", "chatmessage": "hello"}), "Alex said: hello")


if __name__ == "__main__":
    unittest.main()
