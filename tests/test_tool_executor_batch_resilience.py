"""One failing tool must NOT abort the whole batch.

execute_tool_calls runs each tool call in its own try/except (handlers/
tool_executor.py ~1213). A tool that raises is recorded as an "Error: ..."
result keyed by its name, and the loop keeps going — so a single bad call can't
lose the sibling logs in the same turn. These tests pin that isolation by
monkeypatching the internal `_dispatch` so a chosen tool raises while the others
return a benign string.
"""
import pytest

import handlers.tool_executor as te
from db.queries import get_or_create_today_log


@pytest.fixture
def patched_dispatch(monkeypatch):
    """Replace _dispatch: the tool named 'raiser' throws, everything else echoes
    '<name> ok'. Records every name it was asked to dispatch so tests can prove
    the loop did not abort early."""
    dispatched: list[str] = []

    async def fake_dispatch(name, inp, *args, **kwargs):
        dispatched.append(name)
        if name == "raiser":
            raise RuntimeError("boom")
        return f"{name} ok"

    monkeypatch.setattr(te, "_dispatch", fake_dispatch)
    return dispatched


async def _today_log(db, user):
    """Eager-loaded today log (mirrors the prod call site — the relationships must
    be loaded before execute_tool_calls touches them under async SQLite)."""
    return await get_or_create_today_log(db, user.id, "UTC")


async def test_raising_tool_is_caught_and_siblings_survive(db, make_user, patched_dispatch):
    user = await make_user(timezone="UTC")
    log = await _today_log(db, user)
    tool_calls = [
        {"name": "good_one", "input": {}},
        {"name": "raiser", "input": {}},
        {"name": "good_two", "input": {}},
    ]

    # Must not raise despite the middle tool throwing.
    results = await te.execute_tool_calls(tool_calls, user, log, db)

    assert isinstance(results, dict)
    # The failure is recorded as an Error result, keyed by the tool name.
    assert results["raiser"].startswith("Error:")
    assert "boom" in results["raiser"]
    # The sibling tools still ran and their results are present.
    assert results["good_one"] == "good_one ok"
    assert results["good_two"] == "good_two ok"
    # Every tool in the batch was dispatched — the loop did not abort at the raise.
    assert patched_dispatch == ["good_one", "raiser", "good_two"]


async def test_batch_all_succeed_when_none_raise(db, make_user, patched_dispatch):
    """Control: with no raising tool the whole batch returns clean results."""
    user = await make_user(timezone="UTC")
    log = await _today_log(db, user)
    tool_calls = [
        {"name": "alpha", "input": {}},
        {"name": "beta", "input": {}},
    ]
    results = await te.execute_tool_calls(tool_calls, user, log, db)
    assert results == {"alpha": "alpha ok", "beta": "beta ok"}
    assert patched_dispatch == ["alpha", "beta"]


async def test_trailing_tool_after_failure_still_executes(db, make_user, patched_dispatch):
    """A tool AFTER the failing one must still execute and be recorded — the
    batch loss-free property, not just 'the error is caught'."""
    user = await make_user(timezone="UTC")
    log = await _today_log(db, user)
    tool_calls = [
        {"name": "raiser", "input": {}},
        {"name": "survivor", "input": {}},
    ]
    results = await te.execute_tool_calls(tool_calls, user, log, db)
    assert results["raiser"].startswith("Error:")
    assert results["survivor"] == "survivor ok"
    assert "survivor" in patched_dispatch


async def test_multiple_failures_each_recorded_as_error(db, make_user, patched_dispatch):
    """Two raising calls plus a good one: both failures recorded, good one wins.
    (Both raisers share the 'raiser' key — last-write-wins on the dict, but the
    key is present as an Error and the good tool survives regardless.)"""
    user = await make_user(timezone="UTC")
    log = await _today_log(db, user)
    tool_calls = [
        {"name": "raiser", "input": {}},
        {"name": "keeper", "input": {}},
        {"name": "raiser", "input": {}},
    ]
    results = await te.execute_tool_calls(tool_calls, user, log, db)
    assert results["raiser"].startswith("Error:")
    assert results["keeper"] == "keeper ok"
    # Both raising calls were attempted; the loop never short-circuited.
    assert patched_dispatch == ["raiser", "keeper", "raiser"]
