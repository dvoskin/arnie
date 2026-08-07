"""IS PREPARATION MATERIALLY UNRESOLVED FOR THIS FOOD? Asked of the evidence.

B-1.5 shipped able to ask about preparation and unable to decide when to. It
opened the field only when the INTERPRETER volunteered a `preparation`
ambiguity, and for "I had some chicken" it does not — the model identifies the
food confidently and reports no uncertainty. Measured in production
2026-08-07: one field, quantity, and a generic "Chicken" committed at
1.88 cal/g on a food where grilled breast is ~1.65 and fried thigh ~2.4.

THE TWO EASY ANSWERS ARE BOTH FORBIDDEN, AND BOTH WRONG.

* Editing the interpreter prompt. Enhancements go in code — a prompt change is
  invisible, unversioned, and moves behaviour for every lane at once.
* A list of foods that need preparation. That is a food-name branch wearing a
  different hat, wrong for the first food not on it, and the exact shape the
  Semantic Extension Contract exists to refuse.

SO THE EVIDENCE DECIDES. USDA already holds several rows per generic food and
names the preparation in each description. If the rows that come back for
"chicken" carry two or more preparations this system can ACT on, and those rows
disagree about energy by enough to matter, then preparation is a real open
question about this food — and if they do not, it is not, and nobody is
interrupted. No name is special-cased; the same query answers for every food,
including foods nobody thought about.

WHAT THIS DELIBERATELY WILL NOT DO. It does not invent a question from a failed
lookup, a single row, or a preparation the resolver cannot act on. Evidence we
could not gather is not evidence of ambiguity.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

#: How far apart two preparations must price before the question is worth
#: asking. 25% of the lower density — the same order as the quantity slice's
#: `MIN_USEFUL_SPREAD`, and for the same reason: a question that cannot move
#: the number by more than rounding is an interruption, not a clarification.
MATERIAL_SPREAD = 1.25

#: Rows to look at. USDA's curated sets return the common preparations of a
#: generic food well inside this.
_ROWS = 8


def _preparations_in(text: str, vocabulary) -> set:
    """The registered preparations this description names.

    WORD BOUNDARIES, because "fried" is inside "stir-fried" legitimately but
    "raw" is inside "strawberry" by accident.
    """
    low = (text or "").lower()
    return {p for p in vocabulary if re.search(rf"\b{re.escape(p)}\b", low)}


def _density(row: dict) -> Optional[float]:
    per100 = (row or {}).get("per100g") or {}
    try:
        calories = float(per100.get("calories") or 0)
    except (TypeError, ValueError):
        return None
    return calories if calories > 0 else None


async def preparation_is_materially_unresolved(item, context=None) -> bool:
    """The `unresolved_when` predicate for the preparation field.

    ORDER IS THE DIRECTIVE'S, and each step is a reason NOT to ask:

        stated or resolved            -> no field; do not ask twice
        no supported evidence         -> no field; do not invent a question
        fewer than two preparations   -> no field; nothing to choose between
        densities agree               -> no field; the answer changes nothing
    """
    from core.semantic_fields import spec_for
    from skills.nutrition.ambiguity import AmbiguityType

    # THE USER ALREADY TOLD US. `stated` exists to tell a told method from an
    # inferred one, and asking someone to repeat themselves is how a
    # clarification becomes an interrogation.
    prep = getattr(item, "preparation", None)
    if getattr(prep, "stated", False) and getattr(prep, "method", None):
        return False

    # THE INTERPRETER RAISED IT ITSELF — believe it, and skip the lookup.
    for amb in tuple(getattr(item, "material_ambiguities", lambda: ())()):
        if getattr(amb, "ambiguity_type", None) is AmbiguityType.PREPARATION:
            return True

    name = str(getattr(getattr(item, "identity", None), "canonical_name", "")
               or "").strip()
    if not name:
        return False

    # A NAME THAT ALREADY CARRIES A PREPARATION is not an open question, even
    # when the interpreter did not mark it stated — "grilled chicken" answers
    # itself, and re-asking would price a food the user already described.
    vocabulary = tuple(spec_for("preparation").vocabulary)
    if _preparations_in(name, vocabulary):
        return False

    rows = await _rows_for(name)
    by_preparation: dict = {}
    for row in rows:
        density = _density(row)
        if density is None:
            continue
        for found in _preparations_in(str(row.get("description") or ""),
                                      vocabulary):
            # The LOWEST density seen for a preparation, so a single odd row
            # cannot manufacture a spread on its own.
            by_preparation[found] = min(by_preparation.get(found, density),
                                        density)

    if len(by_preparation) < 2:
        return False

    low, high = min(by_preparation.values()), max(by_preparation.values())
    material = low > 0 and (high / low) >= MATERIAL_SPREAD
    logger.info("event=b1_preparation_materiality food=%s preparations=%s "
                "low=%.0f high=%.0f material=%s",
                name, sorted(by_preparation), low, high, material)
    return material


async def _rows_for(name: str) -> list:
    """USDA's own rows for this food. Empty on any failure — see the module
    docstring: a lookup that did not happen is not evidence of ambiguity."""
    try:
        from api.usda import search_food

        return list(await search_food(name, page_size=_ROWS) or ())
    except Exception:
        logger.warning("preparation materiality lookup failed for %r", name,
                       exc_info=True)
        return []
