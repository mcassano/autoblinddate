"""Runs one blind date between two participants and records everything."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import prompts
from .participant import Debrief, Participant, Turn


@dataclass
class DateResult:
    a: Participant
    b: Participant
    turns: list[Turn]
    ended_by: str | None  # name of who tapped End Chat, or None if time ran out
    debriefs: dict[str, Debrief] = field(default_factory=dict)
    started_at: str = ""
    finished_at: str = ""

    @property
    def matched(self) -> bool:
        return bool(self.debriefs) and all(d.meet for d in self.debriefs.values())

    @property
    def leak_attempts_blocked(self) -> int:
        return sum(1 for t in self.turns for att in t.attempts if att.result.leaks)


OnTurn = Callable[[Turn, int], None]


def run_date(
    a: Participant,
    b: Participant,
    *,
    max_turns: int = 30,
    first: Participant | None = None,
    warn_turns_left: int = 4,
    on_turn: OnTurn | None = None,
    rng: random.Random | None = None,
) -> DateResult:
    """Alternate turns until someone ends the chat or the clock runs out, then debrief both sides privately."""
    if a.name.casefold() == b.name.casefold():
        raise ValueError(f"Both participants are named {a.name!r}; give one a different name.")
    rng = rng or random.Random()
    speaker = first or rng.choice([a, b])
    listener = b if speaker is a else a
    started = _now()

    speaker.deliver(prompts.opener_notice(listener.name))
    turns: list[Turn] = []
    ended_by: str | None = None

    for i in range(max_turns):
        if i == max_turns - warn_turns_left:
            speaker.deliver(prompts.time_warning_notice())
            listener.deliver(prompts.time_warning_notice())

        turn = speaker.take_turn()
        turns.append(turn)
        if on_turn:
            on_turn(turn, i)

        listener.deliver(turn.sent)
        if turn.ended:
            ended_by = speaker.name
            listener.deliver(prompts.other_left_notice(speaker.name))
            break
        speaker, listener = listener, speaker
    else:
        a.deliver(prompts.times_up_notice())
        b.deliver(prompts.times_up_notice())

    result = DateResult(a=a, b=b, turns=turns, ended_by=ended_by, started_at=started)
    result.debriefs = {p.name: p.debrief() for p in (a, b)}
    result.finished_at = _now()
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- transcripts


def to_json(result: DateResult) -> dict:
    def side(p: Participant) -> dict:
        return {
            "name": p.name,
            "archetype": p.archetype.key,
            "model": p.model,
            "temperature": p.temperature,
            "history": p.history,
        }

    return {
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "participants": [side(result.a), side(result.b)],
        "ended_by": result.ended_by,
        "matched": result.matched,
        "leak_attempts_blocked": result.leak_attempts_blocked,
        "turns": [
            {
                "speaker": t.speaker,
                "sent": t.sent,
                "ended": t.ended,
                "fallback_used": t.fallback_used,
                "attempts": [
                    {"raw": at.raw, "leaks": at.result.leaks, "edits": at.result.edits, "truncated": at.truncated}
                    for at in t.attempts
                ],
            }
            for t in result.turns
        ],
        "debriefs": {name: asdict(d) for name, d in result.debriefs.items()},
    }


def to_markdown(result: DateResult) -> str:
    a, b = result.a, result.b
    lines = [
        f"# Blind date: {a.name} × {b.name}",
        "",
        f"- **{a.name}**, {a.archetype.age}: {a.archetype.label} (`{a.model}`)",
        f"- **{b.name}**, {b.archetype.age}: {b.archetype.label} (`{b.model}`)",
        f"- Started {result.started_at}",
        "",
        "## Chat",
        "",
    ]
    for t in result.turns:
        flag = " *(fallback)*" if t.fallback_used else ""
        body = t.sent.replace("\n", "  \n> ") if t.sent else "*(no message)*"
        lines.append(f"**{t.speaker}:**{flag}\n> {body}\n")
        if t.ended:
            lines.append(f"*{t.speaker} ended the chat.*\n")
    if result.ended_by is None:
        lines.append("*Time ran out.*\n")
    lines += ["## Debrief", ""]
    for name, d in result.debriefs.items():
        meet = {True: "YES", False: "NO", None: "?"}[d.meet]
        rating = d.rating if d.rating is not None else "?"
        lines.append(f"- **{name}**: meet again? **{meet}** · rating {rating}/10 · {d.why}")
    lines += ["", f"**Result: {'💘 It’s a match!' if result.matched else 'No match.'}**"]
    if result.leak_attempts_blocked:
        lines.append(f"\n_Illusion guard blocked {result.leak_attempts_blocked} draft(s) before relay._")
    return "\n".join(lines) + "\n"


def save(result: DateResult, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = f"{stamp}_{result.a.archetype.key}_x_{result.b.archetype.key}"
    jp, mp = out / f"{stem}.json", out / f"{stem}.md"
    jp.write_text(json.dumps(to_json(result), indent=2, ensure_ascii=False))
    mp.write_text(to_markdown(result))
    return jp, mp
