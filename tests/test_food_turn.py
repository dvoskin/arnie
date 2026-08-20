"""Structured food turn (Danny 2026-07-23): the logger logs, the coach talks.
Covers: the pre-gate, composite splitting into clean editable items, the rich
formatted ask, the structural question-can-never-be-a-food property, and the
run_turn wiring (log path skips the big pass entirely; ask path holds + records
the pending; the answer turn logs the whole exchange). Switch: STRUCTURED_FOOD."""
import json
import re
import pytest
from types import SimpleNamespace

import core.food_turn as FT
import core.conversation as C
import db.queries as Q
import reminders.lifecycle as RL
from core.conversation import run_turn


# ── pre-gate ──────────────────────────────────────────────────────────────────
def test_applies_gate():
    assert FT.applies("I had two slices of pepperoni pizza and half a caesar salad")
    assert FT.applies("had 3 eggs and toast for breakfast")
    assert FT.applies("greek yogurt with honey for a snack")
    # corrections are IN scope (board-aware updates — Danny IMG_8595)
    assert FT.applies("I actually had 2 birria")
    assert FT.applies("actually it was 4 strawberries")
    assert FT.applies("I had 2 of those")
    assert FT.applies("make it 6 oz")
    # exclusions → legacy path
    assert not FT.applies("how many calories in a Quest bar?")   # question
    assert not FT.applies("might grab a burger later")           # plan
    assert not FT.applies("remove the birria taco")              # destructive
    assert not FT.applies("drank 20oz of water")                 # non-food domain
    assert not FT.applies("bench press 135 for 12 reps")         # workout
    assert not FT.applies("ok cool")                             # ack
    assert not FT.applies("")


# ── logger pass parsing ───────────────────────────────────────────────────────
def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        fc.last_content = messages[-1]["content"]
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


@pytest.mark.asyncio
async def test_composite_splits_into_clean_editable_items(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [
            {"food": "Pizza toppings, crust left", "amount": 2, "unit": "slices",
             "calories": 380, "protein": 18, "carbs": 12, "fats": 30},
            {"food": "Caesar salad", "amount": 2, "unit": "handfuls",
             "calories": 180, "protein": 4, "carbs": 8, "fats": 15},
            {"food": "Grilled chicken strips", "amount": 3, "unit": "strips",
             "calories": 150, "protein": 28, "carbs": 0, "fats": 4},
        ]}))
    out = await FT.run("pizza and half a caesar with chicken", SimpleNamespace())
    assert out["action"] == "log"
    calls = out["tool_calls"]
    assert [c["input"]["food_name"] for c in calls] == [
        "Pizza toppings, crust left", "Caesar salad", "Grilled chicken strips"]
    # Clean editable quantities — "amount unit", no prose crammed in.
    assert [c["input"]["quantity"] for c in calls] == [
        "2 slices", "2 handfuls", "3 strips"]
    assert all(c["input"]["estimated"] for c in calls)


@pytest.mark.asyncio
async def test_an_interpreter_ask_goes_through_the_response_contract(monkeypatch):
    """Was `test_ask_is_rich_formatted`, asserting the numbered form and the
    system vocabulary that came with it — "Quick one so it's clean:",
    "1. **crust**:", "locked in ✅", "Nothing hits the board till then".

    That copy was retired from the response contract, but this path never went
    through the contract: `_format_question` rendered it directly. So two meals
    with near-identical uncertainty got different conversational treatment
    depending on which engine noticed it, and the numbered form survived in the
    one place nothing was checking (review item 4).

    ONE question — but not one ITEM. This used to assert the crust's own
    fragment ("How much did you leave?") and treat the chicken as the item that
    waits its turn, which is the compartmentalised shape: extract a point per
    food, ship whichever came first, drop the rest.

    Both points here are asking the same thing — how much — about two foods, so
    they are ONE unknown, and the question covers both. That is still a single
    question the user can answer in one breath; it simply stops pretending the
    two are unrelated. The item-by-item version cost a shipped turn four
    portion questions worth 2,760 calories, dropped in favour of a sauce.

    The retired vocabulary must stay gone either way."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Crust", "q": "how much did you leave?"},
                   {"label": "Chicken", "q": "roughly how much?"}]}))
    out = await FT.run("had pizza and some chicken", SimpleNamespace())
    assert out["action"] == "ask"
    text = out["text"]
    # One question, covering both foods — not one food's fragment.
    assert text.count("?") == 1, f"one question, got {text!r}"
    assert "how much of each" in text.lower(), text
    assert "crust" in text.lower() and "chicken" in text.lower()
    for retired in ("Quick one so it's clean", "locked in ✅",
                    "1. **crust**", "Nothing hits the board till then"):
        assert retired not in text, retired


@pytest.mark.asyncio
async def test_question_can_never_become_a_food(monkeypatch):
    """The structural property: a question-shaped item is dropped; the ask action
    carries no items at all."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [
            {"food": "Caesar salad", "amount": 1, "unit": "bowl", "calories": 300},
            {"food": "2. Did you eat anything else — bread, a drink, dessert?",
             "amount": None, "unit": ""},
        ]}))
    out = await FT.run("had a caesar salad", SimpleNamespace())
    names = [c["input"]["food_name"] for c in out["tool_calls"]]
    assert names == ["Caesar salad"], f"question leaked into items: {names}"


@pytest.mark.asyncio
async def test_update_resolves_against_board(monkeypatch):
    """'I actually had 2 birria' → update_food_entry on the board entry with scaled
    macros — never a dedup-blocked re-log (Danny IMG_8595)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "update",
        "updates": [{"entry_id": 707, "amount": 2, "unit": "tacos",
                     "calories": 360, "protein": 30}],
        "say": "Bumped the birria to 2 tacos, 360 cal now."}))
    board = [{"id": 707, "food": "Birria taco", "qty": "1 taco", "cal": 180}]
    out = await FT.run("I actually had 2 birria", SimpleNamespace(), board=board)
    assert out["action"] == "update"
    tc = out["tool_calls"][0]
    assert tc["name"] == "update_food_entry"
    assert tc["input"]["entry_id"] == 707
    assert tc["input"]["quantity"] == "2 tacos"
    assert tc["input"]["calories"] == 360
    assert "Bumped" in out["say"]
    # The board rendered into the model content (so references can resolve).
    assert "#707 Birria taco" in FT.chat.last_content  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_update_rejects_entry_not_on_board(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "update",
        "updates": [{"entry_id": 999, "amount": 2, "unit": "tacos"}]}))
    board = [{"id": 707, "food": "Birria taco", "qty": "1 taco", "cal": 180}]
    out = await FT.run("I actually had 2 birria", SimpleNamespace(), board=board)
    assert out is None, "an entry_id not on the board must never be updated"


@pytest.mark.asyncio
async def test_answer_turn_logs_and_never_reasks(monkeypatch):
    # Model tries to ask AGAIN on the answer turn → run() refuses (legacy handles).
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask", "points": [{"label": "X", "q": "more?"}]}))
    out = await FT.run("almost all", SimpleNamespace(),
                       prior={"original": "pizza", "question": "how much crust?"})
    assert out is None
    # And the prior context is threaded into the model content.
    assert "Earlier they reported" in FT.chat.last_content  # type: ignore[attr-defined]


def test_thread_routes_state_based_no_phrase_lists():
    """Mid-thread, complaints and confirmations route WITHOUT phrase matching —
    only other-domain messages are excluded (Danny: no complaint-style cue patches)."""
    assert FT.thread_routes("You only logged the sour cream ones")
    assert FT.thread_routes("okay cool log it")
    assert FT.thread_routes("that was actually two bags")
    # excluded domains stay put
    assert not FT.thread_routes("how many calories was that?")   # question → coach
    assert not FT.thread_routes("thanks")                        # ack
    assert not FT.thread_routes("remove the taco")               # destructive
    assert not FT.thread_routes("bench press 135x10")            # workout


def test_keep_as_is_closes_the_thread():
    """'Leave it like this' after a proposed bump is an ACK, not an update —
    the truffle-fries turn applied the bump the user was declining
    (Danny 2026-07-23). Every keep-it form must stay out of the logger."""
    for msg in ("Leave it like this", "leave it as is", "keep it as is",
                "leave it", "keep it like that", "that's fine",
                "don't change it", "as is", "leave them alone"):
        assert not FT.thread_routes(msg), msg
        assert not FT.applies(msg), msg
    # but a real correction with content still routes mid-thread
    assert FT.thread_routes("make it 6 fries not 4")


@pytest.mark.asyncio
async def test_last_assistant_context_threads_in(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({"action": "pass"}))
    await FT.run("okay cool log it", SimpleNamespace(),
                 last_assistant="Both flavors land around 140 cal a bag, want me to log them?")
    assert "Your previous message to them" in FT.chat.last_content  # type: ignore[attr-defined]
    assert "140 cal a bag" in FT.chat.last_content  # type: ignore[attr-defined]


def test_say_contract_enforced_model_digits_rejected():
    """Model wrote its own numbers (647 vs the card's 343 — IMG_8610) → say is
    replaced with a deterministic tokenized line naming the items."""
    calls = [{"name": "log_food", "input": {"food_name": "Everything Bagel"}},
             {"name": "log_food", "input": {"food_name": "Scallion Cream Cheese"}}]
    bad = "Bagel with the works, 647 cal and 46g protein down."
    out = FT.enforce_say_contract(bad, calls)
    assert "647" not in out and "{batch_cal}" in out
    assert "Everything Bagel" in out and "Scallion Cream Cheese" in out
    # A compliant say (numbers only via tokens) passes through untouched.
    good = "Both logged, {batch_cal} cal and {batch_protein}g protein combined."
    assert FT.enforce_say_contract(good, calls) == good
    # A wordy no-numbers say is also fine.
    assert FT.enforce_say_contract("Solid brunch, all on the board.", calls) \
        == "Solid brunch, all on the board."


def test_fill_say_tokens_strips_invented_tokens():
    out = FT.fill_say_tokens("Logged, {batch_cal} cal. {made_up_token} done.",
                             300, 20, 1200, 56, 2165, 180)
    assert "{" not in out and "300 cal" in out


def test_fill_say_tokens_numbers_come_from_committed_day():
    """The logger writes the words, the SYSTEM writes the numbers — say can never
    disagree with the card/DB (Danny: logger+coach must not conflict)."""
    out = FT.fill_say_tokens(
        "Both bags logged, {batch_cal} cal and {batch_protein}g protein combined. "
        "You're at {day_cal} with {cal_left} left, {protein_left}g protein to go.",
        batch_cal=310, batch_protein=18, day_cal=1210, day_protein=56,
        cal_target=2165, protein_target=180)
    assert out == ("Both bags logged, 310 cal and 18g protein combined. "
                   "You're at 1210 with 955 left, 124g protein to go.")
    # Tokens the model didn't use are fine; unknown text untouched.
    assert FT.fill_say_tokens("Logged, nice.", 0, 0, 0, 0, 0, 0) == "Logged, nice."


# ── run_turn wiring ───────────────────────────────────────────────────────────
def _user():
    return SimpleNamespace(
        id=1, onboarding_completed=True, timezone="UTC", name="Danny",
        primary_goal="recomp", nudges_sent="", log_unlocked_at="seeded",
        preferences=SimpleNamespace(calorie_target=2165, protein_target=180,
                                    food_logging_mode="moderate"))


class _DB:
    async def refresh(self, *a, **k): pass
    async def commit(self, *a, **k): pass
    async def rollback(self, *a, **k): pass
    async def execute(self, *a, **k):
        class _R:
            def scalar_one_or_none(self): return None
            def scalars(self): return self
            def all(self): return []
            def first(self): return None
            def scalar(self): return None
        return _R()


def _today_log():
    return SimpleNamespace(id=1, total_calories=0, total_protein=0, total_carbs=0,
                          total_fats=0, total_water_ml=0, workout_completed=False,
                          cardio_completed=False, food_entries=[], exercise_entries=[])


@pytest.fixture(autouse=True)
def _base(monkeypatch):
    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)
    monkeypatch.setenv("STRUCTURED_FOOD", "true")
    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)


@pytest.mark.asyncio
async def test_log_turn_skips_big_pass_and_executes_items(monkeypatch):
    async def fake_sft(message, user, prior=None, **kw):
        return {"action": "log",
                "say": "Salad and chicken logged, {batch_cal} cal in. "
                       "You're at {day_cal} with {cal_left} left.",
                "tool_calls": [
            {"name": "log_food", "input": {"food_name": "Caesar salad",
                                           "quantity": "2 handfuls", "calories": 180}},
            {"name": "log_food", "input": {"food_name": "Grilled chicken strips",
                                           "quantity": "3 strips", "calories": 150}}]}
    import core.food_turn as FTmod
    monkeypatch.setattr(FTmod, "run", fake_sft)

    big = {"n": 0}
    async def fake_chat(*a, **k):
        big["n"] += 1
        return {"text": "SHOULD NOT RUN", "raw_content": [], "tool_calls": []}
    monkeypatch.setattr(C, "chat", fake_chat)
    async def fake_voice(*a, **k):
        raise AssertionError("voice_log must NOT run on a structured turn (say rides the JSON)")
    monkeypatch.setattr(C, "voice_log", fake_voice)

    logged = []
    async def fake_exec(tcs, *a, **k):
        logged.extend((tc.get("input") or {}).get("food_name") for tc in tcs)
        return {"log_food": "Logged."}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    turn = await run_turn(_user(), _DB(),
                          [{"role": "user", "content": "had a caesar salad with chicken"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    assert logged == ["Caesar salad", "Grilled chicken strips"]
    assert big["n"] == 0, "big pass-1 must be SKIPPED on a structured log turn"
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    assert "Salad and chicken" in reply


@pytest.mark.asyncio
async def test_update_turn_executes_and_voices_say(monkeypatch):
    """run_turn integration: a structured UPDATE executes update_food_entry and the
    say line is the reply — no follow-up model call, no dedup template."""
    async def fake_sft(message, user, prior=None, **kw):
        return {"action": "update", "say": "Bumped the birria to 2 tacos, {batch_cal} cal.",
                "tool_calls": [{"name": "update_food_entry",
                                "input": {"entry_id": 707, "quantity": "2 tacos",
                                          "calories": 360}}]}
    import core.food_turn as FTmod
    monkeypatch.setattr(FTmod, "run", fake_sft)
    async def fake_chat(*a, **k):
        return {"text": "SHOULD NOT RUN", "raw_content": [], "tool_calls": []}
    monkeypatch.setattr(C, "chat", fake_chat)
    async def fake_followup(*a, **k):
        raise AssertionError("follow-up must not run on a structured update")
    monkeypatch.setattr(C, "chat_follow_up", fake_followup)

    fired = []
    async def fake_exec(tcs, *a, **k):
        fired.extend((tc.get("name"), (tc.get("input") or {}).get("entry_id"))
                     for tc in tcs)
        return {"update_food_entry": "Updated: Birria taco"}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    turn = await run_turn(_user(), _DB(),
                          [{"role": "user", "content": "I actually had 2 birria"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    assert ("update_food_entry", 707) in fired
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    assert "Bumped the birria" in reply, f"say should be the reply; got {reply!r}"


@pytest.mark.asyncio
async def test_ask_turn_holds_and_records_pending(monkeypatch):
    async def fake_sft(message, user, prior=None, **kw):
        return {"action": "ask",
                "text": "Quick one so it's clean:\n1. **Crust**: how much left?"}
    import core.food_turn as FTmod
    monkeypatch.setattr(FTmod, "run", fake_sft)
    async def fake_chat(*a, **k):
        return {"text": "SHOULD NOT RUN", "raw_content": [], "tool_calls": []}
    monkeypatch.setattr(C, "chat", fake_chat)
    logged = []
    async def fake_exec(tcs, *a, **k):
        logged.extend(tc.get("name") for tc in tcs)
        return {}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)
    recorded = {}
    async def fake_record(db, uid, kind=None, question=None, **kw):
        recorded["kind"] = kind
        return SimpleNamespace(payload_json=None, item_referenced=None)
    monkeypatch.setattr(Q, "record_pending_question", fake_record)

    turn = await run_turn(_user(), _DB(),
                          [{"role": "user", "content": "had pizza but left some crust"}],
                          "SYS", "imessage", in_onboarding=False, was_onboarding=False,
                          today_log=_today_log())
    reply = "|||".join(turn.response.bubbles if turn.response else [])
    assert "**Crust**" in reply, f"the formatted question should BE the reply; got {reply!r}"
    assert not logged, "an ask turn must log NOTHING"
    assert recorded.get("kind") == FT.ASK_KIND


@pytest.mark.asyncio
async def test_ask_threshold_scales_with_mode(monkeypatch):
    """Danny 2026-07-23: quick asks only >300 cal swings, moderate >200, strict >100
    — the threshold IS the strictness gradient, resolved into the system prompt."""
    monkeypatch.setattr(FT, "chat", _fake_chat({"action": "pass"}))
    seen = {}
    _orig = FT.chat
    async def spy(messages, system, **kw):
        seen["system"] = system
        return await _orig(messages, system, **kw)
    monkeypatch.setattr(FT, "chat", spy)
    def U(m): return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=m))
    # PROPORTIONS, NOT A FLAT FLOOR. The interpreter is the component that
    # actually decides, and it used to be briefed with "Under {thresh} cal of
    # swing: do NOT ask" — the exact rule `materiality` exists to abolish, and
    # one a tablespoon of butter clears on any food. It is now briefed on the
    # same three proportional gates the policy scores with.
    await FT.run("had some chips", U("quick"))
    assert "2.0% of their DAY" in seen["system"] and "quick" in seen["system"]
    assert "3.5% of their day" in seen["system"]
    await FT.run("had some chips", U("strict"))
    assert "0.5% of their DAY" in seen["system"] and "strict" in seen["system"]
    assert "15% of the FOOD" in seen["system"]
    await FT.run("had some chips", SimpleNamespace())   # no prefs → moderate
    assert "1.0% of their DAY" in seen["system"]
    assert "30% of the FOOD" in seen["system"]
    # and the abolished framing is gone for every mode
    assert "cal of swing: do NOT ask" not in seen["system"]


@pytest.mark.asyncio
async def test_branded_flag_routes_to_packaged_lookup(monkeypatch):
    """The logger declares brandedness (it read the message) — no noun-list
    heuristics. branded:true -> is_packaged on the write, which routes the item
    through the label-grade lookup lane (Danny IMG_8615: 'Philadelphia' stripped
    + never web-enriched)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [
            {"food": "Philadelphia Scallion Cream Cheese", "amount": 3, "unit": "tbsp",
             "calories": 150, "branded": True},
            {"food": "Tomato and onion", "amount": 1, "unit": "small portion",
             "calories": 15},
        ]}))
    out = await FT.run("bagel with Philadelphia scallion cream cheese and tomato",
                       SimpleNamespace())
    a, b = out["tool_calls"]
    assert a["input"]["food_name"] == "Philadelphia Scallion Cream Cheese"
    assert a["input"].get("is_packaged") is True
    assert "is_packaged" not in b["input"]


@pytest.mark.asyncio
async def test_regulars_ride_into_the_logger_context(monkeypatch):
    """Danny 2026-07-23 (Barebells on strict): the user's own history rides the
    logger's context so a brand resolves to THEIR product — exact macros, and a
    flavor-aware ask ('your usual Caramel Cashew?') instead of invented numbers."""
    monkeypatch.setattr(FT, "chat", _fake_chat({"action": "pass"}))
    regs = [{"name": "Barebells Caramel Cashew", "qty": "1 bar", "count": 14,
             "calories": 200, "protein": 20, "carbs": 18, "fats": 8}]
    await FT.run("had a barebells bar", SimpleNamespace(), regulars=regs)
    c = FT.chat.last_content  # type: ignore[attr-defined]
    assert "THEIR REGULARS" in c and "Barebells Caramel Cashew" in c
    assert "200 cal" in c and "logged 14x" in c


def test_say_contract_strips_questions_after_write():
    """Clarification happens BEFORE the log (Danny 2026-07-24) — a committed
    write's say can never ask. Question sentences are dropped; an all-question
    say falls to the deterministic tokenized line."""
    calls = [{"input": {"food_name": "Venti Cappuccino", "quantity": "1 cup",
                        "calories": 190}}]
    mixed = ("Cappuccino logged, {batch_cal} cal. Was that whole milk for "
             "real, or did they sub something?")
    out = FT.enforce_say_contract(mixed, calls)
    assert "?" not in out
    assert "logged" in out.lower()
    all_q = "Was that whole milk? Should I lock it in?"
    out2 = FT.enforce_say_contract(all_q, calls)
    assert "?" not in out2 and "{day_cal}" in out2   # deterministic fallback
    # ask actions are untouched — this contract only governs log/update says


@pytest.mark.asyncio
async def test_strict_confirm_narrowed_to_where_it_earns_friction(monkeypatch):
    """THE WHOLE-PARSE CONFIRM IS GONE (Danny 2026-07-26: "remove the strict
    confirm line, it's killing the interaction, Arnie should just clarify based
    on our plans instead").

    It had already been narrowed twice and reordered once, and each pass made
    the same discovery from a different direction: every case where the confirm
    seemed to earn its friction was a case the clarification policy could state
    a real question about, or one where there was nothing to ask. "Does that
    all look right?" is not a clarification — it re-shows a parse and invites
    a yes, which is why a user who says "I had 2 chicken thighs" was asked to
    confirm that they had 2 chicken thighs.

    What is left is what was always underneath: the policy asks when a doubt is
    material, discloses the assumption when it is not, and the committed card
    stays one tap from repair. These cases pin that the ASKS survive the
    removal — this is not "strict stopped checking"."""
    strict = SimpleNamespace(preferences=SimpleNamespace(food_logging_mode="strict"))
    # 1. Fully user-stated amounts → direct log, no confirm friction.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Roast turkey breast", "amount": 6.5, "unit": "oz",
                   "calories": 300, "protein": 55, "basis": "stated"},
                  {"food": "White rice", "amount": 100, "unit": "g",
                   "calories": 130, "protein": 3, "basis": "stated"}],
        "say": "Turkey and rice logged, {batch_cal} cal."}))
    out = await FT.run("6.5 oz turkey and 100g rice", strict)
    assert out["action"] == "log", "stated amounts commit directly on strict"
    # 2. A system-estimated amount → confirm before the write.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Caesar salad", "amount": 1.5, "unit": "cups",
                   "calories": 300, "basis": "estimate"}],
        "say": "Salad logged, {batch_cal} cal."}))
    out2 = await FT.run("had some caesar salad", strict)
    # A MATERIAL AMBIGUITY OUTRANKS THE CONFIRM (correction-turn directive §1).
    # This asserted the opposite: the whole-parse confirm used to SUPPRESS
    # `plan_turn` entirely, so on strict the staging, normalization and
    # ambiguity derivation never ran when a confirm was pending.
    #
    # "Some caesar salad" arriving as 1.5 cups is a 30-200g range collapsed to
    # a number the user never gave. "Does that look right?" over a parse that
    # already says 1.5 cups does not ask it — the user says yes to a figure
    # nobody established. So the question comes first, and the confirm is
    # decided afterwards on what is left open.
    assert out2["action"] == "ask" and out2.get("kind") != "confirm"
    assert "caesar salad" in out2["text"].lower()
    # THE RANGE, IN WHATEVER UNIT IT IS BEST SAID IN. This asserted "30g" or
    # "200g" literally, which pinned the gram VOCABULARY rather than the
    # property. A salad is served out of a bowl, so the bracket now reads
    # "closer to 1/2 or 3 cups" — same 30-200g span, said in a unit somebody can
    # answer from memory. What has to hold is that the question offers a spread
    # and does not simply echo the 1.5 cups nobody established.
    _quantities = set(re.findall(r"\d+(?:[./]\d+)?", out2["text"]))
    assert len(_quantities) >= 2, (
        f"the question must name the range, not just re-show our number: "
        f"{out2['text']!r}")
    assert "1.5" not in out2["text"], (
        f"the parse's own invented figure must not be the question: "
        f"{out2['text']!r}")
    # 3. Bulk plan (>=4 items) → confirm even when all stated.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": f"Item {i}", "amount": 1, "unit": "piece",
                   "calories": 100, "basis": "stated"} for i in range(4)],
        "say": "All four logged, {batch_cal} cal."}))
    out3 = await FT.run("had one of each of the four things", strict)
    # FOUR STATED ITEMS COMMIT. This used to confirm on the count alone — the
    # theory being that a last look at four items beats four questions. But
    # there were never four questions to ask: every amount is the user's own
    # words and the policy finds nothing material, so the confirm was asking
    # them to re-read their own sentence. Length is not doubt.
    assert out3["action"] == "log"
    # 4. Consumed doubt reported below threshold → confirm.
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Poke bowl", "amount": 1, "unit": "bowl",
                   "calories": 550, "basis": "stated"}],
        "ambiguities": [{"item": "Poke bowl", "field": "consumed",
                         "impact_cal": 50}],
        "say": "Bowl logged, {batch_cal} cal."}))
    out4 = await FT.run("ate one poke bowl", strict)
    # COMMITS. A 50-calorie doubt is 9% of a 550-calorie bowl — material by
    # neither the absolute nor the proportional rule, so there is nothing for a
    # question to settle. Under the old gate this fell through to the confirm,
    # which is the clearest illustration of what the confirm was doing: asking
    # about something the policy had just decided was not worth asking about.
    #
    # Case 2 still ASKS: "some caesar salad" as 1.5 cups is a 30-200g range
    # collapsed to a number, which IS material. The two differ in the size of
    # the doubt, which is exactly what the policy is for — and what a confirm
    # that fires on both cannot tell apart.
    assert out4["action"] == "log"
    # The wording was "picked up one poke bowl" until the acquisition state
    # landed. Picking a bowl up is not eating it, and that now earns its own
    # question — which is a different mechanism from the whole-parse confirm
    # this test is about, so the verb moved rather than the assertion.
    out4b = await FT.run("picked up one poke bowl", strict)
    assert out4b["action"] == "ask"
    assert "eat" in out4b["text"].lower(), out4b["text"]
    # A vague measure the interpreter CONVERTED now earns a question in
    # moderate (Danny 2026-07-25). "some caesar salad" arriving as 1.5 cups is
    # a 30-200g range collapsed to a number the user never gave — roughly 640
    # calories of doubt, approved silently. Quick still commits it.
    mod = SimpleNamespace(preferences=SimpleNamespace(food_logging_mode="moderate"))
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Caesar salad", "amount": 1.5, "unit": "cups",
                   "calories": 300, "basis": "estimate"}]}))
    out5 = await FT.run("had some caesar salad", mod)
    assert out5["action"] == "ask"
    assert "caesar salad" in out5["text"].lower()

    quick = SimpleNamespace(preferences=SimpleNamespace(food_logging_mode="quick"))
    out5b = await FT.run("had some caesar salad", quick)
    assert out5b["action"] == "log", "quick accepts the risk and commits"
    # and the ANSWER turn (prior set) never re-confirms
    out6 = await FT.run("yes", strict, prior={"original": "turkey", "question": "q"})
    assert out6 is None or out6.get("kind") != "confirm"


def test_item_is_stated_proxy():
    """A number the user TYPED outranks the interpreter's `basis`; otherwise
    the basis decides, and otherwise still the amount must be the user's own
    words (digits, 'half', spelled small counts). Unsure → False (errs toward
    confirming, the safe strict direction).

    ⛔ THE SECOND ASSERTION USED TO READ `not ... ("2 tacos")` *(P17 Tranche
    Q)*. It pinned "basis wins when present" as the contract — so `basis:
    "estimate"` vetoed a number sitting in the user's own message. That is
    not a subtle edge: measured in production 2026-08-20, "I also had 100g of
    grilled chicken" was filed as OUR inference, B-1 asked "How much?", and
    the meal logged 170.1 g against a stated 100 g. The user typed the 2 in
    "2 tacos" exactly as they typed the 100 in "100g", and neither is ours to
    relabel."""
    assert FT._item_is_stated({"amount": 6.5, "basis": "stated"}, "whatever")
    assert FT._item_is_stated({"amount": 2, "basis": "estimate"}, "2 tacos"), (
        "an interpreter label overrode a number the user typed")
    assert FT._item_is_stated({"amount": 6.5}, "6.5 oz turkey")
    assert FT._item_is_stated({"amount": 0.5}, "half a bagel")
    assert FT._item_is_stated({"amount": 2}, "two slices of pizza")
    assert FT._item_is_stated({"amount": 1}, "a banana")
    assert not FT._item_is_stated({"amount": 1.5}, "some caesar salad")
    assert not FT._item_is_stated({"amount": None}, "some fries")


def test_yes_re_shapes():
    for y in ("yes", "Yep", "looks good", "log it", "go ahead", "that's right", "ok"):
        assert FT._YES_RE.match(y), y
    for n in ("no", "make it 2", "actually 8 oz", "add cheese"):
        assert not FT._YES_RE.match(n), n


def test_gate_exclusions_are_semantic_not_lexical():
    """Deterministic-case audit (Danny 2026-07-24): exclusion words must hit
    only in their DOMAIN SHAPE — a french press is coffee, clear broth is
    soup, 'later than usual' is past tense, walking home is not cardio."""
    for msg in ("had a french press coffee this morning",
                "had a clear broth soup for lunch",
                "I had a protein bar later than usual",
                "had a snack while walking home",
                "had 2 sets of ribs from the bbq"):
        assert FT.applies(msg), msg
    for msg in ("grabbing a burrito later", "having lunch later",
                "clear my log for today", "walked 30 min on the treadmill",
                "did 3 sets of bench at 185", "bench press 3x10"):
        assert not FT.applies(msg), msg


def test_prompt_examples_speak_in_tokens():
    """Every cited say example in _SYSTEM uses {tokens} — a literal total in
    an example teaches the violation the runtime contract then strips."""
    import re as _re
    for m in _re.finditer(r'"say":"([^"]+)"', FT._SYSTEM):
        stripped = _re.sub(r"\{[a-z_]+\}", "", m.group(1))
        assert not _re.findall(r"\d{2,}", stripped), m.group(1)


def test_format_confirm_never_renders_none():
    """An amount-less item must read as the food alone, never "None Coffee".

    The bold numbered list this used to assert is gone (Danny 2026-07-25): the
    confirmation now comes from the response contract, which uses prose for a
    short meal and one-food-per-line for a long one. No bold, no numbering —
    that shape read as a form rather than a coach checking something.
    """
    txt = FT.format_confirm([{"food": "Coffee", "amount": None},
                             {"food": "Eggs", "amount": 2, "unit": ""}])
    assert "None" not in txt
    # Cased and spoken for reading aloud now (Danny 2026-07-25): "2 Eggs" was
    # the interpreter's row showing through the sentence.
    assert "coffee" in txt.lower() and "two eggs" in txt.lower()
    assert "**" not in txt and "Locking this in" not in txt
    assert txt.endswith("Does that look right?")


@pytest.mark.asyncio
async def test_logger_meal_slot_rides_the_tool_call(monkeypatch):
    """Universal meal-slot rule (Danny 2026-07-24): the logger's semantic call
    (plate=meal, lone bag=snack) rides each item; invalid values drop to the
    clock default downstream."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Roast turkey plate", "amount": 1, "unit": "plate",
                   "calories": 500, "meal": "dinner"},
                  {"food": "Jerky", "amount": 1, "unit": "oz",
                   "calories": 80, "meal": "snack"},
                  {"food": "Mystery", "amount": 1, "unit": "cup",
                   "calories": 100, "meal": "brunchish"}]}))
    out = await FT.run("turkey plate and jerky",
                       SimpleNamespace(preferences=SimpleNamespace(food_logging_mode="quick")))
    slots = [c["input"].get("meal_type") for c in out["tool_calls"]]
    assert slots == ["dinner", "snack", None]


def test_say_contract_allows_product_name_digits():
    """'Fage 0%' / '5-hour Energy' digits come from the write itself — never
    stripped as invented totals (sim battery false positive, 2026-07-24)."""
    calls = [{"input": {"food_name": "Fage 0% greek yogurt", "quantity": "1 cup",
                        "calories": 120}}]
    say = "Fage 0% logged, {batch_cal} cal. You're at {day_cal} with {cal_left} left."
    assert FT.enforce_say_contract(say, calls) == say


def test_acquisition_verbs_route_structured():
    """'Got like 6-7 oz of roast turkey' leaked to legacy — bare acquisition
    verbs now enter the structured lane, where strict's confirm IS the
    did-you-eat-it checkpoint (Danny 2026-07-24). Storage/future acquisitions
    stay plans."""
    for msg in ("Got like 6-7 oz of roast turkey and 100g of rice",
                "bought a chicken shawarma wrap",
                "ordered a poke bowl",
                "picked up a cold brew"):
        assert FT.applies(msg), msg
    for msg in ("got a pizza for tonight",
                "bought groceries for the week",
                "picked up meal prep to eat later",
                "got snacks for the fridge"):
        assert not FT.applies(msg), msg


@pytest.mark.asyncio
async def test_user_invited_question_lifts_no_reask(monkeypatch):
    """'Yeah but don't you wanna know what kind of ice cream bar' INVITES the
    flavor question — the no-re-ask loop-guard only blocks model-initiated
    chains (Dove bar, 2026-07-24)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask", "points": [{"label": "Dove bar", "q": "which kind?"}]}))
    out = await FT.run("Yeah but don't you wanna know what kind of ice cream bar",
                       SimpleNamespace(),
                       prior={"original": "apple, nutella, a dove bar",
                              "question": "Locking this in..."})
    assert out is not None and out["action"] == "ask"
    assert "dove bar" in out["text"].lower()
    # unprompted model re-ask still refused
    out2 = await FT.run("almost all of it", SimpleNamespace(),
                        prior={"original": "pizza", "question": "how much?"})
    assert out2 is None


def test_note_held_items_names_the_dropped():
    stashed = [{"food": "Apple"}, {"food": "Nutella"}, {"food": "Dove Ice Cream Bar"}]
    calls = [{"input": {"food_name": "Apple"}}, {"input": {"food_name": "Nutella"}}]
    out = FT.note_held_items("Apple and nutella logged, {batch_cal} cal.", stashed, calls)
    assert "Dove Ice Cream Bar" in out and "Holding" in out
    # nothing missing → say untouched
    calls.append({"input": {"food_name": "Dove Ice Cream Bar"}})
    same = FT.note_held_items("All three logged.", stashed, calls)
    assert same == "All three logged."


def test_ask_formats_facet_depth():
    """Facet asks in Arnie's full voice: bubbles (|||), bolded items, facet
    bullets, hold guarantee as its own beat."""
    deep = FT._format_question([
        {"label": "Chicken", "qs": ["grilled, baked, or fried?",
                                    "skin on or off?", "rough amount?"]},
        {"label": "Potato", "qs": ["baked or fries?", "any toppings?"]}])
    assert "Quick one so it's clean:" in deep
    assert "1. **chicken**" in deep and "   • skin on or off?" in deep
    assert deep.endswith("keeps your log exact.")
    assert deep.count("|||") == 1        # question + closer bubbles
    single = FT._format_question([{"label": "Crust", "q": "how much left?"}])
    assert "**crust**" in single and "|||" not in single


def test_ask_acknowledges_ready_items():
    """Locked items get their own ✅ bubble; brands keep their case."""
    txt = FT._format_question(
        [{"label": "Chicken", "qs": ["grilled or fried?", "how much?"]}],
        ready=["Bagel", "Barebells Bar"])
    assert txt.startswith("**bagel** and **Barebells Bar** locked in ✅|||")
    assert "Just need a couple things:" in txt
    one = FT._format_question([{"label": "Corn", "q": "how many ears?"}],
                              ready=["Steak"])
    assert one == "**steak** locked in ✅|||Just need the **corn**: how many ears?"
