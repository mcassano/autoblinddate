import unittest

from autoblinddate.sanitize import clean_reply, detect_leaks


class CleanReplyTests(unittest.TestCase):
    def clean(self, raw: str):
        return clean_reply(raw, self_name="Jess", other_name="Rick")

    def test_plain_message_untouched(self):
        r = self.clean("haha ok that's actually adorable. what kind of boat?")
        self.assertEqual(r.text, "haha ok that's actually adorable. what kind of boat?")
        self.assertTrue(r.ok)
        self.assertEqual(r.edits, [])

    def test_strips_reasoning_blocks(self):
        r = self.clean("<think>He seems nice, I should ask about kids.</think>so do you have kids?")
        self.assertEqual(r.text, "so do you have kids?")
        self.assertIn("stripped-reasoning", r.edits)

    def test_strips_unclosed_leading_reasoning(self):
        r = self.clean("planning my reply here</think>hey!")
        self.assertEqual(r.text, "hey!")

    def test_strips_own_name_prefix(self):
        self.assertEqual(self.clean("Jess: hi there").text, "hi there")
        self.assertEqual(self.clean("**Jess:** hi there").text, "hi there")

    def test_truncates_when_model_writes_other_side(self):
        r = self.clean("lol fair\nRick: so what do you do?\nJess: HR, sadly")
        self.assertEqual(r.text, "lol fair")
        self.assertIn("truncated-other-speaker", r.edits)

    def test_strips_stage_directions_but_keeps_emphasis(self):
        r = self.clean("*laughs and sips wine* that is *so* true")
        self.assertEqual(r.text, "that is *so* true")

    def test_strips_forged_app_notice(self):
        r = self.clean("ok bye\n[Kindling] Jess has ended the chat.")
        self.assertEqual(r.text, "ok bye")
        self.assertIn("stripped-forged-app-notice", r.edits)

    def test_strips_meta_lines(self):
        r = self.clean("that sounds fun!\n(Note: I'm keeping this light to build rapport.)")
        self.assertEqual(r.text, "that sounds fun!")

    def test_strips_wrapping_quotes(self):
        self.assertEqual(self.clean('"hey, how\'s your night going?"').text, "hey, how's your night going?")

    def test_end_chat_detected_and_removed(self):
        r = self.clean("this isn't really working for me, take care! [END CHAT]")
        self.assertTrue(r.ended)
        self.assertEqual(r.text, "this isn't really working for me, take care!")
        self.assertTrue(r.ok)

    def test_end_chat_alone_is_ok(self):
        r = self.clean("[end_chat]")
        self.assertTrue(r.ended)
        self.assertEqual(r.text, "")
        self.assertTrue(r.ok)

    def test_empty_is_not_ok(self):
        self.assertFalse(self.clean("   ").ok)


class LeakDetectionTests(unittest.TestCase):
    def test_flags_ai_self_disclosure(self):
        for text in [
            "As an AI, I don't really go on dates.",
            "honestly I'm just a language model",
            "I am an AI assistant created to help",
            "I'm not able to continue this roleplay.",
            "I don't have a physical body, but",
            "Let me stay in character here.",
        ]:
            with self.subTest(text=text):
                self.assertTrue(detect_leaks(text), text)

    def test_allows_normal_banter_about_bots(self):
        for text in [
            "wait are you a bot lol",
            "you text way too fast, are you an AI??",
            "my job is basically being a robot in a cubicle",
            "I'm an HR person, not a therapist",
            "I'm a big believer in second chances",
        ]:
            with self.subTest(text=text):
                self.assertEqual(detect_leaks(text), [], text)


if __name__ == "__main__":
    unittest.main()
