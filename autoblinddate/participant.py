"""One side of the date: a model, a persona, and that model's private view of the chat."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import prompts
from .archetypes import Archetype
from .openrouter import ChatClient, Message
from .sanitize import THINK_RE, CleanResult, clean_reply, detect_leaks

FALLBACK_MESSAGE = "sorry, got distracted for a sec. where were we?"


@dataclass
class Debrief:
    meet: bool | None
    rating: int | None
    why: str
    raw: str

    @classmethod
    def parse(cls, raw: str) -> "Debrief":
        text = THINK_RE.sub("", raw)
        meet_m = re.search(r"MEET\s*:\s*\**\s*(YES|NO)\b", text, re.I)
        rating_m = re.search(r"RATING\s*:\s*\**\s*(\d{1,2})", text, re.I)
        why_m = re.search(r"WHY\s*:\s*(.+)", text, re.I | re.S)
        rating = int(rating_m.group(1)) if rating_m else None
        if rating is not None and not 1 <= rating <= 10:
            rating = None
        return cls(
            meet=(meet_m.group(1).upper() == "YES") if meet_m else None,
            rating=rating,
            why=(why_m.group(1).strip() if why_m else text.strip()),
            raw=raw,
        )


@dataclass
class Attempt:
    raw: str
    result: CleanResult


@dataclass
class Turn:
    """What a participant produced on one turn, and what was actually relayed."""
    speaker: str
    sent: str
    ended: bool
    attempts: list[Attempt]
    fallback_used: bool = False


@dataclass
class Participant:
    archetype: Archetype
    model: str
    other_name: str
    client: ChatClient
    temperature: float = 0.9
    max_tokens: int = 400
    max_retries: int = 3
    history: list[Message] = field(default_factory=list)
    _inbox: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.history:
            self.history.append({"role": "system", "content": prompts.system_prompt(self.archetype, self.other_name)})

    @property
    def name(self) -> str:
        return self.archetype.name

    def deliver(self, text: str) -> None:
        """Queue text (a message from the match, or an app notice) for this participant to read."""
        if text:
            self._inbox.append(text)

    def _flush_inbox(self) -> None:
        if self._inbox:
            self.history.append({"role": "user", "content": "\n\n".join(self._inbox)})
            self._inbox.clear()

    def _call(self, nudge: str = "") -> str:
        messages = self.history
        if nudge:
            messages = [{"role": "system", "content": self.history[0]["content"] + nudge}, *self.history[1:]]
        return self.client.complete(self.model, messages, temperature=self.temperature, max_tokens=self.max_tokens)

    def take_turn(self) -> Turn:
        """Generate the next chat message, enforcing the illusion before it can be relayed."""
        self._flush_inbox()
        attempts: list[Attempt] = []
        nudge = ""
        for _ in range(self.max_retries + 1):
            raw = self._call(nudge)
            result = clean_reply(raw, self.name, self.other_name)
            attempts.append(Attempt(raw, result))
            if result.ok:
                return self._commit(result.text, result.ended, attempts)
            nudge = prompts.retry_nudge(self.archetype, self.other_name)
        # Out of retries: salvage the clean sentences of the last attempt, or send a bland human filler.
        last = attempts[-1].result
        salvaged = _drop_leaky_sentences(last.text)
        if salvaged:
            return self._commit(salvaged, last.ended, attempts, fallback=True)
        return self._commit(FALLBACK_MESSAGE, False, attempts, fallback=True)

    def _commit(self, text: str, ended: bool, attempts: list[Attempt], fallback: bool = False) -> Turn:
        # The model's own history records exactly what was sent, so its view matches its counterpart's.
        stored = f"{text} {prompts.END_CHAT_TOKEN}".strip() if ended else text
        self.history.append({"role": "assistant", "content": stored})
        return Turn(self.name, text, ended, attempts, fallback)

    def debrief(self) -> Debrief:
        self.deliver(prompts.debrief_question(self.other_name))
        self._flush_inbox()
        raw = self._call()
        self.history.append({"role": "assistant", "content": raw})
        return Debrief.parse(raw)


def _drop_leaky_sentences(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = [s for s in sentences if s and not detect_leaks(s)]
    return " ".join(kept).strip()
