"""The after-session debrief written by Muse Wonder: built only from counted facts, and a text that contains any number the session did
not count is refused (the plain counted line is shown instead). Fake model: no network."""
from __future__ import annotations

import json

from playfellow_coop.debrief import MODEL, Debrief, facts_from, numbers_ok, plain_line

LOG = [
    {"request": "grab the coins on the left", "done": True, "ended": "done", "turns": 4, "actions": 9, "ai_calls": 4, "seconds": 12.4, "done_by": "model_said"},
    {"request": "get me past this jump", "done": False, "ended": "turn_limit", "turns": 12, "actions": 20, "ai_calls": 12, "seconds": 31.0, "done_by": ""},
]


class FakeWonder:
    def __init__(self, text):
        self.text, self.seen, self.model = text, [], MODEL
        self.last_usage = {"prompt_tokens": 1000, "completion_tokens": 100}

    def ask(self, system, text, images):
        self.seen.append((system, text, images))
        return self.text


def test_the_facts_are_counted_from_the_assist_log_only():
    f = facts_from(LOG, refused=3, f12=False)
    assert f == {"parts_asked": 2, "parts_done": 1, "parts_not_done": 1, "done_by_model": 1, "turns": 16, "presses_for_you": 29,
                 "ai_calls": 16, "seconds": 43, "refused_kept_keys": 3, "stopped_with_f12": False}


def test_a_text_with_only_counted_numbers_is_shown_and_the_model_is_sent_only_the_facts():
    wonder = FakeWonder("You asked for 2 parts and I finished 1 of them in 16 turns, pressing 29 keys for you.")
    d = Debrief(wonder)
    out = d.write(facts_from(LOG, refused=0, f12=False), "english")
    assert out["source"] == "muse-wonder" and out["text"].startswith("You asked")
    sent = wonder.seen[0][1]
    assert json.loads(sent.split("FACTS:", 1)[1]) and wonder.seen[0][2] == []  # no picture, no words the player said
    assert "grab the coins" not in sent  # the player's own words are not sent again
    assert out["cost_usd"] == round(1000 * 4e-6 + 100 * 20e-6, 6)


def test_an_invented_number_is_refused_and_the_plain_counted_line_is_shown():
    facts = facts_from(LOG, refused=0, f12=False)
    out = Debrief(FakeWonder("You finished 3 parts in record time, 95% accuracy!")).write(facts, "english")
    assert out["source"] == "counted" and out["rejected"] and out["text"] == plain_line(facts, "english")


def test_arabic_digits_are_checked_too():
    facts = facts_from(LOG, refused=0, f12=False)
    assert numbers_ok("طلبت ٢ أجزاء وأنهيت ١ منها", facts)
    assert not numbers_ok("أنهيت ٧ أجزاء", facts)


def test_a_model_failure_never_hides_the_debrief():
    class Broken(FakeWonder):
        def ask(self, *a):
            raise RuntimeError("down")
    out = Debrief(Broken("")).write(facts_from(LOG, refused=0, f12=True), "arabic")
    assert out["source"] == "counted" and out["text"] == plain_line(facts_from(LOG, refused=0, f12=True), "arabic")


def test_after_an_assisted_session_the_counted_line_is_said_and_wonder_only_when_asked_with_a_key():
    import settings
    from types import SimpleNamespace

    from playfellow_coop import __main__ as entry
    from playfellow_coop.assist import Assist
    parts = SimpleNamespace(assist=Assist(), hands=SimpleNamespace(backend=SimpleNamespace(refused=2)), debrief_mode="counted")
    parts.assist.log = list(LOG)
    line = entry.session_debrief(parts, "stopped_f12", settings.Settings())
    assert line == plain_line(facts_from(LOG, refused=2, f12=True), "english")
    parts.debrief_mode = "wonder"
    assert entry.session_debrief(parts, "round_done", settings.Settings(), key_loader=lambda: None) == plain_line(facts_from(LOG, refused=2, f12=False), "english")
