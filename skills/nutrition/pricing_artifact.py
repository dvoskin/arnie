"""QUALIFIED PRICING EVIDENCE, derived once and READ on every settle.

    build time   USDA rows -> semantic qualification -> qualified candidates
                 -> fingerprinted artifact -> committed
    turn  time   (entity, preparation) -> load -> ArtifactEvidence
                 -> best_candidate -> nutrition basis

SEPARATE FROM THE MATERIALITY ARTIFACT, and the separation is a claim-type
boundary, not filing. `preparation_materiality_v1` answers "is this question
worth asking" and is allowed to rest on web-synthesised text. This answers
"what does this food cost" and may rest ONLY on structured records. Web
densities extracted for materiality must never reach pricing — one artifact
per claim keeps that true by construction rather than by discipline.

STORES EVIDENCE, NOT A WINNER. The qualified candidate SET is what is
committed; `best_candidate` still picks, deterministically, at runtime. If the
artifact stored the chosen record, ranking authority would have moved into
whatever the model happened to prefer on generation day — the opposite of the
defect being fixed, which is that "Chicken, fried" priced 295 kcal and then
329 kcal because a fresh qualification produced a different candidate set.

THE READER NEVER RETRIEVES. No provider, no model, no generation on miss. A
miss returns None and the pricer falls to its estimate rung or refuses; it
does not invoke the generator. That is what makes a synchronous `price()`
honest.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
from typing import Optional

from core.materiality_artifact import MAX_ARTIFACT_AGE_DAYS, Stale, load

logger = logging.getLogger(__name__)

ARTIFACT_PATH = (pathlib.Path(__file__).resolve().parent.parent.parent
                 / "data" / "pricing_evidence_v1.json")

#: How the generator asks for a priced identity. Composed name first, because
#: "Chicken, fried" is the identity pricing actually resolves — preparation
#: composes the name (`Pricing.IDENTITY`) rather than multiplying a number.
QUERY_SHAPES = ("{identity}", "{identity} cooked")

#: Curated only. Branded rows are crowdsourced product names and are the
#: PRODUCT rung's business, reached by exact identifier, not by string match.
DATA_TYPES = ("Foundation", "SR Legacy")

ROWS_PER_SHAPE = 8


def _digest(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return "sha256:" + h.hexdigest()[:32]


def resolver_version() -> str:
    from skills.nutrition import evidence_semantics as food

    return food.VERSION


def vocabulary_fingerprint() -> str:
    """The registered preparations, because they are half of every key. A new
    preparation means (entity, that-preparation) was never generated, and a
    stale artifact would answer for a pairing it never saw."""
    from core.semantic_fields import spec_for

    return _digest(*sorted(spec_for("preparation").vocabulary))


def retrieval_fingerprint() -> str:
    return _digest(*QUERY_SHAPES, *DATA_TYPES, str(ROWS_PER_SHAPE))


def normalize(text: str) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _registered_preparations() -> tuple:
    """The declared vocabulary — never a word list written here."""
    from core.semantic_fields import spec_for

    # Longest first, so an id that contains another cannot be shadowed by it.
    return tuple(sorted(spec_for("preparation").vocabulary,
                        key=len, reverse=True))


def split_identity(entity: str, preparation: str = "") -> tuple:
    """⭐ ONE TYPED IDENTITY, ONE KEY — whichever way it was expressed.

    THE INVERSE OF `preparation_ontology.name_with`, which composes
    `f"{food}, {preparation_id}"`. Preparation reaches pricing by two routes
    and they were producing different keys:

        answered as a FIELD   entity="Beef"          prep="grilled"
        named in the MESSAGE  entity="Beef, grilled" prep=""

    MEASURED IN PRODUCTION 2026-08-10. The artifact holds `beef|grilled` with
    five qualified candidates. The second route built `beef, grilled|`, missed,
    and fell to the estimate rung — so stating the preparation made pricing
    WORSE than omitting it:

        Beef          120 g   151 kcal   29.0 g protein   evidence
        Beef, grilled 120 g   151 kcal   24.0 g protein   estimate

    That is not a coverage gap. The evidence was already there and the lookup
    could not address it, because two representations of one identity did not
    canonicalise to one key.

    DRIVEN BY THE REGISTRY, never by a food or a phrase. There is no "beef"
    here and no "grilled" — a preparation is recognised because it is in the
    declared vocabulary, so extending that vocabulary extends this for free
    and a new food needs nothing.
    """
    ent, prep = normalize(entity), normalize(preparation)
    if prep:
        # An explicit field wins, and the name may ALSO carry it — `name_with`
        # is idempotent precisely because the interpreter sometimes composes
        # it first. Strip it either way so both routes land on one key.
        return _without(ent, prep), prep
    for candidate in _registered_preparations():
        stripped = _without(ent, candidate)
        if stripped != ent:
            return stripped, candidate
    return ent, ""


def _without(entity: str, preparation: str) -> str:
    """`entity` with the preparation token removed, in any position.

    Natural language puts it either side — "grilled salmon" and
    "salmon, grilled" are the same identity — so this matches on WORD
    boundaries rather than substrings: a substring test would maul "friedcake"
    and, worse, silently change the food.
    """
    words = [w for w in entity.replace(",", " ").split() if w]
    kept = [w for w in words if w != preparation]
    if len(kept) == len(words):
        return entity
    return " ".join(kept)


def key(entity: str, preparation: str = "") -> str:
    """`entity|preparation`. Preparation is part of the KEY, not a modifier
    applied afterwards: fried chicken and roasted chicken are different foods
    to price, which is the whole reason the field exists.

    Both arguments pass through `split_identity` first, so a preparation named
    in the food and a preparation answered as a field produce the SAME key.
    """
    ent, prep = split_identity(entity, preparation)
    return f"{ent}|{prep}"


def verified(*, now=None, max_age_days: float = MAX_ARTIFACT_AGE_DAYS):
    """The artifact, or `Stale` with a reason. The release gate calls this."""
    return load(ARTIFACT_PATH, resolver_version=resolver_version(),
                vocabulary_fingerprint=vocabulary_fingerprint(),
                retrieval_fingerprint=retrieval_fingerprint(),
                max_age_days=max_age_days, now=now)


_CACHED = None
_CACHE_FAILED = False


def _artifact():
    global _CACHED, _CACHE_FAILED
    if _CACHED is None and not _CACHE_FAILED:
        try:
            _CACHED = verified()
        except Stale as exc:
            _CACHE_FAILED = True
            logger.warning("event=pricing_artifact_unusable reason=%s — the "
                           "artifact rung is unavailable this process", exc)
    return _CACHED


def _reset_for_tests() -> None:
    global _CACHED, _CACHE_FAILED
    _CACHED, _CACHE_FAILED = None, False


def evidence_for(entity: str, preparation: str = ""):
    """`ArtifactEvidence` for this identity, or None.

    NEVER RETRIEVES AND NEVER RAISES. A miss, a stale artifact and an
    unreadable one are the same answer — None — and the pricer decides what
    that means. Generation happens outside the turn, by the script, or not at
    all this turn.
    """
    from core.canonical_pricing import ArtifactEvidence

    artifact = _artifact()
    if artifact is None:
        return None
    entry = artifact.entries.get(key(entity, preparation))
    if not entry:
        return None
    candidates = tuple(entry.get("candidates") or ())
    if not candidates:
        return None
    return ArtifactEvidence(candidates=candidates,
                            fingerprint=artifact.retrieval_fingerprint)
