import os
import unittest

os.environ.setdefault("DISCORD_CLIENT_ID", "123456789012345678")

from ninjabridge.bot import bot


class CommandMetadataTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
