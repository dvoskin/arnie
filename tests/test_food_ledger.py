"""Food ledger transaction layer (Danny 2026-07-24): interpreter proposes
ordered operations, deterministic policy arbitrates ambiguity, duplicates are
absorbed, and narration renders from one committed snapshot.

Covers: ordered mixed plans (update+log), the delete op, the consumption-
evidence invariant (a question can't execute a log), the policy engine holding
writes on reported ambiguity, bounded follow-up asks, pending-state expiry,
idempotency keys, graded thread relevance, the semantic-claim renderer, and
the update CAS seed."""
import json
import time
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import core.food_turn as FT
import core.food_ledger as FL


def _fake_chat(payload):
    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        fc.last_content = messages[-1]["content"]
        return {"text": json.dumps(payload), "raw_content": [], "tool_calls": []}
    return fc


BOARD = [{"id": 707, "food": "Birria taco", "qty": "1 taco", "cal": 180},
         {"id": 708, "food": "Truffle fries", "qty": "6 fries", "cal": 190}]


# ── ordered operations ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mixed_turn_is_one_ordered_transaction(monkeypatch):
    """'I had another taco, and change the first one to 2' — one plan, two
    operations, executed in the user's order (fix #1/#8)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "operations": [
            {"op": "update", "entry_id": 707, "amount": 2, "unit": "tacos",
             "calories": 360, "protein": 30},
            {"op": "log", "food": "Coke", "amount": 12, "unit": "oz",
             "calories": 140, "carbs": 39},
        ],
        "say": "Bumped the tacos and the Coke is on, {batch_cal} cal for the changes."}))
    out = await FT.run("actually I had 2 birria and a coke with it",
                       SimpleNamespace(), board=BOARD)
    assert out["action"] == "commit"
    assert [c["name"] for c in out["tool_calls"]] == [
        "update_food_entry", "log_food"]
    assert out["kinds"] == ["update", "log"]
    assert out["tool_calls"][0]["input"]["entry_id"] == 707
    assert out["tool_calls"][1]["input"]["food_name"] == "Coke"


@pytest.mark.asyncio
async def test_delete_resolves_against_board(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "delete", "deletes": [{"entry_id": 708}],
        "say": "Took the fries off. You're back to {day_cal}."}))
    out = await FT.run("remove the truffle fries", SimpleNamespace(), board=BOARD)
    assert out["action"] == "delete"
    tc = out["tool_calls"][0]
    assert tc["name"] == "delete_food_entry"
    assert tc["input"]["entry_id"] == 708
    assert tc["input"]["food_hint"] == "Truffle fries"


@pytest.mark.asyncio
async def test_delete_rejects_entry_not_on_board(monkeypatch):
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "delete", "deletes": [{"entry_id": 999}]}))
    out = await FT.run("remove the fries", SimpleNamespace(), board=BOARD)
    assert out is None


@pytest.mark.asyncio
async def test_update_carries_cas_expectation(monkeypatch):
    """The update op rides the board snapshot it was computed from, so the
    executor can refuse a write against a row that changed (fix #9)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "update",
        "updates": [{"entry_id": 707, "amount": 2, "unit": "tacos",
                     "calories": 360}],
        "say": "Bumped it, {batch_cal} cal."}))
    out = await FT.run("I actually had 2 birria", SimpleNamespace(), board=BOARD)
    inp = out["tool_calls"][0]["input"]
    assert inp["expected_calories"] == 180.0
    assert inp["food_hint"] == "Birria taco"


# ── consumption-evidence invariant ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_question_cannot_execute_a_log(monkeypatch):
    """Even when the model misclassifies an interrogative as log, the
    invariant drops the write (fix #5 of the critique)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Chicken Caesar salad", "amount": 1, "unit": "bowl",
                   "calories": 700}]}))
    out = await FT.run("Does a chicken caesar salad have 700 calories",
                       SimpleNamespace())
    assert out is None, "an interrogative message must never yield a log write"


@pytest.mark.asyncio
async def test_evidence_blocks_plans_and_negations_cold(monkeypatch):
    """A cold plan can't execute a log even when the model says log; a
    mid-thread addition ('also a coke with it') carries thread evidence."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "log",
        "items": [{"food": "Coke", "amount": 12, "unit": "oz", "calories": 140}]}))
    plan = await FT.run("might grab a coke later", SimpleNamespace())
    assert plan is None
    warm = await FT.run("also a coke with it", SimpleNamespace(),
                        thread_active=True)
    assert warm is not None and warm["action"] == "log"


def test_consumption_evidence_shapes():
    assert FT.consumption_evidence("had 2 eggs and toast")
    assert FT.consumption_evidence("greek yogurt for a snack")
    assert FT.consumption_evidence("half of it", prior={"original": "pizza"})
    assert not FT.consumption_evidence("would two slices ruin my day?")
    assert not FT.consumption_evidence("can I eat a bagel")
    assert not FT.consumption_evidence("did I already log the yogurt?")
    assert not FT.consumption_evidence("might grab a burger later")
    assert not FT.consumption_evidence("not having the shake today")


# ── policy engine ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_policy_holds_write_on_material_ambiguity(monkeypatch):
    """The model reports its estimated-through unknowns; the SYSTEM decides.
    250 cal of swing holds a moderate (200) write, passes a quick (300) one."""
    payload = {
        "action": "log",
        "items": [{"food": "Chicken", "amount": 1, "unit": "portion",
                   "calories": 400, "protein": 40}],
        "ambiguities": [{"item": "Chicken", "field": "quantity",
                         "impact_cal": 250}],
        "say": "Chicken logged, {batch_cal} cal."}
    monkeypatch.setattr(FT, "chat", _fake_chat(payload))
    def U(m):
        return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=m))
    held = await FT.run("had some chicken for dinner", U("moderate"))
    assert held["action"] == "ask"
    assert "chicken" in held["text"].lower()
    monkeypatch.setattr(FT, "chat", _fake_chat(payload))
    passed = await FT.run("had some chicken for dinner", U("quick"))
    assert passed["action"] == "log"


def test_material_ambiguities_thresholds():
    ambs = [{"item": "Rice", "field": "quantity", "impact_cal": 150}]
    assert FL.material_ambiguities(ambs, "strict")
    assert not FL.material_ambiguities(ambs, "moderate")
    assert not FL.material_ambiguities([{"impact_cal": "junk"}], "strict")
    assert not FL.material_ambiguities(None, "strict")


# ── bounded follow-up ask ─────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_new_ambiguity_permits_one_followup(monkeypatch):
    """'Half, but I only ate some of the fries' introduces a NEW unknown —
    one more ask is information gain, not a loop (fix #11)."""
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask", "new_ambiguity": True,
        "points": [{"label": "Fries", "q": "roughly how many?"}]}))
    out = await FT.run("half, but I only ate some of the fries",
                       SimpleNamespace(),
                       prior={"original": "burger and fries",
                              "question": "full portion or half?",
                              "ask_count": 1})
    assert out is not None and out["action"] == "ask"
    # ...but never a third
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask", "new_ambiguity": True,
        "points": [{"label": "Fries", "q": "curly or straight?"}]}))
    out2 = await FT.run("just a few", SimpleNamespace(),
                        prior={"original": "burger", "question": "how many fries?",
                               "ask_count": 2})
    assert out2 is None
    # ...and an unflagged model re-ask is still refused
    monkeypatch.setattr(FT, "chat", _fake_chat({
        "action": "ask", "points": [{"label": "X", "q": "more?"}]}))
    out3 = await FT.run("almost all", SimpleNamespace(),
                        prior={"original": "pizza", "question": "how much?",
                               "ask_count": 1})
    assert out3 is None


# ── pending-state expiry ──────────────────────────────────────────────────────
def test_pending_expiry_scales_by_kind():
    fresh = SimpleNamespace(asked_at=datetime.utcnow() - timedelta(minutes=5),
                            last_asked_at=None)
    stale_confirm = SimpleNamespace(
        asked_at=datetime.utcnow() - timedelta(minutes=45), last_asked_at=None)
    ancient = SimpleNamespace(
        asked_at=datetime.utcnow() - timedelta(hours=5), last_asked_at=None)
    assert not FL.pending_expired(fresh, "confirm")
    assert FL.pending_expired(stale_confirm, "confirm")
    assert not FL.pending_expired(stale_confirm, "clarify")
    assert FL.pending_expired(ancient, "clarify")
    # No timestamp at all → never expired (fail open, the answer flow resolves it)
    assert not FL.pending_expired(SimpleNamespace(asked_at=None,
                                                  last_asked_at=None), "confirm")


# ── idempotency ───────────────────────────────────────────────────────────────
def test_duplicate_turn_is_absorbed():
    calls = [{"name": "log_food",
              "input": {"food_name": "Banana", "quantity": "1 banana"}}]
    key = FL.turn_idempotency_key(42, "had a banana", calls)
    assert not FL.already_processed(key)
    FL.mark_processed(key)
    assert FL.already_processed(key)
    # A different message is a different turn
    other = FL.turn_idempotency_key(42, "had another banana", calls)
    assert other != key and not FL.already_processed(other)
    # And the window closes
    FL._SEEN[key] = time.monotonic() - 10_000
    assert not FL.already_processed(key)


# ── graded thread relevance ───────────────────────────────────────────────────
def test_thread_intents_classified():
    C = FT.classify_thread_intent
    assert C("that was actually two bags") == "correction"
    assert C("also had a coke") == "report"
    assert C("okay cool log it") == "report"
    assert C("remove the taco") == "deletion"
    assert C("why did you count the sauce?") == "question"
    assert C("what should I eat tonight?") == "question"
    assert C("that seems way too high") == "estimate_challenge"
    assert C("I'm still hungry") == "coaching"
    assert C("that restaurant was terrible") == "commentary"
    assert C("never mind") == "ack"
    assert C("clear my whole day") == "other"
    assert C("bench press 135x10") == "other_domain"


def test_thread_relevance_is_graded_not_a_takeover():
    R = FT.thread_relevance
    # minutes-old write: reports and corrections route
    assert R("also had a coke", 5, False)
    assert R("that was actually two bags", 5, False)
    # commentary and challenges never do, even seconds after a write
    assert not R("that restaurant was terrible", 2, False)
    assert not R("that seems way too high", 2, False)
    assert not R("why did you count the sauce?", 2, False)
    # an hours-old write binds only explicit corrections/removals
    assert R("actually it was grilled", 60, False)
    assert R("remove the fries", 60, False)
    assert not R("had a sandwich", 60, False)
    assert not R("actually it was grilled", 180, False)
    # an open ask binds bare fragments as answers
    assert R("half of it", None, True)
    assert not R("how many calories was that?", None, True)


def test_destructive_gate_shapes():
    assert FT.applies_destructive("remove the truffle fries")
    assert FT.applies_destructive("undo that")
    assert not FT.applies_destructive("clear my whole day")
    assert not FT.applies_destructive("remove the bench press set")
    assert not FT.applies_destructive("should I remove the fries?")


# ── renderer ──────────────────────────────────────────────────────────────────
def _snap(**kw):
    base = dict(batch_cal=340, batch_protein=28, day_cal=1200, day_protein=90,
                cal_target=2165, protein_target=180,
                logged=("Caesar salad", "Chicken strips"))
    base.update(kw)
    return FL.TransactionSnapshot(**base)


def test_renderer_fills_safe_say_from_snapshot():
    out = FL.render_committed(
        "Both logged, {batch_cal} cal and {batch_protein}g protein. "
        "You're at {day_cal} with {cal_left} left.", "", "", _snap())
    assert out == ("Both logged, 340 cal and 28g protein. "
                   "You're at 1200 with 965 left.")


def test_renderer_rejects_semantic_claims():
    """'Great protein-heavy breakfast' has no digits — the numeric contract
    can't see it. The claim filter can (fix #6 of the critique)."""
    out = FL.render_committed("Great protein-heavy breakfast, nicely balanced meal.",
                              "", "", _snap())
    assert "protein-heavy" not in out and "balanced" not in out
    assert "340 cal" in out and "Caesar salad" in out


def test_renderer_deterministic_line_for_deletes():
    out = FL.render_committed("", "", "", _snap(
        logged=(), deleted=("Truffle fries",), batch_cal=0, batch_protein=0))
    assert "Took the Truffle fries off the board." in out
    assert "You're at 1200" in out


def test_renderer_appends_whitelisted_follow_up_only():
    out = FL.render_committed("Logged, {batch_cal} cal.", "",
                              "save_as_regular", _snap())
    assert "|||" in out and "regulars" in out
    out2 = FL.render_committed("Logged, {batch_cal} cal.", "",
                               "tell_me_your_weight", _snap())
    assert "|||" not in out2


def test_note_sanitizer():
    assert FL.sanitize_note("Solid choice before tonight's session.") \
        == "Solid choice before tonight's session."
    assert FL.sanitize_note("You've used about half your calories") == ""
    assert FL.sanitize_note("That's 300 cal of pure win") == ""
    assert FL.sanitize_note("Plenty of fiber in there") == ""
    assert FL.sanitize_note("Want a lighter dinner?") == ""


# ── emoji policing ────────────────────────────────────────────────────────────
# Bug (Danny 2026-07-29): the interpreter's own _SYSTEM prompt (core/food_turn.py)
# never mentions emoji and every "say" example it's shown carries none — the call
# has no persona/voice prompt in its context at all, so any emoji in its output is
# the model's unguided default style. A wrong one shipped (a tomato for a
# cucumber). Policed at the same funnel that already strips ~ and em-dash.
def test_render_committed_strips_stray_emoji():
    out = FL.render_committed(
        "Cucumber logged \U0001F345, {batch_cal} cal and {batch_protein}g "
        "protein.", "", "", _snap())
    assert "\U0001F345" not in out
    assert "340 cal" in out


def test_strip_stray_emoji_removes_checkmarks_and_food_emoji():
    assert FL.strip_stray_emoji("Updated to 1 cucumber ✅") == "Updated to 1 cucumber "
    assert FL.strip_stray_emoji("Rice cake logged \U0001F345") == "Rice cake logged "
    assert FL.strip_stray_emoji("No emoji here.") == "No emoji here."


def test_note_sanitizer_strips_emoji():
    assert FL.sanitize_note("Solid choice \U0001F525 before tonight's session.") \
        == "Solid choice before tonight's session."


# ── executor CAS ──────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_update_cas_refuses_stale_board(monkeypatch):
    """The executor refuses an update whose board snapshot no longer matches
    the row — stale-scale corruption becomes a re-read instead (fix #9)."""
    import handlers.tool_executor as TE

    class _Row:
        calories = 500.0

    class _DB:
        async def get(self, model, eid):
            return _Row()
        async def refresh(self, *a, **k):
            pass
        async def commit(self, *a, **k):
            pass

    applied = {}
    async def fake_update(db, entry_id, user_id, **changes):
        applied["changes"] = changes
        return SimpleNamespace(id=entry_id, parsed_food_name="Birria taco",
                               calories=360, protein=30, fats=None, carbs=None,
                               fiber=None, sugar=None, sodium=None,
                               quantity="2 tacos")
    monkeypatch.setattr(TE, "q_update_food_entry", fake_update)

    user = SimpleNamespace(id=1, timezone="UTC")
    today = SimpleNamespace(id=9, food_entries=[])
    stale = await TE._dispatch(
        "update_food_entry",
        {"entry_id": 707, "quantity": "2 tacos", "calories": 360,
         "expected_calories": 180.0, "food_hint": "Birria taco"},
        user, today, _DB(), "text")
    assert "STALE BOARD" in stale
    assert "changes" not in applied, "a stale update must not reach the DB"

    # Matching expectation applies — and the carrier fields never become columns.
    class _RowFresh:
        calories = 180.0

    class _DBFresh(_DB):
        async def get(self, model, eid):
            return _RowFresh()
    ok = await TE._dispatch(
        "update_food_entry",
        {"entry_id": 707, "quantity": "2 tacos", "calories": 360,
         "expected_calories": 180.0, "food_hint": "Birria taco"},
        user, today, _DBFresh(), "text")
    assert "Updated" in ok
    assert "expected_calories" not in applied["changes"]
    assert "food_hint" not in applied["changes"]
    assert applied["changes"]["calories"] == 360


# ── executor-result awareness + per-kind batch (2026-07-24 cleanup audit) ─────
def test_successful_calls_reads_executor_results():
    calls = [
        {"name": "update_food_entry",
         "input": {"entry_id": 1, "calories": 360,
                   "_result": "STALE BOARD: entry #1 is now 500 cal, not 180."}},
        {"name": "log_food",
         "input": {"food_name": "Coke", "calories": 140,
                   "_result": "Logged Coke: 140 cal."}},
        {"name": "log_food",
         "input": {"food_name": "Banana", "calories": 105}},   # unstamped → ok
    ]
    ok = FL.successful_calls(calls)
    assert [c["input"].get("food_name") for c in ok] == ["Coke", "Banana"]
    assert FL.failed_call_names(calls) == ["entry #1"]


def test_compute_batch_per_kind_semantics():
    log_call = {"name": "log_food", "input": {"food_name": "Coke",
                                              "calories": 140, "protein": 0}}
    up_call = {"name": "update_food_entry", "input": {"entry_id": 1,
                                                      "calories": 360,
                                                      "protein": 30}}
    # Pure log: post-enrichment day delta wins when positive...
    assert FL.compute_batch("log", [log_call], 150, 1) == (150, 1)
    # ...inputs when the refresh missed.
    assert FL.compute_batch("log", [log_call], 0, 0) == (140, 0)
    # Update: the entry's NEW value, never the day delta (+95 bump ≠ a food).
    assert FL.compute_batch("update", [up_call], 95, 8) == (360, 30)
    # Mixed commit: the LOGGED item's own numbers — never the folded day
    # delta ('Coke logged, 320 cal' for a 140-cal Coke was the audit find).
    assert FL.compute_batch("commit", [up_call, log_call], 320, 30) == (140, 0)
    # Delete-only: nothing logged, batch zero — and never negative.
    del_call = {"name": "delete_food_entry", "input": {"entry_id": 2}}
    assert FL.compute_batch("delete", [del_call], -180, -12) == (0, 0)


def test_snapshot_counts_restores_as_logged():
    snap = FL.build_snapshot(
        [{"name": "restore_food_entry",
          "input": {"food_name": "Truffle fries", "calories": 190}}],
        190, 2, 1400, 80, 2100, 180)
    assert snap.logged == ("Truffle fries",)


def test_say_contract_allows_food_hint_digits():
    """An undo/delete narration names the board entry via food_hint — its
    digits ('5-hour Energy') are the system's own write, never an invented
    total (2026-07-24 cleanup audit)."""
    calls = [{"name": "delete_food_entry",
              "input": {"entry_id": 3, "food_hint": "5-hour Energy"}}]
    say = ("Undone, took the 5-hour Energy off the board. "
           "You're at {day_cal} with {cal_left} left.")
    assert FT.enforce_say_contract(say, calls) == say
