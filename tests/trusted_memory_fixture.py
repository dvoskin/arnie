"""Seed a memory row that the CF24 trust predicate will actually accept.

⛔⛔⛔ A TIER IS NO LONGER A STAMP. Fixtures used to write
`origin_tier="canonical_settlement"` and that was enough, because trust WAS a
string comparison. CF24 made trust a RESOLVED LINK — the row's
`settled_by_operation_id` must name a real `meal_commits` row — precisely so
that no caller can mint authority by saying a word.

⭐⭐⭐ WHICH IS WHY THE FIXTURES HAD TO MOVE TOO, and that is the proof rather
than the inconvenience: if a test could still seed trusted memory with a
string, so could production. A fixture that can fake the guard is a guard
nobody has.
"""
from __future__ import annotations

import datetime as _dt
import itertools

_seq = itertools.count(1)


def trusted(db, match, *, basis: str = "per_100g", evidence_id: str = "171077"):
    """Wire `match` as trusted memory and add the settlement it points at.

    Returns the match so it drops straight into an existing
    ``db.add(UserFoodMatch(...))`` call site.
    """
    from db.models import MealCommit

    operation_id = f"op:test-fixture:{next(_seq)}"
    match.origin_tier = "canonical_settlement"
    match.settled_by_operation_id = operation_id
    match.settled_basis = basis
    match.settled_evidence_id = evidence_id
    match.settled_at = _dt.datetime.utcnow()
    db.add(MealCommit(operation_id=operation_id, operation_revision=0,
                      user_id=int(match.user_id), status="committed"))
    return match
