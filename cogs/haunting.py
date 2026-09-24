"""
Passive presence: Maynard noticing things without being asked.

- No unprompted chatter: he only ever speaks in response to a real message
  from someone in the channel.
- Only three trigger words: his name (always answered), and "what if" and
  "prank" (about 1 in 4 times). None overlap the other ghosts'.
- After anything he says unasked, he stays quiet in that channel for 10
  minutes. His name, @mentions and replies to him are always answered.
- Headmasters (HEADMASTERS role) are tagged so he knows who they are -
  they're his favourite targets for playful mischief.
- Whole-word matching, so "prank" doesn't fire inside other words.
- Remembering what members say, and condensing recent activity into running
  notes about what's going on in the server.
- Extra attention on anyone he's been asked to /watch.

Maynard does not talk to the other ghosts. He ignores every bot entirely,
so there's no way for him to get drawn into a ghost conversation.
"""

import asyncio
import logging
import os
import random
import re
import time

import discord
from discord.ext import commands

log = logging.getLogger("moonveil.haunting")


def _parse_channel_ids(env_value: str | None):
    if not env_value:
        return None
    ids = set()
    for part in env_value.split(","):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids or None


# How often he butts into an ordinary message, unasked, just to stir things up.
RANDOM_CHAOS_CHANCE = 0.005
# How often he comments on a message from someone he's /watch-ing.
WATCH_CHANCE = 0.15
# After any line nobody asked for, he stays quiet in that channel this long.
# (His name, @mentions and replies to him are always answered regardless.)
CHIME_COOLDOWN_SECONDS = int(os.getenv("CHIME_COOLDOWN_SECONDS", "600"))

# Members with this role are headmasters - his favourite targets.
HEADMASTER_ROLE_ID = int(os.getenv("HEADMASTER_ROLE_ID", "1542569502653550705") or 0)


def is_headmaster(member) -> bool:
    for role in getattr(member, "roles", None) or []:
        if role.id == HEADMASTER_ROLE_ID or (role.name or "").strip().lower() == "headmasters":
            return True
    return False


def speaker_label(member) -> str:
    name = str(member.display_name)
    return f"{name} (a headmaster)" if is_headmaster(member) else name

# keyword -> (chance of reacting, cue). Just his name and two words that are
# unmistakably him. (The tournament belongs to Sebastian now.)
KEYWORD_TRIGGERS = {
    "maynard": (1.0, "Someone said your name. Burst in with chaotic delight at being summoned - a dramatic entrance, a scheme, or a terrible pun."),
    "what if": (0.25, "Someone asked 'what if'. That is THE question - the one your entire life ran on. Pounce on it and push it three steps too far, into gloriously ridiculous territory."),
    "prank": (0.25, "Someone mentioned a prank. React as the school's undisputed prank legend - thrilled, egging them on, and pitching a bigger, sillier version - bonus delight if a headmaster is the target. Keep it harmless and kind."),
}

_KEYWORD_PATTERNS = {
    kw: re.compile(r"\b" + re.escape(kw) + r"\b", re.IGNORECASE) for kw in KEYWORD_TRIGGERS
}


def match_keyword(content: str, rng=random):
    """First keyword that appears as a whole word and wins its dice roll."""
    text = (content or "").replace("’", "'")
    for keyword, (chance, cue) in KEYWORD_TRIGGERS.items():
        if _KEYWORD_PATTERNS[keyword].search(text):
            if chance >= 1.0 or rng.random() < chance:
                return keyword, cue
            return keyword, None   # heard it, chose to stay quiet
    return None, None


class Haunting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.allowed_channel_ids = _parse_channel_ids(os.getenv("HAUNT_CHANNEL_IDS"))
        self._last_chime = {}  # channel_id -> when he last spoke unasked there

    def _chime_ready(self, channel_id: int) -> bool:
        return time.time() - self._last_chime.get(channel_id, 0) >= CHIME_COOLDOWN_SECONDS

    async def _write_notes_safely(self, personality):
        try:
            await personality.update_notes()
        except Exception:
            log.exception("Failed to update server notes")

    async def _resolve_reply_chain(self, message: discord.Message, limit: int = 3):
        """Walk up a Discord reply chain from `message`, nearest first."""
        chain = []
        current = message
        for _ in range(limit):
            ref = getattr(current, "reference", None)
            if not ref:
                break
            original = ref.resolved if isinstance(ref.resolved, discord.Message) else None
            if original is None and ref.message_id:
                try:
                    original = await current.channel.fetch_message(ref.message_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    break
            if original is None:
                break
            chain.append(original)
            current = original
        return chain

    async def _maybe_answer_direct_address(self, message: discord.Message, personality) -> bool:
        """A reply to something Maynard said, or an @mention, always gets a
        real answer, with the exchange passed as genuine conversation turns
        so he never doubts his own earlier words."""
        me = self.bot.user
        if me is None:
            return False

        chain = await self._resolve_reply_chain(message)
        replying_to_me = bool(chain) and chain[0].author.id == me.id
        mentioned = any(u.id == me.id for u in message.mentions)
        if not (replying_to_me or mentioned):
            return False

        author_name = speaker_label(message.author)
        asked = re.sub(r"<@!?&?\d+>", "", message.content or "").strip()
        if not asked:
            return False

        history = []
        for msg in reversed(chain):
            text = (msg.content or "").strip()
            if not text:
                continue
            if msg.author.id == me.id:
                history.append({"role": "assistant", "content": text})
            else:
                history.append({"role": "user", "content": f"{speaker_label(msg.author)}: {text}"})

        if replying_to_me:
            direction = (
                "Someone has just replied directly to something you said, and their reply is the last "
                "message above. Answer them, in character, carrying on naturally from your own last "
                "message. Everything above is a real exchange you were part of - never say you don't "
                "remember it, never question whether you said it, and never apologise or break character "
                "to explain yourself. Keep it to a couple of sentences."
            )
        else:
            direction = "Someone has just spoken to you directly, by name. Answer them in character, briefly."

        async with message.channel.typing():
            line = await personality.speak(
                f"{author_name}: {asked}", max_tokens=200, history=history, direction=direction,
            )
        try:
            await message.reply(line, mention_author=False)
        except discord.HTTPException:
            log.exception("Failed to answer direct address in %s", message.channel.id)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Maynard keeps to the students. Other ghosts, and every other bot,
        # simply don't register.
        if message.author.bot or not message.guild:
            return
        if self.allowed_channel_ids and message.channel.id not in self.allowed_channel_ids:
            return

        personality = self.bot.get_cog("Personality")
        if not personality:
            return
        personality.maybe_shift_mood()

        content = message.content or ""
        plain_name = str(message.author.display_name)   # what memory is keyed on
        author_name = speaker_label(message.author)      # what the prompt sees

        if len(content.strip()) >= 12:
            if personality.remember(plain_name, content, message.channel.id):
                asyncio.create_task(self._write_notes_safely(personality))

        if await self._maybe_answer_direct_address(message, personality):
            return

        keyword, matched_cue = match_keyword(content)
        haunted = personality.is_haunted(message.author.id)

        cue = None
        unasked = True
        if keyword == "maynard" and matched_cue:
            unasked = False   # called by name: always answers, cooldown or not
            cue = f'{matched_cue} {author_name} said: "{content}"'
        elif not self._chime_ready(message.channel.id):
            return   # he spoke up unasked here recently - let the channel breathe
        elif matched_cue:
            cue = f'{matched_cue} {author_name} said: "{content}"'
        elif keyword:
            return   # a keyword he chose to let pass - don't fall through to a random aside
        elif haunted and random.random() < WATCH_CHANCE:
            cue = (
                f"You've picked {author_name} as your current favourite target for harmless mischief. They just "
                f'said: "{content}". Pop in with something chaotic about it - a tease, a scheme, a wild idea. '
                "Playful and affectionate, never mean or creepy."
            )
        elif random.random() < RANDOM_CHAOS_CHANCE:
            cue = (
                f'Someone said: "{content}". Nobody asked you, which has never once stopped you. Butt in '
                "with a quick burst of harmless chaos - a wild suggestion, a dramatic overreaction, or a pun."
            )

        if not cue:
            return
        if unasked:
            self._last_chime[message.channel.id] = time.time()

        async with message.channel.typing():
            memory_hint = None
            if random.random() < 0.3:
                memory_hint = personality.random_memory(exclude_author=plain_name)
            line = await personality.speak(cue, memory_hint=memory_hint)
        try:
            await message.channel.send(line)
        except discord.HTTPException:
            log.exception("Failed to send reaction in %s", message.channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Haunting(bot))
