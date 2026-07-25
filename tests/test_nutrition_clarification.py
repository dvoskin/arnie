"""Entity-bound nutrition clarifications (review 2026-07-25, step 2).

Distinct from the older `food_clarification` kind (tests/test_pending_clarification.py),
which asks an open conversational question — "grilled or fried?" — and lets the
model use the answer. This one is bound to a specific entity and carries the
answer straight to it.

The failure it closes: a clarification answer re-running identification and
landing on the wrong row. "The label is 80 calories" must update the entry we
asked about, not whatever the answer's words happen to resolve to.

Three properties, in order of how badly they hurt when broken:
  1. the target is bound at ask time and the answer cannot move it;
  2. a value the user states is ground truth, marked so enrichment can't
     overwrite it;
  3. a field the user did NOT state is left alone — unknown is not zero.
"""
import pytest

from core.pending_clarification import (BoundTarget, answer_operations,
                                        answer_is_refusal, build_ask,
                                        from_payload, parse_nutrient_answer,
                                        USER_LABEL_SOURCE, CLARIFY_KIND)


def _pending(entry_id=42, fields=("calories", "protein"), current=None):
    return build_ask(BoundTarget(entry_id=entry_id, label="Royo Plain Bagel"),
                     fields, current or {"calories": 260},
                     source="usda", turn_id="imessage:G-1")


# ── the target cannot move ────────────────────────────────────────────────────
def test_the_answer_never_re_resolves_the_target():
    """The reply names a completely different food. It is still an answer
    about the entity we asked about."""
    ops = answer_operations(
        _pending(), "the bagel I had at my mom's — 80 calories and 8g protein")
    assert len(ops) == 1
    assert ops[0]["name"] == "update_food_entry"
    assert ops[0]["input"]["entry_id"] == 42
    assert "food_name" not in ops[0]["input"]     # no re-identification


def test_an_unbound_payload_is_refused():
    """A pending row with no entity is unusable by construction — better to
    fall through to the interpreter than to guess a target."""
    assert from_payload('{"kind": "nutrition", "target": {}}') is None


def test_a_plan_confirmation_is_never_read_as_a_clarification():
    """The two pending kinds must not cross: a "yes" to "log these three?" is
    approval to write, not a nutrient answer."""
    assert from_payload('{"kind": "confirm", "items": [{"food": "rice"}]}') is None


def test_a_stale_row_refuses_the_update():
    """CAS seed from the values at ask time: if the entry moved while the
    question was open, the update is refused rather than clobbering."""
    ops = answer_operations(_pending(current={"calories": 260}), "80 calories")
    assert ops[0]["input"]["expected_calories"] == 260


# ── the user's numbers are ground truth ───────────────────────────────────────
def test_stated_values_are_marked_ground_truth():
    ops = answer_operations(_pending(), "it's 80 calories and 8g protein")
    inp = ops[0]["input"]
    assert inp["calories"] == 80 and inp["protein"] == 8
    assert inp["source"] == USER_LABEL_SOURCE and inp["user_label"] is True


def test_unstated_fields_are_left_alone():
    """Unknown is not zero. Writing sodium=0 because the user didn't mention
    sodium asserts a product fact nobody established."""
    ops = answer_operations(_pending(fields=("calories", "protein", "sodium")),
                            "80 calories, 8g protein")
    inp = ops[0]["input"]
    assert inp["calories"] == 80 and inp["protein"] == 8
    assert "sodium" not in inp and "carbs" not in inp and "fat" not in inp


def test_a_held_item_commits_with_the_users_numbers():
    """Pre-write clarification: the original operation runs, carrying the
    label values instead of an estimate."""
    pending = build_ask(
        BoundTarget(staged_item_id="s1", label="Royo Plain Bagel"),
        ("calories", "protein"),
        operation={"name": "log_food",
                   "input": {"food_name": "Royo Plain Bagel",
                             "quantity": "1 bagel", "calories": 260}})
    ops = answer_operations(pending, "80 cal, 8g protein")
    assert ops[0]["name"] == "log_food"
    assert ops[0]["input"]["food_name"] == "Royo Plain Bagel"   # identity kept
    assert ops[0]["input"]["calories"] == 80                    # estimate replaced
    assert ops[0]["input"]["source"] == USER_LABEL_SOURCE


# ── parsing ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("80 calories and 8g protein", {"calories": 80, "protein": 8}),
    ("it's 80 cal, 8 g protein", {"calories": 80, "protein": 8}),
    ("calories are 80, protein is 8", {"calories": 80, "protein": 8}),
    ("230 kcal", {"calories": 230}),
    ("sodium 480mg", {"sodium": 480}),
])
def test_spoken_label_readings_parse(text, expected):
    assert parse_nutrient_answer(text, ("calories", "protein")) == expected


def test_bare_numbers_only_map_when_the_count_matches_what_we_asked():
    """We chose the asking order, so "80 and 8" is unambiguous — but only when
    the counts line up. Anything else is a guess, and we don't guess."""
    assert parse_nutrient_answer("80 and 8", ("calories", "protein")) == {
        "calories": 80, "protein": 8}
    assert parse_nutrient_answer("80", ("calories", "protein")) == {}
    assert parse_nutrient_answer("80 and 8 and 12", ("calories", "protein")) == {}


def test_a_reply_with_no_values_falls_through():
    """Not every answer is a label reading. The caller keeps the pending row
    bound and lets the interpreter handle the sentence."""
    assert answer_operations(_pending(), "the everything one, not the plain") is None


@pytest.mark.parametrize("text", [
    "no idea", "I don't know", "not sure", "there's no label on it",
])
def test_a_refusal_is_recognised_as_an_answer(text):
    """"I don't know" closes the question. Re-asking it is nagging, and
    guessing a value because the user declined is worse."""
    assert answer_is_refusal(text)
    assert answer_operations(_pending(), text) is None


def test_round_trips_through_storage():
    pending = _pending()
    restored = from_payload(pending.to_payload())
    assert restored.target.entry_id == 42
    assert restored.fields == ("calories", "protein")
    assert restored.source == "usda"
    assert CLARIFY_KIND == "food_nutrition_clarification"


# ── tier 1 is enforced where it matters: the executor ─────────────────────────
@pytest.mark.asyncio
async def test_a_user_label_skips_enrichment_entirely(monkeypatch, db, make_user):
    """The point of tier 1: we asked, they answered, that IS the product. Not
    "look it up and prefer the answer" — no lookup happens at all, so a cousin
    match cannot leak in through a field the reply left unstated."""
    import handlers.tool_executor as TE
    user = await make_user()

    async def _no_lookups(*a, **k):
        raise AssertionError("a stated label must not trigger enrichment")
    monkeypatch.setattr(TE, "_logged_history_match", _no_lookups)
    monkeypatch.setattr(TE, "_web_lookup_meal", _no_lookups)

    result = await TE._analyze_food(
        db, user, "Royo Plain Bagel",
        {"quantity": "1 bagel", "calories": 80, "protein": 8,
         "source": USER_LABEL_SOURCE, "user_label": True})
    assert result.calories == 80 and result.protein == 8
    assert result.source == "user_label"
    assert result.confidence == "user-confirmed"


@pytest.mark.asyncio
async def test_the_flag_alone_does_not_disable_enrichment(db, make_user):
    """A marked write with nothing to honour must still be enriched — the flag
    means "these values are the label", not "skip the lookup"."""
    import handlers.tool_executor as TE
    user = await make_user()
    assert TE._user_stated_label({"user_label": True}) is False
    assert TE._user_stated_label({"user_label": True, "calories": 80}) is True
    assert TE._user_stated_label({"calories": 80}) is False
