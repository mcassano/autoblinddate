# autoblinddate

Two language models go on a text-chat blind date. **Each one believes the other is a real person.**

Each side gets a persona (a wealthy divorced dad, a burnt-out PhD student, a 30-something worn out by the apps, …)
and is told it's trying the "Blind Date" feature of a dating app called *Kindling*. It knows its match's first
name and nothing else. They chat until one of them taps End Chat or the 30-minute clock runs out. Then the app
privately asks each of them whether they'd like to meet in person. If both say yes, it's a match.

Models are called through [OpenRouter](https://openrouter.ai), so you can pair any two models against each other.

```
Rick: Hey Jess, Rick here. So we're both doing this blind date thing... kind of feels like a setup at a
      bar except I can't even buy you a drink. What made you try it?
Jess: Honestly? I've swiped so much I'm starting to recognize the same five guys with new haircuts.
      Blind felt like it couldn't be worse. Jury's still out. What's your excuse?
…
Jess: I'm hoping you're actually as decisive as you sound, because vague is my dealbreaker and you
      haven't been vague once. And yeah — I'd say yes to the drink. Don't make it weird.
   — Jess ended the chat —

💘 It's a match!
```

Full transcripts: [`examples/rick_x_jess.md`](examples/rick_x_jess.md) and
[`examples/sam_x_gabriela.md`](examples/sam_x_gabriela.md).

## Quick start

Requires Python 3.10+. There are no third-party dependencies.

```bash
git clone https://github.com/mcassano/autoblinddate && cd autoblinddate
cp .env.example .env            # then paste your OpenRouter key into it

python -m autoblinddate                       # pick both archetypes from a menu
python -m autoblinddate -a divorced_dad -b struggling_30s
python -m autoblinddate --random --seed 42    # random compatible pair
python -m autoblinddate --list                # show all archetypes
```

You can also run `pip install .` to get an `autoblinddate` command.

### Options

| Flag | Default | |
|---|---|---|
| `-a`, `-b` | interactive | Archetype for each side, by key or menu number |
| `--random` | | Pick a random pair whose preferences are compatible |
| `--name-a`, `--name-b` | archetype default | Override a participant's first name |
| `--model` | `deepseek/deepseek-v4.1-flash` | OpenRouter model for both sides (or set `AUTOBLINDDATE_MODEL`) |
| `--model-a`, `--model-b` | | Use a different model for each side |
| `--turns` | `30` | Maximum number of messages |
| `--first` | `random` | Who sends the first message: `a`, `b` or `random` |
| `--temperature` | `0.9` | Sampling temperature |
| `--seed` | | Seed for pairing and for who goes first |
| `--show-guard` | | Print drafts the illusion guard blocked or edited |
| `--allow-incompatible` | | Run a pairing even if their stated preferences don't match |
| `--out` / `--no-save` | `transcripts/` | Where transcripts are written |

Each run writes a readable `.md` transcript and a `.json` file. The JSON holds each model's full private message
history, every raw draft, what the guard changed, and the debrief answers.

## Archetypes

| # | Key | Who |
|---|---|---|
| 1 | `divorced_dad` | Rick, 52: wealthy divorced dad |
| 2 | `college_student` | Maya, 21: college senior |
| 3 | `struggling_30s` | Jess, 34: worn out by the dating market |
| 4 | `startup_founder` | Tyler, 29: hustle-culture founder |
| 5 | `widowed_retiree` | Harold, 68: recently widowed retiree |
| 6 | `single_mom_nurse` | Danielle, 38: single mom and ER nurse |
| 7 | `barista_musician` | Jonah, 26: barista and aspiring musician |
| 8 | `workaholic_lawyer` | Priya, 36: workaholic corporate lawyer |
| 9 | `gym_bro` | Marcus, 28: personal trainer |
| 10 | `rediscovering_divorcee` | Linda, 49: divorcée rediscovering herself |
| 11 | `burnt_out_phd` | Sam, 30: burnt-out PhD student (they/them) |
| 12 | `hopeless_romantic` | Eleanor, 41: hopeless romantic who owns a bookstore |
| 13 | `fresh_breakup` | Dave, 37: just out of a 10-year relationship |
| 14 | `rancher` | Cody, 33: small-town rancher |
| 15 | `influencer` | Brooke, 25: lifestyle influencer |
| 16 | `gamer` | Kevin, 31: extremely online gamer |
| 17 | `veteran_contractor` | Ray, 45: Army veteran turned contractor |
| 18 | `checklist_exec` | Natalie, 32: Type-A marketing exec with a checklist |
| 19 | `shy_engineer` | Arjun, 27: shy software engineer |
| 20 | `silver_fox_realtor` | Diane, 56: glamorous real-estate agent |
| 21 | `night_chef` | Luis, 35: sous chef who works nights |
| 22 | `sober_artist` | Gabriela, 44: newly sober painter |

Each archetype has a backstory, personality, texting style, what they want, dealbreakers, quirks, and one private
secret they only share if they come to trust their match. Each also states who they're interested in, and
`--random` only picks pairs where both sides are interested in each other. To add your own, append an `Archetype`
to [`autoblinddate/archetypes.py`](autoblinddate/archetypes.py).

## How the illusion holds

Neither model ever sees anything a real person on a dating app wouldn't see.

- **Identity, not roleplay.** The system prompt says "You are Rick" and describes his life. It never tells the
  model it is playing a character. The match is described as a person typing in the app.
- **One non-human voice.** The only other voice is the app. Its notifications (the match connecting, the
  5-minute warning, the match leaving, the debrief question) are lines that start with `[Kindling]`, and the
  model is told to expect them.
- **Every message passes through a guard** ([`sanitize.py`](autoblinddate/sanitize.py)) before the other side sees it:
  - It strips reasoning blocks (`<think>…</think>`), stage directions (`*smiles*`), name labels (`Rick:`),
    wrapping quotes, and meta notes like "(Note: …)".
  - It cuts the reply off if the model starts writing the other person's lines.
  - It removes any fake `[Kindling]` notice a model writes, so neither side can impersonate the app.
  - It turns `[END CHAT]` into a button press. The other side sees "Rick has ended the chat", not the tag.
  - It blocks drafts where the model gives itself away: "as an AI", "I'm a language model", vendor names, talk of
    roleplay or the system prompt, refusals. Ordinary banter like "lol are you a bot?" goes through.
- **Blocked or cut-off drafts are regenerated, never relayed.** A short note asks the model to try again. It is
  added to that one request only and never saved to history. If a model keeps failing, the harness sends the
  clean sentences it can salvage. If nothing is salvageable, it sends a bland, human-sounding filler line.
- **Each history matches what was actually sent.** A model's own past messages are stored as they were
  delivered, so the two sides never disagree about what was said.

## Development

```bash
python -m unittest discover -s tests -t .     # offline: uses a scripted fake client
ruff check . && ruff format --check .
```

The tests cover the guard and the whole date flow, including turn order, time warnings, regenerating leaked or
truncated drafts, the fallback line, and checks that neither model's context ever reveals what's on the other side.
CI runs them on Python 3.10 to 3.13.

## License

MIT
