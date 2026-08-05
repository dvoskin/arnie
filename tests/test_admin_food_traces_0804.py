"""The shadows become readable, and the endpoint reports its own limits.

Every shadow in this migration emits telemetry that nobody without Render
dashboard access could read. A shadow whose output cannot be seen measures
nothing — the same failure as an audit that under-reports, which is how the
conversion sweep missed four weight-write paths while claiming 74 sites.

The endpoint is deliberately honest about being a sample: per-process, lost on
restart, bounded. Those are in the RESPONSE, not the docs, because a partial
view mistaken for a complete one is the failure being prevented.
"""
import logging

import pytest

from core import trace_buffer


@pytest.fixture(autouse=True)
def _clean():
    trace_buffer.install()
    trace_buffer.reset()
    logging.getLogger().setLevel(logging.INFO)
    yield
    trace_buffer.reset()


def _emit(msg, level=logging.INFO):
    logging.getLogger("core.food_turn").log(level, msg)


def test_it_captures_the_shadow_events():
    _emit("event=identity_shadow outcome=agree kept=1")
    _emit("event=clarification_shadow fields=2 missing_expected=0")
    _emit("event=refinement_refused held='bread' reason=ambiguous",
          logging.WARNING)
    out = trace_buffer.recent(since_seconds=60)
    assert out["by_event"] == {"identity_shadow": 1, "clarification_shadow": 1,
                               "refinement_refused": 1}


def test_prose_and_unwatched_events_are_ignored():
    """An allowlist rather than "anything with event=", so a chatty new logger
    cannot push the shadows out of a bounded window."""
    _emit("the composer ran and everything was fine")
    _emit("event=some_unrelated_thing x=1")
    assert trace_buffer.recent(since_seconds=60)["returned"] == 0


def test_the_response_carries_its_own_caveats():
    _emit("event=turn_trace route=structured_log ms=900")
    out = trace_buffer.recent(since_seconds=60)
    joined = " ".join(out["caveats"])
    assert "per-process" in joined and "restart" in joined
    assert out["capacity"] == trace_buffer.MAX_LINES
    assert out["installed"] is True


def test_eviction_is_counted_not_silent():
    """A reader who cannot tell "nothing happened" from "it scrolled past" will
    conclude the first — which is how a quiet failure reads as success."""
    for i in range(trace_buffer.MAX_LINES + 25):
        _emit(f"event=turn_trace n={i}")
    out = trace_buffer.recent(since_seconds=60, limit=5)
    assert out["dropped_from_ring"] >= 25
    assert out["truncated"] is True
    assert out["matched"] > out["returned"]


def test_filtering_by_event_and_window():
    _emit("event=identity_shadow a=1")
    _emit("event=turn_trace b=2")
    only = trace_buffer.recent(since_seconds=60, event="turn_trace")
    assert only["returned"] == 1 and only["by_event"] == {"turn_trace": 1}
    # A window that excludes everything returns nothing rather than everything.
    assert trace_buffer.recent(since_seconds=0.000001)["returned"] == 0


def test_a_broken_record_never_breaks_the_turn():
    """This handler runs on every food turn. A diagnostic may not cost the
    thing it observes.

    Driven at the HANDLER rather than through `logging`, because every other
    handler attached to the root logger also formats the record — pytest's
    included — so routing it through `log.info` tests their error handling
    rather than this one's.
    """
    class _Bad:
        def __str__(self):
            raise RuntimeError("boom")

    handler = next(h for h in logging.getLogger().handlers
                   if type(h).__name__ == "_RingHandler")
    record = logging.LogRecord("core.food_turn", logging.INFO, __file__, 1,
                               "event=turn_trace %s", (_Bad(),), None)
    handler.emit(record)          # must not raise
    assert trace_buffer.recent(since_seconds=60)["returned"] == 0


def test_install_is_idempotent():
    """Startup is not guaranteed to happen once — a reloader, a test client
    and a worker fork all reach it."""
    before = len(logging.getLogger().handlers)
    trace_buffer.install()
    trace_buffer.install()
    assert len(logging.getLogger().handlers) == before


# ── through the real app, with the real auth ─────────────────────────────────

def test_the_endpoint_requires_the_admin_token(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ADMIN_TOKEN", "test-token-value")
    from api.app import app

    with TestClient(app) as client:
        assert client.get("/admin/food-traces").status_code == 401
        ok = client.get("/admin/food-traces?since=1h",
                        headers={"X-Admin-Token": "test-token-value"})
        assert ok.status_code == 200
        body = ok.json()
        assert "lines" in body and "caveats" in body


def test_the_since_parameter_is_forgiving(monkeypatch):
    """An operator typing `?since=90m` at 2am should get data, not a 422."""
    from fastapi.testclient import TestClient

    monkeypatch.setenv("ADMIN_TOKEN", "test-token-value")
    from api.app import app

    with TestClient(app) as client:
        for value in ("15m", "2h", "1d", "600", "nonsense", ""):
            r = client.get(f"/admin/food-traces?since={value}",
                           headers={"X-Admin-Token": "test-token-value"})
            assert r.status_code == 200, f"{value!r} -> {r.status_code}"
