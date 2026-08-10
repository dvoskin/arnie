"""THE OWNERSHIP FIREWALL — measured in production before it existed.

2026-08-10, user 26, one iOS session:

    13:56:31  created  entry=2947  canonical:create        Chicken, roasted 200 kcal
    13:56:43  updated  entry=2947  structured_food:…v2  -> Salmon 263 kcal

The user said "I had some salmon" — a plain new-food statement, no correction
language — twelve seconds after logging chicken. The legacy interpreter
classified it as a CORRECTION and overwrote the canonical row in place. The
reply was "Updated to salmon." The chicken log survived only in its `created`
event, which is the 2026-08-07 ledger work earning its place.

Three properties made it the worst class found in this migration:

    DATA LOSS    a committed canonical row lost its identity, silently
    OWNERSHIP    a LEGACY writer mutated a row owned by the canonical lane
    INVISIBLE    no error, a plausible reply, and a board that looked right

THE INVARIANT LIVES AT THE MUTATION BOUNDARY, not in the classifier. Every
food-row update in the system funnels through `db.queries.update_food_entry`,
so a guard there rejects a cross-owner write whichever interpretation path
reached it. A special case in the correction classifier would only have
covered the one route that happened to be observed.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from db.models import FoodEntry, LedgerEvent
from db.queries import (AUTHORITY_OVER_CANONICAL, CrossOwnerMutation,
                        MutationAuthority, add_food_entry,
                        creating_source, get_or_create_today_log,
                        update_food_entry)


async def _row(db, user, *, source: str, name="Chicken, roasted", cal=200.0):
    log = await get_or_create_today_log(db, user.id, "UTC")
    return await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name=name, raw_input=name,
        calories=cal, protein=30.0, carbs=0.0, fats=8.0,
        source_type="ios", ledger_source=source, user_id=user.id)


async def _events(db, entry_id, event_type=None):
    q = select(LedgerEvent).where(LedgerEvent.entry_id == entry_id,
                                  LedgerEvent.domain == "food")
    if event_type:
        q = q.where(LedgerEvent.event_type == event_type)
    return (await db.execute(q)).scalars().all()


# ── PROOF 1: a canonical row survives an unrelated legacy write ─────────────

@pytest.mark.asyncio
async def test_a_legacy_writer_cannot_mutate_a_canonical_row(db, make_user):
    """ENTRY 2947, AS A RULE. The exact production sequence: a canonical row,
    then a legacy writer arriving with a different food."""
    user = await make_user(telegram_id="own:1")
    entry = await _row(db, user, source="canonical:create")
    # Read the id BEFORE the rollback: the instance expires, and lazily
    # reloading an attribute would issue sync IO inside an async session.
    entry_id, user_id = entry.id, user.id

    with pytest.raises(CrossOwnerMutation) as caught:
        await update_food_entry(
            db, entry_id, user_id,
            ledger_source="structured_food:food_interpreter_v2",
            authority=MutationAuthority.INFERRED_INTERPRETATION,
            parsed_food_name="Salmon", calories=263.0, protein=21.5)

    assert caught.value.entry_id == entry_id
    assert caught.value.owner == "canonical:create"
    assert caught.value.authority == "inferred_interpretation"

    await db.rollback()
    row = (await db.execute(
        select(FoodEntry).where(FoodEntry.id == entry_id))).scalar_one()
    assert row.parsed_food_name == "Chicken, roasted", (
        "the canonical row lost its identity to a legacy writer")
    assert row.calories == 200.0


# ── PROOF 2: the canonical lane may still mutate its own rows ──────────────

@pytest.mark.asyncio
async def test_the_canonical_lane_may_correct_its_own_row(db, make_user):
    """The firewall is about OWNERSHIP, not immutability. A canonical writer
    correcting a canonical row is the normal path and must stay open —
    otherwise B-1.75 repricing and every future canonical correction break."""
    user = await make_user(telegram_id="own:2")
    entry = await _row(db, user, source="canonical:create")

    updated = await update_food_entry(
        db, entry.id, user.id, ledger_source="canonical:correct",
        authority=MutationAuthority.CANONICAL_OWNER, calories=250.0)
    assert updated is not None and updated.calories == 250.0


# ── PROOF 3: legacy rows keep their existing behaviour ─────────────────────

@pytest.mark.asyncio
async def test_a_legacy_writer_may_still_correct_a_legacy_row(db, make_user):
    """THE REGRESSION THAT WOULD HURT MOST. Corrections on legacy-owned rows
    are the overwhelming majority of production traffic and are untouched by
    this: the firewall only fires when the OWNER is canonical."""
    user = await make_user(telegram_id="own:3")
    entry = await _row(db, user, source="structured_food:food_interpreter_v2",
                       name="Rice", cal=200.0)

    updated = await update_food_entry(
        db, entry.id, user.id,
        ledger_source="structured_food:food_interpreter_v2",
        authority=MutationAuthority.INFERRED_INTERPRETATION, calories=240.0)
    assert updated is not None and updated.calories == 240.0


@pytest.mark.asyncio
async def test_a_row_with_no_created_event_is_not_treated_as_canonical(
        db, make_user):
    """FAIL OPEN ON UNKNOWN OWNERSHIP, deliberately. Rows predating the ledger
    work have no `created` event; treating "unknown" as canonical would refuse
    every correction to the entire existing corpus."""
    user = await make_user(telegram_id="own:4")
    log = await get_or_create_today_log(db, user.id, "UTC")
    # No ledger_source -> no created event -> no recorded owner.
    entry = await add_food_entry(
        db, daily_log_id=log.id, parsed_food_name="Legacy row",
        raw_input="legacy", calories=100.0, source_type="ios")

    assert await creating_source(db, entry.id) is None
    updated = await update_food_entry(
        db, entry.id, user.id,
        ledger_source="structured_food:food_interpreter_v2",
        authority=MutationAuthority.INFERRED_INTERPRETATION, calories=150.0)
    assert updated is not None and updated.calories == 150.0


# ── PROOF 5: the rejected attempt is RECORDED ──────────────────────────────

@pytest.mark.asyncio
async def test_a_rejected_cross_owner_mutation_is_recorded(db, make_user):
    """A firewall that silently drops writes is its own blind spot. The
    rejected event is how anyone learns a legacy path is still trying, and how
    often — which is what tells us when the legacy correction route can be
    deleted rather than guessed at."""
    user = await make_user(telegram_id="own:5")
    entry = await _row(db, user, source="canonical:create")

    with pytest.raises(CrossOwnerMutation):
        await update_food_entry(
            db, entry.id, user.id,
            ledger_source="structured_food:food_interpreter_v2",
            authority=MutationAuthority.INFERRED_INTERPRETATION,
            parsed_food_name="Salmon", calories=263.0)
    await db.commit()

    rejected = await _events(db, entry.id, "mutation_rejected")
    assert len(rejected) == 1, "the refusal left no trace"
    payload = json.loads(rejected[0].payload_json or "{}")
    assert payload["owner"] == "canonical:create"
    assert payload["writer"] == "structured_food:food_interpreter_v2"
    assert payload["authority"] == "inferred_interpretation"
    assert payload["attempted"]["parsed_food_name"] == "Salmon", (
        "the record does not say what was attempted, so nobody can tell a "
        "mis-classified new food from a real correction")

    # And no `updated` event was written — the refusal is not a partial write.
    assert not await _events(db, entry.id, "updated")


# ── THE BOUNDARY ITSELF ────────────────────────────────────────────────────

def test_every_food_row_update_funnels_through_the_guarded_boundary():
    """AST, repo-wide. The guard is worth exactly as much as the claim that
    nothing mutates a food row around it: a second update path would be an
    unguarded door, and the production defect proves the classifier is not
    where this can be enforced."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")) \
                or rel in ("db/queries.py",) or rel.startswith("simulate"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                                # pragma: no cover
            continue
        for node in ast.walk(tree):
            # `entry.calories = x` / `setattr(entry, "calories", x)` on a
            # FoodEntry outside the boundary would bypass the firewall.
            if isinstance(node, ast.Call) and \
                    getattr(node.func, "id", "") == "setattr" and node.args:
                target = getattr(node.args[0], "id", "")
                if "food" in target.lower() or "entry" in target.lower():
                    offenders.append(f"{rel}:{node.lineno} setattr({target}…)")
    assert not offenders, (
        f"food rows are mutated outside `update_food_entry`, so the ownership "
        f"firewall can be walked around: {offenders}")


# ══ THE CAPABILITY CONTRACT ═════════════════════════════════════════════════
#
# The denylist version of this firewall passed every test above. It was still
# wrong: it named the four writers that exist today, so a FUTURE inferred
# writer would have been permitted by omission — and `mutation_rejected` could
# not have revealed it, because an undenied writer is never rejected. A
# permission system whose failure mode is silence is the failure mode this
# whole migration exists to remove.


@pytest.mark.asyncio
async def test_an_undeclared_writer_is_refused_by_default(db, make_user):
    """⭐ THE GATE THE DENYLIST COULD NOT HAVE. A brand-new mutation surface
    that declares nothing — `coach_agent:v3`, `apple_watch_edit`, anything —
    is refused on a canonical row, because UNKNOWN is not in the allowed set.

    It BREAKS rather than silently succeeding, and breaking in development is
    the entire design: making a surface declare its authority costs one
    keyword, and silent permission destroyed six canonical rows in production.
    """
    user = await make_user(telegram_id="own:6")
    entry = await _row(db, user, source="canonical:create")
    entry_id, user_id = entry.id, user.id

    with pytest.raises(CrossOwnerMutation) as caught:
        await update_food_entry(db, entry_id, user_id,
                                ledger_source="coach_agent:v3",
                                calories=999.0)          # no authority declared
    assert caught.value.authority == "unknown"


@pytest.mark.asyncio
async def test_trust_follows_the_declared_capability_not_the_writer_name(
        db, make_user):
    """`ios_edit` is not trusted because its string starts with `ios_`.

    Same writer name, two authorities, two outcomes — which is the whole
    difference between a capability and a namespace convention.
    """
    user = await make_user(telegram_id="own:7")
    allowed = await _row(db, user, source="canonical:create")
    refused = await _row(db, user, source="canonical:create", name="Second")
    allowed_id, refused_id, user_id = allowed.id, refused.id, user.id

    ok = await update_food_entry(
        db, allowed_id, user_id, ledger_source="a_surface_nobody_listed",
        authority=MutationAuthority.EXPLICIT_USER_ACTION, calories=210.0)
    assert ok is not None and ok.calories == 210.0

    with pytest.raises(CrossOwnerMutation):
        await update_food_entry(
            db, refused_id, user_id, ledger_source="ios_edit",
            authority=MutationAuthority.INFERRED_INTERPRETATION,
            calories=210.0)


@pytest.mark.asyncio
async def test_a_recorded_replay_may_roll_a_canonical_row_back(db, make_user):
    """Undo is not trusted because it is on a list — it is trusted because it
    replays an inverse that was WRITTEN DOWN. It reaches the same dispatch as
    the interpreter by emitting a tool call, so the capability has to travel
    with the mutation."""
    user = await make_user(telegram_id="own:8")
    entry = await _row(db, user, source="canonical:create")

    rolled = await update_food_entry(
        db, entry.id, user.id, ledger_source="ledger_undo:v1",
        authority=MutationAuthority.RECORDED_REPLAY, calories=200.0)
    assert rolled is not None


def test_no_call_site_mutates_a_food_row_without_declaring_authority():
    """AST, repo-wide. `authority` defaults to UNKNOWN so an undeclared call
    fails CLOSED at runtime — but failing closed in production is a worse way
    to learn than failing here."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")) \
                or rel == "db/queries.py" or rel.startswith("simulate"):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:                                # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", "") or getattr(node.func, "attr", "")
            if name not in ("update_food_entry", "q_update_food_entry"):
                continue
            if not any(kw.arg == "authority" for kw in node.keywords):
                offenders.append(f"{rel}:{node.lineno}")
    assert not offenders, (
        f"{offenders} mutate a food row without declaring what authority they "
        f"are exercising — they will fail closed on canonical rows")
