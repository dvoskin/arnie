"""⛔ THE RUNG THAT WAS DEAD FOR EVERY ROW IN PRODUCTION.

Found 2026-08-14 by a consumer-side proof, not by a gate. `_memory()` did
`float(m.confidence)` on a column holding the words `'likely'`, `'exact'`,
`'estimated'`, `'user-confirmed'` — each of which raises — inside a bare
`except Exception` that logged at DEBUG and returned None.

    494 'likely' · 298 'exact' · 41 'estimated' · 3 'user-confirmed'
    ────────────────────────────────────────────────────────────────
    0 of 836 production rows the canonical _memory() rung could return

`Rung.MEMORY` is the TOP of the canonical ladder, so the canonical lane has been
pricing from artifact and estimate alone since it was written.

⭐ EVERY GATE OVER IT ASSERTED THE FUNCTION WAS CALLED. None asserted evidence
came back. That is the third time this session that *a function that is called
is not a function whose result is used*, so these gates assert on the RETURNED
`MemoryEvidence` — its macros, its source id, its confidence — and never on a
call having happened.

⚠ AND THE FIX IS NOT A NEW MAPPING. `food_intelligence._CONF_NUM` already
declared the four grades and their numbers; what was missing was a named
boundary for crossing between the persisted vocabulary and the numeric
contract. `test_the_scores_come_from_the_declared_contract` is what stops a
convenient literal reappearing here later.
"""
from __future__ import annotations

import pytest
import pytest_asyncio

from core.canonical_pricing import MemoryEvidence
from core.canonical_pricing_inputs import _memory
from core.food_intelligence import confidence_score
from db.models import UserFoodMatch
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: F401

#: VERBATIM FROM PRODUCTION, with their real counts. Not a plausible set — the
#: actual vocabulary, so a grade the code has never seen cannot hide here.
PRODUCTION_GRADES = (("likely", 494), ("exact", 298),
                     ("estimated", 41), ("user-confirmed", 3))


@pytest_asyncio.fixture
async def store(app_db, seeded):           # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session, seeded


def _key(grade: str) -> str:
    """A per-grade key that SURVIVES normalization.

    ⚠ THE FIRST VERSION USED THE GRADE VERBATIM and `user-confirmed` failed —
    not because the rung was broken but because `normalize_name` strips the
    hyphen, so the seeded key and the lookup key differed. A fixture that
    cannot address its own row proves nothing about the code; it was caught
    only because the failure named a grade rather than a mechanism.
    """
    from core.food_intelligence import normalize_name

    return normalize_name(f"chicken {grade}")


def _row(user_id, name_norm, grade, cal=165.0,
         origin_tier="canonical_settlement"):
    """⛔ CF23 — THE FIXTURE NOW CARRIES PROVENANCE, DELIBERATELY.

    This suite's subject is "a memory row that IS evidence", and after CF23
    that is no longer any row with per-100g numbers: it is a row that can name
    the authority which produced them. Seeding without the stamp would make
    every case here assert the pre-CF23 contract while production rejects the
    same row — a suite green against a rule nobody applies.

    `test_an_unstamped_row_is_no_longer_evidence` below pins the other side."""
    return UserFoodMatch(user_id=user_id, name_norm=name_norm,
                         display_name=name_norm, cal_100=cal, protein_100=31.0,
                         carbs_100=0.0, fat_100=3.6, fdc_id="171077",
                         confidence=grade, origin_tier=origin_tier)


# ── every production grade returns evidence ───────────────────────────────────

@pytest.mark.parametrize("grade,production_rows", PRODUCTION_GRADES)
@pytest.mark.asyncio
async def test_every_production_confidence_grade_returns_evidence(
        store, grade, production_rows):
    """⭐ THE GATE THAT WOULD HAVE CAUGHT IT. One case per grade actually in the
    table, each asserting a `MemoryEvidence` comes BACK with the row's macros —
    not that a lookup was attempted."""
    db, user_id = store
    db.add(_row(user_id, _key(grade), grade))
    await db.commit()

    evidence = await _memory(db, user_id, _key(grade))

    assert isinstance(evidence, MemoryEvidence), (
        f"{grade!r} returned nothing — {production_rows} production rows carry "
        f"this grade and every one of them was invisible to the top rung")
    assert evidence.per100g["calories"] == 165.0
    assert evidence.per100g["protein"] == 31.0
    assert evidence.source_id == "171077"
    assert evidence.confidence == confidence_score(grade)


def test_the_scores_come_from_the_declared_contract_not_from_here():
    """⚠ THE ANTI-HEURISTIC GATE. The four grades and their numbers were
    already declared in `_CONF_NUM`; a convenient literal reappearing at a call
    site is how policy gets smuggled into a type conversion."""
    from core.food_intelligence import _CONF_NUM

    for grade, _ in PRODUCTION_GRADES:
        assert confidence_score(grade) == _CONF_NUM[grade]
    assert set(_CONF_NUM) == {g for g, _ in PRODUCTION_GRADES}, (
        "the declared vocabulary and production's vocabulary diverged — one of "
        "them is now writing a grade the other cannot read")


def test_an_undeclared_grade_scores_nothing_rather_than_defaulting():
    """Absence is not an answer. A grade nobody declared is a fact about our
    vocabulary, and the caller must decide about it visibly."""
    for unknown in ("weird", "", None, "  "):
        assert confidence_score(unknown) is None
    assert confidence_score("EXACT") == 0.9        # case is not a new grade


# ── absence, incompatibility and defect are three different outcomes ──────────

@pytest.mark.asyncio
async def test_no_row_is_a_silent_miss(store):
    db, user_id = store
    assert await _memory(db, user_id, "a food nobody has logged") is None


@pytest.mark.asyncio
async def test_a_row_with_no_calories_is_refused_with_a_reason(store, caplog):
    """A per-100g panel with no calories cannot price anything. It is not the
    same fact as "no row", and it must not spell the same."""
    db, user_id = store
    db.add(_row(user_id, "hollow", "exact", cal=None))
    await db.commit()

    with caplog.at_level("INFO"):
        assert await _memory(db, user_id, "hollow") is None
    assert "memory_row_unusable" in caplog.text


@pytest.mark.asyncio
async def test_an_undeclared_grade_still_yields_the_macros_but_says_so(
        store, caplog):
    """⭐ THE ROW IS NOT DISCARDED OVER ITS METADATA. The macros are still
    evidence; what is refused is silently substituting a number, which is
    precisely what broke this rung."""
    db, user_id = store
    db.add(_row(user_id, "odd grade", "brand-new-grade"))
    await db.commit()

    with caplog.at_level("WARNING"):
        evidence = await _memory(db, user_id, "odd grade")

    assert isinstance(evidence, MemoryEvidence)
    assert evidence.per100g["calories"] == 165.0
    assert "memory_confidence_unmapped" in caplog.text


@pytest.mark.asyncio
async def test_a_failing_lookup_is_loud_and_is_not_an_absence(store, caplog,
                                                              monkeypatch):
    """⛔ THE SHAPE THAT HID THE DEFECT FOR MONTHS. A broad `except` that logs
    at DEBUG makes a permanent failure indistinguishable from an empty cache."""
    import db.queries as q

    async def _explodes(*a, **kw):
        raise RuntimeError("database on fire")

    monkeypatch.setattr(q, "get_user_food_match", _explodes)
    db, user_id = store

    with caplog.at_level("WARNING"):
        assert await _memory(db, user_id, "chicken breast") is None
    assert "memory_rung_unavailable" in caplog.text


@pytest.mark.asyncio
async def test_the_identity_still_selects_which_row_is_returned(store):
    """The repair must not have cost the addressing this tranche just built."""
    db, user_id = store
    db.add(_row(user_id, "tomato", "exact", cal=18.0))
    db.add(_row(user_id, "corn", "likely", cal=96.0))
    await db.commit()

    ru = await _memory(db, user_id, "Помидор", "tomato")
    en = await _memory(db, user_id, "Tomato", "tomato")
    corn = await _memory(db, user_id, "Кукуруза варёная (2 початка)", "corn")

    assert ru.per100g["calories"] == en.per100g["calories"] == 18.0
    assert corn.per100g["calories"] == 96.0
    # And with no identity the Russian surface reaches nothing, as it does today.
    assert await _memory(db, user_id, "Помидор") is None


# ── CF23 — AND THE OTHER SIDE OF THE SAME CONTRACT ────────────────────────


@pytest.mark.asyncio
async def test_an_unstamped_row_is_no_longer_evidence(store):
    """⛔⛔⛔ THE NEGATIVE INVARIANT FOR EVERY CASE ABOVE.

    Each test in this file now seeds `origin_tier="canonical_settlement"`. If
    that stamp were decorative — if the rung returned evidence regardless —
    every one of them would still pass while production rejected the same row.
    This is the test that makes the stamp load-bearing.

    Measured 2026-08-24: 163 fleet rows carried a FABRICATED 200.0 kcal/100g
    density, 154 of them live to the legacy pricer across 13 users."""
    db, user_id = store
    name_norm = _key("exact")
    db.add(_row(user_id, name_norm, "exact", origin_tier="generic_exact"))
    await db.commit()

    got = await _memory(db, user_id, name_norm, "")

    assert got is None, (
        "an unstamped memory row was returned as evidence — this is the shape "
        "of the 154 fabricated production rows")
