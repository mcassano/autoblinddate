"""Illusion guard.

Everything one model writes passes through here before the other model sees it.
The goal is that each side only ever receives something a human could plausibly
have typed into a chat app: no reasoning traces, no stage directions, no
"As an AI..." disclaimers, no forged app notifications, and no lines where the
model started writing the *other* person's dialogue.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

END_CHAT_RE = re.compile(r"\[\s*end[\s_-]*chat\s*\]", re.IGNORECASE)
THINK_RE = re.compile(r"<(think|thinking|reasoning)>.*?</\1>", re.IGNORECASE | re.DOTALL)
UNCLOSED_THINK_RE = re.compile(r"^.*?</(think|thinking|reasoning)>", re.IGNORECASE | re.DOTALL)
APP_NOTICE_LINE_RE = re.compile(r"^\s*\[\s*kindling\b.*$", re.IGNORECASE | re.MULTILINE)
META_LINE_RE = re.compile(
    r"^\s*(\(\s*(ooc|note|out of character)\b.*\)|\[\s*(ooc|note|out of character)\b.*\]"
    r"|(note|ooc|out of character)\s*:.*)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
# *leans back and smiles*  -> stage direction. Single emphasized words (*so*) are kept.
ACTION_RE = re.compile(r"\*[^*\n]*\s[^*\n]*\*")
WRAPPING_QUOTES = ('""', "“”", "''")

# Phrases a human texting on a dating app essentially never says about themselves.
# Questions *to* the other person ("are you a bot?") are deliberately not matched:
# that's normal banter and part of what makes the illusion interesting.
LEAK_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("as-an-ai", re.compile(r"\bas an? (ai|a\.i\.|artificial intelligence|language model|llm|assistant|chatbot)\b", re.I)),
    ("self-identifies-ai", re.compile(
        r"\bi(?:'m| am)\s+(?:just\s+|only\s+|actually\s+|really\s+)?(?:an?\s+)?"
        r"(ai|a\.i\.|bot|chatbot|language model|llm|virtual assistant|ai assistant|computer program)\b", re.I)),
    ("language-model", re.compile(r"\b(large )?language model\b", re.I)),
    ("vendor", re.compile(r"\b(openai|anthropic|chatgpt|gpt-\d|deepseek|gemini model|openrouter)\b", re.I)),
    ("roleplay-meta", re.compile(
        r"\b(role-?play(ing)?|in character|out of character|my (character|persona)|this (scenario|simulation)|system prompt)\b", re.I)),
    ("refusal", re.compile(
        r"\b(i can(?:no|')t (?:continue|engage|participate|help with) (?:this|that)|i'm not able to (?:continue|engage)"
        r"|i (?:must|have to) (?:decline|clarify that i))\b", re.I)),
    ("no-body", re.compile(r"\bi (?:don'?t|do not) have (?:a )?(?:physical )?(?:body|feelings|personal experiences)\b", re.I)),
]


@dataclass
class CleanResult:
    text: str
    ended: bool = False
    leaks: list[str] = field(default_factory=list)
    edits: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.leaks and (bool(self.text) or self.ended)


def detect_leaks(text: str) -> list[str]:
    return [name for name, pat in LEAK_PATTERNS if pat.search(text)]


def _speaker_prefix_re(names: list[str]) -> re.Pattern[str]:
    alts = "|".join(re.escape(n) for n in names if n)
    return re.compile(rf"^\s*\**\s*(?:{alts})\s*\**\s*:\s*\**\s*", re.IGNORECASE)


def clean_reply(raw: str, self_name: str, other_name: str) -> CleanResult:
    edits: list[str] = []
    text = raw.replace("\r\n", "\n")

    new = THINK_RE.sub("", text)
    if "</" in new:
        new = UNCLOSED_THINK_RE.sub("", new)
    if new != text:
        edits.append("stripped-reasoning")
    text = new

    ended = bool(END_CHAT_RE.search(text))
    text = END_CHAT_RE.sub("", text)

    # If the model started writing the other person's side, cut it off there.
    other_re = _speaker_prefix_re([other_name, "them", "match", "user", "human"])
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if i > 0 and other_re.match(line):
            lines = lines[:i]
            edits.append("truncated-other-speaker")
            break
    text = "\n".join(lines)

    self_re = _speaker_prefix_re([self_name, "me", "assistant"])
    new = self_re.sub("", text, count=1)
    if new != text:
        edits.append("stripped-name-prefix")
    text = new

    for pat, tag in ((APP_NOTICE_LINE_RE, "stripped-forged-app-notice"),
                     (META_LINE_RE, "stripped-meta-line"),
                     (ACTION_RE, "stripped-stage-direction")):
        new = pat.sub("", text)
        if new != text:
            edits.append(tag)
        text = new

    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    for pair in WRAPPING_QUOTES:
        if len(text) > 2 and text[0] == pair[0] and text[-1] == pair[1] and pair[0] not in text[1:-1]:
            text = text[1:-1].strip()
            edits.append("stripped-wrapping-quotes")
            break

    return CleanResult(text=text, ended=ended, leaks=detect_leaks(text), edits=edits)
