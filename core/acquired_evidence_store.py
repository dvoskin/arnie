"""The artifact rung's durable half — evidence Arnie established, not was given.

⭐ SAME RUNG, SAME SHAPE, SAME KEY. Rows come back as `ArtifactEvidence`, keyed
by `pricing_artifact.key`, ranked by the unchanged `select_priced_rung`. The
sequencing directive is explicit that acquisition sources "do not become
arbitrary extra pricing rungs inside `look()`" — they establish evidence, and
canonical consumes it under the authority rules it already has.

⛔⛔ THE CATALOG WINS WHEN IT HAS THE IDENTITY, AND THAT IS A MEASUREMENT
SAFEGUARD, NOT A PREFERENCE. Merging acquired candidates into one of the 27
seeded identities would re-run `best_candidate` over a larger pool, and it
could pick differently — silently repricing foods that are IN THE FROZEN
BASELINE. The 9.0% figure is only worth having because it does not move
underneath us, so acquisition is PURELY ADDITIVE: it may fill an identity the
catalog does not cover and may never alter one it does. That also buys a clean
A/B — any ownership movement is attributable to newly covered identities alone.

⛔⛔ AND ACQUIRED EVIDENCE OBEYS THE SEEDED EVIDENCE'S STALENESS CONTRACT. A row
is served only when its `resolver_version` and `retrieval_fingerprint` match the
running instrument AND it is younger than `MAX_ARTIFACT_AGE_DAYS`. Without all
three the cache is simply the way to EVADE the freshness rule the file artifact
already answers to: a row written once would outlive the vocabulary that
qualified it and keep pricing meals under a resolver nobody runs any more.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)


async def evidence_for(db, entity: str, preparation: str = "", *, now=None):
    """Acquired `ArtifactEvidence` for this identity, or None. LOCAL READ ONLY.

    ⛔ NEVER RETRIEVES AND NEVER RAISES — the same contract
    `pricing_artifact.evidence_for` states. A miss, a stale row and an
    unavailable database are the same answer here (None) and the pricer decides
    what that means. An exception escaping into `look()` would turn a covered
    food into a coverage miss and report it as an architecture failure.
    """
    from core.materiality_artifact import MAX_ARTIFACT_AGE_DAYS
    from core.canonical_pricing import ArtifactEvidence
    from db.models import AcquiredEvidenceRecord
    from skills.nutrition import pricing_artifact as art

    try:
        identity = art.key(entity, preparation)
        if not identity:
            return None

        # ⛔ THE CATALOG IS CONSULTED FIRST AND ITS ANSWER IS FINAL. Not a
        # ranking preference — a guarantee that the frozen 27 cannot move.
        if art.evidence_for(entity, preparation) is not None:
            return None

        rows = (await db.execute(
            select(AcquiredEvidenceRecord)
            .where(AcquiredEvidenceRecord.canonical_identity == identity,
                   AcquiredEvidenceRecord.resolver_version == art.resolver_version(),
                   AcquiredEvidenceRecord.retrieval_fingerprint ==
                   art.retrieval_fingerprint())
            .order_by(AcquiredEvidenceRecord.acquired_at.desc())
            .limit(1))).scalars().all()
        if not rows:
            return None
        row = rows[0]

        cutoff = (now or datetime.now(timezone.utc)) - timedelta(
            days=MAX_ARTIFACT_AGE_DAYS)
        acquired = row.acquired_at
        if acquired is not None and acquired.tzinfo is None:
            acquired = acquired.replace(tzinfo=timezone.utc)
        if acquired is None or acquired < cutoff:
            logger.info("event=acquired_evidence_stale identity=%r acquired_at=%s",
                        identity, acquired)
            return None

        candidates = tuple(row.candidates or ())
        if not candidates:
            # A hit at the rung that prices nothing is worse than a miss. The
            # write side refuses this too; both, because either alone is a
            # guard whose protected input might never occur.
            return None
        return ArtifactEvidence(candidates=candidates,
                                fingerprint=row.retrieval_fingerprint or "")
    except Exception:                                    # noqa: BLE001
        logger.warning("acquired evidence unavailable for %s|%s", entity,
                       preparation, exc_info=True)
        return None


async def remember(db, acquired) -> bool:
    """Persist one `AcquiredEvidence`. Returns whether a NEW row was written.

    ⭐ IDEMPOTENT ON THE FACT, NOT ON THE FETCH. Two turns racing to acquire the
    same food under the same instrument must leave ONE row; a re-acquisition
    returning byte-identical evidence is a duplicate write, not a new fact. The
    unique constraint owns that, and a collision is a normal outcome — logged
    at info, never raised at the user.
    """
    from sqlalchemy.exc import IntegrityError

    from db.models import AcquiredEvidenceRecord
    from skills.nutrition import pricing_artifact as art

    prov = dict(acquired.provenance or {})
    row = AcquiredEvidenceRecord(
        canonical_identity=acquired.canonical_identity,
        source_type=acquired.source_type,
        source_identifier=acquired.source_identifier,
        authority_grade=acquired.authority_grade,
        nutrition_basis=acquired.nutrition_basis,
        candidates=list(acquired.nutrition_evidence),
        identity_evidence=dict(acquired.identity_evidence or {}),
        serving_basis=list(acquired.serving_basis or ()),
        quantity_compatibility=sorted(acquired.quantity_compatibility or ()),
        provenance=prov,
        source_fingerprint=str(prov.get("source_fingerprint") or ""),
        resolver_version=art.resolver_version(),
        retrieval_fingerprint=art.retrieval_fingerprint(),
    )
    # ⛔⛔ A SAVEPOINT, NOT A ROLLBACK. The first draft caught IntegrityError
    # and called `db.rollback()`, which unwinds the WHOLE transaction — so the
    # second `remember()` of the same fact deleted the row the first one wrote
    # and the table came back EMPTY. The duplicate test caught it ("0 rows for
    # one fact"); in production it would have discarded the caller's unrelated
    # work on a collision that is a NORMAL outcome, not an error.
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        logger.info("event=acquired_evidence_duplicate identity=%r",
                    acquired.canonical_identity)
        return False
    logger.info("event=acquired_evidence_written identity=%r source=%s grade=%s",
                acquired.canonical_identity, acquired.source_type,
                acquired.authority_grade)
    return True
