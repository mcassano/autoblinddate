"""Command-line interface: `python -m autoblinddate`."""
from __future__ import annotations

import argparse
import os
import random
import sys
import textwrap

from . import archetypes
from .archetypes import ARCHETYPES, Archetype
from .openrouter import DEFAULT_MODEL, OpenRouterClient, OpenRouterError, load_dotenv
from .participant import Participant, Turn
from .session import run_date, save

COLORS = ("\033[36m", "\033[35m")  # cyan, magenta
DIM, BOLD, RESET = "\033[2m", "\033[1m", "\033[0m"


def _c(code: str, s: str) -> str:
    return f"{code}{s}{RESET}" if sys.stdout.isatty() and not os.environ.get("NO_COLOR") else s


def print_archetypes() -> None:
    for i, a in enumerate(ARCHETYPES, 1):
        seeks = "/".join(a.seeking)
        who = f"{a.name}, {a.age}"
        print(f"{i:>2}. {a.key:<24} {who:<14} {a.gender:<9} seeks {seeks:<22} {a.label}")


def pick_interactively(prompt: str) -> Archetype:
    print_archetypes()
    while True:
        choice = input(f"\n{prompt} (number or key): ").strip()
        try:
            return archetypes.get(choice)
        except KeyError:
            print("Not a valid choice, try again.")


def random_pair(rng: random.Random) -> tuple[Archetype, Archetype]:
    pairs = [(x, y) for x in ARCHETYPES for y in ARCHETYPES if x is not y and x.compatible_with(y)]
    return rng.choice(pairs)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="autoblinddate",
        description="Simulate a text-chat blind date between two LLMs, each of which believes the other is human.",
    )
    p.add_argument("--list", action="store_true", help="list archetypes and exit")
    p.add_argument("-a", "--a", dest="a", help="archetype for participant A (key or number)")
    p.add_argument("-b", "--b", dest="b", help="archetype for participant B (key or number)")
    p.add_argument("--random", action="store_true", help="pick a random mutually-compatible pair")
    p.add_argument("--name-a", help="override participant A's first name")
    p.add_argument("--name-b", help="override participant B's first name")
    p.add_argument("--model", default=os.environ.get("AUTOBLINDDATE_MODEL", DEFAULT_MODEL),
                   help=f"OpenRouter model for both sides (default: {DEFAULT_MODEL})")
    p.add_argument("--model-a", help="OpenRouter model for A (overrides --model)")
    p.add_argument("--model-b", help="OpenRouter model for B (overrides --model)")
    p.add_argument("--temperature", type=float, default=0.9)
    p.add_argument("--turns", type=int, default=30, help="max messages in the chat (default: 30)")
    p.add_argument("--first", choices=["a", "b", "random"], default="random", help="who sends the first message")
    p.add_argument("--seed", type=int, help="random seed for pairing / who goes first")
    p.add_argument("--out", default="transcripts", help="directory for transcripts (default: transcripts)")
    p.add_argument("--no-save", action="store_true", help="don't write transcripts")
    p.add_argument("--allow-incompatible", action="store_true",
                   help="run even if the archetypes' stated preferences don't match")
    p.add_argument("--show-guard", action="store_true", help="print drafts the illusion guard blocked or edited")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.list:
        print_archetypes()
        return 0
    if args.turns < 2:
        print("--turns must be at least 2", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    try:
        if args.random:
            arch_a, arch_b = random_pair(rng)
        else:
            arch_a = archetypes.get(args.a) if args.a else pick_interactively("Participant A")
            arch_b = archetypes.get(args.b) if args.b else pick_interactively("Participant B")
    except KeyError as e:
        print(f"{e.args[0]}. Use --list to see options.", file=sys.stderr)
        return 2
    except EOFError:
        print("\nNo archetype chosen.", file=sys.stderr)
        return 2

    arch_a, arch_b = arch_a.with_name(args.name_a), arch_b.with_name(args.name_b)
    if not arch_a.compatible_with(arch_b) and not args.allow_incompatible:
        print(f"{arch_a.name} ({arch_a.gender}, seeks {'/'.join(arch_a.seeking)}) and {arch_b.name} "
              f"({arch_b.gender}, seeks {'/'.join(arch_b.seeking)}) aren't each other's type. "
              "Pass --allow-incompatible to run anyway.", file=sys.stderr)
        return 2
    if arch_a.name.casefold() == arch_b.name.casefold():
        print(f"Both participants are named {arch_a.name}; use --name-b to rename one.", file=sys.stderr)
        return 2

    load_dotenv()
    try:
        client = OpenRouterClient.from_env()
    except OpenRouterError as e:
        print(e, file=sys.stderr)
        return 2

    a = Participant(arch_a, args.model_a or args.model, arch_b.name, client, temperature=args.temperature)
    b = Participant(arch_b, args.model_b or args.model, arch_a.name, client, temperature=args.temperature)
    color = {a.name: COLORS[0], b.name: COLORS[1]}
    first = {"a": a, "b": b}.get(args.first)

    print(_c(BOLD, f"\n{a.name}, {arch_a.age} ({arch_a.label}) [{a.model}]"))
    print(_c(BOLD, f"   × {b.name}, {arch_b.age} ({arch_b.label}) [{b.model}]\n"))

    def on_turn(turn: Turn, _i: int) -> None:
        if args.show_guard:
            for att in turn.attempts:
                if att.result.leaks or att.result.edits:
                    tag = "BLOCKED" if att.result.leaks else "edited"
                    detail = ", ".join(att.result.leaks + att.result.edits)
                    raw = textwrap.shorten(att.raw.replace("\n", " "), 200)
                    print(_c(DIM, f"   [guard {tag}: {detail}] {raw}"))
        name = _c(color[turn.speaker] + BOLD, f"{turn.speaker}:")
        body = turn.sent or _c(DIM, "(no message)")
        print(f"{name} {body}")
        if turn.ended:
            print(_c(DIM, f"   — {turn.speaker} ended the chat —"))

    try:
        result = run_date(a, b, max_turns=args.turns, first=first, on_turn=on_turn, rng=rng)
    except OpenRouterError as e:
        print(f"\nOpenRouter request failed: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130

    if result.ended_by is None:
        print(_c(DIM, "   — time's up —"))
    print(_c(BOLD, "\nDebrief"))
    for name, d in result.debriefs.items():
        meet = {True: "YES", False: "NO", None: "?"}[d.meet]
        print(f"  {_c(color[name] + BOLD, name)}: meet again? {meet}  rating {d.rating or '?'}/10")
        print(textwrap.indent(textwrap.fill(d.why, 90), "    "))
    print(_c(BOLD, "\n💘 It's a match!" if result.matched else "\nNo match."))
    if result.leak_attempts_blocked:
        print(_c(DIM, f"(illusion guard blocked {result.leak_attempts_blocked} draft(s))"))

    if not args.no_save:
        jp, mp = save(result, args.out)
        print(_c(DIM, f"\nSaved {mp} and {jp}"))
    return 0
