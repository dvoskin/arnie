"""The food response contract (directive 2026-07-25).

One place decides what a food turn may say; one place checks that what came
back obeyed it. Before this, confirmation copy lived in food_turn.py,
transaction narration in conversation.py, failure prose in families.py and
coaching in the model — four systems taking turns in one conversation.

The two rules under most of these tests:

  the card owns the facts — reciting them after it renders is duplication
  a question needs a purpose — ending every commit with one is not engagement
"""
import pytest

from core.food_response import (CARD_FACTS, CoachingOpportunity, arnie_voice,
                                FailureIntent, FoodItemSummary,
                                FoodResponseIntent, FoodResponsePlan, Reason,
                                apply_policy, build_prompt, compose, fallback,
                                mentions_unapproved_item, plan_clarify,
                                plan_clarify_from_question,
                                plan_confirm_answer, plan_correct,
                                REVIEW_OPENER, plan_failure, plan_from_resolution, plan_review,
                                plan_undo, validate)

def _leads_with_the_meal(text, *names):
    """The lead-in VARIES now — keyed on the meal AND the question, so two
    clarification rounds on one meal no longer open with the identical
    sentence. The contract is that it acknowledges what we understood before
    asking, not that it uses one exact phrase."""
    from core.food_response import _CLARIFY_LEADS, _REVIEW_LEADS
    heads = {l.split("{")[0].strip() for l in _CLARIFY_LEADS + _REVIEW_LEADS}
    assert any(text.startswith(h) for h in heads), text
    for n in names:
        assert n in text, (n, text)



def _items(*pairs):
    return tuple(FoodItemSummary(name=n, portion=p) for n, p in pairs)


def _commit_plan(**kw):
    base = dict(intent=FoodResponseIntent.COMMIT,
                committed_items=_items(("toast", "1 slice")),
                card_will_render=True, facts_visible_in_card=CARD_FACTS)
    base.update(kw)
    return apply_policy(FoodResponsePlan(**base))


# ── intent policy is deterministic, never model-chosen ────────────────────────
def test_a_commit_that_wrote_a_row_may_not_be_silent():
    """The card said the numbers. It did not say the message was heard.

    COMMIT's `allow_no_text` is still on the intent table — a COMMIT plan that
    committed nothing has nothing to name, and silence there is honest. What is
    withdrawn is silence on a turn that actually put a row in the log."""
    plan = _commit_plan()
    assert not plan.allow_no_text
    assert validate("", plan).reason == Reason.EMPTY_NOT_ALLOWED


def test_a_commit_that_wrote_nothing_keeps_its_silence():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT, card_will_render=True,
        facts_visible_in_card=CARD_FACTS))
    assert plan.allow_no_text
    assert validate("", plan).ok


def test_commit_forbids_a_question():
    """Ending every commit with a question is a system asking to be talked
    to."""
    plan = _commit_plan()
    assert not plan.allow_question
    assert validate("Nice. What are you having next?",
                    plan).reason == Reason.FORBIDDEN_QUESTION


def test_clarify_requires_one_and_allows_one():
    plan = plan_clarify(question="Which Fairlife bottle was it?")
    assert plan.requires_answer and plan.allow_question
    assert not validate("I've got the toast.", plan).ok
    assert validate("I've got the toast. Which Fairlife bottle was it?",
                    plan).ok


def test_undo_permits_no_question_and_no_silence():
    plan = plan_undo("the bagel update")
    assert not plan.allow_question and not plan.allow_no_text
    assert validate("", plan).reason == Reason.EMPTY_NOT_ALLOWED
    assert validate("Undid the bagel update.", plan).ok


def test_requires_answer_always_wins_over_the_intent_default():
    """A plan that must be answered has to be allowed to ask."""
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COMMIT,
                                         requires_answer=True))
    assert plan.allow_question and not plan.allow_no_text


# ── transaction narration ─────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Give me a moment. Logging all 2 now.",
    "Give me a moment. Logging it now.",
    "Processing that now.",
    "Working on it.",
    "Saving that now.",
    "Successfully logged your meal.",
    "Updating your log.",
    "One sec, calculating.",
])
def test_transaction_narration_is_rejected(text):
    """The exact shapes the live path used to emit. The system prompt already
    bans the MODEL from producing these and turn_health flags them as stalls —
    but the structured path emitted them deterministically, bypassing both."""
    assert validate(text, _commit_plan()).reason == Reason.TRANSACTION_NARRATION


@pytest.mark.parametrize("text", [
    "Please confirm whether the information is correct.",
    "Your food entry has been updated.",
    "Is there anything else I can help with?",
])
def test_system_register_is_rejected(text):
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.REVIEW,
                                         requires_answer=True))
    assert validate(text, plan).reason in (Reason.SYSTEM_TONE,
                                           Reason.TRANSACTION_NARRATION)


# ── the card owns the facts ───────────────────────────────────────────────────
def test_reciting_the_card_is_rejected():
    """The failure from the screenshot: a card, then a message repeating its
    contents back."""
    plan = _commit_plan()
    result = validate("Locked in, 130 calories and 3g protein.", plan)
    assert result.reason in (Reason.CARD_DUPLICATION,
                             Reason.TRANSACTION_NARRATION)
    assert validate("That's 130 calories and 3g protein.",
                    plan).reason == Reason.CARD_DUPLICATION


def test_a_number_serving_a_recommendation_is_allowed():
    """Not a blanket ban on digits. "I'd aim for 30-40g at lunch" does work
    that the card does not."""
    plan = _commit_plan()
    assert validate("Light start. I'd aim for 30-40g protein at lunch.",
                    plan).ok


def test_numbers_are_free_when_no_card_renders():
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COMMIT,
                                         card_will_render=False))
    assert validate("That's about 130 calories.", plan).ok


def test_an_interpretation_without_numbers_passes():
    plan = _commit_plan()
    assert validate("Light start. I'd make your next meal protein-heavy.",
                    plan).ok
    assert validate("That leaves you plenty of room for dinner.", plan).ok
    assert validate("Got it.", plan).ok


# ── pending is never described as committed ───────────────────────────────────
def test_a_held_item_may_be_named_but_not_called_logged():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.PARTIAL_COMMIT,
        committed_items=_items(("sandwich", "half")),
        pending_items=(FoodItemSummary(name="shake"),),
        clarification_question="Was it Core Power or Elite?",
        requires_answer=True))
    good = "I've got the sandwich in. Was the shake Core Power or Elite?"
    assert validate(good, plan).ok
    bad = "I've got the sandwich and shake logged. Was it Core Power or Elite?"
    assert validate(bad, plan).reason == Reason.PENDING_AS_COMMITTED


# ── length and coaching discipline ────────────────────────────────────────────
def test_a_verbose_response_is_rejected():
    plan = _commit_plan()
    long = ("Based on the nutritional information associated with the meal you "
            "have just logged it may be beneficial for you to prioritize "
            "protein during your next eating occasion because your current "
            "intake appears to be running somewhat below the target level.")
    assert validate(long, plan).reason == Reason.TOO_LONG


def test_an_item_list_is_not_counted_as_many_sentences():
    """A four-line review is one readable thing. Counting each line as a
    sentence would force prose that is harder to scan."""
    plan = plan_review(_items(("chicken shawarma", "4 oz"), ("rice", "1 cup"),
                              ("hummus", "2 tbsp"), ("pita", "half")))
    text = ("I've got:\nchicken shawarma, 4 oz\nrice, 1 cup\nhummus, 2 tbsp\n"
            "half a pita\n\nDoes that look right?")
    assert validate(text, plan).ok


def test_coaching_is_limited_to_one_recommendation():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COACH,
        coaching_opportunity=CoachingOpportunity(kind="low_protein")))
    assert validate("Protein is light so far, so lunch is the place to catch "
                    "up.", plan).ok
    assert validate("I'd get protein at lunch. You should also aim for more "
                    "fibre.", plan).reason == Reason.MULTIPLE_COACHING


# ── question quality ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("text", [
    "Got it. Anything else?",
    "Logged. What are you eating next?",
    "Done. How are you feeling?",
    "That's in. Does that make sense?",
])
def test_engagement_questions_are_rejected_even_where_questions_are_allowed(text):
    """A question earns its place by resolving something. These only ask to be
    talked to."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.GENERAL_CONVERSATION))
    assert validate(text, plan).reason == Reason.FORBIDDEN_QUESTION


def test_a_purposeful_question_passes():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.GENERAL_CONVERSATION))
    assert validate("The sauce is probably driving it. Was it a light drizzle "
                    "or pretty heavy?", plan).ok


# ── variation ─────────────────────────────────────────────────────────────────
def test_a_repeated_opener_is_rejected():
    """Across consecutive logs, "Got it." every time reads as a template."""
    plan = _commit_plan(recent_response_openers=("Got it, that's in.",
                                                 "Nice one."))
    assert validate("Got it.", plan).reason == Reason.REPEATED_OPENER
    assert validate("Light start there.", plan).ok


# ── invented items ────────────────────────────────────────────────────────────
def test_a_food_outside_the_plan_is_detectable():
    plan = _commit_plan()
    known = ("toast", "bacon", "eggs")
    assert mentions_unapproved_item("Nice, the bacon works there.", plan, known)
    assert not mentions_unapproved_item("Light start.", plan, known)


# ── deterministic fallbacks ───────────────────────────────────────────────────
def test_the_review_fallback_is_prose_for_a_simple_meal():
    """Was: "Locking this in:" over a numbered bold list ending "Good to log,
    or anything to fix?" — a form, not a coach checking something."""
    text = fallback(plan_review(_items(("toast", "1 slice"),
                                       ("gooseberry jam", "1 tbsp"))))
    # Spoken, not tabulated (Danny 2026-07-25). "1 slice toast" is a row from
    # the interpreter; "one slice of toast" is what a person says.
    _leads_with_the_meal(text, "one slice of toast",
                         "one tablespoon of gooseberry jam")
    assert text.endswith("Does that look right?"), text
    assert "Locking this in" not in text
    assert "anything to fix" not in text


def test_the_review_fallback_switches_to_lines_when_prose_stops_scanning():
    text = fallback(plan_review(_items(("chicken shawarma", "4 oz"),
                                       ("rice", "1 cup"), ("hummus", "2 tbsp"),
                                       ("pita", "half"))))
    # The opener VARIES now — one fixed sentence read as a template the
    # moment a user logged twice in a session. Still deterministic on the
    # meal, so the assertion is membership rather than identity.
    from core.food_response import _REVIEW_OPENERS
    assert any(text.startswith(o) for o in _REVIEW_OPENERS), text
    assert "• 4oz of chicken shawarma" in text
    # "all" because a list was rendered — it asks about the set, not one item.
    assert text.endswith("Does that all look right?")
    assert "1." not in text and "**" not in text     # no numbering, no bold


def test_the_commit_fallback_names_what_it_wrote():
    """It used to be silence, and silence is what shipped — see
    `test_a_commit_that_wrote_a_row_may_not_be_silent`. The figures still stay
    on the card."""
    text = fallback(_commit_plan())
    assert text == "Logged toast."


def test_the_coach_fallback_is_silence_not_generic_advice():
    """Omitting the message beats "Keep it up." — filler teaches the user to
    skip the text after the card."""
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COACH))
    assert fallback(plan) == ""


def test_the_clarify_fallback_acknowledges_context_before_asking():
    text = fallback(plan_clarify(question="Which Chobani yogurt was it?",
                                 resolved=_items(("toast", ""), ("fruit", ""))))
    _leads_with_the_meal(text, "toast", "fruit")
    assert text.endswith("Which Chobani yogurt was it?"), text


def test_the_partial_commit_fallback_never_implies_the_held_item_landed():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.PARTIAL_COMMIT,
        committed_items=_items(("sandwich", ""), ("blueberries", "")),
        pending_items=(FoodItemSummary(name="shake"),),
        clarification_question="Was the shake Core Power or Elite?",
        requires_answer=True))
    text = fallback(plan)
    assert "sandwich and blueberries in" in text
    assert validate(text, plan).ok


def test_correction_and_undo_fallbacks_are_immediate():
    assert fallback(plan_correct("the jam")) == "Updated the jam."
    assert fallback(plan_undo("the bagel update")) == "Undid the bagel update."


def test_the_failure_fallback_uses_the_approved_recovery_message():
    plan = plan_failure(FailureIntent(
        code="source_unavailable", user_fixable=False,
        recovery_action="offer an estimate or the label",
        approved_message="I can't verify that product right now. I can use a "
                         "reasonable estimate, or the label if you have it."))
    assert "can't verify" in fallback(plan)


# ── MealResolution is the only authority for committed state ──────────────────
class _Outcome(str):
    value = "committed_exact"


def _resolution(committed=(), pending=(), assumptions=()):
    from skills.nutrition.meal_resolution import (ItemOutcome, MealResolution,
                                                  PendingItem, ResolvedItem)
    return MealResolution(
        meal_group_id="meal_1",
        committed=tuple(ResolvedItem(staged_item_id=f"i{i}",
                                     outcome=ItemOutcome.COMMITTED_EXACT,
                                     entry_id=i, name=n, quantity_text=q)
                        for i, (n, q) in enumerate(committed)),
        pending=tuple(PendingItem(staged_item_id=f"p{i}", name=n)
                      for i, n in enumerate(pending)),
        assumptions=tuple(assumptions))


def test_a_fully_committed_meal_plans_as_commit():
    plan = plan_from_resolution(_resolution(committed=[("toast", "1 slice")]))
    assert plan.intent is FoodResponseIntent.COMMIT
    assert plan.card_will_render
    assert plan.facts_visible_in_card == CARD_FACTS
    assert not plan.allow_question


def test_a_mixed_meal_plans_as_partial_commit():
    plan = plan_from_resolution(
        _resolution(committed=[("sandwich", "half")], pending=["shake"]),
        clarification_question="Was the shake Core Power or Elite?")
    assert plan.intent is FoodResponseIntent.PARTIAL_COMMIT
    assert plan.requires_answer and plan.allow_question
    assert plan.unresolved_item.name == "shake"


def test_a_fully_held_meal_plans_as_clarify():
    plan = plan_from_resolution(_resolution(pending=["shake"]),
                                clarification_question="Which bottle?")
    assert plan.intent is FoodResponseIntent.CLARIFY
    assert not plan.card_will_render


def test_no_card_means_no_card_facts_are_suppressed():
    plan = plan_from_resolution(_resolution(pending=["shake"]))
    assert plan.facts_visible_in_card == frozenset()


# ── the prompt ────────────────────────────────────────────────────────────────
def test_the_prompt_marks_card_facts_as_off_limits():
    prompt = build_prompt(_commit_plan())
    assert "do not recite them" in prompt
    assert "ALREADY ON THE CARD" in prompt
    assert "no questions" in prompt


def test_the_prompt_distinguishes_an_outage_from_a_user_fixable_gap():
    outage = build_prompt(plan_failure(FailureIntent(
        code="source_unavailable", user_fixable=False,
        recovery_action="offer an estimate")))
    assert "Do not ask them to fix it" in outage
    fixable = build_prompt(plan_failure(FailureIntent(
        code="no_match", user_fixable=True, recovery_action="ask for the label",
        requires_question=True)))
    assert "user can resolve" in fixable


def test_the_prompt_carries_emotional_context():
    plan = _commit_plan(user_emotional_context="they disliked the meal")
    assert "THEY SIGNALLED: they disliked the meal" in build_prompt(plan)


def test_the_voice_prompt_bans_the_right_things():
    voice = arnie_voice()
    for phrase in ("Do not narrate internal operations",
                   "Do not repeat information marked as visible",
                   "Do not force a question",
                   "Do not praise routine logging"):
        assert phrase in voice


def test_the_food_lane_speaks_with_the_same_persona_as_every_other_turn():
    """There were two Arnies. This module carried its own 323-token voice and
    imported nothing from `core/prompts/arnie`, so a logged meal was written
    against a miniature persona with no bubble rules, no emoji policy and no
    register — while every other turn got the full one. A food reply that does
    not sound like the rest of the product is the symptom; two definitions of
    who Arnie is was the cause."""
    from core.prompts.arnie import IDENTITY, LANGUAGE, VOICE, EMOJI_SYSTEM
    voice = arnie_voice()
    for block in (IDENTITY, LANGUAGE, VOICE, EMOJI_SYSTEM):
        assert block in voice, "the shared persona must reach the food lane"
    # ...and the lane still adds what only it needs.
    assert "Do not add, alter, recompute" in voice


# ── composition ───────────────────────────────────────────────────────────────
def test_a_valid_generation_is_used_as_is():
    plan = _commit_plan()
    text, reason = compose(plan, lambda p: "Light start there.")
    assert text == "Light start there." and reason == Reason.OK


def test_an_invalid_generation_is_retried_then_falls_back():
    plan = plan_correct("the jam")
    attempts = {"n": 0}

    def _bad(prompt):
        attempts["n"] += 1
        return "Updating your log now."
    text, reason = compose(plan, _bad)
    assert attempts["n"] == 2                    # tried, told why, tried again
    assert reason == Reason.TRANSACTION_NARRATION
    assert text == "Updated the jam."            # deterministic, not procedural


def test_the_retry_is_told_what_it_broke():
    seen = []

    def _capture(prompt):
        seen.append(prompt)
        return "Give me a moment."
    compose(plan_correct("the jam"), _capture)
    assert "YOUR LAST ATTEMPT FAILED" in seen[-1]
    assert Reason.TRANSACTION_NARRATION in seen[-1]


def test_a_composer_that_raises_falls_back_rather_than_failing_the_turn():
    def _boom(prompt):
        raise RuntimeError("model down")
    text, _ = compose(plan_undo("that log"), _boom)
    assert text == "Undid that log."


def test_no_composer_means_the_deterministic_text():
    text, reason = compose(plan_correct("the jam"))
    assert text == "Updated the jam." and reason == "no_composer"


def test_a_composer_returning_nothing_on_a_write_gets_the_subject_back():
    """COACH may be silent; a turn that wrote a row may not. An empty composer
    now fails its own plan and the deterministic floor names the food."""
    text, reason = compose(_commit_plan(), lambda p: "")
    assert text == "Logged toast."
    assert reason == Reason.EMPTY_NOT_ALLOWED


# ── the invariant that catches fallback drift ─────────────────────────────────
def _every_intent_plan():
    """One plan per intent, built the way a caller would."""
    return {
        FoodResponseIntent.REVIEW: plan_review(_items(("toast", "1 slice"))),
        FoodResponseIntent.CLARIFY: plan_clarify(
            question=None, unresolved=FoodItemSummary(name="shake")),
        FoodResponseIntent.CONFIRM_ANSWER: plan_confirm_answer(
            "half of the Elite"),
        FoodResponseIntent.COMMIT: _commit_plan(),
        FoodResponseIntent.PARTIAL_COMMIT: apply_policy(FoodResponsePlan(
            intent=FoodResponseIntent.PARTIAL_COMMIT,
            committed_items=_items(("sandwich", "")),
            pending_items=(FoodItemSummary(name="shake"),))),
        FoodResponseIntent.CORRECT: plan_correct("the jam"),
        FoodResponseIntent.UNDO: plan_undo("the bagel update"),
        FoodResponseIntent.FAILURE: plan_failure(FailureIntent(
            code="no_match", user_fixable=True,
            recovery_action="ask for the label",
            approved_message="I couldn't identify that exact product. The "
                             "label calories and protein would be enough.")),
        FoodResponseIntent.COACH: apply_policy(FoodResponsePlan(
            intent=FoodResponseIntent.COACH)),
        FoodResponseIntent.GENERAL_CONVERSATION: apply_policy(FoodResponsePlan(
            intent=FoodResponseIntent.GENERAL_CONVERSATION)),
    }


def test_the_intent_table_covers_every_intent():
    """Enumerated by hand, this table missed GENERAL_CONVERSATION — whose
    fallback was the empty string against a plan that forbids one, so on the
    turn where the composer had already failed twice the user got nothing.

    `compose()` returns a fallback WITHOUT re-validating it, so nothing else
    would have caught it. Exhaustive over the enum now: a new intent cannot be
    added without a fallback that satisfies its own plan.
    """
    assert set(_every_intent_plan()) == set(FoodResponseIntent)


@pytest.mark.parametrize("intent,plan", list(_every_intent_plan().items()),
                         ids=lambda v: getattr(v, "value", ""))
def test_every_fallback_satisfies_its_own_plan(intent, plan):
    """compose() returns a fallback WITHOUT re-validating it, so a fallback that
    violates its own plan ships unchecked. This is the guard: a CLARIFY fallback
    with no question, or a CORRECT fallback that narrates the write, would be
    emitted silently otherwise."""
    text = fallback(plan)
    result = validate(text, plan)
    assert result.ok, f"{intent.value} fallback {text!r} → {result.reason}"


def test_a_clarify_fallback_names_the_item_it_is_asking_about():
    """"Which one was it?" names nothing — the vague question this whole layer
    exists to avoid. It must reach for the held item's name."""
    from_unresolved = fallback(plan_clarify(
        question=None, unresolved=FoodItemSummary(name="shake")))
    assert "shake" in from_unresolved

    from_pending = fallback(apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        pending_items=(FoodItemSummary(name="yogurt"),))))
    assert "yogurt" in from_pending


def test_a_partial_commit_fallback_names_the_held_item():
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.PARTIAL_COMMIT,
        committed_items=_items(("sandwich", "")),
        pending_items=(FoodItemSummary(name="shake"),)))
    text = fallback(plan)
    assert "shake" in text and "one item" not in text


def test_a_long_committed_list_is_honest_about_overflow():
    """Silent truncation is how "A, B and C in" gets said about five committed
    items — a miscount the user cannot see."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.PARTIAL_COMMIT,
        committed_items=_items(("eggs", ""), ("toast", ""), ("jam", ""),
                               ("coffee", ""), ("banana", "")),
        pending_items=(FoodItemSummary(name="shake"),)))
    text = fallback(plan)
    assert "2 more" in text


def test_a_quantities_only_card_does_not_make_calories_a_duplicate():
    """facts_visible_in_card granularity has to mean something. A card showing
    only portions leaves the nutrition unsaid, so saying it is not repetition."""
    plan = apply_policy(FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT, card_will_render=True,
        facts_visible_in_card=frozenset({"quantities"})))
    assert validate("That's about 300 calories.", plan).ok


def test_the_directive_approved_quick_disclosure_survives_the_filter():
    """A near-miss worth pinning: "I logged that as a regular Core Power
    bottle" is the approved QUICK-mode assumption disclosure, and the
    transaction-narration filter must not eat it."""
    plan = _commit_plan()
    assert validate("I logged that as a regular Core Power bottle. Tell me if "
                    "it was the Elite.", plan).ok


def test_an_invented_food_is_rejected_when_a_vocabulary_is_supplied():
    plan = _commit_plan(known_foods=("toast", "bacon"))
    assert validate("Nice, the bacon works there.",
                    plan).reason == Reason.INVENTED_ITEM
    assert validate("Light start.", plan).ok


# ── stripping the card read-back (the screenshot failure) ─────────────────────
def _card_plan(**kw):
    base = dict(intent=FoodResponseIntent.COMMIT, card_will_render=True,
                facts_visible_in_card=CARD_FACTS)
    base.update(kw)
    return apply_policy(FoodResponsePlan(**base))


def test_pure_recitation_becomes_silence_when_a_card_renders():
    """The screenshot: a card, then "130 calories and 3g protein, 1,990
    remaining" underneath it."""
    from core.food_response import strip_card_recitation
    text = ("Toast logged, 130 cal and 3g protein. You're at 130 with 1990 "
            "left and 176g protein to go.")
    assert strip_card_recitation(text, _card_plan()) == ""


def test_nothing_is_stripped_when_no_card_renders():
    """Telegram has no card frame — there the same sentences are the ONLY
    confirmation the user gets, so stripping them would lose the reply."""
    from core.food_response import strip_card_recitation
    text = "Rice logged, 200 cal and 5g protein. You're at 1500."
    plan = apply_policy(FoodResponsePlan(intent=FoodResponseIntent.COMMIT))
    assert strip_card_recitation(text, plan) == text


def test_a_vetted_follow_up_bubble_survives_the_strip():
    """Each ||| bubble is judged on its own, so the whitelisted coaching
    follow-up is never collateral damage."""
    from core.food_response import strip_card_recitation
    text = ("Toast logged, 130 cal and 3g protein. You're at 130.|||Want me to "
            "save that as one of your regulars?")
    out = strip_card_recitation(text, _card_plan())
    assert out == "Want me to save that as one of your regulars?"


def test_a_recommendation_survives_alongside_a_stripped_recitation():
    from core.food_response import strip_card_recitation
    text = "Rice logged, 200 cal. I'd aim for 30-40g protein at lunch."
    assert strip_card_recitation(text, _card_plan()) == \
        "I'd aim for 30-40g protein at lunch."


def test_a_confirmation_without_numbers_is_left_alone():
    """"Took the fries off the board" is not recitation — the card does not say
    it, and a delete has no macros to repeat."""
    from core.food_response import strip_card_recitation
    text = "Took the fries off the board."
    assert strip_card_recitation(text, _card_plan()) == text


def test_the_refusal_notice_survives():
    """A write the board refused must still be named — that bubble is the
    honest part of the reply.

    Built from the REAL producer rather than a copy of its output: as a frozen
    string this passed while the notice it was standing in for had changed
    wording, so it would not have noticed the live notice being stripped.
    """
    from core.food_ledger import build_failure_notice
    from core.food_response import strip_card_recitation
    notice = build_failure_notice([("fries", "it didn't save")])
    text = f"Rice logged, 200 cal and 5g protein. You're at 1500.|||{notice}"
    out = strip_card_recitation(text, _card_plan())
    assert notice in out, out
    assert "200 cal" not in out


def test_stripping_leaves_a_result_that_passes_validation():
    """The point of the exercise: what survives must itself obey the plan."""
    from core.food_response import strip_card_recitation
    plan = _card_plan()
    for text in ("Toast logged, 130 cal and 3g protein. You're at 130.",
                 "Rice logged, 200 cal. I'd aim for 30-40g at lunch.",
                 "Took the fries off the board."):
        assert validate(strip_card_recitation(text, plan), plan).ok, text


# ── PR #27: semantic plans, typed failures, the live composer ────────────────
def _question(**kw):
    from skills.nutrition.clarify_policy import (ClarificationOption,
                                                 ClarificationQuestion,
                                                 ResponseSchema)
    base = dict(question_id="q1", staged_item_id="i1",
                requested_fields=("product_line",),
                prompt="Which Chobani yogurt was it?",
                response_schema=ResponseSchema.PRODUCT_SELECTION,
                options=(ClarificationOption("Zero Sugar", "Zero Sugar"),),
                resolved_item_names=("toast", "fruit"),
                unresolved_item_name="yogurt")
    base.update(kw)
    return ClarificationQuestion(**base)


def test_a_clarify_plan_carries_what_was_already_understood():
    """Without this the composer can only ask "Which yogurt?" — the
    acknowledgement that makes it one conversation is unavailable to it."""
    plan = plan_clarify_from_question(_question())
    assert [i.name for i in plan.resolved_items] == ["toast", "fruit"]
    assert plan.unresolved_item.name == "yogurt"
    assert plan.requires_answer and plan.allow_question


def test_the_semantic_fallback_acknowledges_before_asking():
    text = fallback(plan_clarify_from_question(_question()))
    _leads_with_the_meal(text, "toast", "fruit")
    assert text.endswith("Which Chobani yogurt was it?"), text


def test_a_material_assumption_reaches_the_prompt():
    plan = plan_clarify_from_question(
        _question(material_assumption="Estimated the handful at about 45g."))
    assert "45g" in build_prompt(plan)


def test_the_policy_supplies_semantics_without_owning_the_voice():
    """clarify_policy decides WHAT must be asked. If it also wrote the
    sentence, a tone change would mean editing the policy engine."""
    import inspect
    import skills.nutrition.clarify_policy as CP
    # Comments may quote an example sentence to explain WHY the semantics are
    # exported; what must not appear is voice in the code itself.
    code = "\n".join(line for line in inspect.getsource(CP).splitlines()
                     if not line.strip().startswith("#"))
    for voice in ("I've got", "Got it,", "Light start"):
        assert voice not in code


# ── typed failure intents ─────────────────────────────────────────────────────
def test_a_failure_becomes_a_typed_intent_not_prose():
    from skills.nutrition.families import (CandidateResolutionFailure,
                                           failure_intent)
    intent = failure_intent(CandidateResolutionFailure.NO_MATCH)
    assert intent.code == "no_match"
    assert intent.user_fixable and intent.requires_question
    assert "label" in intent.recovery_action


def test_an_outage_is_not_the_users_problem_to_solve():
    """The distinction that matters most: asking someone to read a label they
    may not need, because our API is down, is worse than saying we can't
    check."""
    from skills.nutrition.families import (CandidateResolutionFailure,
                                           failure_intent)
    intent = failure_intent(CandidateResolutionFailure.SOURCE_UNAVAILABLE)
    assert not intent.user_fixable
    assert not intent.requires_question
    plan = plan_failure(intent)
    assert not plan.requires_answer
    assert "Do not ask them to fix it" in build_prompt(plan)


def test_every_failure_state_produces_a_usable_intent():
    from skills.nutrition.families import (CandidateResolutionFailure,
                                           failure_intent)
    for failure in CandidateResolutionFailure:
        intent = failure_intent(failure)
        assert intent.code and intent.recovery_action
        assert intent.approved_message
        plan = plan_failure(intent)
        assert validate(fallback(plan), plan).ok, failure


# ── the constrained live composer ─────────────────────────────────────────────
def test_the_composer_is_on_by_default(monkeypatch):
    """Was off, on the reasoning that the fallbacks are "correct and
    non-robotic". Correct held; non-robotic did not — they pick openers by
    rotation, which is variety without intelligence, on the most frequent
    interaction in the app."""
    from core.food_response import composer_enabled
    monkeypatch.delenv("FOOD_COMPOSER", raising=False)
    assert composer_enabled()
    monkeypatch.setenv("FOOD_COMPOSER", "false")
    assert not composer_enabled()


@pytest.mark.asyncio
async def test_the_async_composer_uses_a_valid_generation(monkeypatch):
    import core.llm as LLM

    async def _chat(messages, system, **kw):
        return {"text": "Light start there."}
    monkeypatch.setattr(LLM, "chat", _chat)

    from core.food_response import compose_async
    text, reason = await compose_async(_commit_plan())
    assert text == "Light start there." and reason == Reason.OK


@pytest.mark.asyncio
async def test_the_async_composer_falls_back_on_a_violating_generation(
        monkeypatch):
    import core.llm as LLM

    async def _chat(messages, system, **kw):
        return {"text": "Give me a moment. Logging it now."}
    monkeypatch.setattr(LLM, "chat", _chat)

    from core.food_response import compose_async
    text, reason = await compose_async(plan_correct("the jam"))
    assert reason == Reason.TRANSACTION_NARRATION
    assert text == "Updated the jam."


@pytest.mark.asyncio
async def test_a_model_outage_is_not_an_error_just_a_plainer_reply(monkeypatch):
    import core.llm as LLM

    async def _boom(*a, **k):
        raise RuntimeError("model down")
    monkeypatch.setattr(LLM, "chat", _boom)

    from core.food_response import compose_async
    text, _ = await compose_async(plan_undo("that log"))
    assert text == "Undid that log."


@pytest.mark.asyncio
async def test_the_composer_shares_the_validator_with_the_sync_path(monkeypatch):
    """Wrapping rather than duplicating: the rules cannot drift between the
    path tests exercise and the one production uses."""
    import core.llm as LLM
    calls = []

    async def _chat(messages, system, **kw):
        calls.append(system)
        return {"text": "Nice. Anything else?"}
    monkeypatch.setattr(LLM, "chat", _chat)

    from core.food_response import compose_async
    _, reason = await compose_async(_commit_plan())
    assert reason == Reason.FORBIDDEN_QUESTION
    assert "YOUR LAST ATTEMPT FAILED" in calls[-1]
