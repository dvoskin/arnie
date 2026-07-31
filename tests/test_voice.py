"""The voice contract, its seam, and the corpus gate (B6).

core/voice is the single source of truth §8 was missing. These pin the three
things that make it trustworthy: the character/case transforms are correct and
conservative, the linter catches what it claims and nothing it shouldn't, and
the corpus proves the seam closes the lowercase-lead class on everything the
product actually ships.
"""
import os

import pytest

from core import voice
from core.voice import (
    CoachMessagePlan, Segment, V, check_voice, enforce_sentence_case, normalize,
    render_bubble,
)


# ── normalize: the merged character pass ─────────────────────────────────────

def test_em_dash_becomes_comma_en_dash_and_hyphen_survive():
    assert normalize("nice — clean day") == "nice, clean day"
    # The bug this module exists to end: a range must survive both dash forms.
    assert normalize("12–13% body fat") == "12–13% body fat"
    assert normalize("8-10 reps") == "8-10 reps"


def test_tilde_becomes_about_without_doubling():
    assert normalize("~230 cal") == "about 230 cal"
    assert normalize("about ~230 cal") == "about 230 cal"   # no "about about"
    assert normalize("plain ~ tilde") == "plain tilde"


def test_normalize_is_idempotent():
    for s in ("~230 — x", "a  b   c", "12–13%", "nice — clean ~5 day"):
        assert normalize(normalize(s)) == normalize(s)


# ── enforce_sentence_case: conservative lead capitalization ──────────────────

@pytest.mark.parametrize("raw,expected", [
    ("good to meet you", "Good to meet you"),
    ("morning sam.", "Morning sam."),
    ("i'll pull out what matters", "I'll pull out what matters"),
])
def test_lowercase_lead_is_capitalized(raw, expected):
    assert enforce_sentence_case(raw) == expected


@pytest.mark.parametrize("raw", [
    "iOS synced fine", "iPhone is paired", "eBay order landed",   # internal caps
    "http://x.co has it", "www.x.co works",                        # URLs
    "📋 Sunday, June 14", "190 now, 175 before",                   # emoji / number lead
    "Already capitalized", "", "   ",                              # nothing to do
])
def test_intentional_or_non_letter_leads_are_left_alone(raw):
    assert enforce_sentence_case(raw) == raw


def test_sentence_case_is_idempotent():
    assert enforce_sentence_case(enforce_sentence_case("good")) == "Good"


def test_non_latin_scripts_pass_through_untouched():
    # Cyrillic/CJK are out of scope for the Latin-only rule — never mis-cased.
    for s in ("привет, как дела", "今日は", "مرحبا"):
        assert enforce_sentence_case(s) == s


# ── the linter ───────────────────────────────────────────────────────────────

def test_check_voice_flags_each_rule():
    codes = {v.code for v in check_voice(
        "logged.|||feel free to let me know~230!! 😅")}
    assert V.TILDE in codes
    assert V.LOWERCASE_LEAD in codes
    assert V.JOKE_EMOJI in codes
    assert V.HELPDESK_FILLER in codes
    assert V.EXCLAMATION_PILE in codes
    assert V.ROBOTIC_ACK in codes


def test_check_voice_flags_em_dash_and_leaked_markers():
    assert V.EM_DASH in {v.code for v in check_voice("nice — day")}
    assert V.LEAKED_MARKER in {v.code for v in check_voice("got it [[LOGGED]]")}
    assert V.LEAKED_MARKER in {v.code for v in check_voice("done {say_x}")}
    assert V.EMPTY_BUBBLE in {v.code for v in check_voice("first|||")}


def test_clean_in_voice_text_has_no_violations():
    for good in ("You're at 840, protein's strong.",
                 "📋 Sunday, June 14|||Total: 1,470 cal",
                 "8-10 reps, felt strong."):
        assert check_voice(good) == [], good


# ── CoachMessagePlan ─────────────────────────────────────────────────────────

def test_plan_renders_in_voice_by_construction():
    plan = (CoachMessagePlan()
            .read("morning sam")
            .receipt("245 cal, 32g protein")
            .nudge("get some protein in at lunch — you're low"))
    out = plan.render()
    assert out == "Morning sam|||245 cal, 32g protein|||Get some protein in at lunch, you're low"
    assert check_voice(out) == []


def test_plan_caps_bubbles():
    plan = CoachMessagePlan(max_bubbles=2)
    for i in range(5):
        plan.read(f"line {i}")
    assert len(plan.render().split("|||")) == 2


# ── the seam: what actually ships ────────────────────────────────────────────

def test_seam_sentence_cases_and_preserves_ranges():
    from core.platform import Response
    r = Response.from_text("morning bob.|||you're at ~230 cal — nice|||8–10 reps")
    assert r.bubbles == ["Morning bob.", "You're at about 230 cal, nice", "8–10 reps"]


def test_kill_switch_disables_sentence_case(monkeypatch):
    monkeypatch.setenv("VOICE_SENTENCE_CASE", "false")
    # normalize still runs; only the capitalization is suppressed.
    assert render_bubble("morning bob") == "morning bob"
    monkeypatch.setenv("VOICE_SENTENCE_CASE", "true")
    assert render_bubble("morning bob") == "Morning bob"


# ── the corpus gate — the measurement, frozen so it can't regress ────────────

def test_seam_closes_the_lowercase_class_on_the_whole_corpus():
    from scripts.voice_audit import audit
    rows = audit()
    # Every lowercase-lead in the shipped corpus is fixed by the seam.
    assert sum(r["pre"].count("lowercase_lead") for r in rows) >= 7  # there ARE some
    assert sum(r["post"].count("lowercase_lead") for r in rows) == 0


def test_negative_controls_still_bite():
    from scripts.voice_audit import audit
    rows = audit()
    negs = [r for r in rows if r["negative"]]
    assert negs and all(r["post"] for r in negs), "a bad:* control stopped tripping the linter"


def test_only_known_shipped_finding_is_the_city_nudge_joke_emoji():
    # The audit surfaces exactly one shipped violation on a clean shape: the
    # proactive city ask ships 😅. It is FROZEN here, not silently passed —
    # whether to strip it is a voice call for Danny (the main prompt itself is
    # self-contradictory on 😂: an approved example uses it, a rule bans it).
    # If this set changes, re-run scripts/voice_audit.py and update the scorecard.
    from scripts.voice_audit import audit
    findings = {(r["shape"], tuple(r["post"]))
                for r in audit() if r["post"] and not r["negative"]}
    assert findings == {("proactive:city_ask", ("joke_emoji",))}, findings
