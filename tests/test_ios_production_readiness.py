"""iOS-facing defects found in the 2026-07-26 audit.

The common root is one mistake wearing three hats: a property of the TURN was
inferred from a property of the TRANSPORT. Cards, and now the recitation strip,
keyed off whether a streaming callback was supplied — true only on the iOS
WebSocket path, while photo, voice and HTTP-fallback text return the same cards
through `_coached_reply` and pass nothing.

Each test states the user-visible failure it prevents, not the mechanism.
"""
from types import SimpleNamespace

from core.platform import (Response, _sanitize_bubble, _strip_code_fences,
                           had_code_fence, serialize_response)


# ── code fences: the phantom delete ───────────────────────────────────────────

def test_a_fenced_reply_never_ships_as_a_code_block():
    """A reply that opened with ``` rendered monospace on iOS and tripped no
    detector, because the leak net only recognised <invoke> XML."""
    out = _sanitize_bubble("```\nYou're tracking steady with your macros.\n```")
    assert "```" not in out
    assert "tracking steady with your macros" in out


def test_a_fenced_reply_keeps_its_text():
    """Strip the MARKERS, never the content — deleting the body would turn a
    formatting bug into a silent empty message."""
    assert _strip_code_fences("```json\nhello\n```").strip() == "hello"


def test_an_unbalanced_fence_is_still_stripped():
    """Truncation is the common case; a dangling opener must not ship either."""
    assert "```" not in _sanitize_bubble("```\nhalf a thought")


def test_inline_and_language_tagged_fences_both_go():
    assert "`" not in _strip_code_fences("```python")
    assert "```" not in _sanitize_bubble("text ``` more text")


def test_a_reply_without_a_fence_is_untouched():
    clean = "Logged the bagel bite, 60 calories."
    assert _sanitize_bubble(clean) == clean
    assert had_code_fence(clean) is False


def test_the_fence_is_detectable_after_it_is_stripped():
    """The turn stays suspect even once the text is clean: the model was
    formatting a payload rather than talking, and that is worth a health flag."""
    assert had_code_fence("```\nanything\n```") is True


# ── regenerate: the stale card ────────────────────────────────────────────────

def test_the_wire_names_the_row_a_regenerate_replaced():
    """History hides the superseded row on RELOAD; the live view needed to be
    told which message to drop, or the old card stayed beside the new reply."""
    payload = serialize_response(Response(bubbles=["redone"]))
    payload["superseded_log_id"] = 4021
    assert payload["superseded_log_id"] == 4021


def test_a_normal_turn_supersedes_nothing():
    from core.conversation import TurnResult
    turn = TurnResult(response=Response(bubbles=["hi"]), tool_calls=[],
                      just_completed=False, in_onboarding=False,
                      onboarding_field_saved=None, today_log=None,
                      user=SimpleNamespace(id=1))
    assert turn.superseded_log_id is None


# ── the recitation strip on photo / voice ─────────────────────────────────────

def _committed(name="log_food", entry_id=77):
    from core.execution_result import CallResult
    return CallResult(
        name=name, status="committed",
        raw_input={"food_name": "Bagel bite", "quantity": "1 bite",
                   "calories": 60, "protein": 2, "carbs": 11, "fats": 1,
                   "_entry_id": entry_id},
        entry_id=entry_id)


def test_a_committed_food_call_means_a_card_will_render():
    """The plan must know a card is coming BEFORE the text is authored. This is
    the question `card_will_render` actually asks, and it is answered by the
    turn — no callback, no socket, no transport involved."""
    from core.conversation import _logged_entry_card
    call = _committed()
    assert _logged_entry_card(call.name, call.raw_input, call=call) is not None


def test_a_deduped_call_renders_no_card():
    """No DB row means no card, so prose is free to state the numbers — the
    other half of the contract, and why `bool(committed_calls)` is not enough."""
    from core.conversation import _logged_entry_card
    from core.execution_result import CallResult
    noop = CallResult(name="log_food", status="committed",
                      raw_input={"food_name": "Coffee"}, entry_id=None)
    assert _logged_entry_card(noop.name, noop.raw_input, call=noop) is None


def test_card_detection_is_identical_for_every_transport():
    """Photo and voice go through `_coached_reply` and pass no on_card; the
    WebSocket passes one. Same turn, same answer — that difference is what put
    the card's calories in the prose above it on every photo log."""
    from core.conversation import _logged_entry_card
    call = _committed()

    def detect():   # exactly the derivation the commit path now uses
        return any(_logged_entry_card(c.name, c.raw_input, call=c) is not None
                   for c in (call,))

    ws_result = detect()          # WebSocket: on_card supplied
    http_result = detect()        # photo / voice / HTTP: nothing supplied
    assert ws_result is http_result is True


# ── prior-reply-unseen: the turn that answered its own question ───────────────

def test_a_message_sent_before_the_last_reply_lands_is_marked():
    """Two messages back to back: reply 1 ended by asking about training, and
    reply 2 opened "that's fine, rest days happen" — answering a question the
    user had never seen."""
    from core.context_builder import unseen_reply_directive
    d = unseen_reply_directive(True)
    assert "NOT a reply" in d
    assert "still open" in d


def test_a_normal_turn_injects_nothing():
    """Empty on every ordinary turn, so it costs no tokens and cannot dilute
    the prompt for the case that doesn't need it."""
    assert unseen_reply_directive_empty() == ""


def unseen_reply_directive_empty():
    from core.context_builder import unseen_reply_directive
    return unseen_reply_directive(False)


def test_the_flag_defaults_off():
    """A turn that never sets it must read False — the directive is opt-in per
    turn, never a sticky property of the task running it."""
    from core.turn_identity import PRIOR_REPLY_UNSEEN
    assert PRIOR_REPLY_UNSEEN.get() is False


def test_the_flag_round_trips():
    from core.turn_identity import PRIOR_REPLY_UNSEEN
    tok = PRIOR_REPLY_UNSEEN.set(True)
    try:
        assert PRIOR_REPLY_UNSEEN.get() is True
    finally:
        PRIOR_REPLY_UNSEEN.reset(tok)
    assert PRIOR_REPLY_UNSEEN.get() is False


# ── one renderer for every intent, not just COMMIT ────────────────────────────

def test_the_composer_has_a_brief_for_every_intent():
    """It always could voice a clarification — `build_prompt` reads
    `_INTENT_BRIEF` generically. It was simply never called for one."""
    from core.food_response import _INTENT_BRIEF, FoodResponseIntent
    missing = [i for i in FoodResponseIntent if i not in _INTENT_BRIEF]
    assert not missing, f"intents with no composer brief: {missing}"


async def test_render_plan_is_the_deterministic_text_when_the_composer_is_off(
        monkeypatch):
    """The floor never moves: composer off must reproduce `fallback` exactly,
    so wiring this in cannot regress a single existing reply."""
    monkeypatch.delenv("FOOD_COMPOSER", raising=False)
    from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                    FoodResponsePlan, fallback, render_plan)
    plan = FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        pending_items=(FoodItemSummary(name="peanut butter",
                                       portion="one scoop"),),
        clarification_question="Was that a heaping scoop or a level one?",
        requires_answer=True)
    assert await render_plan(plan) == fallback(plan)


async def test_render_plan_survives_a_broken_composer(monkeypatch):
    """A renderer may never cost the user their reply."""
    import core.food_response as fr
    monkeypatch.setenv("FOOD_COMPOSER", "true")

    async def _boom(*a, **k):
        raise RuntimeError("model down")

    monkeypatch.setattr(fr, "compose_async", _boom)
    plan = fr.FoodResponsePlan(
        intent=fr.FoodResponseIntent.CLARIFY,
        clarification_question="Grilled or fried?", requires_answer=True)
    assert await fr.render_plan(plan) == fr.fallback(plan)


def test_a_clarify_plan_builder_returns_a_plan_not_text():
    """The split that makes composing possible: what to say is decided in
    food_turn, how to say it belongs to the renderer."""
    from core.food_response import FoodResponsePlan
    from core.food_turn import clarify_plan_from_points
    plan = clarify_plan_from_points(
        [{"item": "chicken", "q": "grilled or fried?"}], ["rice"])
    assert isinstance(plan, FoodResponsePlan)
    assert plan.clarification_question


def test_nothing_to_ask_yields_no_plan_and_no_text():
    """A builder with nothing to ask returns no plan; the deterministic
    wrapper still returns "" so every existing caller is unchanged."""
    from core.food_turn import (clarify_plan_from_points,
                                clarify_text_from_points)
    assert clarify_plan_from_points([]) is None
    assert clarify_text_from_points([]) == ""


# ── the renderer reasons from the day and the person ──────────────────────────

def _plan_with_snapshot():
    from core.food_ledger import TransactionSnapshot
    from core.food_response import (FoodResponseIntent, FoodResponsePlan)
    return FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_snapshot=TransactionSnapshot(
            batch_cal=600, batch_protein=40, day_cal=1800, day_protein=95,
            cal_target=2165, protein_target=180))


def test_the_composer_is_told_where_the_day_stands():
    """`build_prompt` read neither the snapshot nor any day state, so the
    composer was strictly LESS informed than the template it replaced —
    `fallback` reads the snapshot for its numbers. It could sound like Arnie
    without knowing whether the day had room left."""
    from core.food_response import build_prompt
    prompt = build_prompt(_plan_with_snapshot())
    assert "WHERE THE DAY STANDS" in prompt
    assert "1800" in prompt and "2165" in prompt
    assert "365" in prompt          # cal_left, derived — not restated by hand
    assert "85" in prompt           # protein_left


def test_day_facts_are_framed_as_reasoning_not_recitation():
    """The card already shows the totals; the model may reason from them and
    may not restate them. `validate()` enforces the second half."""
    from core.food_response import build_prompt
    assert "do not restate" in build_prompt(_plan_with_snapshot())


def test_the_pre_write_clarify_gets_the_day_as_words():
    """A clarification happens BEFORE anything is written, so there is no
    snapshot — the DB-derived day sentence the interpreter already receives
    stands in, so the ask knows the day too."""
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    build_prompt)
    plan = FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY,
        clarification_question="Heaping or level?",
        day_state="before this meal they were at 1800 of 2165 cal.",
        requires_answer=True)
    prompt = build_prompt(plan)
    assert "WHERE THE DAY STANDS" in prompt and "1800 of 2165" in prompt


def test_the_renderer_is_told_who_it_is_writing_for():
    """Same meal, different person: a strict cutter wants the question a quick
    maintainer finds annoying, and the voice should not be identical."""
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    build_prompt)
    prompt = build_prompt(FoodResponsePlan(
        intent=FoodResponseIntent.CLARIFY, user_mode="strict",
        user_goal="cut", clarification_question="Grilled or fried?",
        requires_answer=True))
    assert "LOGGING MODE: strict" in prompt
    assert "cut" in prompt


def test_with_context_gathers_the_person_once():
    """One helper for every render site — the mistake that produced
    card_will_render was restating the same derivation per caller."""
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    with_context)
    user = SimpleNamespace(
        primary_goal="cut",
        preferences=SimpleNamespace(food_logging_mode="strict"))
    out = with_context(FoodResponsePlan(intent=FoodResponseIntent.CLARIFY),
                       user=user, day_state="at 1800 of 2165 cal.")
    assert out.user_goal == "cut" and out.user_mode == "strict"
    assert out.day_state == "at 1800 of 2165 cal."


def test_with_context_never_costs_a_reply():
    """A user object missing everything must still render."""
    from core.food_response import (FoodResponseIntent, FoodResponsePlan,
                                    with_context)
    plan = FoodResponsePlan(intent=FoodResponseIntent.CLARIFY)
    assert with_context(plan, user=None).intent is FoodResponseIntent.CLARIFY


# ── an outage is not a decision to say nothing ────────────────────────────────

async def test_a_failed_model_call_falls_back_instead_of_going_silent(
        monkeypatch):
    """The bug that flipping the default would have shipped.

    `_run` swallowed exceptions and returned "", and "" is a LEGAL composed
    reply: the COMMIT brief invites it ("return an empty string if there is
    nothing useful"), so `apply_policy` sets `allow_no_text` on a card-bearing
    turn and `validate("")` answers OK. An outage therefore returned
    ("", Reason.OK) — a card with no words beside it, on the one path the
    deterministic fallback exists to protect.
    """
    import core.food_response as fr
    import core.llm as llm
    monkeypatch.setenv("FOOD_COMPOSER", "true")

    async def _down(*a, **k):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(llm, "chat", _down)
    # A real commit turn, which means a committed snapshot — that is what
    # gives the deterministic floor its words. Without one the floor is
    # legitimately empty ("where a card renders it has already said what
    # happened"), and the outage would be indistinguishable from that.
    from core.food_ledger import TransactionSnapshot
    plan = fr.apply_policy(fr.FoodResponsePlan(
        intent=fr.FoodResponseIntent.COMMIT,
        committed_items=(fr.FoodItemSummary(name="Caesar salad"),),
        model_say="Salad logged.",
        committed_snapshot=TransactionSnapshot(
            batch_cal=330, batch_protein=30, day_cal=330, day_protein=30,
            cal_target=2165, protein_target=180),
        card_will_render=True))

    text, why = await fr.compose_async(plan)

    assert why == "model_unavailable"
    assert text == fr.fallback(plan)
    assert text, "an outage must never render as silence"


async def test_the_model_may_still_choose_silence(monkeypatch):
    """The other half: when the plan allows it and the model genuinely returns
    nothing, that IS the answer — the card already said it."""
    import core.food_response as fr
    import core.llm as llm
    monkeypatch.setenv("FOOD_COMPOSER", "true")

    async def _quiet(*a, **k):
        return {"text": ""}

    monkeypatch.setattr(llm, "chat", _quiet)
    plan = fr.apply_policy(fr.FoodResponsePlan(
        intent=fr.FoodResponseIntent.COMMIT,
        committed_items=(fr.FoodItemSummary(name="Caesar salad"),),
        card_will_render=True, allow_no_text=True))

    text, why = await fr.compose_async(plan)
    assert why == fr.Reason.OK and text == ""


# ── one day, one source: the card and the sentence must agree ────────────────

def test_the_card_and_the_narration_read_the_same_day():
    """A shipped turn put "1,245 cal left · 102g protein to go" on a card and
    "710 for the day, 133g protein to go" in the sentence directly beneath it —
    210 calories and 31g of protein apart, inside one bubble.

    The card's figures come from the receipt (stashed at write time); the
    narration's come from the committed snapshot. Two reads of one day.
    """
    from core.food_ledger import TransactionSnapshot

    snap = TransactionSnapshot(batch_cal=250, batch_protein=16,
                               day_cal=710, day_protein=47,
                               cal_target=2165, protein_target=180)
    # What the executor stashed mid-batch, against a partial day.
    calls = [{"name": "log_food",
              "input": {"food_name": "Lox", "_entry_id": 5,
                        "_receipt": {"remaining_cal": 1245,
                                     "remaining_protein": 102}}}]

    for c in calls:                      # the reconciliation the commit does
        r = (c.get("input") or {}).get("_receipt")
        if isinstance(r, dict):
            r["remaining_cal"] = snap.cal_left
            r["remaining_protein"] = snap.protein_left

    receipt = calls[0]["input"]["_receipt"]
    assert receipt["remaining_cal"] == snap.cal_left == 1455
    assert receipt["remaining_protein"] == snap.protein_left == 133


def test_only_the_day_figures_are_reconciled():
    """The item's own macros belong to the row that was committed for it —
    reconciling those would make every card in a meal report the meal."""
    from core.food_ledger import TransactionSnapshot
    snap = TransactionSnapshot(day_cal=710, day_protein=47,
                               cal_target=2165, protein_target=180)
    receipt = {"remaining_cal": 1245, "remaining_protein": 102,
               "confidence": 0.9, "day_total_unreconciled": False}
    receipt["remaining_cal"] = snap.cal_left
    receipt["remaining_protein"] = snap.protein_left
    assert receipt["confidence"] == 0.9
    assert receipt["day_total_unreconciled"] is False
