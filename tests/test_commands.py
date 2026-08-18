import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DISCORD_CLIENT_ID", "123456789012345678")

from ninjabridge.bot import bot, webhook_username
from ninjabridge.relay import ReflectionTracker


class CommandMetadataTests(unittest.TestCase):
    def test_webhook_username_avoids_discord_reserved_names(self) -> None:
        self.assertEqual(webhook_username("Discord Helper", "kick"), "Dis-cord Helper (Kick)")
        self.assertEqual(webhook_username("Clyde", "youtube"), "C-lyde (Youtube)")
        self.assertLessEqual(len(webhook_username("x" * 100, "twitch")), 80)

    def test_ssn_reflection_trackers_are_isolated_by_discord_server(self) -> None:
        bot.ssn_reflections.pop(1, None)
        bot.ssn_reflections.pop(2, None)
        try:
            first = bot.ssn_reflections.setdefault(1, ReflectionTracker())
            second = bot.ssn_reflections.setdefault(2, ReflectionTracker())
            first.add("youtube", "Alex said: Hello")

            self.assertFalse(second.consume("youtube", "Alex said: Hello"))
            self.assertTrue(first.consume("youtube", "Alex said: Hello"))
        finally:
            bot.ssn_reflections.pop(1, None)
            bot.ssn_reflections.pop(2, None)

    def test_direct_platforms_reports_configured_adapters(self) -> None:
        guild_id = 987654321
        bot.direct_hubs[guild_id] = SimpleNamespace(adapters={"twitch": object(), "youtube": object()})
        try:
            self.assertEqual(bot.direct_platforms(guild_id), ["twitch", "youtube"])
        finally:
            bot.direct_hubs.pop(guild_id, None)

    def test_direct_platforms_is_empty_without_configuration(self) -> None:
        guild_id = 987654322
        bot.direct_hubs.pop(guild_id, None)

        self.assertEqual(bot.direct_platforms(guild_id), [])

    def test_every_command_and_subcommand_has_a_description(self) -> None:
        commands = bot.tree.get_commands()
        self.assertTrue(commands)
        for command in commands:
            self.assertTrue(command.description.strip(), command.qualified_name)
            for child in getattr(command, "commands", []):
                self.assertTrue(child.description.strip(), child.qualified_name)

    def test_direct_message_replaces_top_level_template(self) -> None:
        names = {command.name for command in bot.tree.get_commands()}
        direct = next(command for command in bot.tree.get_commands() if command.name == "direct")
        direct_names = {command.name for command in direct.commands}

        self.assertNotIn("template", names)
        self.assertIn("message", direct_names)

    def test_direct_kick_authorizes_without_requesting_an_account_id(self) -> None:
        direct = next(command for command in bot.tree.get_commands() if command.name == "direct")
        kick = next(command for command in direct.commands if command.name == "kick")

        self.assertEqual(kick.parameters, [])

    def test_direct_youtube_authorizes_without_requesting_a_live_chat_id(self) -> None:
        direct = next(command for command in bot.tree.get_commands() if command.name == "direct")
        youtube = next(command for command in direct.commands if command.name == "youtube")

        self.assertEqual(youtube.parameters, [])


if __name__ == "__main__":
    unittest.main()
