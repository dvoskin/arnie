"""RETRIEVAL INTENT — how to FIND evidence, never what evidence MEANS.

⚠ UNWIRED. Nothing imports this. It was wired into `build_one` on 2026-09-01,
measured (20 identities recovered, 0 qualification regressions, 16 of 20
non-Latin), and then UNWIRED with the blocked v2 artifact chain — the artifact
it produced failed the reachability contract suite and carried consumed-form
ranking errors. The mechanism is PROVEN; its publication is deferred. Wiring it
again means re-opening that chain, not just adding an import.

⭐⭐⭐ THE MEASURED PROBLEM *(dev-half census, 2026-09-01)*. Of 86 generic
no-evidence items, only ONE was a true source gap. 72% retrieved rows and had
every one refused by identity qualification — correctly:

    "mustard"              -> Oil, mustard · Cabbage, mustard, salted · Mustard greens
    "whipped cream cheese" -> Cream, whipped, topping · Cream, fluid, heavy whipping
    "творог"               -> nothing at all; USDA is an English database

Mustard greens is not mustard. Whipped cream is not cream cheese. The gate was
right every time; the QUERY was wrong. So the repair belongs in retrieval, and
the sources already hold these foods.

⛔⛔⛔ THIS LAYER IMPROVES RECALL AND NOTHING ELSE. It may never decide that two
foods are the same — that is identity qualification's job and it stays the sole
authority. Concretely, this module:

    RETURNS   query strings
    NEVER     evidence, provenance, authority, an identity mapping, or a verdict

`творог -> cottage cheese, dry curd` as a stored MAPPING would be a second
nutrition authority wearing a normalization costume, and it would admit mustard
greens the moment a query was slightly off. As a QUERY whose candidates still
face the unchanged gate, it is free recall at zero authority cost.

⛔⛔ NUTRITION-RELEVANT QUALIFIERS SURVIVE. Expansion may rephrase toward source
wording; it may NOT drop `boiled`, `fried`, `raw`, `whole`, `nonfat` or a
preparation, because those change the nutrition. A query that widens the search
by discarding what made the food specific is not recall, it is a different food.

⛔ AND IT IS NOT A SYNONYM DICTIONARY. Hand-listing `творог = cottage cheese`
one food at a time works beautifully on the dev set and becomes another catalog
— the same defect as the 27-food artifact and the 54-identity work order. The
capability is: given a semantic food identity, produce SOURCE-APPROPRIATE search
descriptions while preserving what matters nutritionally.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

#: Bumped whenever the prompt or shaping rules change. Participates in the
#: retrieval fingerprint: different queries reach different rows, so evidence
#: found under a different expansion was found by a different instrument.
EXPANSION_VERSION = "retrieval_intent_v1"

#: How many expanded descriptors to ask for. Small on purpose — each one costs
#: a provider round trip, and the census says the right descriptor is usually
#: the first or second a competent speaker would try.
MAX_QUERIES = 4

_PROMPT = """You translate an everyday food name into search queries for a \
nutrition database (USDA FoodData Central), whose entries are written like \
"Cheese, cottage, lowfat, 1% milkfat" or "Mustard, prepared, yellow".

Food as the user said it: {identity!r}

Return ONLY a JSON array of up to {n} short search queries, best first.

Rules:
- Translate non-English food names to their English culinary equivalent.
- Prefer the wording the database itself would use.
- PRESERVE anything nutrition-relevant: preparation (boiled, fried, roasted), \
fat level (nonfat, 2%, lean), form (dried, canned, raw).
- Do NOT broaden to a different food. "mustard" is the condiment, not mustard \
greens; "cream cheese" is not whipped cream.
- No explanation, no prose, JSON array only."""


@dataclass(frozen=True)
class RetrievalIntent:
    """WHERE TO LOOK for one food. Carries no nutrition and no verdict.

    ⭐ `original` is always first and always present: expansion ADDS ways to
    find evidence, it never replaces the user's own words. If the model is
    unavailable the intent degrades to exactly today's behaviour rather than
    to nothing — an outage must not reduce recall below the status quo.
    """
    original: str
    queries: tuple = ()
    expansion_version: str = EXPANSION_VERSION
    #: Why each query exists, for telemetry. Never consulted by pricing.
    provenance: dict = field(default_factory=dict)

    def __post_init__(self):
        for f in ("evidence", "authority", "grade", "identity_map", "verdict"):
            assert not hasattr(self, f), (
                f"RetrievalIntent.{f} — this layer returns QUERIES ONLY; "
                "deciding what evidence MEANS belongs to qualification")


def _parse(text: str) -> list:
    """The model's array, or []. NEVER raises: an unreadable expansion must
    degrade to the original query, not fail the acquisition."""
    if not text:
        return []
    m = re.search(r"\[.*\]", text, re.S)
    if not m:
        return []
    try:
        got = json.loads(m.group(0))
    except Exception:                                    # noqa: BLE001
        return []
    return [str(q).strip() for q in got
            if isinstance(q, (str, int, float)) and str(q).strip()]


async def expand(identity: str, *, complete=None, max_queries: int = MAX_QUERIES):
    """`RetrievalIntent` for one food. The original query is always included.

    ⛔ FAILURE IS SILENT AND SAFE. A model outage, an unreadable reply, or a
    timeout yields the original query alone — which is exactly what the system
    does today. Expansion can only ever ADD candidates for the gate to judge.
    """
    original = str(identity or "").strip()
    if not original:
        return RetrievalIntent(original="", queries=())

    if complete is None:
        from skills.nutrition.evidence_qualification import _default_complete
        complete = _default_complete

    extra = []
    try:
        reply = await complete(_PROMPT.format(identity=original, n=max_queries))
        extra = _parse(reply)
    except Exception:                                    # noqa: BLE001
        logger.info("event=retrieval_expansion_unavailable identity=%r", original)

    seen, queries = set(), []
    for q in [original, *extra]:
        k = q.lower().strip()
        if k and k not in seen:
            seen.add(k)
            queries.append(q)
        if len(queries) >= max_queries + 1:
            break
    logger.info("event=retrieval_expanded identity=%r queries=%d",
                original, len(queries))
    return RetrievalIntent(original=original, queries=tuple(queries),
                           provenance={"expanded": len(queries) - 1})
