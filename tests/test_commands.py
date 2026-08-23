import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("DISCORD_CLIENT_ID", "123456789012345678")

from streambridge.bot import bot, format_discord_status, format_status, webhook_username
from streambridge.relay import ReflectionTracker


class CommandMetadataTests(unittest.TestCase):
    def test_status_labels_remain_bold(self) -> None:
        message = format_status("#chat (forwarding/receiving)", "abc••••••", "connected", "twitch, youtube", "twitch (channel)", "{message}")

        self.assertIn("**Discord relay channel:** #chat (forwarding/receiving)", message)
        self.assertIn("**SSN session:**", message)
        self.assertIn("**SSN Platforms:** twitch, youtube", message)
        self.assertIn("**Direct platforms:**", message)
        self.assertIn("**Direct relay message:**", message)

    def test_status_displays_disabled_in_place_of_discord_channel(self) -> None:
        message = format_status("Disabled", "not set", "disconnected", "none", "none", "{message}")

        self.assertIn("**Discord relay channel:** Disabled", message)
        self.assertNotIn("**Discord integration:**", message)

    def test_discord_status_combines_channel_and_relay_directions(self) -> None:
        self.assertEqual(format_discord_status("123", True, True, True), "<#123> (forwarding/receiving)")
        self.assertEqual(format_discord_status("123", True, True, False), "<#123> (forwarding only)")
        self.assertEqual(format_discord_status("123", True, False, True), "<#123> (receiving only)")
        self.assertEqual(format_discord_status("123", False, True, True), "Disabled")

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
        self.assertEqual(direct_names, {"setup", "disable", "message"})
        message = next(command for command in direct.commands if command.name == "message")
        self.assertEqual(message.parameters, [])

    def test_ssn_commands_are_grouped_and_old_top_level_names_are_gone(self) -> None:
        commands = {command.name: command for command in bot.tree.get_commands()}

        self.assertNotIn("setup", commands)
        self.assertNotIn("disable", commands)
        self.assertIn("ssn", commands)
        self.assertEqual({command.name for command in commands["ssn"].commands}, {"connect", "disconnect"})

    def test_ssn_connect_does_not_request_an_overlay_password(self) -> None:
        ssn = next(command for command in bot.tree.get_commands() if command.name == "ssn")
        connect = next(command for command in ssn.commands if command.name == "connect")

        self.assertEqual([parameter.name for parameter in connect.parameters], ["session_id", "relay_targets"])

    def test_direct_commands_only_open_the_dashboard(self) -> None:
        direct = next(command for command in bot.tree.get_commands() if command.name == "direct")
        self.assertEqual({command.name for command in direct.commands}, {"setup", "disable", "message"})
        self.assertTrue(all(command.parameters == [] for command in direct.commands))

    def test_channel_commands_replace_forward_and_receive_groups(self) -> None:
        commands = {command.name: command for command in bot.tree.get_commands()}

        self.assertNotIn("forward", commands)
        self.assertNotIn("receive", commands)
        self.assertIn("channel", commands)
        self.assertEqual({command.name for command in commands["channel"].commands}, {"set", "remove"})

        set_command = next(command for command in commands["channel"].commands if command.name == "set")
        self.assertEqual(
            [parameter.name for parameter in set_command.parameters],
            ["channel", "forward", "receive"],
        )


if __name__ == "__main__":
    unittest.main()
