"""THE TWO-TURN INVARIANT: ask, then answer — every reported food, exactly once.

The gap this closes (open task #26). Every food-turn test in this suite drives
ONE turn. `test_leave_no_food_behind.py` asserts what the ASK writes;
`test_the_answer_applies_the_resolution.py` asserts what the ANSWER writes given
a hand-built prior. Nothing joined them, and the join is where the class of bug
lives: "150g turkey and a corn" lost the corn ACROSS the pair — the ask didn't
write it and the answer didn't mention it. Neither turn looks wrong on its own.

So these run the real `FT.run` twice, threading the ask's return into the answer
turn through the SAME payload `core/conversation.py` stashes, and count rows
across BOTH turns. The counting is the assertion: not "did it write" but "does
each food exist exactly once when the exchange is over".

The answer turn's interpreter is mocked to be UNRELIABLE on purpose — dropping a
food, renaming one, re-emitting all of them — because that unreliability is the
premise. `_orphan_calls`' own words: "the interpreter's sorting of items/ready/
points is not reliable enough to trust with data integrity."

Flag-agnostic by construction: the invariant is the same whether the ask writes
immediately or defers, so every case runs under both settings of
FOOD_PARTIAL_COMMIT. That is what makes this a gate on the switch rather than a
description of one side of it.
"""
import json
from types import SimpleNamespace

import pytest

import core.food_turn as FT


BOTH = pytest.mark.parametrize("partial", ["true", "false"])


def _chat_returning(*payloads):
    """A fake interpreter that answers each successive turn from `payloads`."""
    seq = list(payloads)

    async def fc(messages, system, tools=True, max_tokens=0, model=None, **k):
        fc.calls += 1
        fc.last_content = messages[-1]["content"]
        payload = seq.pop(0) if len(seq) > 1 else seq[0]
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    fc.calls = 0
    return fc


def _user():
    return SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode="moderate"))


def _item(food, cal=100, **kw):
    return {"food": food, "amount": 1, "unit": "", "calories": cal,
            "protein": 5, "carbs": 10, "fats": 3, **kw}


def _logged(*outs):
    """Every food_name written across the turns, in order, normalized.

    Deliberately a LIST and not a set — "exactly once" is the assertion, and a
    set is how a double-write hides.
    """
    from skills.nutrition.food_dedup import normalize_food_name
    names = []
    for out in outs:
        for call in ((out or {}).get("tool_calls") or []):
            if call.get("name") != "log_food":
                continue
            names.append(normalize_food_name(
                (call.get("input") or {}).get("food_name")))
    return names


def _prior_from(ask_out, original, question=""):
    """The pending-question payload, exactly as core/conversation.py stashes it.

    Round-tripped through JSON because that is what the DB column holds — a
    payload that only survives in memory is not a payload that survives the
    turn. This mirrors the whitelist in `record_pending_question`'s caller; if
    that dict and this one drift, an ask stops carrying what it staged and
    these tests are how it gets caught.
    """
    return json.loads(json.dumps({
        "original": original,
        "question": question or (ask_out or {}).get("text") or "",
        "kind": (ask_out or {}).get("kind") or "clarify",
        "ask_count": 1,
        "items": (ask_out or {}).get("items") or None,
        "response_schema": (ask_out or {}).get("response_schema") or "",
        "question_id": (ask_out or {}).get("question_id") or "",
        "staged_item_id": (ask_out or {}).get("staged_item_id") or "",
        "staged_items": (ask_out or {}).get("staged_items") or [],
        "deferred_calls": (ask_out or {}).get("deferred_calls") or [],
        "requested_fields": list((ask_out or {}).get("requested_fields") or ()),
        "options": list((ask_out or {}).get("options") or ()),
        "questions": list((ask_out or {}).get("questions") or ()),
        "meal_group_id": (ask_out or {}).get("meal_group_id") or "",
        "log_date": "",
    }))


async def _exchange(monkeypatch, *, message, ask_payload, answer_payload,
                    answer="150g", user=None):
    """Ask, stash, answer. Returns (ask_out, answer_out)."""
    user = user or _user()
    monkeypatch.setattr(FT, "chat", _chat_returning(ask_payload))
    ask = await FT.run(message, user)
    assert ask is not None and ask["action"] == "ask", (
        f"turn 1 was meant to raise a question, got {ask and ask['action']}")
    monkeypatch.setattr(FT, "chat", _chat_returning(answer_payload))
    reply = await FT.run(answer, user, prior=_prior_from(ask, message))
    return ask, reply


# ── The prod bug, end to end ────────────────────────────────────────────────

@BOTH
@pytest.mark.asyncio
async def test_the_corn_survives_a_turkey_clarification(monkeypatch, partial):
    """"150g turkey and a corn" — the corn is an ORPHAN on the ask (in `items`,
    neither asked about nor `ready`) and the answer turn forgets it entirely.
    That pair is the production drop. It must land exactly once regardless."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", partial)
    ask, reply = await _exchange(
        monkeypatch,
        message="150g turkey and a corn",
        ask_payload={"action": "ask",
                     "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
                     "items": [_item("Turkey", 220), _item("Corn", 90)]},
        # THE ANSWER TURN LOSES THE CORN — the whole premise. It re-reads the
        # original message and reports only the food it was asked about.
        answer_payload={"action": "log", "items": [_item("Turkey", 220)]})
    names = _logged(ask, reply)
    assert names.count("corn") == 1, f"the corn was lost or doubled: {names}"
    assert names.count("turkey") == 1, f"the turkey was lost or doubled: {names}"


@BOTH
@pytest.mark.asyncio
async def test_a_ready_food_survives_when_the_answer_forgets_it(monkeypatch,
                                                                partial):
    """The same drop one slot over: the interpreter sorted the food into
    `ready` (settled, not asked about) and the answer turn never mentions it."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", partial)
    ask, reply = await _exchange(
        monkeypatch,
        message="a spoon of peanut butter and a banana",
        ask_payload={"action": "ask",
                     "points": [{"label": "Peanut butter", "qs": ["how much?"]}],
                     "items": [_item("Peanut butter", 350)],
                     "ready": [_item("Banana", 105)]},
        answer_payload={"action": "log",
                        "items": [_item("Peanut butter", 190)]})
    names = _logged(ask, reply)
    assert names.count("banana") == 1, f"the banana was lost or doubled: {names}"
    assert names.count("peanut butter") == 1, f"bad peanut butter: {names}"


# ── The other half: no double-writes ────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_re_emitted_food_is_not_written_twice(monkeypatch):
    """The answer turn re-reads the ORIGINAL message, so it usually re-emits
    every food — including the ones already settled. Both calls land in the
    SAME batch, where the executor's dedup cannot see them (it filters to the
    entry ids that existed before the batch), so nothing downstream would catch
    a second row. It has to not be built.

    Flag-OFF only, and `test_the_writing_ask_has_no_such_guarantee` below is
    why: this is the half of the exchange where the guard can be deterministic
    at all, because both readings are in this process at the same moment."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    ask, reply = await _exchange(
        monkeypatch,
        message="150g turkey and a corn",
        ask_payload={"action": "ask",
                     "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
                     "items": [_item("Turkey", 220), _item("Corn", 90)]},
        # The ordinary case: the answer turn reports the WHOLE meal back.
        answer_payload={"action": "log",
                        "items": [_item("Turkey", 240), _item("Corn", 90)]})
    names = _logged(ask, reply)
    assert names.count("corn") == 1, f"the corn was written twice: {names}"
    assert names.count("turkey") == 1, f"the turkey was written twice: {names}"


@pytest.mark.asyncio
async def test_the_writing_ask_has_no_such_guarantee(monkeypatch):
    """THE ASYMMETRY, PINNED — the reason the switch is worth throwing.

    With the partial commit ON the settled food is already a row, so the only
    thing standing between the answer turn and a second one is the model
    choosing to UPDATE instead of LOG. That steer is real but it is a PROMPT
    LINE: `_board_lines` renders "JUST LOGGED, seconds ago" and the interpreter
    is asked to prefer an update. Nothing enforces it, and when the model
    re-emits the food anyway — as it does here — the write lands twice, because
    the first row is in the database and the second is in a fresh batch that
    the executor's snapshot-filtered dedup deliberately will not block.

    Held, the same two readings meet inside one plan and the duplicate is
    dropped before anything is written. This test exists so that difference
    stays visible if anyone reaches for the switch again."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "true")
    ask, reply = await _exchange(
        monkeypatch,
        message="150g turkey and a corn",
        ask_payload={"action": "ask",
                     "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
                     "items": [_item("Turkey", 220), _item("Corn", 90)]},
        answer_payload={"action": "log",
                        "items": [_item("Turkey", 240), _item("Corn", 90)]})
    assert _logged(ask, reply).count("corn") == 2, (
        "the writing path grew a deterministic dedup — if that is real, this "
        "test should become an equality with the held path, not be deleted")


@pytest.mark.asyncio
async def test_the_answers_own_reading_of_a_held_food_wins(monkeypatch):
    """When both readings exist, the ANSWER turn's is kept: the user has just
    spoken, and their reply may have revised a food we were not asking about.
    The stash is a backstop, not an override."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    ask, reply = await _exchange(
        monkeypatch,
        message="a spoon of peanut butter and a banana",
        answer="a tablespoon, and the banana was a big one",
        ask_payload={"action": "ask",
                     "points": [{"label": "Peanut butter", "qs": ["how much?"]}],
                     "items": [_item("Peanut butter", 350)],
                     "ready": [_item("Banana", 105)]},
        answer_payload={"action": "log",
                        "items": [_item("Peanut butter", 190),
                                  _item("Banana", 135)]})
    banana = [c for c in ((reply or {}).get("tool_calls") or [])
              if (c.get("input") or {}).get("food_name") == "Banana"]
    assert len(banana) == 1, "the banana landed twice"
    assert banana[0]["input"]["calories"] == 135, (
        "the stash overrode a correction the user had just made")


# ── Every disposition the answer turn can take ──────────────────────────────

@pytest.mark.asyncio
async def test_a_held_food_survives_the_answer_falling_to_legacy(monkeypatch):
    """The interpreter returning None hands the turn to the legacy path — and
    with it, a meal nobody else knows about. This is the disposition that made
    the exit the right place to settle the debt rather than the plan."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), _item("Corn", 90)]}))
    ask = await FT.run("150g turkey and a corn", user)
    # The interpreter fails outright on the answer turn.
    monkeypatch.setattr(FT, "chat", _chat_returning({"action": "pass"}))
    reply = await FT.run("150g", user, prior=_prior_from(ask, "150g turkey and a corn"))
    assert _logged(ask, reply).count("corn") == 1, "the corn went to legacy"


@pytest.mark.asyncio
async def test_cancelling_the_meal_writes_nothing_at_all(monkeypatch):
    """The one disposition that discards the stash. "Nothing went on the board"
    has to be true of the held foods too."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), _item("Corn", 90)]}))
    ask = await FT.run("150g turkey and a corn", user)
    assert ask.get("deferred_calls"), "nothing was staged to cancel"
    reply = await FT.run("cancel the meal", user,
                         prior=_prior_from(ask, "150g turkey and a corn"))
    assert not _logged(ask, reply), "a cancelled meal put rows on the board"


@pytest.mark.asyncio
async def test_skipping_the_asked_item_still_lands_everything_else(monkeypatch):
    """"Left that one off. Everything else stands." — everything else has to
    actually stand, which under a held ask means it has to be written now."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), _item("Corn", 90)]}))
    ask = await FT.run("150g turkey and a corn", user)
    reply = await FT.run("skip it", user,
                         prior=_prior_from(ask, "150g turkey and a corn"))
    names = _logged(ask, reply)
    assert names.count("corn") == 1, f"'everything else' did not stand: {names}"
    assert "turkey" not in names, "the skipped item was logged anyway"


@pytest.mark.asyncio
async def test_the_stash_rides_a_second_question_forward(monkeypatch):
    """A re-ask must not drop what the first ask was holding — otherwise the
    fix only covers exchanges that end on the first answer."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), _item("Corn", 90)]}))
    ask = await FT.run("150g turkey and a corn", user)
    # The user asks US a question back, which is one of the two lifts that let
    # the answer turn ask again.
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask", "new_ambiguity": True,
        "points": [{"label": "Turkey", "qs": ["breast or thigh?"]}],
        "items": [_item("Turkey", 220)]}))
    second = await FT.run("what kind do you mean?", user,
                          prior=_prior_from(ask, "150g turkey and a corn"))
    assert second is not None and second["action"] == "ask"
    carried = [(c.get("input") or {}).get("food_name")
               for c in (second.get("deferred_calls") or [])]
    assert "Corn" in carried, f"the corn fell out of the re-ask: {carried}"


@pytest.mark.asyncio
async def test_the_stash_does_not_double_when_it_rides_forward(monkeypatch):
    """Carrying forward must be idempotent — a three-turn exchange that
    accumulated the same food twice would write it twice at the end."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    original = "150g turkey and a corn"
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), _item("Corn", 90)]}))
    ask = await FT.run(original, user)
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask", "new_ambiguity": True,
        "points": [{"label": "Turkey", "qs": ["breast or thigh?"]}],
        "items": [_item("Turkey", 220)]}))
    second = await FT.run("what kind do you mean?", user,
                          prior=_prior_from(ask, original))
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "log", "items": [_item("Turkey", 220)]}))
    third = await FT.run("breast", user, prior=_prior_from(second, original))
    names = _logged(ask, second, third)
    assert names.count("corn") == 1, f"the corn accumulated: {names}"


# ── The staging contract itself ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_an_ask_that_writes_nothing_still_stages_everything(monkeypatch):
    """The switch decides WHEN the settled foods are written, never WHETHER.
    With it off the ask carries no writes and the same rows ride the question
    instead — byte for byte, because one `_log_call` built both."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "true")
    user = _user()
    payload = {"action": "ask",
               "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
               "items": [_item("Turkey", 220), _item("Corn", 90)],
               "ready": [_item("Rice", 200)]}
    monkeypatch.setattr(FT, "chat", _chat_returning(payload))
    writing = await FT.run("150g turkey, a corn and rice", user)
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    monkeypatch.setattr(FT, "chat", _chat_returning(payload))
    holding = await FT.run("150g turkey, a corn and rice", user)

    assert not (holding.get("tool_calls") or []), "a held ask carried writes"
    assert (writing.get("tool_calls") or []) == (holding.get("deferred_calls") or []), (
        "the deferred rows are not the rows the partial commit would have made")
    assert not (writing.get("deferred_calls") or []), (
        "a writing ask also stashed — the same food would land twice")


@pytest.mark.asyncio
async def test_the_asked_food_is_never_staged(monkeypatch):
    """The held item waits for its answer; it is not in the stash, or the
    question would answer itself."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), _item("Corn", 90)]}))
    ask = await FT.run("150g turkey and a corn", user)
    staged = [(c.get("input") or {}).get("food_name")
              for c in (ask.get("deferred_calls") or [])]
    assert staged == ["Corn"], f"the asked food was staged too: {staged}"


@pytest.mark.asyncio
async def test_a_food_with_no_calories_is_not_staged_as_a_phantom(monkeypatch):
    """A name with no number cannot be written, so it cannot be deferred into a
    write either — the deferral must not become a way to smuggle a phantom row
    past the guard that rejects it today."""
    monkeypatch.setenv("FOOD_PARTIAL_COMMIT", "false")
    user = _user()
    monkeypatch.setattr(FT, "chat", _chat_returning({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [_item("Turkey", 220), {"food": "Corn"}]}))
    ask = await FT.run("150g turkey and a corn", user)
    assert not (ask.get("deferred_calls") or []), "staged a food with no macros"
