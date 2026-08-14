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
    VERSION, FoodIntent, from_usda)

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


#: THE SHARED KEY for a food's structured-evidence classification. Every
#: consumer that wants it — the pricing path, preparation, product variant —
#: asks the turn's `EvidenceContext` for THIS key, so the retrieval and the
#: semantic classification happen exactly once per turn per food.
#:
#: The module-global reuse dict this replaced was keyed `(food, version)` and
#: called turn-scoped while nothing cleared it. Lifetime now comes from the
#: context's own lifetime rather than from remembering to put a turn id in a
#: key; a durable cross-turn cache would additionally need an EVIDENCE
#: FINGERPRINT, since one food string retrieves different evidence on
#: different days.
def assessment_key(food_name: str, resolver_version: str) -> str:
    return f"assess:{str(food_name or '').strip().lower()}:{resolver_version}"


@dataclass(frozen=True)
class Qualification:
    """What qualification did, for telemetry and for the fallback decision."""
    rows: tuple
    #: qualified | resolver_down_no_candidates | empty_input
    disposition: str
    raw_count: int = 0
    kept_count: int = 0
    resolver_version: str = ""
    #: ⛔ THE ROWS THE MODEL DECLINED TO JUDGE, and they are NOT the same thing
    #: as the rows it judged and rejected. Only `rows` used to leave this
    #: function, so a caller could see what was KEPT and had no way to tell a
    #: considered "not this food" from "the model did not answer about this
    #: one". `build_one` then wrote DIFFERENT_IDENTITY at confidence 0.95 for
    #: both — a durable, confident negative about a row nobody assessed, which
    #: `needs_resolution` would never reopen.
    #:
    #: An outage is already handled: ALL-abstain becomes
    #: `resolver_down_no_candidates`. This is the PARTIAL case — some rows
    #: judged, some abstained — which reads as a fully successful batch from
    #: the outside and is exactly how a completed model operation can silently
    #: shrink the evidence universe.
    abstained: tuple = ()


class ResolverReplyUnusable(RuntimeError):
    """The model returned nothing this code can read.

    NAMED, because it used to surface as a bare `StopIteration` from `next()`
    — which inside a coroutine becomes `RuntimeError: coroutine raised
    StopIteration`, an opaque message that was FILED AS BENIGN GENERATOR NOISE
    and was in fact changing the durable evidence universe. A failure mode
    needs a name before anyone can count how often it happens.
    """


def _text_of(reply) -> str:
    """Every text block, joined — a TOTAL function over the reply.

    `next(b.text for b in reply.content if hasattr(b, "text"))` was partial in
    two ways: it raised `StopIteration` when the reply carried NO text block,
    and it silently took only the FIRST when it carried several.
    """
    parts = [b.text for b in reply.content if hasattr(b, "text")]
    if not parts:
        kinds = [getattr(b, "type", "?") for b in reply.content]
        raise ResolverReplyUnusable(
            f"the resolver reply carries no text block (blocks={kinds}, "
            f"stop_reason={getattr(reply, 'stop_reason', '?')})")
    return "".join(parts)


async def _default_complete(prompt: str) -> str:
    """The calibrated resolver model. Kept tiny; the eval script owns
    measurement and this owns production invocation.

    ⭐ THINKING IS EXPLICITLY DISABLED, and that is a REPRODUCIBILITY fix
    before it is a cost one. `max_tokens` bounds thinking AND text TOGETHER,
    and this model thinks nondeterministically — so the text budget was
    whatever thinking happened to leave. Measured 2026-08-11 against the real
    qualification prompt, six runs:

        thinking + text   out=3000  stop=max_tokens  text truncated mid-JSON
        thinking ONLY     out=3000  stop=max_tokens  NO TEXT BLOCK AT ALL
        thinking + text   out=2498  stop=end_turn    valid

    THREE OF SIX FAILED, and every failure abstained the whole batch. That is
    how `mackerel|roasted` lost three valid cooked-mackerel rows between two
    builds which differed in nothing else — not the seeds, not the prompt, not
    the resolver version, not the USDA response.

    With thinking disabled: 4/4 valid, and output fell from 2371-3000 tokens
    to 544-620.
    """
    from core.llm import _get_anthropic  # late; heavy import

    client = _get_anthropic()
    reply = await client.messages.create(
        model=RESOLVER_MODEL, max_tokens=3000,
        thinking={"type": "disabled"},
        # ⛔ TEMPERATURE IS NOT AVAILABLE ON THIS MODEL. Setting it returns
        # `400 — \`temperature\` is deprecated for this model.`, measured
        # 2026-08-11 against every one of 84 identities.
        #
        # THAT IS A LOAD-BEARING FACT, not a footnote. Sampling variation was
        # the measured cause of the remaining build divergence — one row
        # scoring DIFFERENT_IDENTITY 0.6 / 0.7 / 0.75 and
        # COMPATIBLE_SPECIALIZATION 0.8 across runs, either side of
        # MINIMUM_IDENTITY_CONFIDENCE. The knob that would pin it does not
        # exist here, so BUILD-TIME DETERMINISM CANNOT BE OBTAINED BY
        # CONFIGURING THE MODEL. It has to come from giving the model less to
        # decide: mechanical dimensions (raw vs cooked, preparation
        # compatibility, branded vs generic, duplicate equivalence) move into
        # deterministic code, and the model keeps only what is genuinely
        # semantic — as ADVISORY metadata that cannot delete durable evidence.
        messages=[{"role": "user", "content": prompt}])
    return _text_of(reply)


async def classify_rows(food_name: str, rows, complete=None) -> tuple:
    """`(records, assessments)` for one food's structured evidence.

    THE SHARED UNIT OF WORK. `qualify_usda_rows` filters with it and
    preparation projects from it, so the model runs once for both.
    """
    records = from_usda(rows)
    assessments = await resolve(
        DOMAIN, FoodIntent(base_identity=food_name), records,
        complete or _default_complete)
    return records, assessments


async def qualify_usda_rows(food_name: str, rows, complete=None,
                            context=None) -> Qualification:
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
    from core.evidence_context import ensure

    shared = ensure(context)
    _t0 = _time.monotonic()
    try:
        records, assessments = await shared.shared(
            assessment_key(food_name, VERSION),
            lambda: classify_rows(food_name, rows, complete))
    except Exception:
        logger.warning("event=evidence_qualification_failed food=%s — "
                       "USDA contributes NO candidate this turn; the ladder's "
                       "qualification-free rungs still serve the user",
                       food_name, exc_info=True)
        # NOTHING was assessed, so every row is unjudged — not rejected.
        return Qualification(rows=(), disposition="resolver_down_no_candidates",
                             raw_count=len(rows), kept_count=0,
                             abstained=tuple(rows))

    if all(a.abstained for a in assessments):
        # Indistinguishable from "resolver down" at this distance — and either
        # way, evidence that exists here BECAUSE it needs qualification does
        # not regain authority from the qualifier's absence.
        logger.warning("event=evidence_qualification_unavailable food=%s "
                       "rows=%d latency_ms=%d — no USDA candidate this turn",
                       food_name, len(rows),
                       int((_time.monotonic() - _t0) * 1000))
        return Qualification(rows=(), disposition="resolver_down_no_candidates",
                             raw_count=len(rows), kept_count=0,
                             abstained=tuple(rows))

    kept = tuple(
        row for row, a in zip(rows, assessments)
        if a.relationship in IDENTITY_BEARING
        and a.confidence >= MINIMUM_IDENTITY_CONFIDENCE)
    # ⛔ THE PARTIAL ABSTENTION, WHICH LOOKS LIKE A COMPLETED BATCH. Only
    # ALL-abstain is treated as an outage above; a batch where SOME rows were
    # judged and others were not returns `qualified` and drops the unjudged
    # ones out of `kept` — indistinguishable, from outside, from rows the
    # model considered and rejected. Carrying them explicitly is what lets a
    # caller record "no answer" instead of manufacturing "no".
    abstained = tuple(row for row, a in zip(rows, assessments) if a.abstained)
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
                         resolver_version=assessments[0].resolver_version,
                         abstained=abstained)
