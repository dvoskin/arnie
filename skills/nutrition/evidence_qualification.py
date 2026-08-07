"""QUALIFICATION BEFORE RANKING: eligibility, never truth.

The seam Danny named:

    retrieval -> SEMANTIC QUALIFICATION -> authority ladder -> pricing

`best_candidate` and `analyze()` still own the nutrition decision. This module
only decides which retrieved rows are ELIGIBLE to compete — the heavy-syrup
papaya row (206 kcal/100g, three rows above `Papayas, raw` at 43, and the
evidence behind shipped entry 2896) is removed before ranking ever sees it,
not out-argued afterwards.

CLAIMS ARE TYPED, AND ADMISSIBILITY IS PER CLAIM. The dangerous future
shortcut is "web says fried matters, therefore web calories are
authoritative". Structurally refused: a source admitted for
`preparation_materiality` can open a field and can NEVER contribute a
calorie/macro candidate to settlement — `admissible_for_pricing` is the one
place that rule lives, and a gate holds it.

FAILURE IS SPLIT BETWEEN THE ACTION AND THE EVIDENCE, deliberately:

    SEMANTIC_RESOLVER_DOWN  !=  RAW_EVIDENCE_AUTHORIZED

  the user's action   fails OPEN — logging keeps working, because the
                      authority ladder's other rungs (own-log memory,
                      structured barcode/product matches, the interpreter's
                      estimate) never needed semantic qualification.
  ambiguous evidence  fails CLOSED — keyword-retrieved USDA rows exist here
                      precisely because they cannot be trusted unqualified,
                      and a resolver outage must not re-authorize the
                      babyfood row. Unavailable qualification returns NO
                      rows, named in the disposition; USDA simply contributes
                      no candidate that turn.

The first version failed open to the unfiltered rows, which made the safety
boundary optional exactly when it was unavailable. Danny's correction, and it
is the right one: fail open for the user action, fail closed for unqualified
evidence — those are different things.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from core.semantic_evidence import resolve
from skills.nutrition.evidence_semantics import (
    DOMAIN, IDENTITY_BEARING, MINIMUM_IDENTITY_CONFIDENCE, RESOLVER_MODEL,
    FoodIntent, from_usda)

logger = logging.getLogger(__name__)

#: What a piece of evidence may be USED FOR. Typed here, consumed by policy;
#: never inferred from where the evidence happened to come from at use time.
CLAIM_RELEVANCE = "preparation_materiality"
CLAIM_PRICING = "nutrition_pricing"

#: Evidence types admissible per claim. Synthesized web text can justify
#: ASKING a question; it can never price a meal.
_ADMISSIBLE = {
    CLAIM_RELEVANCE: frozenset({"structured_record", "synthesized_text"}),
    CLAIM_PRICING: frozenset({"structured_record"}),
}


def admissible_for_pricing(record) -> bool:
    return getattr(record, "evidence_type", "") in _ADMISSIBLE[CLAIM_PRICING]


def admissible_for_relevance(record) -> bool:
    return getattr(record, "evidence_type", "") in _ADMISSIBLE[CLAIM_RELEVANCE]


#: ASSESSMENTS THIS TURN ALREADY PAID FOR, keyed by (food, resolver version).
#:
#: §24: preparation must reuse enrichment the turn already performed rather
#: than re-querying the same provider. `_u()` classifies USDA rows for
#: PRICING eligibility; those same assessments carry the extracted
#: preparations the materiality question needs, so the second consumer pays
#: nothing.
#:
#: VERSION IS IN THE KEY (guardrail 2) so a resolver version bump cannot serve
#: conclusions made under the old policy. Bounded and process-local — this is
#: NOT the durable cache, which stays unbuilt until measured traffic justifies
#: its invalidation and privacy decisions.
#:
#: ⚠ THIS KEY IS INCOMPLETE FOR A DURABLE CACHE. `(food, version)` is
#: sufficient only because these entries cannot outlive the turn that wrote
#: them: the same food STRING can retrieve different evidence sets on
#: different days (providers change, rankings move), so a cross-turn cache
#: must also key on an EVIDENCE FINGERPRINT — hash the record ids and titles —
#: or it will serve conclusions about rows nobody retrieved this time.
_ASSESSED: dict = {}
_ASSESSED_MAX = 64


def remember_assessments(food_name: str, records, assessments) -> None:
    if len(_ASSESSED) >= _ASSESSED_MAX:
        _ASSESSED.clear()          # crude, bounded, and never stale-by-version
    key = (str(food_name or "").strip().lower(),
           assessments[0].resolver_version if assessments else "")
    _ASSESSED[key] = (tuple(records), tuple(assessments))


def recall_assessments(food_name: str, resolver_version: str):
    """What this turn already classified for this food, or None."""
    return _ASSESSED.get((str(food_name or "").strip().lower(),
                          resolver_version))


@dataclass(frozen=True)
class Qualification:
    """What qualification did, for telemetry and for the fallback decision."""
    rows: tuple
    #: qualified | resolver_down_no_candidates | empty_input
    disposition: str
    raw_count: int = 0
    kept_count: int = 0
    resolver_version: str = ""


async def _default_complete(prompt: str) -> str:
    """The calibrated resolver model. Kept tiny; the eval script owns
    measurement and this owns production invocation."""
    from core.llm import _get_anthropic  # late; heavy import

    client = _get_anthropic()
    reply = await client.messages.create(
        model=RESOLVER_MODEL, max_tokens=3000,
        messages=[{"role": "user", "content": prompt}])
    return next(b.text for b in reply.content if hasattr(b, "text"))


async def qualify_usda_rows(food_name: str, rows, complete=None) -> Qualification:
    """USDA rows -> the subset eligible to compete for pricing.

    ELIGIBILITY, NOT TRUTH: `best_candidate` still ranks whatever survives.
    On resolver unavailability, no row survives — see the module docstring:
    the user's logging fails open through the ladder's other rungs, the
    ambiguous evidence fails closed, and the disposition names it so a trace
    can never mistake an outage for a verdict.
    """
    import time as _time

    rows = list(rows or ())
    if not rows:
        return Qualification(rows=(), disposition="empty_input")
    records = from_usda(rows)
    _t0 = _time.monotonic()
    try:
        assessments = await resolve(
            DOMAIN, FoodIntent(base_identity=food_name), records,
            complete or _default_complete)
    except Exception:
        logger.warning("event=evidence_qualification_failed food=%s — "
                       "USDA contributes NO candidate this turn; the ladder's "
                       "qualification-free rungs still serve the user",
                       food_name, exc_info=True)
        return Qualification(rows=(), disposition="resolver_down_no_candidates",
                             raw_count=len(rows), kept_count=0)

    if all(a.abstained for a in assessments):
        # Indistinguishable from "resolver down" at this distance — and either
        # way, evidence that exists here BECAUSE it needs qualification does
        # not regain authority from the qualifier's absence.
        logger.warning("event=evidence_qualification_unavailable food=%s "
                       "rows=%d latency_ms=%d — no USDA candidate this turn",
                       food_name, len(rows),
                       int((_time.monotonic() - _t0) * 1000))
        return Qualification(rows=(), disposition="resolver_down_no_candidates",
                             raw_count=len(rows), kept_count=0)

    # The second consumer's free ride: preparation reads these instead of
    # paying for its own classification of the same rows.
    remember_assessments(food_name, records, assessments)

    kept = tuple(
        row for row, a in zip(rows, assessments)
        if a.relationship in IDENTITY_BEARING
        and a.confidence >= MINIMUM_IDENTITY_CONFIDENCE)
    # THE TRACE CONTRACT (Danny): everything the production turn needs to
    # answer "is the model call expensive enough to optimize" — invocation,
    # counts, latency, per-relationship dispositions — in ONE line, so the
    # trace is a grep and not a join.
    from collections import Counter as _Counter
    dispositions = _Counter(a.relationship for a in assessments)
    logger.info(
        "event=evidence_qualified food=%s raw=%d kept=%d latency_ms=%d "
        "version=%s dispositions=%s",
        food_name, len(rows), len(kept),
        int((_time.monotonic() - _t0) * 1000),
        assessments[0].resolver_version,
        dict(dispositions))
    return Qualification(rows=kept, disposition="qualified",
                         raw_count=len(rows), kept_count=len(kept),
                         resolver_version=assessments[0].resolver_version)
