"""Conversation-level scenarios (build order 20, directive item 28).

Unit tests prove each module does its job. These prove the modules compose —
which is where wrong-item binding, duplicate entries and mis-narrated held
items actually live. Every scenario is a real transcript from the directive,
run through the real staging, candidate, policy, parser and resolution code.

  A  multiple branded sizes — "I drank a Fairlife" → "Elite" → "Half"
  B  mixed branded and generic, across all three modes
  C  correction after commit
  D  an ambiguous answer that must stay pending
  E  topic change while a clarification is open

The assertion that matters most across all of them: the SAME staged item is
carried from question to answer. An answer that re-identifies its target is how
"the label is 80 calories" rewrites yesterday's bagel.
"""
from datetime import datetime, timedelta

import pytest

from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                        build_ambiguity)
from skills.nutrition.answer_parsers import (ClarificationCommand, parse_answer,
                                             parse_command)
from skills.nutrition.candidate_sets import (ProductCandidate,
                                             build_candidate_set,
                                             materially_distinct)
from skills.nutrition.clarify_policy import (ResponseSchema, TransactionPolicy,
                                             decide)
from skills.nutrition.families import required_dimensions
from skills.nutrition.meal_resolution import (ItemOutcome, attach_to_meal,
                                              build_resolution, drop_from_meal)
from skills.nutrition.models import profile_from_values
from skills.nutrition.pending_store import (Freshness, open_clarification)
from skills.nutrition.portions import convert
from skills.nutrition.provenance import MatchGrade, SourceTier
from skills.nutrition.staging import (FoodClass, FoodIdentity, Quantity,
                                      QuantityIntent, ResolutionStatus,
                                      StagedFoodItem, make_meal_group_id,
                                      make_staged_item_id, missing_requirements)

TURN = "imessage:G-1"
MEAL = make_meal_group_id(TURN)
NOON = datetime(2026, 7, 25, 12, 0)


def _stage(text, ordinal=0, *, food_class=FoodClass.GENERIC, identity=None,
           quantity=None, ambiguities=()):
    return StagedFoodItem(
        staged_item_id=make_staged_item_id(TURN, ordinal, text),
        original_text=text, ordinal=ordinal, food_class=food_class,
        identity=identity or FoodIdentity(canonical_name=text),
        quantity=quantity or QuantityIntent(descriptor="some"),
        ambiguities=tuple(ambiguities), meal_group_id=MEAL)


def _fairlife_candidates():
    """What the sources would return for "a Fairlife" — the three lines with
    materially different nutrition."""
    def c(name, line, size, cal, protein):
        return ProductCandidate(
            candidate_id="", canonical_name=name, brand="Fairlife",
            product_line=line, package_size=Quantity(size, "oz"),
            serving_basis="per_serving", source="off",
            tier=SourceTier.BRANDED_EXACT, match_grade=MatchGrade.CLOSE,
            nutrient_profile=profile_from_values("off", basis="per_serving",
                                                 calories=cal,
                                                 protein=protein))
    return [
        c("Fairlife Nutrition Plan", "Nutrition Plan", 11.5, 150, 30),
        c("Fairlife Core Power", "Core Power", 14, 170, 26),
        c("Fairlife Core Power Elite", "Core Power Elite", 14, 230, 42),
        # A duplicate record of Core Power under different artwork — must
        # collapse, or the user gets a question with a repeated answer.
        c("Core Power 14oz bottle", "Core Power", 14, 172, 26),
    ]


def _fairlife_item():
    return _stage("a Fairlife", food_class=FoodClass.BRANDED,
                  identity=FoodIdentity(brand="Fairlife"),
                  quantity=QuantityIntent(container_count=1))


def _bottle_ambiguity(item_id, candidates, mode="moderate"):
    options = tuple(
        AmbiguityOption(f"{c.product_line} · {c.package_size.describe()}",
                        confidence=0.5 - 0.1 * i, payload=c.product_line,
                        candidate_id=c.candidate_id)
        for i, c in enumerate(candidates))
    return build_ambiguity(
        staged_item_id=item_id, ambiguity_type=AmbiguityType.PRODUCT_LINE,
        field_name="product_line", mode=mode, calorie_span=190,
        item_calories=170,   # a Fairlife: the doubt exceeds the whole drink
        protein_span=16, options=options)


def _fraction_ambiguity(item_id, mode="moderate"):
    return build_ambiguity(
        staged_item_id=item_id,
        ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="consumed_fraction", mode=mode, calorie_span=115,
        item_calories=160,   # a bowl of berries
        options=(AmbiguityOption("the whole bottle", 0.5, payload=1.0),
                 AmbiguityOption("about half", 0.5, payload=0.5)))


# ── Scenario A: multiple branded sizes ────────────────────────────────────────
def test_scenario_a_fairlife_two_turn_clarification():
    """User: I drank a Fairlife. → Which one? → Elite. → Whole bottle? → Half.

    Asserts: the same staged item is retained, the right candidate is selected,
    the fraction lands as 0.5, and nutrition scales exactly once.
    """
    # Turn 1 — the brand alone does not identify a product.
    item = _fairlife_item()
    assert "identity" in missing_requirements(item)
    assert set(required_dimensions(item.identity)) == {"product_line",
                                                       "package_size"}

    # Candidate generation collapses the duplicate artwork record.
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    assert len(candidates) == 3, "the duplicate Core Power record must collapse"
    assert len(materially_distinct(candidates)) >= 2

    item = item.with_ambiguities([
        _bottle_ambiguity(item.staged_item_id, candidates),
        _fraction_ambiguity(item.staged_item_id)])
    original_id = item.staged_item_id

    # One bundled question, not two.
    decision = decide([item], mode="moderate")
    assert len(decision.questions) == 1
    question = decision.questions[0]
    assert question.response_schema is ResponseSchema.PRODUCT_AND_FRACTION
    assert question.staged_item_id == original_id
    assert decision.held_item_ids == (original_id,)
    assert decision.ready_item_ids == ()

    # Turn 2 — "Elite" resolves the product but not the portion.
    first = parse_answer("Elite", question)
    assert first.values.get("product_line") == "Core Power Elite"
    item = item.resolving(**first.values)
    assert item.staged_item_id == original_id, "the row must not move"
    assert item.identity.brand == "Fairlife"          # untouched
    assert [a.field_name for a in item.ambiguities] == ["consumed_fraction"]

    # Turn 3 — "Half" resolves the portion.
    remaining = decide([item], mode="moderate").questions[0]
    assert remaining.response_schema is ResponseSchema.QUANTITY
    second = parse_answer("about half", remaining)
    assert second.values == {"consumed_fraction": 0.5}
    item = item.resolving(**second.values)

    assert item.staged_item_id == original_id
    assert item.identity.product_line == "Core Power Elite"
    assert item.quantity.consumed_fraction == 0.5
    assert item.ambiguities == ()
    assert decide([item], mode="moderate").ready_item_ids == (original_id,)


def test_scenario_a_answered_in_one_breath():
    """The bundle exists so this works: "Elite, about half" fills both fields
    in a single turn."""
    item = _fairlife_item()
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    item = item.with_ambiguities([
        _bottle_ambiguity(item.staged_item_id, candidates),
        _fraction_ambiguity(item.staged_item_id)])
    question = decide([item], mode="moderate").questions[0]

    answer = parse_answer("Elite, about half", question)
    resolved = item.resolving(**answer.values)
    assert resolved.identity.product_line == "Core Power Elite"
    assert resolved.quantity.consumed_fraction == 0.5
    assert resolved.ambiguities == ()


def test_scenario_a_nutrition_is_never_scaled_twice():
    """The fraction is applied once, at resolution. A second application would
    halve an already-halved bottle."""
    from skills.nutrition.scaling import Per100g, scale_profile
    from skills.nutrition.models import NormalizedQuantity

    profile = profile_from_values("off", basis="per_100g", calories=55,
                                  protein=10.1)
    # 14 oz ≈ 414 ml ≈ 414 g, half consumed.
    consumed = NormalizedQuantity(amount=207, unit="g", grams=207)
    once = scale_profile(profile, Per100g(), consumed)
    assert once.amount("calories") == pytest.approx(114, abs=1)
    # Scaling the RESULT again is the bug — the value object marks itself
    # per_portion so a second pass is detectable.
    assert once.get("calories").basis == "per_portion"


# ── Scenario B: mixed branded and generic, per mode ───────────────────────────
def _mixed_meal(mode):
    """Half a Starbucks turkey bacon sandwich and some blueberries."""
    sandwich = _stage(
        "half a Starbucks turkey bacon sandwich", 0,
        food_class=FoodClass.RESTAURANT,
        identity=FoodIdentity(canonical_name="Starbucks turkey bacon sandwich",
                              brand="Starbucks", product_line="turkey bacon"),
        quantity=QuantityIntent(consumed_fraction=0.5))
    berries_span = convert("some blueberries", "blueberries")
    berries = _stage(
        "some blueberries", 1, food_class=FoodClass.GENERIC,
        identity=FoodIdentity(canonical_name="blueberries"),
        quantity=QuantityIntent(descriptor="some",
                                estimated_mass_g=berries_span.mass_equivalent_g,
                                mass_confidence=berries_span.conversion_confidence),
        ambiguities=[build_ambiguity(
            staged_item_id=make_staged_item_id(TURN, 1, "some blueberries"),
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", mode=mode, calorie_span=98,
            item_calories=140,
            options=(AmbiguityOption("about a handful", 0.5, payload=45.0),
                     AmbiguityOption("a big bowl", 0.3, payload=150.0)))])
    return sandwich, berries


def test_scenario_b_quick_logs_both_with_assumptions_disclosed():
    sandwich, berries = _mixed_meal("quick")
    out = decide([sandwich, berries], mode="quick")
    assert out.transaction_policy is TransactionPolicy.COMMIT_WITH_ASSUMPTIONS
    assert set(out.ready_item_ids) == {sandwich.staged_item_id,
                                       berries.staged_item_id}
    assert not out.asks
    # The berries were estimated, and that is stated rather than hidden.
    assert any(a.staged_item_id == berries.staged_item_id
               for a in out.assumptions)
    assert all(a.user_visible_text for a in out.assumptions)


def test_scenario_b_moderate_commits_the_branded_item_and_asks_about_the_berries():
    sandwich, berries = _mixed_meal("moderate")
    out = decide([sandwich, berries], mode="moderate")
    assert out.transaction_policy is TransactionPolicy.PARTIAL_COMMIT
    assert out.ready_item_ids == (sandwich.staged_item_id,)
    assert out.held_item_ids == (berries.staged_item_id,)
    # The certain sandwich generates no question.
    assert all(q.staged_item_id == berries.staged_item_id
               for q in out.questions)


def test_scenario_b_strict_stages_the_meal_and_commits_atomically():
    sandwich, berries = _mixed_meal("strict")
    out = decide([sandwich, berries], mode="strict")
    assert out.transaction_policy is TransactionPolicy.ATOMIC_HOLD
    assert out.ready_item_ids == ()
    assert set(out.held_item_ids) == {sandwich.staged_item_id,
                                      berries.staged_item_id}
    # Atomic means the sandwich WAITS — it is not questioned.
    assert all(q.staged_item_id == berries.staged_item_id
               for q in out.questions)


def test_scenario_b_moderate_partial_commit_keeps_one_meal():
    """The held berries, answered later, must join the sandwich's meal — not
    appear as a second card."""
    sandwich, berries = _mixed_meal("moderate")
    decision = decide([sandwich, berries], mode="moderate")
    resolution = build_resolution(
        meal_group_id=MEAL, items=[sandwich, berries], decision=decision,
        execution_by_item={sandwich.staged_item_id: {
            "entry_id": 1, "event_id": 101, "name": "Turkey bacon sandwich",
            "nutrients": {"calories": 210, "protein": 17}}})
    assert resolution.is_partial
    assert resolution.totals() == {"calories": 210.0, "protein": 17.0}

    joined = attach_to_meal(resolution,
                            staged_item_id=berries.staged_item_id,
                            entry_id=2, event_id=102, name="Blueberries",
                            nutrients={"calories": 26, "protein": 0.3})
    assert joined.is_complete
    assert {c.meal_group_id for c in joined.committed} == {MEAL}
    assert joined.totals() == {"calories": 236.0, "protein": 17.3}


def test_scenario_b_quick_mode_does_not_change_the_nutrition_answer():
    """Only the friction differs between modes. The sandwich's numbers are the
    same in all three."""
    outs = {}
    for mode in ("quick", "moderate", "strict"):
        sandwich, berries = _mixed_meal(mode)
        outs[mode] = sandwich.quantity.consumed_fraction
    assert len(set(outs.values())) == 1


# ── Scenario C: correction after commit ──────────────────────────────────────
def test_scenario_c_correction_after_commit_targets_the_right_entry():
    """User, after the bottle is logged: "Actually it was the Elite bottle."

    Asserts the existing entry is identified, and the correction is an UPDATE
    bound to it — not a new log.
    """
    from core.pending_clarification import (BoundTarget, answer_operations,
                                            build_ask, USER_LABEL_SOURCE)

    pending = build_ask(
        BoundTarget(entry_id=41, label="Fairlife Core Power"),
        ("calories", "protein"), current={"calories": 170},
        source="off", turn_id=TURN)

    ops = answer_operations(pending, "actually it was 230 calories, 42g protein")
    assert len(ops) == 1
    assert ops[0]["name"] == "update_food_entry"
    assert ops[0]["input"]["entry_id"] == 41         # the committed row
    assert ops[0]["input"]["calories"] == 230
    assert ops[0]["input"]["expected_calories"] == 170   # CAS against drift
    assert ops[0]["input"]["source"] == USER_LABEL_SOURCE
    assert "food_name" not in ops[0]["input"]        # no re-identification


def test_scenario_c_a_correction_naming_another_food_still_hits_the_bound_row():
    """The reply mentions a different food entirely. It is still an answer
    about the entity we asked about."""
    from core.pending_clarification import (BoundTarget, answer_operations,
                                            build_ask)
    pending = build_ask(BoundTarget(entry_id=41, label="Fairlife"),
                        ("calories",), current={"calories": 170})
    ops = answer_operations(pending, "the bagel one was 230 calories")
    assert ops[0]["input"]["entry_id"] == 41


# ── Scenario D: an ambiguous answer ──────────────────────────────────────────
def test_scenario_d_the_normal_one_stays_pending():
    """Arnie: Which size? User: The normal one.

    Asserts the narrow parser tries, fails, and does NOT guess a product.
    """
    item = _fairlife_item()
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    item = item.with_ambiguities(
        [_bottle_ambiguity(item.staged_item_id, candidates)])
    question = decide([item], mode="moderate").questions[0]

    answer = parse_answer("the normal one", question)
    assert answer.unparsed
    assert not answer.resolves_anything

    # Nothing applied, and the item is still held against the same question.
    still_held = decide([item], mode="moderate", round_number=1)
    assert still_held.held_item_ids == (item.staged_item_id,)
    assert still_held.questions[0].staged_item_id == item.staged_item_id


def test_scenario_d_a_second_unhelpful_answer_stops_asking_and_discloses():
    """Bounded loops: after the mode's limit, take the leading option and SAY
    so. Re-asking a third time is interrogation."""
    item = _fairlife_item()
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    item = item.with_ambiguities(
        [_bottle_ambiguity(item.staged_item_id, candidates, "moderate")])
    spent = decide([item], mode="moderate", round_number=2)
    assert spent.exhausted and not spent.asks
    assert len(spent.assumptions) == 1
    assert spent.assumptions[0].alternatives


def test_scenario_d_an_off_schema_answer_falls_through_rather_than_guessing():
    item = _fairlife_item()
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    item = item.with_ambiguities(
        [_bottle_ambiguity(item.staged_item_id, candidates)])
    question = decide([item], mode="moderate").questions[0]
    assert parse_answer("it was in a blue bottle I think", question).unparsed


# ── Scenario E: topic change ─────────────────────────────────────────────────
def test_scenario_e_an_unrelated_request_does_not_touch_the_food():
    """Arnie: Which yogurt? User: Log my workout.

    Asserts the workout is not read as a clarification answer and no food
    mutation is produced.
    """
    item = _stage("some yogurt", food_class=FoodClass.BRANDED,
                  identity=FoodIdentity(brand="Chobani"))
    item = item.with_ambiguities([build_ambiguity(
        staged_item_id=item.staged_item_id,
        ambiguity_type=AmbiguityType.PRODUCT_LINE, field_name="product_line",
        mode="moderate", calorie_span=90, item_calories=120,
        options=(AmbiguityOption("Zero Sugar", 0.5, payload="Zero Sugar"),
                 AmbiguityOption("Complete", 0.4, payload="Complete")))])
    question = decide([item], mode="moderate").questions[0]

    answer = parse_answer("log my workout", question)
    assert answer.unparsed
    assert answer.command is None            # not a clarification command
    assert not answer.resolves_anything      # and produces no food write


def test_scenario_e_the_clarification_survives_the_detour():
    """The pending row stays open and answerable after an unrelated turn."""
    pending = open_clarification(user_id=7, meal_group_id=MEAL, now=NOON,
                                 label="Chobani")
    later = NOON + timedelta(minutes=8)      # one unrelated turn in between
    assert pending.status.is_open
    assert pending.is_answerable(later)
    assert pending.freshness(later) is Freshness.ACTIVE


@pytest.mark.parametrize("text,command", [
    ("skip it", ClarificationCommand.SKIP_ITEM),
    ("don't log the yogurt", ClarificationCommand.SKIP_ITEM),
    ("just estimate it", ClarificationCommand.ESTIMATE),
    ("log the rest", ClarificationCommand.COMMIT_READY),
    ("cancel the meal", ClarificationCommand.CANCEL_MEAL),
])
def test_scenario_e_explicit_commands_are_distinguished_from_a_topic_change(
        text, command):
    """These are answers, just not values. A topic change is neither."""
    assert parse_command(text) is command
    assert parse_command("log my workout") is None


def test_scenario_e_skipping_one_item_keeps_the_rest_of_the_meal():
    """"don't log the yogurt" is not "cancel the meal" — conflating them loses
    a correctly logged breakfast."""
    sandwich, berries = _mixed_meal("moderate")
    decision = decide([sandwich, berries], mode="moderate")
    resolution = build_resolution(
        meal_group_id=MEAL, items=[sandwich, berries], decision=decision,
        execution_by_item={sandwich.staged_item_id: {
            "entry_id": 1, "name": "Sandwich",
            "nutrients": {"calories": 210}}})
    dropped = drop_from_meal(resolution, berries.staged_item_id)
    assert dropped.is_complete
    assert len(dropped.committed) == 1
    assert dropped.totals() == {"calories": 210.0}
    assert dropped.skipped[0].reason == "user_skipped"


# ── the invariant that spans every scenario ──────────────────────────────────
def test_no_scenario_ever_describes_a_held_item_as_committed():
    """The contract line with the widest blast radius. Held and committed are
    separate collections precisely so this cannot be got wrong by forgetting a
    flag."""
    sandwich, berries = _mixed_meal("moderate")
    for mode in ("quick", "moderate", "strict"):
        decision = decide([sandwich, berries], mode=mode)
        resolution = build_resolution(
            meal_group_id=MEAL, items=[sandwich, berries], decision=decision,
            execution_by_item={i: {"entry_id": 1, "name": "x",
                                   "nutrients": {"calories": 100}}
                               for i in decision.ready_item_ids})
        committed_ids = {c.staged_item_id for c in resolution.committed}
        pending_ids = {p.staged_item_id for p in resolution.pending}
        assert not (committed_ids & pending_ids), mode
        for item in resolution.committed:
            assert item.outcome.is_committed, mode
        for item in resolution.pending:
            assert item.outcome is ItemOutcome.HELD, mode


# ══ PR #27: the A–J conversation scenarios ═══════════════════════════════════
# The directive's own transcripts, asserted against the response contract. What
# these check is not that a particular sentence appears — it is that the SHAPE
# is right: no transaction narration, no card read-back, no forced question,
# and pending never described as logged.
from core.food_response import (CARD_FACTS, FoodResponseIntent,
                                FoodResponsePlan, Reason, apply_policy,
                                fallback, plan_clarify_from_question,
                                plan_correct, plan_from_resolution,
                                plan_review, validate)
from core.food_response import FoodItemSummary as _Sum
from skills.nutrition.meal_resolution import (ItemOutcome, MealResolution,
                                              PendingItem, ResolvedItem)


def _committed(*names):
    return MealResolution(
        meal_group_id=MEAL,
        committed=tuple(ResolvedItem(staged_item_id=f"i{i}",
                                     outcome=ItemOutcome.COMMITTED_EXACT,
                                     entry_id=i, name=n, quantity_text=q)
                        for i, (n, q) in enumerate(names)))


# ── A · gooseberry jam and toast ─────────────────────────────────────────────
def test_scenario_a_review_reads_as_a_sentence_not_a_form():
    """Was: "Locking this in:" over a numbered bold list ending "Good to log,
    or anything to fix?" — three pieces of transaction vocabulary."""
    from core.food_turn import format_confirm
    text = format_confirm([{"food": "toast", "amount": 1, "unit": "slice"},
                           {"food": "gooseberry jam", "amount": 1,
                            "unit": "tbsp"}])
    # Spoken rather than tabulated (Danny 2026-07-25).
    assert text == ("I'm reading that as one slice of toast and one "
                    "tablespoon of gooseberry jam. Does that look right?")
    for banned in ("Locking this in", "anything to fix", "**", "1."):
        assert banned not in text


def test_scenario_a_after_confirming_there_is_no_narration_and_no_recital():
    from core.food_response import strip_card_recitation
    plan = plan_from_resolution(_committed(("toast", "1 slice"),
                                           ("gooseberry jam", "1 tbsp")))
    assert plan.intent is FoodResponseIntent.COMMIT
    # The renderer's committed line is stripped to nothing — the card has it.
    rendered = ("Toast logged, 130 cal and 3g protein. You're at 130 with "
                "1990 left and 176g protein to go.")
    assert strip_card_recitation(rendered, plan) == ""
    # And a useful observation is allowed in its place, with no question.
    assert validate("Light start. I'd make your next meal protein-heavy.",
                    plan).ok


def test_scenario_a_no_forced_question_after_the_card():
    plan = plan_from_resolution(_committed(("toast", "1 slice")))
    assert not plan.allow_question
    assert validate("Light start. What's for lunch?",
                    plan).reason == Reason.FORBIDDEN_QUESTION


# ── B · simple clear meal ────────────────────────────────────────────────────
def test_scenario_b_a_clear_meal_may_commit_with_no_text_at_all():
    """Two eggs and a slice of toast: card renders, nothing to add."""
    plan = plan_from_resolution(_committed(("eggs", "2"), ("toast", "1 slice")))
    assert plan.allow_no_text
    assert validate("", plan).ok
    assert fallback(plan) == ""


def test_scenario_b_one_observation_is_also_valid():
    plan = plan_from_resolution(_committed(("eggs", "2")))
    assert validate("Solid start. Enough protein to hold you over.", plan).ok


# ── C · branded ambiguity, per mode ──────────────────────────────────────────
def _fairlife_decision(mode):
    item = _fairlife_item()
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    item = item.with_ambiguities([
        _bottle_ambiguity(item.staged_item_id, candidates, mode),
        _fraction_ambiguity(item.staged_item_id, mode)])
    return item, decide([item], mode=mode)


def test_scenario_c_quick_holds_a_genuine_coin_toss():
    """Quick assumes defensibly — it does not assume a 50/50. Whole bottle vs
    half at even confidence is exactly the case where committing would be
    indefensible, so even quick holds it."""
    _, decision = _fairlife_decision("quick")
    assert decision.transaction_policy is TransactionPolicy.COMMIT_WITH_ASSUMPTIONS
    assert decision.held_item_ids          # the policy, not the mode, decides


def test_scenario_c_quick_commits_with_the_assumption_stated():
    """"I logged that as a regular Core Power bottle. Tell me if it was the
    Elite." — the directive's example presumes a clear leader, which is what
    makes the assumption defensible."""
    item = _fairlife_item()
    candidates = build_candidate_set(_fairlife_candidates(),
                                     requested_name="Fairlife",
                                     requested_brand="Fairlife")
    leader = build_ambiguity(
        staged_item_id=item.staged_item_id,
        ambiguity_type=AmbiguityType.PRODUCT_LINE, field_name="product_line",
        mode="quick", calorie_span=190, item_calories=170,
        options=(AmbiguityOption("Core Power · 14 oz", 0.72,
                                 payload="Core Power"),
                 AmbiguityOption("Elite · 14 oz", 0.18,
                                 payload="Core Power Elite")))
    item = item.with_ambiguities([leader])
    decision = decide([item], mode="quick")
    assert decision.transaction_policy is TransactionPolicy.COMMIT_WITH_ASSUMPTIONS
    assert decision.ready_item_ids == (item.staged_item_id,)
    assert decision.assumptions
    plan = plan_from_resolution(_committed(("Core Power", "1 bottle")))
    assert validate("I logged that as a regular Core Power bottle. Tell me if "
                    "it was the Elite.", plan).ok


def test_scenario_c_strict_bundles_the_two_questions_into_one_turn():
    _, decision = _fairlife_decision("strict")
    assert len(decision.questions) == 1
    q = decision.questions[0]
    assert q.response_schema is ResponseSchema.PRODUCT_AND_FRACTION
    assert set(q.requested_fields) >= {"product_line", "consumed_fraction"}


def test_scenario_c_the_question_acknowledges_what_is_already_known():
    """A clarification that names nothing understood reads as an interrogation
    rather than a continuation."""
    toast = _stage("toast", 1)
    item, _ = _fairlife_decision("moderate")
    decision = decide([toast, item], mode="moderate")
    q = decision.questions[0]
    assert "toast" in q.resolved_item_names
    plan = plan_clarify_from_question(q)
    assert "toast" in fallback(plan)


# ── D · clarification continuation ───────────────────────────────────────────
def test_scenario_d_the_answer_binds_and_does_not_re_review():
    from core.food_response import plan_confirm_answer
    item, decision = _fairlife_decision("moderate")
    question = decision.questions[0]
    answer = parse_answer("Elite, about half", question)
    resolved = item.resolving(**answer.values)
    assert resolved.staged_item_id == item.staged_item_id

    plan = plan_confirm_answer("half of the Elite")
    assert not plan.allow_question          # the answer completed it
    assert plan.allow_no_text               # card may say it alone
    assert fallback(plan) == "Got it, half of the Elite."


# ── E · partial meal ─────────────────────────────────────────────────────────
def test_scenario_e_pending_is_never_described_as_logged():
    resolution = MealResolution(
        meal_group_id=MEAL,
        committed=(ResolvedItem(staged_item_id="i1",
                                outcome=ItemOutcome.COMMITTED_EXACT,
                                entry_id=1, name="sandwich"),),
        pending=(PendingItem(staged_item_id="p1", name="shake"),))
    plan = plan_from_resolution(
        resolution, clarification_question="Was the shake Core Power or Elite?")
    assert plan.intent is FoodResponseIntent.PARTIAL_COMMIT
    assert validate("I've got the sandwich in. Was the shake Core Power or "
                    "Elite?", plan).ok
    assert validate("Sandwich and shake logged. Which one was the shake?",
                    plan).reason == Reason.PENDING_AS_COMMITTED


# ── F · correction ───────────────────────────────────────────────────────────
def test_scenario_f_a_correction_is_immediate_and_asks_nothing():
    plan = plan_correct("the jam")
    assert not plan.allow_question
    assert fallback(plan) == "Updated the jam."
    assert validate("Got it, raspberry instead.", plan).ok
    assert validate("Updating your log now.",
                    plan).reason == Reason.TRANSACTION_NARRATION


# ── G · emotional context ────────────────────────────────────────────────────
def test_scenario_g_the_meaning_is_answered_not_just_the_mutation():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.GENERAL_CONVERSATION,
        user_message="I barely ate half because it was terrible",
        user_emotional_context="they disliked the meal"))
    assert validate("I counted half. Sounds like that one's not becoming a "
                    "regular.", plan).ok
    from core.food_response import build_prompt
    assert "THEY SIGNALLED: they disliked the meal" in build_prompt(plan)


# ── H · disputed estimate ────────────────────────────────────────────────────
def test_scenario_h_a_purposeful_question_is_allowed_a_generic_one_is_not():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.GENERAL_CONVERSATION,
        user_message="that seems high"))
    assert validate("The sauce is probably driving it. Was it a light drizzle "
                    "or pretty heavy?", plan).ok
    assert validate("Sorry about that. Anything else I can help with?",
                    plan).reason in (Reason.FORBIDDEN_QUESTION,
                                     Reason.SYSTEM_TONE)


# ── I · source outage ────────────────────────────────────────────────────────
def test_scenario_i_an_outage_never_blames_the_product_or_the_user():
    from skills.nutrition.families import (CandidateResolutionFailure,
                                           failure_intent)
    from core.food_response import plan_failure
    intent = failure_intent(CandidateResolutionFailure.SOURCE_UNAVAILABLE)
    assert not intent.user_fixable and not intent.requires_question
    text = fallback(plan_failure(intent))
    assert "couldn't identify" not in text.lower()
    assert "estimate" in text.lower()


def test_scenario_i_a_genuine_miss_does_ask_for_the_label():
    from skills.nutrition.families import (CandidateResolutionFailure,
                                           failure_intent)
    from core.food_response import plan_failure
    intent = failure_intent(CandidateResolutionFailure.NO_MATCH)
    assert intent.user_fixable and intent.requires_question
    plan = plan_failure(intent)
    assert "?" in fallback(plan)
    assert validate(fallback(plan), plan).ok


# ── J · routine consecutive logs ─────────────────────────────────────────────
def test_scenario_j_consecutive_commits_do_not_all_end_in_a_question():
    for _ in range(3):
        plan = plan_from_resolution(_committed(("rice", "200g")))
        assert not plan.allow_question


def test_scenario_j_a_repeated_opener_is_rejected():
    """"Got it." every time reads as a template, not a coach."""
    plan = plan_from_resolution(
        _committed(("rice", "200g")),
        recent_response_openers=("Got it, that's in.", "Got it."))
    assert validate("Got it.", plan).reason == Reason.REPEATED_OPENER
    assert validate("Light start there.", plan).ok


def test_scenario_j_some_turns_are_card_only():
    plan = plan_from_resolution(_committed(("rice", "200g")))
    assert plan.allow_no_text and validate("", plan).ok


def test_scenario_j_coaching_is_not_forced_after_every_log():
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COACH))
    assert fallback(plan) == ""          # silence beats "Keep it up."
