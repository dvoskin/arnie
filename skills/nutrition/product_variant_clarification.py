"""⭐ B-1.8c2.1 — THE PRODUCT_VARIANT PRODUCER: IT REOPENS. IT NEVER ASSEMBLES.

    WHERE DID THIS EXACT SET OF ALTERNATIVES COME FROM?   *(Danny's question,
    which this module must be able to answer in stable IDs and persisted
    evidence ONLY, or refuse)*

    A: an already-persisted exact product candidate universe for this
       operation — reopened by candidate_set_id / operation_id, every member an
       ExactProductCandidate naming a `product_evidence` snapshot.

That is the only source. NOT "similar", NOT "same brand", NOT "same barcode
prefix", NOT "search again". A barcode proves a product, not its siblings; a
scanned snapshot proves itself. A correction days later with no persisted
universe and no exact mechanical relation to alternatives REFUSES — the correct
answer to "which product did you mean" is "I don't have that on record", never
a synthesized list of likely variants.

Form B — building the universe at the moment exact candidate evidence exists
(the acquisition wire persisting several snapshots and recording them as one
universe) — is a LATER producer with the acquisition wire as its input. It is
deliberately not in this module.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

GENERATOR_VERSION = "product_variant_reopen_v1"

#: There is deliberately NO static vocabulary for this field. Its answers are
#: the persisted exact CandidateSet for the operation — the registry's
#: GENERATED+ENUMERATED rule — and membership is checked at answer time.


class NoExactUniverse(Exception):
    """No persisted exact product universe exists for this operation. The
    field cannot be asked; a correction naming a variant REFUSES."""


async def reopen(db, *, operation_id: str, user_id: int,
                 candidate_set_id: Optional[str] = None):
    """The persisted exact product universe for this operation, or raise.

    Reads through `candidate_repository.load_universe` — the same
    revision-pinned, tap-traceable store quantity uses, via the decision-free
    read a REOPENED universe needs — and accepts ONLY a set whose declared kind
    is "product". A quantity set found under this operation is not this
    field's universe and is refused, not coerced.
    """
    from core import candidate_repository as repo

    if not candidate_set_id:
        raise NoExactUniverse(
            f"no candidate_set_id for operation {operation_id!r} — nothing "
            f"persisted names an exact product universe here")
    universe = await repo.load_universe(db, candidate_set_id, user_id=int(user_id))
    if universe is None:
        # wrong user OR missing set — load_universe is user-scoped, so both
        # present as None here, and both are refusals.
        raise NoExactUniverse(f"candidate set {candidate_set_id!r} not found "
                              f"for user {user_id}")
    if str(universe.operation_id) != str(operation_id):
        raise NoExactUniverse(
            f"candidate set {candidate_set_id!r} belongs to operation "
            f"{universe.operation_id!r}, not {operation_id!r} — a universe is "
            f"not transferable between meals")
    if getattr(universe, "candidate_kind", "quantity") != "product":
        raise NoExactUniverse(
            f"candidate set {candidate_set_id!r} is a "
            f"{universe.candidate_kind!r} universe, not a product universe — "
            f"refusing to coerce")
    return universe


async def verify_candidate_binding(db, candidate) -> None:
    """⛔⛔ VERIFY, DO NOT TRUST *(Danny)*. Generation writes entity_id and
    product_evidence_id together — but persisted data can be corrupt or stale,
    and the CONSUMER must check that

        candidate.entity_id  ==  the identity the snapshot mechanically
                                 represents (off:<canonical_code>)

    before anything prices from it. A candidate whose snapshot is gone, or
    whose snapshot is about a different product, is refused — not "close
    enough", not repaired.
    """
    from skills.nutrition.product_store import canonical_code
    from db.models import ProductEvidenceRecord

    row = await db.get(ProductEvidenceRecord, int(candidate.product_evidence_id))
    if row is None:
        raise NoExactUniverse(
            f"candidate {candidate.candidate_id!r} names snapshot "
            f"{candidate.product_evidence_id}, which does not exist")
    want = str(candidate.entity_id or "")
    if ":" not in want:
        raise NoExactUniverse(
            f"candidate {candidate.candidate_id!r} entity {want!r} is not a "
            f"namespaced exact id")
    ns, ident = want.split(":", 1)
    if ns != str(row.provider or "off") or canonical_code(ident) != str(row.canonical_code):
        raise NoExactUniverse(
            f"candidate {candidate.candidate_id!r} says {want!r} but its "
            f"snapshot {row.id} is {row.provider}:{row.canonical_code} — the "
            f"candidate and its evidence disagree; refusing to price from "
            f"either")


def exact_universe_members(universe=None) -> tuple:
    """The vocabulary this field's answers must come from: the entity ids of a
    persisted exact universe. With no universe there is NO vocabulary — the
    late-bound registry hook returns empty, and an empty enumerated vocabulary
    means the field cannot be asked, which is the correct state."""
    if universe is None:
        return ()
    return tuple(c.entity_id for c in getattr(universe, "candidates", ()))


def options_for(universe, *, event_id: str, field_id: str) -> tuple:
    """Stored options for a persisted exact universe: one ClarificationOption
    per candidate, each carrying the typed SelectProductVariant patch WITH the
    snapshot id — the three ids written TOGETHER, at generation, never
    resolved later. The client receives ids and labels; the meaning stays
    server-side.

    ⛔ `event_id` IS REQUIRED — the patch contract refuses a patch with no
    target ("a patch with no target is a guess"), and it is right: a product
    selection is about ONE food event in ONE meal, never floating.
    """
    from core.semantics import (ClarificationOption, Provenance,
                                SelectProductVariant)

    if not str(event_id or "").strip():
        raise ValueError("options_for needs the food event these options are "
                         "about — a selection with no target is a guess")
    out = []
    for cand in getattr(universe, "candidates", ()):
        patch = SelectProductVariant(
            event_id=event_id, field_id=field_id,
            provenance=Provenance.USER_SELECTED,
            entity_id=cand.entity_id, serving_id=cand.serving_id,
            product_evidence_id=cand.product_evidence_id)
        out.append(ClarificationOption(
            label=cand.label or cand.entity_id, value=cand.entity_id,
            option_id=f"opt:{cand.candidate_id}", field_id=field_id,
            patch=patch, candidate_id=cand.candidate_id,
            candidate_set_id=universe.candidate_set_id, candidate=cand))
    return tuple(out)
