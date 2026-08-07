"""FOOD'S BINDING to the materiality artifact: path, stamps, and the lookup.

`core.materiality_artifact` is the mechanism and knows nothing about food.
This module supplies what the stamps MEAN for this domain and is the only
thing the turn path calls. Mirrors the `core.semantic_evidence` /
`evidence_semantics` split already in use.

THE QUERY SHAPES LIVE HERE, and they are the retrieval fingerprint. They are
shared by exactly two callers — the generator that issues them and the
fingerprint that records which ones produced an artifact — so an edit to a
shape invalidates every artifact built from the old ones, automatically. That
is the point: it is not possible to change how evidence is gathered and keep
reading a document gathered the other way.

MEASURED, and why there are several shapes rather than one. Live 2026-08-07:

    "chicken roasted"          -> Chicken, roasting, meat only, cooked,
                                  roasted — 167
    "chicken fried"            -> giblets · meatless · POPEYES, every one of
                                  them refused, correctly, by the resolver
    "chicken, cooked, fried"   -> broilers or fryers, meat only, cooked,
                                  fried — 219

One shape reaches a comparable row for some preparations and not others, so a
single query yields `{roasted: …}` alone and materiality cannot be shown. The
set below reaches both, and 219/167 = 1.31 clears `MATERIAL_SPREAD`.
Affordable only because this runs at build time: retrieval quality stopped
being latency-bound the moment the answer stopped being computed per turn.

NOT FOOD-SPECIFIC, AND IT MUST STAY THAT WAY. An earlier draft of this tuple
contained `{food} breast {prep}`, because that shape is what first surfaced a
comparable fried row in probing. It is a poultry cut written into a template —
a food-name branch wearing a different hat, wrong for the first food without
that part, and precisely what this layer is forbidden to contain. It was
removed and the generic set re-measured; `{food}, cooked, {prep}` reaches the
same evidence. The shapes name only the food, the preparation, and words USDA
itself uses for composition rows.

A shape that is nonsense for a given food (`potato meat only cooked fried`
returns chicken) costs a query and nothing else: those rows come back
DIFFERENT_IDENTITY and the boundary discards them. Wasteful offline is fine;
wrong is not.
"""
from __future__ import annotations

import hashlib
import logging
import pathlib
from typing import Optional

from core.materiality_artifact import MAX_ARTIFACT_AGE_DAYS, Stale, load

logger = logging.getLogger(__name__)

ARTIFACT_PATH = (pathlib.Path(__file__).resolve().parent.parent.parent
                 / "data" / "preparation_materiality_v1.json")

#: GENERIC query templates. `{food}` and `{prep}` only — no cut, no part, no
#: food-specific vocabulary. Editing this tuple changes `retrieval_fingerprint`
#: and invalidates every artifact built from the old shapes, which is the
#: intended consequence: evidence gathered one way must not be read as though
#: it were gathered another.
QUERY_SHAPES = (
    "{food} {prep}",
    "{food}, cooked, {prep}",
    "{food} meat only cooked {prep}",
)

#: USDA data types the generator reads. Curated only: Branded is crowdsourced
#: product names, and a materiality claim built on "GRILLED CHICKEN BURRITO"
#: is a claim about burritos.
DATA_TYPES = ("Foundation", "SR Legacy")

#: Rows per shape. Small: this is evidence that a preparation EXISTS and
#: prices differently, not a survey.
ROWS_PER_SHAPE = 3


def _digest(*parts: str) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return "sha256:" + h.hexdigest()[:32]


def vocabulary_fingerprint() -> str:
    """The registered preparation ids, from the LIVE registry.

    Adding a preparation must invalidate every artifact: the new state was
    never queried for, so a stale document would report a space that is
    silently missing an option the field can now offer.
    """
    from core.semantic_fields import spec_for

    return _digest(*sorted(spec_for("preparation").vocabulary))


def retrieval_fingerprint() -> str:
    return _digest(*QUERY_SHAPES, *DATA_TYPES, str(ROWS_PER_SHAPE))


def resolver_version() -> str:
    from skills.nutrition import evidence_semantics as food

    return food.VERSION


def normalize(food_name: str) -> str:
    """The artifact key. The same normalization the generator applies, so a
    lookup and a build agree by construction rather than by convention."""
    return " ".join(str(food_name or "").strip().lower().split())


def verified(*, now=None, max_age_days: float = MAX_ARTIFACT_AGE_DAYS):
    """The artifact, or `Stale` with the reason. The release gate calls this
    and prints what it raises; runtime calls `space_for`, which swallows."""
    return load(ARTIFACT_PATH, resolver_version=resolver_version(),
                vocabulary_fingerprint=vocabulary_fingerprint(),
                retrieval_fingerprint=retrieval_fingerprint(),
                max_age_days=max_age_days, now=now)


#: Read once per process. The document is immutable and deploys with the code,
#: so re-reading it per turn would be file IO for a constant.
_CACHED: Optional[object] = None
_CACHE_FAILED = False


def _artifact():
    global _CACHED, _CACHE_FAILED
    if _CACHED is None and not _CACHE_FAILED:
        try:
            _CACHED = verified()
        except Stale as exc:
            _CACHE_FAILED = True
            # ONCE, LOUDLY, AT WARNING. Runtime degrades to "no question" —
            # but a stale artifact in production is an operational fault that
            # the release gate was supposed to have made unreachable, so it
            # must not pass unremarked.
            logger.warning("event=materiality_artifact_unusable reason=%s — "
                           "preparation will not open", exc)
    return _CACHED


def _reset_for_tests() -> None:
    global _CACHED, _CACHE_FAILED
    _CACHED, _CACHE_FAILED = None, False


def space_for(food_name: str) -> dict:
    """`{preparation_id: kcal_per_100g}` for this food, or `{}`.

    FAILS CLOSED, ALWAYS. A missing food, a stale artifact, an unreadable
    document — every one of them means UNKNOWN, and UNKNOWN means the field
    does not open. There is no provider call and no computation behind this;
    it cannot block, and it cannot raise.
    """
    artifact = _artifact()
    if artifact is None:
        return {}
    entry = artifact.entries.get(normalize(food_name)) or {}
    space = entry.get("space") or {}
    return {str(k): (float(v) if v is not None else None)
            for k, v in space.items()}
