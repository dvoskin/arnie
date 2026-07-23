"""Structured food turn (Danny 2026-07-23): the logger logs, the coach talks.
Covers: the pre-gate, composite splitting into clean editable items, the rich
formatted ask, the structural question-can-never-be-a-food property, and the
run_turn wiring (log path skips the big pass entirely; ask path holds + records
the pending; the answer turn logs the whole exchange). Switch: STRUCTURED_FOOD."""
import json
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
async def test_ask_is_rich_formatted(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask",
        "points": [{"label": "Crust", "q": "how much did you leave?"},
                   {"label": "Chicken", "q": "roughly how much?"}]}))
    out = await FT.run("had pizza and some chicken", SimpleNamespace())
    assert out["action"] == "ask"
    assert out["text"].startswith("Quick one so it's clean:")
    assert "1. **Crust**: how much did you leave?" in out["text"]
    assert "2. **Chicken**: roughly how much?" in out["text"]


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


@pytest.mark.asyncio
async def test_last_assistant_context_threads_in(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({"action": "pass"}))
    await FT.run("okay cool log it", SimpleNamespace(),
                 last_assistant="Both flavors land around 140 cal a bag, want me to log them?")
    assert "Your previous message to them" in FT.chat.last_content  # type: ignore[attr-defined]
    assert "140 cal a bag" in FT.chat.last_content  # type: ignore[attr-defined]


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
        return {"action": "update", "say": "Bumped the birria to 2 tacos, 360 cal.",
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
