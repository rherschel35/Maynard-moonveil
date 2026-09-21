"""
Passive presence: Maynard noticing things without being asked.

- No unprompted chatter: he only ever speaks in response to a real message
  from someone in the channel.
- Keyword reactions tuned to Maynard - research, hypotheses, "what if",
  pranks, chaos, puns. Chosen so they don't overlap the other ghosts' words:
  Cassy already answers to "experiment", and two ghosts replying to the same
  message would be exactly the pile-up the channel doesn't need.
- Whole-word matching, so "pun" doesn't fire on "punch" or "math" on
  "aftermath".
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


# keyword -> (chance of reacting, cue). Most always fire; the tournament
# only sometimes, because it's the one subject that hurts, and the server
# talks about it constantly.
KEYWORD_TRIGGERS = {
    "maynard": (1.0, "Someone said your name. React with delight at being noticed - a pun wouldn't go amiss."),
    "moonveil": (1.0, "Someone mentioned House Moonveil, your house. React with fond, slightly smug pride."),
    "research": (1.0, "Someone mentioned research. That's practically your religion - react with scholarly glee and ask what they're investigating."),
    "hypothesis": (1.0, "Someone mentioned a hypothesis. React like a scientist handed a gift - ask how they plan to test it."),
    "theory": (1.0, "Someone mentioned a theory. Take it seriously and a little mischievously - how would one test it?"),
    "what if": (1.0, "Someone asked 'what if'. That is THE question - the one your entire life ran on. Pounce on it with delight and push it one step further."),
    "prank": (1.0, "Someone mentioned a prank. React as the school's foremost authority on the subject - appreciative, critiquing their methodology. Keep it harmless."),
    "chaos": (1.0, "Someone mentioned chaos. Controlled chaos is your field of expertise - react like a proud specialist."),
    "pun": (1.0, "Someone mentioned puns. Respond with one, naturally - ideally one only you find funny."),
    "math": (1.0, "Someone mentioned maths. React with a joke so arithmetic that you're the only one who'll laugh at it."),
    "science": (1.0, "Someone mentioned science. React with genuine enthusiasm - science is just curiosity with better notes."),
    "tournament": (0.25, "Someone mentioned the tournament. This is the one subject that stops you cold. React briefly and quietly - a line, no joke, no deflection into cleverness - then let it go. Do not explain the whole story unless asked."),
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

        author_name = str(message.author.display_name)
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
                history.append({"role": "user", "content": f"{msg.author.display_name}: {text}"})

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
        author_name = str(message.author.display_name)

        if len(content.strip()) >= 12:
            if personality.remember(author_name, content, message.channel.id):
                asyncio.create_task(self._write_notes_safely(personality))

        if await self._maybe_answer_direct_address(message, personality):
            return

        keyword, matched_cue = match_keyword(content)
        haunted = personality.is_haunted(message.author.id)

        cue = None
        if matched_cue:
            cue = f'{matched_cue} They said: "{content}"'
        elif keyword:
            return   # a keyword he chose to let pass - don't fall through to a random aside
        elif haunted and random.random() < 0.35:
            cue = (
                f"You're currently observing {author_name} - a subject in one of your studies. They just "
                f'said: "{content}". Remark on it like a delighted researcher noting a data point. '
                "Warm, never creepy."
            )
        elif random.random() < 0.03:
            cue = f'Someone said: "{content}". React to it in passing, briefly, as an aside.'

        if not cue:
            return

        async with message.channel.typing():
            memory_hint = None
            if random.random() < 0.3:
                memory_hint = personality.random_memory(exclude_author=author_name)
            line = await personality.speak(cue, memory_hint=memory_hint)
        try:
            await message.channel.send(line)
        except discord.HTTPException:
            log.exception("Failed to send reaction in %s", message.channel.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(Haunting(bot))
