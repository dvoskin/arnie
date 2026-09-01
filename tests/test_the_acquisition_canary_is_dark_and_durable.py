"""The canary wiring: dark by default, fast in-turn, durable on expiry.

⛔⛔⛔ THE 12-SECOND VERSION DID NOT SHIP *(Danny, 2026-09-01)*: "Twelve seconds
on a food log is too expensive." Keeping acquisition outside SYNCHRONOUS
settlement was necessary and not sufficient — the remaining question was whether
the TURN blocks on it.

    canonical miss
        -> ~2 s attempt   hit     -> canonical owns THIS turn
                          expiry  -> legacy finishes the turn
                                     + DURABLE job -> next encounter is canonical
"""
from __future__ import annotations

import asyncio

import pytest

from core import general_settlement as GS
from skills.nutrition import acquisition as acq


def _facts(**kw):
    """An ItemFacts with the fields `acquirable` reads."""
    base = dict(identity="cod", entity="cod", preparation="", has_identity=True,
                has_quantity=True, has_mass=True, has_memory=False,
                has_artifact=False, product_bound=False, selected_rung="")
    base.update(kw)
    return GS.ItemFacts(**base)


# ── DARK BY DEFAULT, AND ITS OWN DIAL ───────────────────────────────────────

def test_acquisition_is_off_when_nobody_is_enrolled(monkeypatch):
    monkeypatch.delenv("CANONICAL_ACQUISITION_ALLOWLIST", raising=False)
    assert GS.acquisition_cohort(26) is False
    assert GS.acquisition_cohort(None) is False


def test_enabling_settlement_does_not_enable_retrieval(monkeypatch):
    """⛔⛔ NEITHER ROLLOUT MAY IMPLICITLY WIDEN THE OTHER. Being settled
    canonically and being willing to make a PROVIDER CALL inside the user's turn
    are different consents — the second spends that user's latency."""
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", "26")
    monkeypatch.delenv("CANONICAL_ACQUISITION_ALLOWLIST", raising=False)
    assert GS.settlement_cohort(26) is True
    assert GS.acquisition_cohort(26) is False, \
        "settlement enrolment silently enabled retrieval"


def test_the_canary_is_one_user(monkeypatch):
    monkeypatch.setenv("CANONICAL_ACQUISITION_ALLOWLIST", "26")
    assert GS.acquisition_cohort(26) is True
    assert GS.acquisition_cohort(27) is False


# ── WOULD IT HELP, NOT IS IT MISSING ────────────────────────────────────────

@pytest.mark.parametrize("kw,why", [
    ({"has_mass": False}, "count-blocked: no evidence prices '2 bowls'"),
    ({"product_bound": True}, "bound: a scan constrains the evidence universe"),
    ({"has_identity": False}, "nothing to look up"),
    ({"has_artifact": True}, "rung exists and does not SCALE — a scaling problem"),
    ({"has_memory": True}, "rung exists and does not SCALE — a scaling problem"),
    ({"selected_rung": "artifact"}, "already priced"),
])
def test_a_call_that_cannot_help_is_never_spent(kw, why):
    """⭐ MEASURED PARTITION: 68 meals evidence-blocked, 116 purely
    COUNT-blocked, 1 mixed. Under a 2 s budget, wasting it on an unfixable item
    costs the meal that WAS fixable."""
    assert GS.acquirable(_facts(**kw)) is False, why


def test_an_evidence_blocked_item_is_acquirable():
    assert GS.acquirable(_facts()) is True


# ── FAST IN-TURN, DURABLE ON EXPIRY ─────────────────────────────────────────

def _stub_acquire(monkeypatch, *, refuse=None, hang=False):
    async def fake(db, *, identity, item=None, deadline_s=2.0):
        if hang:
            await asyncio.sleep(deadline_s + 5)
        if refuse:
            raise acq.AcquisitionRefused(refuse, "stub")
        return object()
    monkeypatch.setattr(acq, "acquire", fake)


@pytest.mark.asyncio
async def test_a_provider_timeout_defers_instead_of_losing_the_work(
        db, make_user, monkeypatch):
    """⛔⛔ THE CONTINUATION IS A ROW, NOT `asyncio.create_task`. Render
    instances are ephemeral — an in-process task dies with the instance, which
    is the SAME failure this tranche exists to fix: established evidence with
    nowhere durable to go."""
    from sqlalchemy import select
    from db.models import BackgroundJob
    user = await make_user()
    _stub_acquire(monkeypatch, refuse=acq.PROVIDER_UNAVAILABLE)

    n = await GS.acquire_for_miss(
        db, user_id=user.id,
        items=[{"food_name": "cod", "quantity": "180 g", "calories": 999.0}])
    await db.commit()

    assert n == 0, "nothing was established synchronously"
    jobs = (await db.execute(select(BackgroundJob).where(
        BackgroundJob.kind == "acquire_evidence"))).scalars().all()
    assert len(jobs) == 1, "the work was lost instead of deferred"
    assert "cod" in (jobs[0].dedup_key or "")


@pytest.mark.asyncio
async def test_a_food_the_provider_will_never_hold_is_not_queued_forever(
        db, make_user, monkeypatch):
    """⛔ ONLY A REFUSAL A RETRY COULD FIX BECOMES A JOB. No USDA English
    description will ever match `окрошка на айране с курицей`, and half the
    frozen corpus's tail is Russian — retrying that forever is a busy loop
    wearing the costume of persistence."""
    from sqlalchemy import select
    from db.models import BackgroundJob
    user = await make_user()
    _stub_acquire(monkeypatch, refuse=acq.IDENTITY_UNQUALIFIED)

    await GS.acquire_for_miss(
        db, user_id=user.id,
        items=[{"food_name": "окрошка", "quantity": "300 g", "calories": 9.0}])
    await db.commit()
    assert (await db.execute(select(BackgroundJob))).scalars().all() == []


@pytest.mark.asyncio
async def test_the_meal_shares_one_budget_and_the_rest_is_deferred(
        db, make_user, monkeypatch):
    """⭐ THE BUDGET IS SPENT, THE WORK IS NOT LOST. Otherwise a meal's LAST
    food is permanently unlearnable purely because it was listed last."""
    from sqlalchemy import select
    from db.models import BackgroundJob
    user = await make_user()
    _stub_acquire(monkeypatch)                       # succeeds instantly

    items = [{"food_name": n, "quantity": "180 g", "calories": 9.0}
             for n in ("cod", "lentils", "гречка")]
    n = await GS.acquire_for_miss(db, user_id=user.id, items=items,
                                  budget_s=0.0)      # budget already spent
    await db.commit()
    assert n == 0
    jobs = (await db.execute(select(BackgroundJob))).scalars().all()
    assert len(jobs) == 3, f"{len(jobs)} deferred, expected all 3"


@pytest.mark.asyncio
async def test_acquisition_failure_is_never_settlement_failure(
        db, make_user, monkeypatch):
    """The turn falls to legacy exactly as it did before this existed."""
    user = await make_user()

    async def boom(db, *, identity, item=None, deadline_s=2.0):
        raise RuntimeError("provider exploded")
    monkeypatch.setattr(acq, "acquire", boom)

    n = await GS.acquire_for_miss(
        db, user_id=user.id,
        items=[{"food_name": "cod", "quantity": "180 g", "calories": 9.0}])
    assert n == 0                                    # no raise reached the turn


# ── THE DURABLE HALF ACTUALLY RUNS ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_sweep_dispatches_the_new_job_kind(monkeypatch):
    """A queued acquisition that no sweeper handles is a row, not a mechanism."""
    import core.background_jobs as BJ
    seen = []

    async def fake(identity):
        seen.append(identity)
    monkeypatch.setattr(BJ, "run_acquire_evidence", fake)

    src = __import__("inspect").getsource(BJ.sweep_background_jobs)
    assert 'job.kind == "acquire_evidence"' in src, \
        "sweep has no branch for acquire_evidence — the job would be 'unknown kind'"
    assert "run_acquire_evidence" in src
