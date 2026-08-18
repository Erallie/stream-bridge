import unittest

from streambridge.relay import ReflectionTracker, normalize_relay_text


class ReflectionTrackerTests(unittest.TestCase):
    def test_matches_case_and_whitespace_without_crossing_platforms(self) -> None:
        tracker = ReflectionTracker()
        tracker.add("YouTube", "  Alice:   Hello WORLD ")

        self.assertFalse(tracker.consume("twitch", "Alice: Hello World"))
        self.assertTrue(tracker.consume("youtube", "alice: hello world"))
        self.assertFalse(tracker.consume("youtube", "alice: hello world"))

    def test_expires_and_stays_bounded(self) -> None:
        tracker = ReflectionTracker(ttl_seconds=0.001, max_per_platform=2)
        tracker.add("kick", "one")
        tracker.add("kick", "two")
        tracker.add("kick", "three")

        self.assertFalse(tracker.consume("kick", "one"))
        tracker.items["kick"] = type(tracker.items["kick"])(
            (created_at - 1, text) for created_at, text in tracker.items["kick"]
        )
        self.assertFalse(tracker.consume("kick", "two"))

    def test_normalization_is_stable(self) -> None:
        self.assertEqual(normalize_relay_text(" A\n B  "), "a b")

    def test_kick_emote_name_reflection_is_consumed(self) -> None:
        tracker = ReflectionTracker()
        tracker.add("kick", "Erika Gozar said: erallieHeart")

        self.assertTrue(tracker.consume("kick", "Erika Gozar said: erallieHeart"))
        self.assertFalse(tracker.consume("kick", "Erika Gozar said: erallieHeart"))


if __name__ == "__main__":
    unittest.main()
