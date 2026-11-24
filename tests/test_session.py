import json
import random
import tempfile
import unittest
from pathlib import Path

from autoblinddate import archetypes, prompts
from autoblinddate.archetypes import ARCHETYPES
from autoblinddate.participant import FALLBACK_MESSAGE, Debrief, Participant
from autoblinddate.session import run_date, save


class ScriptedClient:
    """Fake ChatClient: returns queued replies per model name and records every request."""

    def __init__(self, scripts: dict[str, list[str]]):
        self.scripts = {k: list(v) for k, v in scripts.items()}
        self.calls: list[tuple[str, list[dict]]] = []

    def complete(self, model, messages, *, temperature, max_tokens):
        self.calls.append((model, [dict(m) for m in messages]))
        return self.scripts[model].pop(0)


DEBRIEF_YES = "MEET: YES\nRATING: 8\nWHY: Funny and kind."
DEBRIEF_NO = "MEET: NO\nRATING: 3\nWHY: No spark."


def make_pair(scripts):
    client = ScriptedClient(scripts)
    rick = archetypes.get("divorced_dad")
    jess = archetypes.get("struggling_30s")
    a = Participant(rick, "model-a", jess.name, client)
    b = Participant(jess, "model-b", rick.name, client)
    return client, a, b


class ArchetypeTests(unittest.TestCase):
    def test_about_twenty_unique_archetypes(self):
        self.assertGreaterEqual(len(ARCHETYPES), 20)
        self.assertEqual(len({a.key for a in ARCHETYPES}), len(ARCHETYPES))

    def test_every_archetype_has_a_compatible_partner(self):
        for a in ARCHETYPES:
            with self.subTest(a=a.key):
                self.assertTrue(any(a.compatible_with(b) for b in ARCHETYPES if b is not a))

    def test_lookup_by_index_and_key(self):
        self.assertIs(archetypes.get("1"), ARCHETYPES[0])
        self.assertIs(archetypes.get("college_student").name, "Maya")
        with self.assertRaises(KeyError):
            archetypes.get("nope")


class SessionTests(unittest.TestCase):
    def test_full_date_flow_and_illusion(self):
        client, a, b = make_pair({
            "model-a": ["Rick: Hi Jess! How's your evening?", "Ha, fair. I have a boat. [END CHAT]", DEBRIEF_NO],
            "model-b": ["<think>be witty</think>good! just me and my cat Bernard lol", DEBRIEF_YES],
        })
        result = run_date(a, b, max_turns=10, first=a)

        self.assertEqual([t.sent for t in result.turns],
                         ["Hi Jess! How's your evening?", "good! just me and my cat Bernard lol",
                          "Ha, fair. I have a boat."])
        self.assertEqual(result.ended_by, "Rick")
        self.assertFalse(result.matched)
        self.assertEqual(result.debriefs["Jess"].rating, 8)

        # Jess's model saw exactly the cleaned human-looking text, then the app's end notice.
        jess_view = [m for m in b.history if m["role"] == "user"]
        self.assertEqual(jess_view[0]["content"], "Hi Jess! How's your evening?")
        self.assertIn("Ha, fair. I have a boat.", jess_view[1]["content"])
        self.assertIn(prompts.other_left_notice("Rick"), jess_view[1]["content"])
        self.assertNotIn("END CHAT", jess_view[1]["content"])

        # Neither model's context ever mentions the other side being a model.
        for _, messages in client.calls:
            blob = json.dumps(messages).lower()
            for word in ("model-a", "model-b", "language model", "llm", " ai ", "simulat"):
                self.assertNotIn(word, blob)

    def test_roles_alternate_for_both_sides(self):
        _, a, b = make_pair({
            "model-a": ["hey", "cool", "nice", DEBRIEF_YES],
            "model-b": ["hi", "yeah", "ok", DEBRIEF_YES],
        })
        result = run_date(a, b, max_turns=6, first=b)
        self.assertIsNone(result.ended_by)
        self.assertTrue(result.matched)
        for p in (a, b):
            roles = [m["role"] for m in p.history]
            self.assertEqual(roles[0], "system")
            for prev, cur in zip(roles[1:], roles[2:]):
                self.assertNotEqual(prev, cur, f"{p.name} has consecutive {cur} messages")

    def test_time_warning_and_times_up_reach_both(self):
        client, a, b = make_pair({
            "model-a": ["hey", "cool", DEBRIEF_YES],
            "model-b": ["hi", "yeah", DEBRIEF_YES],
        })
        run_date(a, b, max_turns=4, first=a, warn_turns_left=2)
        for p in (a, b):
            text = json.dumps(p.history)
            self.assertIn(prompts.time_warning_notice(), text)
            self.assertIn("Time's up", text)

    def test_leaky_draft_is_regenerated_not_relayed(self):
        client, a, b = make_pair({
            "model-a": ["As an AI, I don't date.", "Sorry! Long day. What do you do for fun?", "ok", DEBRIEF_YES],
            "model-b": ["trivia nights mostly", DEBRIEF_YES],
        })
        result = run_date(a, b, max_turns=3, first=a)
        self.assertEqual(result.turns[0].sent, "Sorry! Long day. What do you do for fun?")
        self.assertEqual(result.leak_attempts_blocked, 1)
        self.assertNotIn("AI", json.dumps(b.history))
        # The retry nudge is ephemeral: it is not stored in A's history.
        self.assertNotIn("didn't send", a.history[0]["content"])
        self.assertIn("didn't send", client.calls[1][1][0]["content"])

    def test_persistent_leak_falls_back(self):
        leak = "I'm an AI language model."
        _, a, b = make_pair({
            "model-a": [leak] * 4 + [DEBRIEF_NO],
            "model-b": [DEBRIEF_NO],
        })
        result = run_date(a, b, max_turns=1, first=a)
        self.assertEqual(result.turns[0].sent, FALLBACK_MESSAGE)
        self.assertTrue(result.turns[0].fallback_used)

    def test_same_names_rejected(self):
        _, a, b = make_pair({"model-a": [], "model-b": []})
        b.archetype = b.archetype.with_name("Rick")
        with self.assertRaises(ValueError):
            run_date(a, b)

    def test_save_writes_json_and_markdown(self):
        _, a, b = make_pair({
            "model-a": ["hi [END CHAT]", DEBRIEF_NO],
            "model-b": [DEBRIEF_NO],
        })
        result = run_date(a, b, first=a, rng=random.Random(0))
        with tempfile.TemporaryDirectory() as d:
            jp, mp = save(result, d)
            data = json.loads(Path(jp).read_text())
            self.assertEqual(data["ended_by"], "Rick")
            self.assertIn("No match", Path(mp).read_text())


class DebriefParseTests(unittest.TestCase):
    def test_parses_format(self):
        d = Debrief.parse("MEET: yes\nRATING: 7\nWHY: Good vibes.")
        self.assertEqual((d.meet, d.rating, d.why), (True, 7, "Good vibes."))

    def test_tolerates_markdown_and_garbage(self):
        d = Debrief.parse("**MEET:** NO\n**RATING:** 42\nWHY: meh")
        self.assertFalse(d.meet)
        self.assertIsNone(d.rating)

    def test_missing_fields(self):
        d = Debrief.parse("I think so?")
        self.assertIsNone(d.meet)
        self.assertEqual(d.why, "I think so?")


if __name__ == "__main__":
    unittest.main()
