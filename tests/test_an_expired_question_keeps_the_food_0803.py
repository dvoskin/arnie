"""The question expires. The food does not.

Since `FOOD_PARTIAL_COMMIT` defaults false, an ask writes NOTHING — the whole
understood meal lives only as `deferred_calls` inside the pending question's
`payload_json`, and the only thing that ever commits it is `_settle_deferred`
at `run()`'s exit, which needs the user to send another turn.

`core/conversation.py` retired an expired pending WITHOUT reading that payload.
On `origin/main` that cost one item, because the ready foods had already been
written by partial commit. With the flag flipped it costs THE MEAL — every food
the user reported, gone, with no tombstone and no log line naming them. The
branch's headline change created the exact silent-loss class the branch exists
to close.

Settled at expiry rather than deferred to the next turn, because expiry is the
last moment anything knows the food exists: the next turn may not be a food
turn, and then `run()` never executes and `_settle_deferred` never runs.

WHAT IS DELIBERATELY NOT RESCUED: the asked-about item. It rides `staged_items`,
it genuinely has no answer, and inventing one is the opposite of the fix.
`deferred_calls` is the rest of the meal — foods the user reported, that we
understood and priced, held back only because a DIFFERENT item raised a
question. Their day was never in doubt, only their company.
"""
import pytest

from core.conversation import _settle_expired_deferred


class _FakeLog:
    id = 1
    date = None


def _call(name, cal=100):
    return {"name": "log_food",
            "input": {"food_name": name, "quantity": "1", "calories": cal}}


@pytest.mark.asyncio
async def test_the_held_meal_is_committed_when_the_question_ages_out(monkeypatch):
    import core.conversation as CV
    seen = {}

    async def _exec(calls, user, today_log, db, source_type="text", **kw):
        seen["calls"] = calls
        return {}

    monkeypatch.setattr(CV, "execute_tool_calls", _exec)
    _calls, _results = await _settle_expired_deferred(
        None, _user(), {"deferred_calls": [_call("Corn"), _call("Rice")]},
        _FakeLog())
    # WHAT it committed, not how many. A count cannot become a card, and
    # returning one is why held food landed in the day total and rendered
    # nothing — see `test_the_settled_food_gets_a_card` below.
    assert len(_calls) == 2
    assert [(c["input"]["food_name"]) for c in seen["calls"]] == ["Corn", "Rice"]


@pytest.mark.asyncio
async def test_a_meal_held_overnight_lands_on_the_day_it_was_eaten(monkeypatch):
    """`log_food` already accepts `input["date"]` and resolves the target day
    via `get_or_create_log_for_date`, so the past-day case needs no new
    machinery — only that the stashed date is carried onto the call."""
    import core.conversation as CV
    seen = {}

    async def _exec(calls, user, today_log, db, source_type="text", **kw):
        seen["calls"] = calls
        return {}

    monkeypatch.setattr(CV, "execute_tool_calls", _exec)
    await _settle_expired_deferred(
        None, _user(),
        {"deferred_calls": [_call("Corn")], "log_date": "2026-08-02"},
        _FakeLog())
    assert seen["calls"][0]["input"]["date"] == "2026-08-02"


@pytest.mark.asyncio
async def test_a_call_that_names_its_own_day_keeps_it(monkeypatch):
    import core.conversation as CV
    seen = {}

    async def _exec(calls, user, today_log, db, source_type="text", **kw):
        seen["calls"] = calls
        return {}

    monkeypatch.setattr(CV, "execute_tool_calls", _exec)
    c = _call("Corn")
    c["input"]["date"] = "2026-07-30"
    await _settle_expired_deferred(
        None, _user(), {"deferred_calls": [c], "log_date": "2026-08-02"},
        _FakeLog())
    assert seen["calls"][0]["input"]["date"] == "2026-07-30"


@pytest.mark.asyncio
async def test_an_empty_payload_writes_nothing():
    assert await _settle_expired_deferred(None, _user(), {}, _FakeLog()) \
        == ([], [])
    assert await _settle_expired_deferred(None, _user(), None, _FakeLog()) \
        == ([], [])


@pytest.mark.asyncio
async def test_it_never_raises(monkeypatch):
    """A failure here must degrade to the OLD behaviour — the food is lost —
    rather than cost the user the reply they are waiting for."""
    import core.conversation as CV

    async def _boom(*a, **k):
        raise RuntimeError("executor down")

    monkeypatch.setattr(CV, "execute_tool_calls", _boom)
    assert await _settle_expired_deferred(
        None, _user(), {"deferred_calls": [_call("Corn")]}, _FakeLog()) \
        == ([], [])


@pytest.mark.asyncio
async def test_the_settled_food_gets_a_card(monkeypatch):
    """THE OTHER HALF OF "the food did not expire": it has to be VISIBLE.

    Live, 2026-08-04 — "Having some chicken and rice". The rice was held, the
    clarification resolved, the rice committed and moved the day's totals, and
    it appeared on no card on any turn. The user saw a total that matched
    nothing on screen and reasonably concluded the meal was wrong.

    The cause is structural rather than a missed branch. `_logged_entry_card`
    is gated on an `entry_id`, and since P0.3e ("executor immutability
    complete") that id exists ONLY on the typed `CallResult` —
    `execution_result.stash` is explicit that the command input is never
    written. So a settle that discarded what the executor published had
    destroyed the only object a card can be built from, and no amount of
    downstream care could recover it.

    This pins the RESULTS coming back, which is what makes the card possible.
    """
    import core.conversation as CV
    from core.execution_result import (LAST_EXECUTION, ExecutionResult,
                                       CallResult)

    _inp = {"food_name": "White rice", "quantity": "1 cup", "calories": 205}
    _committed = CallResult(name="log_food", raw_input=_inp, entry_id=4242,
                            status="committed")

    async def _exec(calls, user, today_log, db, source_type="text", **kw):
        LAST_EXECUTION.set(ExecutionResult(calls=(_committed,)))
        return {}

    monkeypatch.setattr(CV, "execute_tool_calls", _exec)
    _calls, _results = await _settle_expired_deferred(
        None, _user(), {"deferred_calls": [{"name": "log_food",
                                            "input": _inp}]},
        _FakeLog())
    assert len(_calls) == 1
    assert [r.entry_id for r in _results] == [4242], (
        "without the typed result there is no entry_id, and without an "
        "entry_id there is no card")
    # And that result really does render — the same builder run_turn uses.
    card = CV._logged_entry_card("log_food", None, call=_results[0])
    assert card is not None and card["type"] == "macro_card"
    assert card["payload"]["entry_id"] == 4242


def _user():
    from types import SimpleNamespace
    return SimpleNamespace(id=1, timezone="UTC")


# ── and a stash may pay its debt without taking the turn ──────────────────────

def test_a_legacy_fall_through_writes_the_food_but_not_the_reply():
    """`out is None` means the interpreter passed or failed and the turn
    belongs to the conversational brain — `_to_legacy("interpreter_none")` calls
    that "the most common one".

    Returning a log plan there made `_sft` non-None, so the structured branch
    took the turn and the food composer answered over the recovered rows: a
    coaching question, a non-food message, or a model failure on a turn with an
    open stash got a meal recap instead of an answer. The debt still has to be
    paid; it just may not buy the microphone.
    """
    import core.food_turn as FT
    out = FT._settle_deferred(None, {"deferred_calls": [_call("Corn")]})
    assert out["action"] == "log"
    assert out["_writes_only"] is True, (
        "the recovered rows would take the turn away from legacy")
    assert [c["input"]["food_name"] for c in out["tool_calls"]] == ["Corn"]


def test_no_stash_leaves_a_declined_turn_completely_alone():
    import core.food_turn as FT
    assert FT._settle_deferred(None, {}) is None
    assert FT._settle_deferred(None, None) is None
