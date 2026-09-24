"""
Maynard Moonveil - founder of House Moonveil, the castle's most gleeful agent of chaos,
and the ghost who designed the tournament. Entry point: wires up the client
and loads cogs. He only ever speaks in response to someone, and he never
talks to the other ghosts.
"""

import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("moonveil")

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
DEV_GUILD_ID = os.getenv("DEV_GUILD_ID")


def _parse_guild_ids(env_value: str | None):
    """Comma-separated list of server IDs this ghost is allowed to be in."""
    if not env_value:
        return None
    ids = set()
    for part in env_value.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids or None


ALLOWED_GUILD_IDS = _parse_guild_ids(os.getenv("ALLOWED_GUILD_IDS"))

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!moonveil-unused-", intents=intents, help_command=None)

INITIAL_COGS = (
    "cogs.personality",
    "cogs.haunting",
    "cogs.commands",
)


async def _leave_if_unauthorized(guild: discord.Guild) -> bool:
    if ALLOWED_GUILD_IDS and guild.id not in ALLOWED_GUILD_IDS:
        log.warning("Not authorized for guild %r (id=%s) - leaving immediately.", guild.name, guild.id)
        await guild.leave()
        return True
    return False


_synced = False


async def sync_commands():
    """Register slash commands straight to Velmora so they appear at once,
    rather than globally, where new commands can take a long while to show
    up in people's apps. Global copies are cleared so nothing appears twice.
    Runs once per start - on_ready fires again after every reconnect."""
    global _synced
    if _synced:
        return
    _synced = True

    targets = set(ALLOWED_GUILD_IDS or ())
    if DEV_GUILD_ID:
        targets.add(int(DEV_GUILD_ID))

    if not targets:
        synced = await bot.tree.sync()
        log.info("Synced %d global commands (no server set)", len(synced))
        return

    for guild_id in targets:
        guild = discord.Object(id=guild_id)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        log.info("Synced %d commands to server %s", len(synced), guild_id)

    bot.tree.clear_commands(guild=None)
    await bot.tree.sync()


@bot.event
async def on_guild_join(guild: discord.Guild):
    await _leave_if_unauthorized(guild)


@bot.event
async def on_ready():
    log.info("Maynard has arrived. Logged in as %s (id=%s)", bot.user, bot.user.id)

    for guild in list(bot.guilds):
        await _leave_if_unauthorized(guild)

    try:
        await sync_commands()
    except Exception:
        log.exception("Slash command sync failed")

    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching,
                                  name="the students, for research purposes")
    )


async def main():
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")

    async with bot:
        for cog in INITIAL_COGS:
            await bot.load_extension(cog)
            log.info("Loaded %s", cog)
        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
