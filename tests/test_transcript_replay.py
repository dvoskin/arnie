"""The transcript replay runner (PR #28).

Every transcript in tests/gold/transcripts.py is replayed against the real
pipeline — `plan_turn` for the decision, the narrow parsers for the answer,
`resolving()` to apply it, and `decide` again for the next round. Nothing is
mocked but the interpreter, because the interpreter is the one part these
transcripts are not testing.

What this covers that the single-resolution gold set cannot: whether the
question is asked at all, which item it is about, whether the answer binds to
that item, what commits while something else waits, and whether the second turn
remembers the first.

A failure names the transcript and the turn, which is also the ticket.
"""
from collections import Counter
from datetime import datetime, timedelta

import pytest

from core.food_pipeline import plan_turn
from skills.nutrition.answer_parsers import parse_answer, parse_command
from skills.nutrition.clarify_policy import decide
from skills.nutrition.preferences import (UserFoodPreference, confirm,
                                          observe_answer)
from tests.gold.transcripts import ALL_TRANSCRIPTS

NOW = datetime(2026, 7, 25, 12, 0, 0)


def _ids(items):
    return [t["id"] for t in items]


class _Replay:
    """The conversation state a transcript walks through.

    Deliberately small: staged items, the outstanding question and the round
    number are the entire lifecycle. If a transcript needs more state than
    this, the production lifecycle probably needs it too.
    """

    def __init__(self, transcript):
        self.transcript = transcript
        self.mode = transcript["mode"]
        self.round_number = 0
        self.items = ()
        self.decision = None
        self.question = None
        self.preferences = []

    @property
    def where(self):
        return f"[{self.transcript['id']}]"

    def run_log(self, turn):
        self.decision = plan_turn(
            turn["data"], turn_id=f"t_{self.transcript['id']}",
            message=turn["message"], mode=self.mode,
            round_number=self.round_number, preferences=self.preferences,
            now=NOW)
        if self.decision is not None:
            self.items = self.decision.staged_items
            self.question = self.decision.question

    def run_reply(self, turn):
        """Parse against the question we asked, then apply it to that item."""
        text = turn["message"]
        if self.question is None:
            return None, parse_command(text)
        answer = parse_answer(text, self.question)
        if answer.command is None and answer.values:
            self.items = tuple(
                i.answering(self.question, **answer.values)
                if i.staged_item_id == self.question.staged_item_id else i
                for i in self.items)
            self.round_number += 1
            self.decision = decide(list(self.items), mode=self.mode,
                                   round_number=self.round_number)
            self.question = (self.decision.questions[0]
                             if self.decision.questions else None)
        return answer, answer.command

    def run_learn(self, turn):
        pref = None
        for _ in range(turn["confirmations"]):
            pref = observe_answer(pref, term=turn["term"], now=NOW,
                                  identity={turn["field"]: turn["value"]})
        self.preferences = [pref]
        return pref


# ── assertions, one per expectation key ───────────────────────────────────────
def _check_log(state, expect, where):
    decision = state.decision
    if expect.get("decision", "unset") is None:
        assert decision is None, f"{where} expected no plan, got one"
        return
    assert decision is not None, f"{where} the pipeline planned nothing"

    if "asks" in expect:
        assert decision.asks == expect["asks"], (
            f"{where} expected asks={expect['asks']}, got {decision.asks} "
            f"(questions: {[q.prompt for q in decision.clarification.questions]})")

    if "questions" in expect:
        assert len(decision.clarification.questions) == expect["questions"], (
            f"{where} expected {expect['questions']} questions, got "
            f"{len(decision.clarification.questions)}")

    if "committed" in expect:
        assert len(decision.clarification.ready_item_ids) == expect["committed"], (
            f"{where} expected {expect['committed']} ready, got "
            f"{len(decision.clarification.ready_item_ids)}")

    if "held" in expect:
        assert len(decision.clarification.held_item_ids) == expect["held"], (
            f"{where} expected {expect['held']} held, got "
            f"{len(decision.clarification.held_item_ids)}")

    if "held_min" in expect:
        assert len(decision.clarification.held_item_ids) >= expect["held_min"], where

    if "policy" in expect:
        assert decision.clarification.transaction_policy.value == expect["policy"], (
            f"{where} expected policy {expect['policy']}, got "
            f"{decision.clarification.transaction_policy.value}")

    if "fields" in expect:
        asked = set()
        for q in decision.clarification.questions:
            asked.update(q.requested_fields)
        assert set(expect["fields"]) <= asked, (
            f"{where} expected fields {expect['fields']} to be asked, got "
            f"{sorted(asked)}")

    if "first_question_about" in expect:
        first = decision.clarification.questions[0]
        item = next(i for i in decision.staged_items
                    if i.staged_item_id == first.staged_item_id)
        assert expect["first_question_about"] in item.original_text.lower(), (
            f"{where} the highest-value question was about "
            f"{item.original_text!r}, expected "
            f"{expect['first_question_about']!r}")

    if "assumptions_min" in expect:
        assert len(decision.clarification.assumptions) >= expect["assumptions_min"], (
            f"{where} expected at least {expect['assumptions_min']} "
            f"assumptions, got {len(decision.clarification.assumptions)}")

    if "assumption_contains" in expect:
        texts = " ".join(a.user_visible_text
                         for a in decision.clarification.assumptions)
        assert expect["assumption_contains"] in texts.lower(), (
            f"{where} no assumption mentions "
            f"{expect['assumption_contains']!r}: {texts!r}")


def _check_reply(state, answer, command, expect, where):
    if "command" in expect:
        assert command is not None and command.value == expect["command"], (
            f"{where} expected command {expect['command']}, got {command}")
        return

    if expect.get("unparsed"):
        assert answer is None or answer.unparsed or not answer.values, (
            f"{where} expected the answer to be unparsed, got {answer}")
        return

    if "values" in expect:
        assert answer is not None, f"{where} nothing parsed"
        for field, value in expect["values"].items():
            assert field in answer.values, (
                f"{where} expected {field!r} in the answer, got "
                f"{dict(answer.values)}")

    if expect.get("resolves"):
        assert answer is not None and answer.resolves_anything, (
            f"{where} the answer resolved nothing: {answer}")

    if "not_field" in expect:
        assert expect["not_field"] not in (answer.values if answer else {}), (
            f"{where} the answer was written to {expect['not_field']!r}, "
            f"which is not what was asked: {dict(answer.values)}")

    if "asks_after" in expect:
        asks = state.decision is not None and state.decision.asks
        assert asks == expect["asks_after"], (
            f"{where} after the answer, expected asks={expect['asks_after']}, "
            f"got {asks}")

    if "committed_after" in expect:
        ready = len(state.decision.ready_item_ids or ())
        assert ready == expect["committed_after"], (
            f"{where} after the answer, expected {expect['committed_after']} "
            f"ready, got {ready}")

    if "bound_to" in expect:
        item = next(i for i in state.items
                    if i.staged_item_id == state.transcript["_asked_item"])
        assert expect["bound_to"] in item.original_text.lower(), (
            f"{where} the answer bound to {item.original_text!r}")


@pytest.mark.parametrize("transcript", ALL_TRANSCRIPTS,
                         ids=_ids(ALL_TRANSCRIPTS))
def test_transcript(transcript):
    state = _Replay(transcript)
    for index, turn in enumerate(transcript["turns"]):
        where = f"[{transcript['id']} turn {index} {turn['kind']}]"
        if turn["kind"] == "log":
            state.run_log(turn)
            _check_log(state, turn["expect"], where)
        elif turn["kind"] == "reply":
            asked_item = (state.question.staged_item_id
                          if state.question else None)
            transcript["_asked_item"] = asked_item
            answer, command = state.run_reply(turn)
            _check_reply(state, answer, command, turn["expect"], where)
        elif turn["kind"] == "learn":
            pref = state.run_learn(turn)
            if turn["expect"].get("promoted") is not None:
                assert pref.is_promoted == turn["expect"]["promoted"], where


# ── properties that must hold across every transcript ─────────────────────────
@pytest.mark.parametrize("transcript", ALL_TRANSCRIPTS,
                         ids=_ids(ALL_TRANSCRIPTS))
def test_a_question_always_names_the_item_it_is_about(transcript):
    """The defect this pins: a question that cannot be bound to one staged row
    cannot have its answer applied, so the user answers into nothing."""
    state = _Replay(transcript)
    for turn in transcript["turns"]:
        if turn["kind"] == "learn":
            state.run_learn(turn)
            continue
        if turn["kind"] != "log":
            continue
        state.run_log(turn)
        if state.decision is None:
            continue
        staged = {i.staged_item_id for i in state.decision.staged_items}
        for q in state.decision.clarification.questions:
            assert q.staged_item_id in staged, (
                f"[{transcript['id']}] question {q.question_id} names an item "
                f"that is not in the meal")
            assert q.requested_fields, (
                f"[{transcript['id']}] question {q.question_id} requests no "
                f"fields, so no answer to it can be applied")
            assert q.prompt.strip(), (
                f"[{transcript['id']}] question {q.question_id} has no prompt")


@pytest.mark.parametrize("transcript", ALL_TRANSCRIPTS,
                         ids=_ids(ALL_TRANSCRIPTS))
def test_no_item_is_both_committed_and_held(transcript):
    """Partial commit is the whole point of the split, and an item on both
    sides of it is either logged twice or logged and then asked about."""
    state = _Replay(transcript)
    for turn in transcript["turns"]:
        if turn["kind"] == "learn":
            state.run_learn(turn)
        elif turn["kind"] == "log":
            state.run_log(turn)
            if state.decision is None:
                continue
            ready = set(state.decision.clarification.ready_item_ids or ())
            held = set(state.decision.clarification.held_item_ids or ())
            assert not (ready & held), (
                f"[{transcript['id']}] {ready & held} is both ready and held")


@pytest.mark.parametrize("transcript", ALL_TRANSCRIPTS,
                         ids=_ids(ALL_TRANSCRIPTS))
def test_an_assumption_is_always_something_a_user_could_read(transcript):
    """An assumption with no user-visible text is an assumption that was made
    silently, which is the thing disclosure exists to prevent."""
    state = _Replay(transcript)
    for turn in transcript["turns"]:
        if turn["kind"] == "learn":
            state.run_learn(turn)
        elif turn["kind"] == "log":
            state.run_log(turn)
            if state.decision is None:
                continue
            for a in state.decision.clarification.assumptions:
                assert a.user_visible_text.strip(), (
                    f"[{transcript['id']}] a silent assumption on "
                    f"{a.staged_item_id}")


def test_transcript_ids_are_unique():
    ids = [t["id"] for t in ALL_TRANSCRIPTS]
    assert len(ids) == len(set(ids))


def test_the_set_covers_every_transcript_category():
    categories = {t["category"] for t in ALL_TRANSCRIPTS}
    assert categories >= {"clarification", "preferences", "corrections"}


def test_the_transcript_set_has_not_shrunk():
    """Same floor rule as the gold set: attrition is invisible without a
    number that fails."""
    counts = Counter(t["category"] for t in ALL_TRANSCRIPTS)
    floors = {"clarification": 22, "preferences": 18, "corrections": 2}
    short = {k: (counts.get(k, 0), f) for k, f in floors.items()
             if counts.get(k, 0) < f}
    assert not short, f"categories below their floor (have, floor): {short}"


def test_a_contradiction_demotes_a_promoted_preference():
    """The rule a correction depends on: being wrong once stops the default
    applying now, not after it has been wrong three times."""
    pref = None
    for _ in range(3):
        pref = observe_answer(pref, term="fairlife", now=NOW,
                              identity={"product_line": "Core Power"})
    assert pref.is_promoted
    contradicted = confirm(pref, NOW + timedelta(days=1), matches=False)
    assert not contradicted.is_promoted
    assert contradicted.blocked_by_contradiction(NOW + timedelta(days=1))


def test_a_preference_never_applies_before_promotion():
    pref = UserFoodPreference(trigger_term="fairlife",
                              product_line="Core Power", confirmations=2)
    assert not pref.applies(NOW)
