"""
Slash commands for talking to Maynard directly:

- /ask <question>   - ask Maynard something
- /watch <member>   - he takes a particular interest in someone, as a study
- /experiment       - an entry from his old research journals
- /mood             - (admin) peek at his current mood

There is no /interact. Maynard doesn't talk to the other ghosts.
"""

import json
import logging
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("moonveil.commands")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
LORE_PATH = DATA_DIR / "lore.json"

WATCH_DURATION_SECONDS = 60 * 60 * 6  # 6 hours


def _load_lore():
    try:
        with open(LORE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        log.exception("Failed to load lore.json")
        return []


class GhostCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.lore = _load_lore()

    def _personality(self):
        return self.bot.get_cog("Personality")

    @app_commands.command(name="ask", description="Ask Maynard Moonveil a question.")
    @app_commands.describe(question="What do you want to ask him?")
    async def ask(self, interaction: discord.Interaction, question: str):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("No one's answering right now.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        asker = str(interaction.user.display_name)
        prior = personality.memories_about(asker, limit=1)
        memory_hint = prior[0] if prior else None

        cue = (
            f'{asker} asks you directly: "{question}". Answer as yourself - curious, delighted to be '
            "asked, and genuinely engaged with what they actually asked."
        )
        line = await personality.speak(cue, memory_hint=memory_hint, max_tokens=220)

        embed = discord.Embed(description=line, color=0x8B5FBF)
        embed.set_author(name=f"{asker} asks Maynard…")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="watch", description="Ask Maynard to take a particular interest in someone.")
    @app_commands.describe(member="Who should he observe?")
    async def watch(self, interaction: discord.Interaction, member: discord.Member):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("No response right now.", ephemeral=True)
            return
        if member.bot:
            await interaction.response.send_message(
                "He keeps to the students. The other spirits are not part of this study.", ephemeral=True
            )
            return

        personality.set_haunt_target(member.id, WATCH_DURATION_SECONDS)

        cue = (
            f"You've just been asked to take a particular interest in {member.display_name} for a while - "
            "to observe them as a subject in one of your studies. Announce it in character: delighted, "
            "affectionate, a scientist with a promising new specimen. Warm, never ominous."
        )
        line = await personality.speak(cue, max_tokens=150)

        embed = discord.Embed(description=line, color=0x8B5FBF)
        embed.set_footer(text=f"{member.display_name} is now under observation.")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="experiment", description="Hear an entry from Maynard's old research journals.")
    async def experiment(self, interaction: discord.Interaction):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("The journals stay shut tonight.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        fragment = personality.next_lore_fragment(self.lore)
        if fragment is None:
            line = await personality.speak(
                "Someone has asked for another entry from your research journals, but you've shared every "
                "one you're willing to share for now. Deflect, in character, playfully - more research is "
                "required - without saying you've run out.",
                max_tokens=120,
            )
            await interaction.followup.send(embed=discord.Embed(description=line, color=0x5A5A5A))
            return

        cue = (
            "Tell whoever's listening about this entry from your old research journals, in your own voice - "
            f'not verbatim, but true to it: "{fragment}"'
        )
        line = await personality.speak(cue, max_tokens=220)

        embed = discord.Embed(title="From the journals of Maynard Moonveil…",
                              description=line, color=0x8B5FBF)
        remaining = len(self.lore) - personality.state.get("lore_index", 0)
        embed.set_footer(text=f"{remaining} entr{'ies' if remaining != 1 else 'y'} still unread.")
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="mood", description="(admin) Peek at Maynard's current mood.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def mood(self, interaction: discord.Interaction):
        personality = self._personality()
        if not personality:
            await interaction.response.send_message("No mood to report.", ephemeral=True)
            return
        from cogs.personality import GHOST_NAME
        await interaction.response.send_message(
            f"{GHOST_NAME}'s current mood: `{personality.current_mood()}`", ephemeral=True
        )

    @mood.error
    async def mood_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You need permission for this one.", ephemeral=True)
        else:
            log.exception("Unhandled error in /mood", exc_info=error)


async def setup(bot: commands.Bot):
    await bot.add_cog(GhostCommands(bot))
