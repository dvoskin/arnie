"""Canonical turn identity (P0.1, 2026-07-24): one transaction id per inbound
message, preferred over semantic fingerprints for exactly-once, stamped onto
every ledger event via the ambient contextvar.

Covers: id construction (client-id form, channel scoping, content-hash
fallback), event stamping, and the run_turn-level dedup semantics — the same
turn_id is absorbed as a duplicate delivery while the same TEXT under a new
turn_id (a genuine re-send) executes."""
import json
from types import SimpleNamespace

import pytest

import core.turn_identity as TI
from core.turn_identity import make_turn_id, CURRENT_TURN_ID


# ── id construction ───────────────────────────────────────────────────────────
def test_client_id_form_and_channel_scoping():
    assert make_turn_id("imessage", "GUID-123", 7) == "imessage:GUID-123"
    assert make_turn_id("telegram", 4567, 7) == "telegram:4567"
    # the same client id on different channels can never collide
    assert make_turn_id("imessage", "42", 7) != make_turn_id("telegram", "42", 7)


def test_fallback_hash_is_stable_and_scoped():
    a = make_turn_id("ios", None, 7, "had a banana")
    b = make_turn_id("ios", "", 7, "had a banana")
    assert a == b and a.startswith("ios:h:")
    # different user or text → different turn
    assert a != make_turn_id("ios", None, 8, "had a banana")
    assert a != make_turn_id("ios", None, 7, "had two bananas")


# ── event stamping ────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_ledger_events_stamp_current_turn(db, make_user):
    from db.queries import record_ledger_event, get_ledger_events
    user = await make_user()
    tok = CURRENT_TURN_ID.set("imessage:GUID-abc")
    try:
        await record_ledger_event(db, user.id, "created", domain="food",
                                  entry_id=1, payload={"food_name": "Eggs"})
    finally:
        CURRENT_TURN_ID.reset(tok)
    await record_ledger_event(db, user.id, "created", domain="food",
                              entry_id=2, payload={"food_name": "Toast"})
    events = {e.entry_id: e for e in await get_ledger_events(db, user.id)}
    assert events[1].turn_id == "imessage:GUID-abc"
    assert events[2].turn_id is None       # non-turn write → no identity


# ── run_turn dedup semantics ──────────────────────────────────────────────────
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
    return SimpleNamespace(id=1, total_calories=0, total_protein=0,
                           total_carbs=0, total_fats=0, total_water_ml=0,
                           workout_completed=False, cardio_completed=False,
                           food_entries=[], exercise_entries=[])


@pytest.mark.asyncio
async def test_same_turn_id_absorbed_new_turn_id_executes(monkeypatch):
    """The discriminating pair: identical text re-delivered under the SAME
    turn_id is a transport retry (absorbed, zero writes); identical text
    under a NEW turn_id is the user genuinely sending it again (executes).
    Semantic fingerprints alone could not tell these apart."""
    import core.conversation as C
    import core.food_turn as FTmod
    import db.queries as Q
    import reminders.lifecycle as RL

    async def _noop(db, user, llm_reply_text="", **kwargs): return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)
    async def fake_reload(db, uid): return _user()
    monkeypatch.setattr(Q, "reload_user", fake_reload)

    async def fake_sft(message, user, prior=None, **kw):
        return {"action": "log",
                "say": "Banana logged, {batch_cal} cal.",
                "tool_calls": [{"name": "log_food",
                                "input": {"food_name": "Banana",
                                          "quantity": "1 banana",
                                          "calories": 105}}]}
    monkeypatch.setattr(FTmod, "run", fake_sft)
    async def fake_chat(*a, **k):
        return {"text": "", "raw_content": [], "tool_calls": []}
    monkeypatch.setattr(C, "chat", fake_chat)

    executed = {"n": 0}
    async def fake_exec(tcs, *a, **k):
        executed["n"] += len(tcs)
        return {"log_food": "Logged."}
    monkeypatch.setattr(C, "execute_tool_calls", fake_exec)

    async def _turn(tid):
        return await C.run_turn(
            _user(), _DB(),
            [{"role": "user", "content": "had a banana"}],
            "SYS", "imessage", in_onboarding=False, was_onboarding=False,
            today_log=_today_log(), turn_id=tid)

    t1 = await _turn("imessage:G-1")
    assert executed["n"] == 1
    # Same turn_id again — a redelivery. Absorbed: no second write.
    t2 = await _turn("imessage:G-1")
    assert executed["n"] == 1
    reply2 = "|||".join(t2.response.bubbles if t2.response else [])
    assert "Already got that one" in reply2
    # New turn_id, same text — a genuine re-send. Executes.
    t3 = await _turn("imessage:G-2")
    assert executed["n"] == 2
