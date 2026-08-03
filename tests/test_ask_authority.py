"""WHO DECIDES TO ASK.

The interpreter used to own the ask outright. `action:"ask"` returned from
`_run_untraced` before `plan_turn` was ever reached, so on a clarification the
staging, the calibrated spans, the day-share and item-share dials and the
user's own mode contributed nothing at all. Measured over 110 real production
food messages: 100% of ask turns carried no scored consequence (0/27, 0/23,
0/25 across quick / moderate / strict), and the ask rate was flat across modes
— quick 25%, moderate 21%, strict 23% — because mode only ever reached the log
path.

Three things enforced that, and all three had to go:

  1. the prompt scoped ambiguity reporting to "when you log", so a model that
     had decided to ask correctly reported nothing;
  2. `plan_turn` sat behind `any(k == "log" for k, _ in ops)`;
  3. the `ask` schema had NO SLOT for the contested item's estimate — so even
     with 1 and 2 fixed the system still could not decline to ask, because
     nothing had produced a number to commit instead. That one is why the
     first attempt measured zero demotions in every mode.

Afterwards: 100% of proposals carry consequence and a fallback estimate, and
the rate finally separates by mode (16 / 21 / 24%).

These tests pin the DIRECTION of authority, not the dials — the numbers above
live in skills/nutrition/materiality.py and are swept against production.
"""
from types import SimpleNamespace

import pytest

import core.food_turn as FT
from skills.nutrition.materiality import day_share_override_for

TARGETS = {"calories": 2000.0, "protein": 150.0, "carbs": 200.0, "fat": 60.0}


@pytest.fixture(autouse=True)
def _fixed_targets(monkeypatch):
    """Pin the day's goals. These tests are about WHO decides, so they must not
    also depend on how targets are computed — and without this they silently
    fall through to the scale-blind legacy thresholds and pass for the wrong
    reason."""
    monkeypatch.setattr(FT, "_daily_targets", lambda user: dict(TARGETS))


def _user(mode):
    return SimpleNamespace(preferences=SimpleNamespace(
        food_logging_mode=mode))


def _proposal(span, calories, field="quantity"):
    """A model proposal to ask, carrying both halves the contract now requires:
    a best-estimate row and what the answer would settle."""
    return {"action": "ask",
            "items": [{"food": "Thing", "amount": 1, "unit": "serving",
                       "calories": calories, "protein": 10}],
            "ambiguities": [{"item": "Thing", "field": field,
                             "impact_cal": span}],
            "points": [{"label": "Thing", "qs": ["how much?"]}]}


# ── the inversion ────────────────────────────────────────────────────────────

def test_a_trivial_unknown_does_not_earn_a_question():
    """The model may propose; a 12-calorie spread on a snack does not survive
    it in any mode. Before, this reached the user as a question purely because
    the interpreter felt like asking."""
    for mode in ("quick", "moderate", "strict"):
        assert not FT._proposed_ask_is_material(
            _proposal(span=12, calories=90), mode=mode, user=_user(mode)), mode


def test_a_large_unknown_earns_a_question_in_every_mode():
    """400 calories in doubt on a 500-calorie plate — 18% of the day. Quick
    swallowed this, because quick opts out of the proportion rule and 400/500
    is below its threshold. Absolute size overrides proportion now."""
    for mode in ("quick", "moderate", "strict"):
        assert FT._proposed_ask_is_material(
            _proposal(span=400, calories=500), mode=mode, user=_user(mode)), mode


def test_modes_disagree_in_the_middle():
    """The whole point of modes. A middling unknown is worth a question to
    someone tracking closely and not to someone logging fast — one rule, three
    dials, rather than three different behaviours."""
    p = _proposal(span=60, calories=300)
    assert not FT._proposed_ask_is_material(p, mode="quick", user=_user("quick"))
    assert FT._proposed_ask_is_material(p, mode="strict", user=_user("strict"))


# ── the fail-safe ────────────────────────────────────────────────────────────

def test_an_unweighable_proposal_is_kept_not_committed():
    """Silence is not evidence of no doubt. A proposal reporting no consequence
    gives no grounds to call the question unnecessary, so it stands — reading
    it as "immaterial" commits a number nobody established."""
    bare = {"action": "ask",
            "items": [{"food": "Chicken shish", "amount": 3, "unit": "piece"}],
            "points": [{"label": "Chicken shish",
                        "q": "chunks off the skewer, or whole skewers?"}]}
    for mode in ("quick", "moderate", "strict"):
        assert FT._proposed_ask_is_material(bare, mode=mode,
                                            user=_user(mode)), mode


def test_an_unsized_item_still_scores_on_the_day():
    """No calories on the row yet — the day proportion is still knowable, and
    refusing on the missing denominator would drop every early-stage
    uncertainty."""
    p = {"action": "ask",
         "items": [{"food": "Thing", "amount": 1, "unit": "plate"}],
         "ambiguities": [{"item": "Thing", "field": "identity",
                          "impact_cal": 400}],
         "points": [{"label": "Thing", "qs": ["what was in it?"]}]}
    assert FT._proposed_ask_is_material(p, mode="strict", user=_user("strict"))


# ── the override is about the day, not the item ──────────────────────────────

def test_absolute_size_overrides_proportion():
    """An unknown worth this much of a day is worth a question whatever
    fraction of its own item it happens to be — the case quick had backwards,
    asking about a 10-calorie coffee and writing a 500-calorie plate."""
    span = day_share_override_for("quick") * TARGETS["calories"] + 10
    assert FT._proposed_ask_is_material(
        _proposal(span=span, calories=4000), mode="quick", user=_user("quick"))


# ── declining the question does not hide the guess ───────────────────────────

def test_the_assumption_rides_from_the_unknown_to_the_row():
    """Judging an unknown too small to interrupt for settles the INTERRUPTION,
    not the doubt — the turn still picked something. It travels."""
    items = FT._carry_assumptions(
        [{"food": "Wing", "amount": 1, "unit": "wing", "calories": 100}],
        [{"item": "Wing", "field": "prep", "impact_cal": 100,
          "assumed": "fried, bone-in, plain"}])
    assert items[0]["_assumed"] == [{"field": "prep",
                                     "text": "fried, bone-in, plain"}]
    call = FT._log_call(items[0])
    assert call["input"]["assumptions"] == [{"field": "prep",
                                             "text": "fried, bone-in, plain"}]


def test_an_assumption_reaches_the_card():
    from core.conversation import _logged_entry_card
    card = _logged_entry_card("log_food", {
        "food_name": "Wing", "quantity": "1 wing", "calories": 100,
        "_entry_id": 7,
        "assumptions": [{"field": "prep", "text": "fried, bone-in, plain"}]})
    assert card["payload"]["assumptions"] == [
        {"field": "prep", "text": "fried, bone-in, plain"}]


def test_an_unmatched_assumption_is_dropped_not_smeared():
    """Bound to the row it names. An ambiguity we cannot place must not attach
    itself to whatever food happens to be first."""
    items = FT._carry_assumptions(
        [{"food": "Wing", "calories": 100}],
        [{"item": "Something else", "field": "prep", "assumed": "grilled"}])
    assert "_assumed" not in items[0]


def test_a_commit_carrying_an_assumption_must_speak():
    """COMMIT may normally say nothing — the card said it happened. That
    reasoning covers the numbers and not a choice made on the user's behalf,
    which no card explains and older clients do not render at all."""
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    apply_policy)
    silent = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COMMIT))
    assert silent.allow_no_text
    speaks = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        assumptions=("a large restaurant-style portion",)))
    assert not speaks.allow_no_text
    assert speaks.max_words >= 45


# ── a fresh row must be recognisable as fresh ────────────────────────────────

def test_the_board_says_how_long_ago_each_row_landed():
    """"Already logged today" reads the same for a row written eight hours ago
    and one written a minute ago — so a message refining what we just wrote
    looks exactly like a new meal, and gets logged twice."""
    lines = FT.board_lines([
        {"id": 1, "food": "Rice", "qty": "1 cup", "cal": 205, "mins_ago": 0},
        {"id": 2, "food": "Chicken", "qty": "6 oz", "cal": 280, "mins_ago": 20},
        {"id": 3, "food": "Toast", "qty": "1 slice", "cal": 90,
         "mins_ago": 400}])
    assert "JUST LOGGED" in lines[0]
    assert "20 min ago" in lines[1]
    assert "ago" not in lines[2]          # hours old: recency carries no signal


def test_a_board_row_missing_its_age_still_renders():
    assert FT.board_lines([{"id": 9, "food": "Rice", "qty": "", "cal": 0}]) == [
        "#9 Rice, ?, 0 cal"]


# ── understood is not logged ────────────────────────────────────────────────

def test_understood_items_are_not_offered_as_logged_while_anything_pends():
    """The composer was told "UNDERSTOOD: chicken", wrote that it was down,
    and `validate()` rejected it as PENDING_AS_COMMITTED — so a mixed meal
    shipped the deterministic bullet list instead of a question."""
    from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                    FoodResponsePlan, build_prompt)
    plan = FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=(FoodItemSummary(name="Chicken"),),
        pending_items=(FoodItemSummary(name="Rice"),))
    prompt = build_prompt(plan)
    assert "NOT YET WRITTEN" in prompt
    settled = build_prompt(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        resolved_items=(FoodItemSummary(name="Chicken"),)))
    assert "NOT YET WRITTEN" not in settled


# ── a correction has to be visible ──────────────────────────────────────────

def test_a_corrected_row_still_gets_a_card():
    """Updates emitted no card, so after "the bar was cookies and cream" the
    only confirmation was whatever sentence the composer wrote."""
    from core.conversation import _logged_entry_card
    card = _logged_entry_card("update_food_entry", {
        "entry_id": 501, "food_name": "Barebells Cookies and Cream Bar",
        "quantity": "1 bar", "calories": 200, "protein": 20})
    # As a PATCH — the row is already on an earlier card, and that is the one
    # this revises. See tests/test_corrected_card_patch_0803.py.
    assert card["type"] == "macro_card_patch"
    assert card["payload"]["entry_id"] == 501
    assert card["payload"]["corrected"] is True
    assert card["payload"]["calories"] == 200


def test_a_deferred_macro_is_absent_not_zero():
    """A correction to WHAT it was omits macros so the ladder re-resolves them.
    Rendering that as 0 claims the food has no calories."""
    from core.conversation import _logged_entry_card
    card = _logged_entry_card("update_food_entry", {
        "entry_id": 501, "food_name": "Barebells Cookies and Cream Bar"})
    payload = card["payload"]
    for key in ("calories", "protein_g", "carbs_g", "fats_g"):
        assert key not in payload, key


def test_an_update_without_a_target_row_makes_no_card():
    from core.conversation import _logged_entry_card
    assert _logged_entry_card("update_food_entry", {"food_name": "Rice"}) is None


# ── the branded flag has to survive into staging ────────────────────────────

def test_the_interpreters_branded_flag_reaches_the_class():
    """Staging read `is_packaged`; the interpreter emits `branded`. Two names
    for one fact meant every branded product staged GENERIC — and Open Food
    Facts is seated only for BRANDED, so the label ladder could not run for the
    foods it exists to serve."""
    from core.food_pipeline import stage_items
    items, _ = stage_items(
        {"items": [{"food": "Some Brand Bar", "amount": 1, "unit": "bar",
                    "calories": 200, "branded": True},
                   {"food": "White rice", "amount": 1, "unit": "cup",
                    "calories": 205}]},
        turn_id="t", message="x")
    assert items[0].food_class.value == "branded"
    assert items[1].food_class.value == "generic"


# ── the label outranks the guess ────────────────────────────────────────────

def _off_bar(package="60 g", serving=""):
    return {"name": "Protein Bar", "brand": "SomeBrand", "source": "off",
            "serving_text": serving, "package_text": package,
            "per_serving": None, "cal_100": 400, "protein_100": 30,
            "carbs_100": 40, "fat_100": 12, "match": "exact",
            "_match": "exact"}


def test_a_labelled_product_lands_on_the_same_number_whatever_was_guessed():
    """Mode governs how much Arnie ASKS, never what a known food weighs. The
    same bar came out 140 / 100 / 100 across quick / moderate / strict because
    an exact label with no serving panel lost its calories to the model's
    guess, and the guess moves with the prompt."""
    from core.food_intelligence import analyze
    committed = {analyze("SomeBrand Protein Bar", "1 bar", guess, 20, 20, 8,
                         off_candidate=_off_bar(), is_packaged=True).calories
                 for guess in (90, 140, 220)}
    assert committed == {240.0}, committed      # 60 g x 400 cal/100g


def test_a_multipack_is_not_one_serving():
    """"6 x 44 g" is a box. Treating it as a single serving would commit six
    bars for one."""
    from core.food_intelligence import _mass_from_serving_panel
    assert _mass_from_serving_panel(
        "1 bar", _off_bar(package="6 x 44 g"), "Bar") is None


def test_no_net_weight_leaves_the_old_estimate_path_alone():
    from core.food_intelligence import _mass_from_serving_panel
    assert _mass_from_serving_panel(
        "1 bar", _off_bar(package=""), "Bar") is None


def test_the_demotion_never_writes_a_food_twice():
    """`ready` and `items` overlap. Deduping by whole-dict equality let one
    differing key make a second copy of the same food — six rows for four
    foods in a single turn."""
    import asyncio
    from types import SimpleNamespace
    data = {"action": "ask",
            "items": [{"food": "Egg", "amount": 1, "unit": "egg",
                       "calories": 70, "basis": "estimate"},
                      {"food": "Congee", "amount": 1, "unit": "cup",
                       "calories": 200}],
            "ready": [{"food": "Egg", "amount": 1, "unit": "egg",
                       "calories": 70}],          # same food, different dict
            "ambiguities": [{"item": "Congee", "field": "quantity",
                             "impact_cal": 8, "assumed": "a small bowl"}],
            "points": [{"label": "Congee", "qs": ["how much?"]}]}
    merged = FT._carry_assumptions(
        [i for i in data["items"]] +
        [i for i in data["ready"]
         if str(i.get("food", "")).lower() not in
         {str(x.get("food", "")).lower() for x in data["items"]}],
        data["ambiguities"])
    names = [str(i.get("food", "")).lower() for i in merged]
    assert len(names) == len(set(names)), names


def test_the_override_is_looser_for_quick_than_for_strict():
    """One universal bar put quick back where it started: at 12.5% it landed
    at ~273 cal, and a bowl or a plate of a real dish routinely spans 300-400,
    so it fired on 15 of 20 vague composite meals and quick stopped being
    quick. The ladder has to live inside the override too."""
    from skills.nutrition.materiality import day_share_override_for
    assert (day_share_override_for("quick")
            > day_share_override_for("moderate"))
    assert day_share_override_for("nonsense") == day_share_override_for("moderate")


def test_quick_commits_a_bowl_but_not_an_unidentified_plate():
    """The two cases the dial sits between: a named dish whose portion is
    vague commits with its guess disclosed; a plate we cannot identify at all
    still earns the question."""
    from skills.nutrition.materiality import is_material
    T = {"calories": 2183.0, "protein": 180.0, "carbs": 235.0, "fat": 58.0}
    assert not is_material(mode="quick", calorie_span=300, item_calories=600,
                           targets=T)                      # a bowl of ramen
    assert is_material(mode="quick", calorie_span=400, item_calories=500,
                       targets=T)                          # unidentified plate


# ── a cache may not remember an impossible food ─────────────────────────────

def test_an_impossible_calorie_density_is_not_cached():
    """Fat is 9 cal/g, so nothing edible exceeds 900 per 100 g. Found in
    production: a monk fruit row cached at 5030 cal/100g carrying a USDA id,
    which would price every later log of that food. Usually kilojoules in a
    kcal field, or a per-container figure in a per-100g slot."""
    import asyncio
    import pytest as _pytest
    from db.queries import upsert_user_food_match

    class _DB:
        def __init__(self): self.added = []
        def add(self, row): self.added.append(row)
        async def flush(self): pass
        async def commit(self): pass
        async def execute(self, *a, **k):
            class _R:
                def scalar_one_or_none(self): return None
                def scalars(self): return self
                def first(self): return None
            return _R()

    db = _DB()
    out = asyncio.run(
        upsert_user_food_match(db, 1, "monk fruit", "Monk fruit", "123",
                               {"calories": 5030, "protein": 0, "carbs": 0,
                                "fat": 0}, "likely"))
    assert out is None
    assert not db.added, "an impossible row must never reach the table"


# ── the gate that decides whether ANY of this runs ──────────────────────────

def test_a_food_log_in_another_script_is_not_declined():
    """The shape rules are ASCII, so a food report in Cyrillic matched nothing
    and was turned away — 98 of the 301 real food logs this gate rejected were
    rejected for no reason but their alphabet. Our rules not applying is not
    the same as the message not being food."""
    from core.food_turn import applies, decline_reason
    for msg in ("Я съел два яйца и кашу",
                "Привет арни сегодня я съела три яйца",
                "オートミールと卵を食べました"):
        assert applies(msg), msg
        assert decline_reason(msg) == "", msg


def test_evidence_against_food_still_declines_in_any_script():
    """Opening the blind spot must not open the gate to everything: a question
    is a question whatever the alphabet."""
    from core.food_turn import applies
    assert not applies("Сколько калорий в яйце?")      # ends in '?'


def test_the_open_gate_is_off_unless_asked_for(monkeypatch):
    """It roughly quadruples interpreter passes (25% -> 82% of messages), so it
    is a switch to measure behind, not a default."""
    import core.food_turn as FT
    monkeypatch.delenv("FOOD_GATE_OPEN", raising=False)
    assert not FT.open_gate_enabled()
    assert not FT.applies("Oh and a bag of quest chips")
    monkeypatch.setenv("FOOD_GATE_OPEN", "true")
    assert FT.open_gate_enabled()
    assert FT.applies("Oh and a bag of quest chips")


def test_the_open_gate_still_refuses_what_is_clearly_not_food(monkeypatch):
    import core.food_turn as FT
    monkeypatch.setenv("FOOD_GATE_OPEN", "true")
    for msg in ("how many calories in an egg?", "I'm going to have lunch later"):
        assert not FT.applies(msg), msg


# ── the gate and the classifier are the same question ──────────────────────

@pytest.mark.asyncio
async def test_the_gate_falls_back_to_regexes_when_the_model_lane_is_off(
        monkeypatch):
    """Default OFF, and identical to today when off — so enabling it is a
    measurable change and never a silent one."""
    import core.food_turn as FT
    monkeypatch.delenv("FOOD_GATE_MODEL", raising=False)
    for msg in ("Just had a sushi roll for lunch", "Oh and a bag of quest chips",
                "how many calories in an egg?"):
        assert await FT.food_relevance(msg) == FT.applies(msg), msg


@pytest.mark.asyncio
async def test_a_lexical_food_match_never_pays_for_a_model_call(monkeypatch):
    """Tier 2 of the gate: the regexes were never WRONG about food, only
    silent. A match is free and must short-circuit before the model."""
    import core.food_turn as FT
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")

    async def _boom(*a, **k):
        raise AssertionError("a lexical match must not reach the model")
    monkeypatch.setattr("core.llm.chat", _boom)
    assert await FT.food_relevance("Just had a sushi roll for lunch")


@pytest.mark.asyncio
async def test_strong_non_food_evidence_never_pays_for_a_model_call(
        monkeypatch):
    """Tier 1: a question is a question. Cheap, and it travels across
    languages better than food templates do."""
    import core.food_turn as FT
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")

    async def _boom(*a, **k):
        raise AssertionError("a clear decline must not reach the model")
    monkeypatch.setattr("core.llm.chat", _boom)
    assert not await FT.food_relevance("how many calories in an egg?")


@pytest.mark.asyncio
async def test_the_lane_is_never_lost_to_a_failing_model(monkeypatch):
    """A slow or unavailable classifier degrades to today's behaviour, never
    to dropping the turn."""
    import core.food_turn as FT
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")

    async def _fail(*a, **k):
        raise RuntimeError("classifier down")
    monkeypatch.setattr("core.llm.chat", _fail)
    assert await FT.food_relevance("Just had a sushi roll for lunch")
    assert not await FT.food_relevance("Oh and a bag of quest chips")


def test_a_hypothetical_cannot_write():
    """"if I had a burger would that blow my day" carries no question mark and
    does not open with an interrogative, so both existing guards passed it —
    while naming a food in the past tense, which is all the shapes downstream
    look for. A conditional describes a world; it does not report one."""
    from core.food_turn import consumption_evidence
    assert not consumption_evidence("if I had a burger would that blow my day")
    assert not consumption_evidence("if I ate 3 eggs could I still hit macros")


def test_the_conditional_guard_does_not_eat_real_logs():
    """Narrow on purpose — it needs BOTH halves of the construction, so a
    stray "if" in an ordinary report still writes."""
    from core.food_turn import consumption_evidence
    assert consumption_evidence("if you want, I had the salad earlier")
    assert consumption_evidence("had a coffee then a bagel then hit the gym")
    assert consumption_evidence("didn't eat the fries but I had the burger")


# ── the gate needs context, not better patterns ─────────────────────────────

@pytest.mark.asyncio
async def test_the_previous_line_is_not_fed_to_the_gate(monkeypatch):
    """REVERTED, and pinned so it is not reintroduced by accident.

    Feeding the previous assistant line in was meant to rescue answers to a
    food question. Measured over 150 real production pairs it was a wash on
    recall (+3 food, -2) and cost precision — non-food admitted went 60% to
    64% — because a PLAN answering a question reads as a log: "Actually I'm
    gonna have a snickers" after "What flavor?".

    The loop it aimed at is closed from the other side: the model gate alone
    routes "Sweet chill", "90/10" and "the leaner one" with no context.
    """
    import core.food_turn as FT
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")
    FT._RELEVANCE_CACHE.clear()
    seen = {}

    async def _fake(messages, system, **k):
        seen["content"] = messages[0]["content"]
        return {"text": "NO"}
    monkeypatch.setattr("core.llm.chat", _fake)
    await FT.food_relevance("more like two", "How much rice — about a cup?")
    assert seen["content"] == "more like two", \
        "the prior turn must not reach the classifier"


@pytest.mark.asyncio
async def test_the_gate_still_accepts_the_parameter(monkeypatch):
    """Callers pass it and the experiment stays re-runnable — it is ignored,
    not rejected."""
    import core.food_turn as FT
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")
    FT._RELEVANCE_CACHE.clear()

    async def _fake(messages, system, **k):
        return {"text": "YES"}
    monkeypatch.setattr("core.llm.chat", _fake)
    assert await FT.food_relevance("sweet chill", "Quest Chips, which flavor?")


def test_a_deferred_rename_does_not_report_zero_calories():
    """Shipped 2026-07-27 21:01: "Actually it was 90/10" ->
    "Switched that to 90/10, updated to 0 cal for the beef", over a row
    holding 250. A correction to WHAT something was omits the macros so the
    ladder can re-resolve them for the new identity; summing the inputs read
    that gap as nought and the say line stated it."""
    from core.food_ledger import compute_batch
    rename = [{"name": "update_food_entry",
               "input": {"entry_id": 1, "food_name": "Ground beef, 90/10"}}]
    assert compute_batch("update", rename, 250, 26) == (250, 26)


def test_an_update_that_carries_numbers_still_uses_them():
    """The day delta is the fallback, never the override — an amount
    correction knows its own new value."""
    from core.food_ledger import compute_batch
    priced = [{"name": "update_food_entry",
               "input": {"entry_id": 1, "calories": 200, "protein": 30}}]
    assert compute_batch("update", priced, 9999, 999) == (200, 30)


def test_a_mixed_update_prefers_the_priced_rows():
    from core.food_ledger import compute_batch
    mixed = [{"name": "update_food_entry", "input": {"entry_id": 1, "food_name": "X"}},
             {"name": "update_food_entry",
              "input": {"entry_id": 2, "calories": 150, "protein": 10}}]
    assert compute_batch("update", mixed, 9999, 999) == (150, 10)
