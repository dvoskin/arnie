"""Correction turns: the chicken shish transcript (correction-turn directive).

    USER   Just had 3 pieces of chicken shish and a little salad at this
           party place
    ARNIE  must ask whether "pieces" means chunks or whole skewers
    USER   Like 3 pieces of chicken shish and like 1/3 bowl of salad

What went wrong, in the order it went wrong:

  * §1 — on strict, a pending whole-meal confirm SUPPRESSED `plan_turn`
    entirely, so the unit was never staged, normalized or questioned. "Does
    that look right?" arrived over a parse that already said "3 pieces", and a
    yes to that is a yes to a number nobody established.
  * §3 §4 — a piece and a skewer are different foods. The count is the only
    thing they share, and it is the one thing that looks unchanged, so a
    correction rewrote the unit string and left the mass, count basis,
    resolver result and macros derived for skewers in place.
  * §2 — the answer turn was treated as automatically safe to estimate and
    commit, so none of that was re-derived.
  * §5 — the card then said "3 skewers" back to a user who had twice said
    pieces.
"""
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from skills.nutrition.unit_change import compare, may_commit, question_for

MESSAGE_1 = ("Just had 3 pieces of chicken shish and a little salad at this "
             "party place")
MESSAGE_2 = "Like 3 pieces of chicken shish and like 1/3 bowl of salad"


def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fc


def _strict():
    return SimpleNamespace(preferences=SimpleNamespace(
        food_logging_mode="strict"))


# ── §3, §4: what a unit correction costs ────────────────────────────────────

def test_nothing_derived_for_skewers_survives_a_correction_to_pieces():
    change = compare("skewer", "piece")
    assert change.changed
    for field in ("normalized_mass_g", "count_basis", "portion_assumptions",
                  "resolver_result", "calories", "macros",
                  "cached_serving_interpretation"):
        assert field in change.invalidated, field


def test_a_piece_and_a_skewer_block_the_commit():
    """Not an approximation — a category error. A skewer holds several
    pieces."""
    change = compare("skewer", "piece")
    assert change.blocks_commit
    assert may_commit(change) is False


@pytest.mark.parametrize("before,after", [
    ("skewer", "piece"), ("bowl", "piece"), ("whole pizza", "slice"),
    ("serving", "bite"),
])
def test_the_incompatible_pairs_the_directive_names(before, after):
    assert compare(before, after).blocks_commit


def test_a_mass_or_a_disclosed_range_earns_the_commit_back():
    """Three ways out, and a silent re-estimate is not one of them — that is
    the same confident number the correction just said was wrong."""
    change = compare("skewer", "piece")
    assert may_commit(change, mass_g=60.0)
    assert may_commit(change, serving_definition="1 piece = 30 g")
    assert may_commit(change, disclosed_range=(90.0, 320.0))
    assert not may_commit(change, mass_g=None)


def test_a_count_only_correction_invalidates_nothing():
    """"3 pieces" to "4 pieces" is arithmetic on a basis that still holds.
    Treating it like a unit change would re-ask about something settled."""
    assert not compare("piece", "pieces").changed
    assert not compare("cup", "cups").changed


def test_the_question_names_both_units():
    """The user's correction was about the difference between them; a question
    that does not mention it reads as though we did not hear."""
    q = question_for(compare("skewer", "piece"), "chicken shish")
    assert "piece" in q and "skewer" in q
    assert "chicken shish" in q


# ── §1: the confirm may not stand in for the unit question ──────────────────

@pytest.mark.asyncio
async def test_strict_asks_about_the_unit_instead_of_confirming_the_parse(
        monkeypatch):
    """The first turn. A pending confirm used to suppress the pipeline, so the
    ambiguity was never derived and the confirm went out over an unestablished
    number."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Chicken shish",
                    "q": "chunks off the skewer, or whole skewers?"}],
        "items": [{"food": "Chicken shish", "amount": 3, "unit": "piece"}]}))
    out = await FT.run(MESSAGE_1, _strict())
    assert out["action"] == "ask"
    assert out.get("kind") != "confirm", (
        "a generic confirmation may never replace an unresolved unit question")
    assert "skewer" in out["text"].lower()


@pytest.mark.asyncio
async def test_the_question_carries_the_prior_interpretation(monkeypatch):
    """§2. Without it the answer turn has the user's words and its own parse
    but nothing to compare against — and so nothing to invalidate."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Caesar salad", "amount": 1.5, "unit": "cups",
                   "calories": 300, "basis": "estimate"}]}))
    out = await FT.run("had some caesar salad", _strict())
    assert out["action"] == "ask"
    assert out.get("items"), "the ask must stash what we made of the message"


# ── §2, §5: the answer turn re-derives, and keeps the user's word ───────────

@pytest.mark.asyncio
async def test_the_answer_turn_does_not_reuse_skewer_nutrition(monkeypatch):
    """The whole point. The count is unchanged, so nothing looks wrong — and
    every value under it was computed for a different food."""
    prior = {"original": MESSAGE_1,
             "question": "chunks off the skewer, or whole skewers?",
             "kind": "clarify", "ask_count": 1,
             "items": [{"food": "Chicken shish", "amount": 3,
                        "unit": "skewer", "calories": 660, "protein": 75}]}
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Chicken shish", "amount": 3, "unit": "piece",
                   "calories": 660, "protein": 75},
                  {"food": "Salad", "amount": 0.33, "unit": "bowl",
                   "calories": 80, "protein": 3}],
        "say": "Logged."}))
    out = await FT.run(MESSAGE_2, _strict(), prior=prior)

    # The skewer→piece correction has no mass behind it, so it holds.
    assert out is not None
    assert out["action"] == "ask"
    assert "skewer" in out["text"].lower() and "piece" in out["text"].lower()


@pytest.mark.asyncio
async def test_a_compatible_answer_still_commits(monkeypatch):
    """The guard must not swallow ordinary answers. An added detail on a unit
    that did not change is exactly what an answer turn is for."""
    prior = {"original": "had some caesar salad",
             "question": "roughly how much?", "kind": "clarify",
             "ask_count": 1,
             "items": [{"food": "Caesar salad", "amount": 1.5,
                        "unit": "cups", "calories": 300}]}
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Caesar salad", "amount": 2, "unit": "cups",
                   "calories": 400, "protein": 8}],
        "say": "Logged."}))
    out = await FT.run("more like two cups", _strict(), prior=prior)
    assert out["action"] == "log"


@pytest.mark.asyncio
async def test_the_corrected_wording_is_what_reaches_the_write(monkeypatch):
    """§5. The card may not say "3 skewers" to a user who twice said pieces."""
    prior = {"original": MESSAGE_1, "question": "whole skewers?",
             "kind": "clarify", "ask_count": 1,
             "items": [{"food": "Chicken shish", "amount": 3,
                        "unit": "skewer", "calories": 660}]}
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Chicken shish", "amount": 3, "unit": "piece",
                   "calories": 200, "protein": 25, "grams": 90},
                  {"food": "Salad", "amount": 0.33, "unit": "bowl",
                   "calories": 80}],
        "say": "Logged."}))
    out = await FT.run(MESSAGE_2, _strict(), prior=prior)
    if out["action"] == "log":
        units = [str((c.get("input") or {}).get("quantity") or "")
                 for c in out["tool_calls"]]
        joined = " ".join(units).lower()
        assert "skewer" not in joined
        assert "piece" in joined


def test_one_third_of_a_bowl_is_preserved():
    """The salad half of the same message. "1/3 bowl" is a stated fraction and
    must survive as one — this is the digit-fraction parse that used to read
    the numerator."""
    from skills.nutrition.normalize import normalize_quantity
    q = normalize_quantity("1/3 bowl", "salad")
    assert q.amount == pytest.approx(1 / 3)
    assert q.user_stated_amount == pytest.approx(1 / 3)


def test_no_singular_three_skewer():
    """"3 skewer" — the suffix bug and the wrong noun in one string."""
    from core.food_response import describe_portion
    assert describe_portion("3 piece", "chicken shish") == "three chicken shish"


# ── §7: no coaching from an unreconciled day ────────────────────────────────

def _receipt(entries, total_cal, **kw):
    from core.receipt import build_receipt
    return build_receipt(
        calories=kw.pop("calories", 300), protein=kw.pop("protein", 20),
        total_cal=total_cal, total_protein=190, cal_target=2200,
        protein_target=150, local_hour=19, entry_calories=entries, **kw)


def test_an_extreme_overage_is_not_voiced_from_a_total_that_does_not_add_up():
    """The sentence most likely to be built on the disagreement is the one
    leading with a large number, which is also the one a user acts on."""
    out = _receipt([2200, 1320], total_cal=4520)
    assert out.get("day_total_unreconciled") is True
    assert "2320" not in out["verdict"]
    assert "re-check" in out["verdict"] or "adding up" in out["verdict"]


def test_the_numbers_still_ride_so_the_card_can_render():
    """Fail closed on the CLAIM, not on the data. The user can still see the
    day for themselves; what is withheld is the reading of it."""
    out = _receipt([2200, 1320], total_cal=4520)
    assert out["remaining_cal"] == -2320
    assert out["day_total_gap_cal"] != 0


def test_a_reconciled_day_reads_normally():
    out = _receipt([2200, 2320], total_cal=4520)
    assert out.get("day_total_unreconciled") is None
    assert "2320" in out["verdict"]


def test_rounding_scale_disagreement_is_not_a_mismatch():
    """Entries are stored rounded, so near-exact agreement is the expectation
    and a tolerance this tight would fire on arithmetic."""
    out = _receipt([2200.4, 2319.7], total_cal=4520)
    assert out.get("day_total_unreconciled") is None


def test_a_mild_overage_is_flagged_but_still_read():
    """A day 80 calories over reads the same whether the total is off by 30 or
    not. Failing closed there trades a rare wrong sentence for a common
    missing one."""
    out = _receipt([1000, 280], total_cal=2280, calories=200, protein=20)
    assert out.get("day_total_unreconciled") is True
    assert "re-check" not in out["verdict"]


def test_no_entries_means_no_check_rather_than_an_empty_day():
    """`None` is "cannot see the entries". An empty list would claim the day is
    empty, and every stored total would look wrong."""
    out = _receipt(None, total_cal=4520)
    assert out.get("day_total_unreconciled") is None
    assert "2320" in out["verdict"]


# ── Moderate is the daily experience ────────────────────────────────────────
#
# A second question on an answer turn is the most expensive thing a correction
# can cost: the user has already been interrupted once, and answered. The modes
# differ in what they do with an unresolvable correction, never in whether they
# notice it.

def _mod():
    return SimpleNamespace(preferences=SimpleNamespace(
        food_logging_mode="moderate"))


def _quick():
    return SimpleNamespace(preferences=SimpleNamespace(
        food_logging_mode="quick"))


#: 3 pieces corrected to 1 bowl. Incompatible — a bowl holds several pieces —
#: but the NEW unit is the one that has to be sizeable, and the ontology knows
#: a bowl of salad (100-250 g). The reverse direction is not rangeable, which
#: is the point: a piece of something nobody has written a row for cannot be
#: sized, so it is a question in every mode.
PRIOR_PIECES = {"original": "had a few pieces of salad", "question": "how much?",
                "kind": "clarify", "ask_count": 1,
                "items": [{"food": "Salad", "amount": 3, "unit": "piece",
                           "calories": 200}]}


@pytest.mark.asyncio
@pytest.mark.parametrize("who", [_mod, _quick])
async def test_moderate_and_quick_resolve_a_rangeable_correction(monkeypatch, who):
    """`piece` → `bowl` is incompatible, and the ontology can size a bowl. The
    honest move is a committed log that says what it assumed — not a second
    question."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Salad", "amount": 1, "unit": "bowl",
                   "calories": 320, "protein": 8}],
        "say": "Logged."}))
    out = await FT.run("actually a whole bowl", who(), prior=PRIOR_PIECES)
    assert out["action"] == "log", "moderate must not re-ask what it can range"


@pytest.mark.asyncio
async def test_strict_still_asks_the_same_correction(monkeypatch):
    """Same input, different posture. Confirming an assumption before the write
    is the whole of what strict is."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Salad", "amount": 1, "unit": "bowl",
                   "calories": 320, "protein": 8}],
        "say": "Logged."}))
    out = await FT.run("actually a whole bowl", _strict(), prior=PRIOR_PIECES)
    assert out["action"] == "ask"


@pytest.mark.asyncio
@pytest.mark.parametrize("who", [_mod, _quick, _strict])
async def test_a_repeated_number_stops_every_mode(monkeypatch, who):
    """The interpreter sees the prior exchange, and the easiest thing it can do
    with "actually they were pieces" is hand back the figure it already gave.
    Identical calories across a unit change that means a different amount of
    food is the previous answer, unrevised.

    Quick's licence is to accept an estimate, not to accept one nobody made."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Salad", "amount": 1, "unit": "bowl",
                   "calories": 200}],          # ← identical to the prior read
        "say": "Logged."}))
    out = await FT.run("actually a whole bowl", who(), prior=PRIOR_PIECES)
    assert out["action"] == "ask", (
        "a rangeable correction still stops when the number is not a new one")


@pytest.mark.asyncio
@pytest.mark.parametrize("who", [_mod, _quick])
async def test_moderate_asks_when_there_is_nothing_honest_to_range_with(
        monkeypatch, who):
    """No piece weight and no ontology row for a piece of chicken shish. One
    question is the floor — inventing a number to avoid it is the failure this
    whole directive is about."""
    prior = {"original": MESSAGE_1, "question": "whole skewers?",
             "kind": "clarify", "ask_count": 1,
             "items": [{"food": "Chicken shish", "amount": 3,
                        "unit": "skewer", "calories": 660}]}
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Chicken shish", "amount": 3, "unit": "piece",
                   "calories": 240, "protein": 30}],
        "say": "Logged."}))
    out = await FT.run(MESSAGE_2, who(), prior=prior)
    assert out["action"] == "ask"


@pytest.mark.asyncio
@pytest.mark.parametrize("who", [_mod, _quick, _strict])
async def test_an_ordinary_answer_is_never_slowed_down(monkeypatch, who):
    """The guard must cost nothing on the common path. A unit that did not
    change invalidates nothing, in any mode."""
    prior = {"original": "had some caesar salad", "question": "how much?",
             "kind": "clarify", "ask_count": 1,
             "items": [{"food": "Caesar salad", "amount": 1.5,
                        "unit": "cups", "calories": 300}]}
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Caesar salad", "amount": 2, "unit": "cups",
                   "calories": 400, "protein": 8}],
        "say": "Logged."}))
    out = await FT.run("more like two cups", who(), prior=prior)
    assert out["action"] == "log"
