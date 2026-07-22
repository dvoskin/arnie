"""Multi-item enrichment prewarm (handlers.tool_executor).

The USDA+OFF lookups for a multi-food paste are network-only (no DB), so they are
fanned out CONCURRENTLY before the serial dispatch loop instead of paid one item
at a time. These tests pin: the fan-out populates a per-turn cache, it actually
overlaps, _analyze_food consumes the cache instead of re-fetching, the result is
identical to the inline fetch, and the kill switch / single-item / error paths
all degrade to the safe serial behavior.
"""
import time
import types

import pytest

import handlers.tool_executor as te
from core.food_intelligence import normalize_name


def _log_food(name, **inp):
    return {"name": "log_food", "input": {"food_name": name, **inp}}


def _reset_cache():
    te._ENRICH_PREFETCH.set({})


# ── _prewarm_enrichment: population + concurrency ─────────────────────────────

async def test_prewarm_populates_cache_for_each_distinct_food(monkeypatch):
    _reset_cache()
    calls = []

    async def fake_fetch(food_name, is_packaged):
        calls.append(food_name)
        return (f"usda:{food_name}", f"off:{food_name}")

    monkeypatch.setattr(te, "_fetch_usda_off", fake_fetch)
    await te._prewarm_enrichment([
        _log_food("Barebells caramel"),
        _log_food("Fairlife Core Power"),
        _log_food("David protein bar"),
    ])
    cache = te._ENRICH_PREFETCH.get()
    assert set(cache.keys()) == {
        normalize_name("Barebells caramel"),
        normalize_name("Fairlife Core Power"),
        normalize_name("David protein bar"),
    }
    assert cache[normalize_name("David protein bar")] == (
        "usda:David protein bar", "off:David protein bar")
    assert len(calls) == 3


async def test_prewarm_runs_concurrently_not_serially(monkeypatch):
    _reset_cache()

    async def slow_fetch(food_name, is_packaged):
        import asyncio
        await asyncio.sleep(0.1)
        return (f"usda:{food_name}", None)

    monkeypatch.setattr(te, "_fetch_usda_off", slow_fetch)
    t0 = time.monotonic()
    await te._prewarm_enrichment([
        _log_food("Barebells one"), _log_food("Barebells two"),
        _log_food("Barebells three"), _log_food("Barebells four"),
    ])
    elapsed = time.monotonic() - t0
    # 4 × 0.1s serial would be ~0.4s; overlapped it's ~0.1s. Generous bound.
    assert elapsed < 0.25, f"prewarm did not overlap: {elapsed:.2f}s"
    assert len(te._ENRICH_PREFETCH.get()) == 4


async def test_prewarm_dedupes_repeated_food(monkeypatch):
    _reset_cache()
    calls = []

    async def fake_fetch(food_name, is_packaged):
        calls.append(food_name)
        return ("u", "o")

    monkeypatch.setattr(te, "_fetch_usda_off", fake_fetch)
    await te._prewarm_enrichment([
        _log_food("Barebells caramel"),
        _log_food("barebells   caramel"),   # same after normalize
        _log_food("David bar"),
    ])
    assert len(calls) == 2            # caramel fetched once, not twice
    assert len(te._ENRICH_PREFETCH.get()) == 2


async def test_prewarm_skips_single_item_batch(monkeypatch):
    _reset_cache()
    called = False

    async def fake_fetch(food_name, is_packaged):
        nonlocal called
        called = True
        return ("u", "o")

    monkeypatch.setattr(te, "_fetch_usda_off", fake_fetch)
    await te._prewarm_enrichment([_log_food("Barebells caramel")])
    assert called is False                       # nothing to overlap
    assert te._ENRICH_PREFETCH.get() == {}


async def test_prewarm_skips_pure_generics(monkeypatch):
    _reset_cache()
    seen = []

    async def fake_fetch(food_name, is_packaged):
        seen.append(food_name)
        return ("u", "o")

    monkeypatch.setattr(te, "_fetch_usda_off", fake_fetch)
    # "oatmeal"/"coffee" are generic (is_generic_food_name) → excluded, exactly
    # as _analyze_food's own `not generic` gate would skip enriching them; the two
    # branded items remain. Prewarm and the inline path share that classifier, so
    # the prewarm never warms a key the loop won't look up.
    await te._prewarm_enrichment([
        _log_food("oatmeal"), _log_food("coffee"),
        _log_food("Barebells caramel"), _log_food("Fairlife Core Power"),
    ])
    assert "oatmeal" not in seen and "coffee" not in seen
    assert set(seen) == {"Barebells caramel", "Fairlife Core Power"}


async def test_prewarm_survives_one_fetch_error(monkeypatch):
    _reset_cache()

    async def flaky_fetch(food_name, is_packaged):
        if "boom" in food_name:
            raise RuntimeError("simulated USDA outage")
        return (f"usda:{food_name}", None)

    monkeypatch.setattr(te, "_fetch_usda_off", flaky_fetch)
    await te._prewarm_enrichment([
        _log_food("Barebells boom"), _log_food("David good"),
        _log_food("Quest good"),
    ])
    cache = te._ENRICH_PREFETCH.get()
    # The raising item is dropped (it will fetch inline later); the rest cached.
    assert normalize_name("Barebells boom") not in cache
    assert normalize_name("David good") in cache
    assert normalize_name("Quest good") in cache


# ── _analyze_food consumes the prewarm cache ─────────────────────────────────

def _patch_analyze_deps(monkeypatch, fetch_spy):
    """Silence the DB + LLM edges of _analyze_food so we test only the enrichment
    routing: no history, no memory, no cache write, no micro estimation."""
    import db.queries as q
    import core.micro_estimator as me

    async def _none(*a, **k): return None
    async def _noop(*a, **k): return None

    monkeypatch.setattr(te, "_logged_history_match", _none)
    monkeypatch.setattr(q, "get_user_food_match", _none)
    monkeypatch.setattr(q, "upsert_user_food_match", _noop)
    monkeypatch.setattr(me, "estimate_micros", _none)
    monkeypatch.setattr(te, "_fetch_usda_off", fetch_spy)


async def test_analyze_food_uses_prewarmed_candidate_without_refetch(monkeypatch):
    _reset_cache()
    spy = {"n": 0}

    async def fetch_spy(food_name, is_packaged):
        spy["n"] += 1
        return (None, None)

    _patch_analyze_deps(monkeypatch, fetch_spy)
    usda_cand = {"per100g": {"calories": 360, "protein": 30, "carbs": 30,
                             "fat": 12, "fiber": 5, "sugar": 2, "sodium": 200},
                 "_match": "exact", "fdc_id": None}
    te._ENRICH_PREFETCH.set({normalize_name("Barebells bar"): (usda_cand, None)})

    user = types.SimpleNamespace(id=1)
    res = await te._analyze_food(object(), user, "Barebells bar",
                                 {"quantity": "100g"})
    assert spy["n"] == 0                          # cache hit → no inline fetch
    assert res.source == "usda"
    assert res.calories == 360                    # 100g × 360/100g (ground truth)


async def test_analyze_food_fetches_inline_on_cache_miss(monkeypatch):
    _reset_cache()                                # empty cache
    spy = {"n": 0}
    usda_cand = {"per100g": {"calories": 360, "protein": 30, "carbs": 30,
                             "fat": 12, "fiber": 5, "sugar": 2, "sodium": 200},
                 "_match": "exact", "fdc_id": None}

    async def fetch_spy(food_name, is_packaged):
        spy["n"] += 1
        return (usda_cand, None)

    _patch_analyze_deps(monkeypatch, fetch_spy)
    user = types.SimpleNamespace(id=1)
    res = await te._analyze_food(object(), user, "Barebells bar",
                                 {"quantity": "100g"})
    assert spy["n"] == 1                          # miss → inline fetch happened
    assert res.calories == 360


async def test_kill_switch_ignores_warm_cache(monkeypatch):
    _reset_cache()
    monkeypatch.setenv("ENRICH_PREFETCH", "false")
    spy = {"n": 0}
    usda_cand = {"per100g": {"calories": 360, "protein": 30, "carbs": 30,
                             "fat": 12, "fiber": 5, "sugar": 2, "sodium": 200},
                 "_match": "exact", "fdc_id": None}

    async def fetch_spy(food_name, is_packaged):
        spy["n"] += 1
        return (usda_cand, None)

    _patch_analyze_deps(monkeypatch, fetch_spy)
    # Warm cache with a DIFFERENT sentinel; the switch-off path must ignore it.
    te._ENRICH_PREFETCH.set({normalize_name("Barebells bar"): ("STALE", "STALE")})
    user = types.SimpleNamespace(id=1)
    res = await te._analyze_food(object(), user, "Barebells bar",
                                 {"quantity": "100g"})
    assert spy["n"] == 1                          # ignored cache → inline fetch
    assert res.calories == 360
