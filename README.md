# Maynard Moonveil

A Discord bot that plays Maynard Moonveil, founder of House Moonveil and the
castle's most gleeful agent of chaos. It speaks in character via the Claude API
(dynamic, not canned lines) when someone has spoken — name cues, replies and
mentions, keyword reactions (`what if`, `prank`), and the occasional chaos
aside — remembers things members say and brings them up later, and answers
direct questions through `/ask`. `/watch` picks someone as his next target for
harmless mischief, `/experiment` opens an entry from his old journals, and
`/mood` is for admins.

The name is configurable via `GHOST_NAME` in `.env` if you ever want to
rename it — it's woven into the system prompt, the bot's Discord presence,
and `/mood`.

This is meant to run as a **separate bot/service** from the other Velmora
ghosts — its own Discord application, its own Railway service — so the
personalities don't collide in the same process. He only ever speaks in
response to someone, and he never talks to the other ghosts.

## Setup

1. Create a Discord application + bot at https://discord.com/developers/applications
   - Enable the **Message Content Intent** and **Server Members Intent** under Bot settings.
   - Invite it to your server with the `bot` and `applications.commands` scopes,
     and at least: View Channels, Send Messages, Read Message History, Embed Links.
2. `cp .env.example .env` and fill in `DISCORD_TOKEN` and `ANTHROPIC_API_KEY`.
3. `pip install -r requirements.txt`
4. `python bot.py`

Slash commands sync automatically on startup (guild-instant if you set
`DEV_GUILD_ID` / `ALLOWED_GUILD_IDS` in `.env`, otherwise global sync which
can take up to an hour the first time).

## Commands

- `/ask question:<text>` — ask Maynard something; he answers with gleeful chaos.
- `/watch member:<@member>` — he picks someone as his next target for harmless mischief.
- `/experiment` — an entry from his old journals of (alleged) experiments.
- `/mood` — (admin) peek at his current mood, for debugging.

## Structure

```
bot.py                 # entrypoint and client setup
cogs/
  personality.py       # Claude API wrapper + ghost voice/mood/memory
  haunting.py           # passive behaviors: name cues, keywords, watch asides, memory
  commands.py           # /ask, /watch, /experiment, /mood
  diary.py              # long-term diary memory mixed into personality
data/
  memory_store.json     # persisted member quotes + mood + watch targets (runtime-created)
  lore.json              # journal fragments, revealed in order
  velmora_lore.json      # shared Velmora ghost lore
  shared_history.json    # shared stories with Cassy and others
```

## Notes

- All dialogue is generated at request time by Claude (Haiku by default,
  configurable via `MOONVEIL_MODEL`) using a system prompt that defines its
  voice, current mood, and any relevant remembered snippets — nothing is
  hardcoded canned text, though there are graceful fallback lines if the API
  call fails.
- State (mood, memories, watch targets, lore progress) is persisted to a
  small JSON file under `STATE_DIR` (defaults to `data/`) so it survives restarts.
- Academy rumors (`/rumor` and the scheduled posts) live in Housecup.
