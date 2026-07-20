"""Memory-graph open-loops (user_threads) — Stage 1 spine.

Pins the behaviors that decide whether this stays useful or rots:
  • dedup/merge on write — a restated commitment is ONE thread, not two
    (the "planned the Hamptons trip twice" bug)
  • bounded, ranked read — top-N by proximity x salience for context
  • lifecycle — resolve closes a loop so it stops surfacing; stale/expired drop
  • the [OPEN THREADS] context block renders with [#id]s + a when-phrase
  • the tool handlers create / merge / resolve and never leak "memory" talk
  • the prompt ships the capture + dedup + resolve discipline
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from db.thread_queries import (
    upsert_thread, get_open_threads, resolve_thread, edit_thread,
    get_thread, _similar,
)


# ── Similarity (the dedup signal) ─────────────────────────────────────────────

def test_similar_matches_restatement_that_adds_words():
    # The exact failure: a restatement that ADDS words must still match.
    assert _similar(
        "Hamptons trip with wife and baby, high-end restaurants",
        "Hamptons trip, want good high-end restaurants for the family",
    )


def test_similar_verbatim_and_substring():
    assert _similar("resting my shoulder", "resting my shoulder")
    assert _similar("resting a tweaked left shoulder", "resting a tweaked left shoulder ~1 week")


def test_similar_rejects_different_commitments():
    assert not _similar(
        "Hamptons trip with wife and baby, high-end restaurants",
        "Austin work trip next week, hotel gym only",
    )
    assert not _similar("starting a cut monday", "trying to fix my breakfast")


# ── Dedup / merge on write ────────────────────────────────────────────────────

async def test_upsert_merges_restatement_not_duplicate(db, make_user):
    u = await make_user()
    t1, c1 = await upsert_thread(db, u.id, "event",
                                 "Hamptons trip with wife and baby, high-end restaurants",
                                 salience=4)
    assert c1 is True
    t2, c2 = await upsert_thread(db, u.id, "event",
                                 "Hamptons trip, want good high-end restaurants for the family")
    assert c2 is False, "restatement must MERGE, not create a second thread"
    assert t2.id == t1.id
    # merge keeps the higher salience and takes the newer summary
    assert t2.salience == 4
    assert "family" in t2.summary
    opens = await get_open_threads(db, u.id)
    assert len([t for t in opens if t.kind == "event"]) == 1


async def test_upsert_distinct_commitments_coexist(db, make_user):
    u = await make_user()
    await upsert_thread(db, u.id, "event", "Hamptons trip with family", salience=4)
    await upsert_thread(db, u.id, "event", "Austin work trip, hotel gym only", salience=4)
    assert len(await get_open_threads(db, u.id)) == 2


async def test_different_kinds_do_not_merge(db, make_user):
    u = await make_user()
    await upsert_thread(db, u.id, "intention", "start cutting monday")
    _, created = await upsert_thread(db, u.id, "habit", "start cutting carbs monday")
    # same-ish words but different kind → distinct nodes
    assert created is True


# ── Bounded, ranked read ──────────────────────────────────────────────────────

async def test_get_open_threads_ranks_imminent_and_salient_first(db, make_user):
    u = await make_user()
    soon = datetime.utcnow() + timedelta(days=1)
    far = datetime.utcnow() + timedelta(days=40)
    await upsert_thread(db, u.id, "milestone", "hit 180 by fall", salience=2, start_at=far)
    await upsert_thread(db, u.id, "event", "flight tomorrow", salience=5, start_at=soon)
    await upsert_thread(db, u.id, "intention", "mull switching to mornings", salience=2)
    ranked = await get_open_threads(db, u.id)
    assert ranked[0].summary == "flight tomorrow", "imminent + salient must lead"


async def test_get_open_threads_is_bounded(db, make_user):
    u = await make_user()
    topics = [
        "watch weekend overeating", "protein chronically low", "HRV drifting down",
        "sleep under six hours", "skipping breakfast lately", "knee aches on squats",
        "hydration falling off", "late-night snacking", "cardio adherence slipping",
        "stress eating at work",
    ]
    for t in topics:
        await upsert_thread(db, u.id, "watch_item", t)
    assert len(await get_open_threads(db, u.id, limit=6)) == 6


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def test_resolve_closes_the_loop(db, make_user):
    u = await make_user()
    t, _ = await upsert_thread(db, u.id, "event", "Hamptons trip")
    await resolve_thread(db, t.id, u.id, status="done")
    assert await get_open_threads(db, u.id) == []
    row = await get_thread(db, t.id, u.id)
    assert row.status == "done"


async def test_resolve_wrong_user_is_noop(db, make_user):
    u1 = await make_user(telegram_id="a")
    u2 = await make_user(telegram_id="b")
    t, _ = await upsert_thread(db, u1.id, "event", "u1 trip")
    assert await resolve_thread(db, t.id, u2.id, status="done") is None
    assert (await get_thread(db, t.id, u1.id)).status == "open"


async def test_expired_thread_drops_from_read(db, make_user):
    u = await make_user()
    t, _ = await upsert_thread(db, u.id, "constraint", "resting shoulder")
    await edit_thread(db, t.id, u.id, expires_at=datetime.utcnow() - timedelta(hours=1))
    assert await get_open_threads(db, u.id) == []


# ── Context block ─────────────────────────────────────────────────────────────

def test_context_block_renders_ids_and_when():
    from core.context_builder import _format_open_threads
    from types import SimpleNamespace as NS
    threads = [
        NS(id=12, kind="event", summary="Hamptons trip with family",
           salience=5, start_at=datetime.utcnow() + timedelta(days=1), due_at=None),
        NS(id=7, kind="habit", summary="add protein at breakfast",
           salience=3, start_at=None, due_at=None),
    ]
    block = _format_open_threads(threads, "America/New_York")
    assert "[OPEN THREADS" in block
    assert "[#12]" in block and "[#7]" in block
    assert "UPDATE it" in block  # the don't-duplicate discipline is in the header
    assert "tomorrow" in block   # the dated one gets a when-phrase


# ── Tool handlers ─────────────────────────────────────────────────────────────

async def test_remember_thread_handler_creates_then_merges(db, make_user):
    from handlers.tool_executor import _dispatch
    u = await make_user(timezone="America/New_York")
    r1 = await _dispatch("remember_thread",
                         {"kind": "event", "summary": "Hamptons trip with the family",
                          "salience": 4, "when": None}, u, None, db, "ios")
    assert "Filed" in r1 and "thread" in r1.lower()
    assert "COACH INSTRUCTION" in r1 and "do NOT announce" in r1
    r2 = await _dispatch("remember_thread",
                         {"kind": "event", "summary": "Hamptons trip, high-end restaurants for the family"},
                         u, None, db, "ios")
    assert "Updated" in r2  # merged, not a second row
    assert len(await get_open_threads(db, u.id)) == 1


async def test_update_thread_handler_resolves(db, make_user):
    from handlers.tool_executor import _dispatch
    u = await make_user()
    t, _ = await upsert_thread(db, u.id, "event", "Austin trip")
    r = await _dispatch("update_thread", {"thread_id": t.id, "status": "done"},
                        u, None, db, "ios")
    assert "Closed" in r and "COACH INSTRUCTION" in r
    assert await get_open_threads(db, u.id) == []


# ── Prompt discipline ─────────────────────────────────────────────────────────

def test_prompt_ships_memory_discipline():
    import pytest
    pytest.skip("OPEN THREADS / memory-graph discipline rolled out of the "
                "conversational prompt 2026-07-20 to restore food-logging focus; "
                "tables/tools stay dormant. Un-skip if the feature is re-enabled.")
    from core.prompts import build_arnie_system
    s = " ".join(build_arnie_system(platform="ios").split())
    assert "OPEN THREADS" in s
    assert "remember_thread" in s
    assert "DON'T DUPLICATE" in s
    assert "CLOSE loops" in s


def test_thread_tools_registered():
    from core.tools import build_tools
    names = {t["name"] for t in build_tools()}
    assert "remember_thread" in names and "update_thread" in names
