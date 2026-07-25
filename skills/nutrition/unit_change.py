"""When the user corrects a unit, what survives (correction-turn directive §3, §4).

A correction turn is not an edit to a number. "Three skewers" and "three pieces"
are different foods in every way that matters — different mass, different count
basis, different portion assumption, different resolver winner, different
calories. The count is the only thing they share, and it is the one thing that
looks unchanged.

That resemblance is the whole problem. A correction that only rewrites the unit
string leaves every value DERIVED from the old unit in place, and those values
are the answer: the mass we estimated for a skewer, the serving basis we picked,
the macros we scaled, the row we cached under this food's name. Nothing derived
for three skewers may survive a correction to three pieces, and "the number
didn't change" is not evidence that anything is still true.

Two questions, kept separate because they have different answers:

  * **What does this correction invalidate?** `invalidated_fields` — everything
    downstream of the unit, always, whatever the units were.
  * **Can we still answer at all?** `compatible` — whether the new unit has a
    mass we can stand behind. When it does not, the honest outcomes are a
    disclosed range or a question, and a silent re-estimate is neither.

Nothing here fetches or scales. It says what is no longer known.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple

from skills.nutrition.normalize import _singular

#: Everything computed FROM a unit. A unit correction invalidates all of it —
#: not selectively, because the selection is exactly the judgement that gets
#: this wrong. Enumerated rather than implied so a new derived field is a
#: deliberate addition to this list instead of a silent survivor.
DERIVED_FROM_UNIT = (
    "normalized_mass_g",
    "normalized_volume_ml",
    "count_basis",
    "portion_assumptions",
    "resolver_result",
    "calories",
    "macros",
    "cached_serving_interpretation",
)

#: Units that describe DIFFERENT PHYSICAL THINGS, not different ways of saying
#: the same one. Symmetric — the pair is what is incompatible, not a direction.
#:
#: These are the corrections where reusing the old nutrition is not an
#: approximation but a category error. A skewer holds several pieces; a bowl
#: holds several servings; a slice is a fraction of a whole pizza; a bite is
#: not a portion of anything in particular.
INCOMPATIBLE_PAIRS = frozenset({
    frozenset({"piece", "skewer"}),
    frozenset({"piece", "bowl"}),
    frozenset({"piece", "plate"}),
    frozenset({"slice", "pizza"}),
    frozenset({"slice", "pie"}),
    frozenset({"slice", "loaf"}),
    frozenset({"bite", "serving"}),
    frozenset({"bite", "bowl"}),
    frozenset({"bite", "plate"}),
    frozenset({"sip", "glass"}),
    frozenset({"sip", "bottle"}),
    frozenset({"handful", "bag"}),
    frozenset({"scoop", "tub"}),
    frozenset({"square", "bar"}),
    frozenset({"skewer", "bowl"}),
    frozenset({"skewer", "plate"}),
})

#: Phrases that mean "the whole thing", normalised to the container word so
#: "whole pizza" and "pizza" compare the same.
_WHOLE_PREFIXES = ("whole ", "entire ", "full ", "a whole ", "one whole ")


def _canon(unit: str) -> str:
    """The comparable form of a unit word: lowercased, de-pluralised, and with
    a "whole X" phrase reduced to X."""
    text = (unit or "").strip().lower()
    for prefix in _WHOLE_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break
    return _singular(text)


@dataclass(frozen=True)
class UnitChange:
    """What a correction from `before` to `after` costs.

    `invalidated` is never empty for a real change — that is the point. A
    caller that finds it empty is looking at a correction that did not change
    the unit, and should say so rather than pretending to have re-derived
    anything.
    """
    before: str = ""
    after: str = ""
    invalidated: Tuple[str, ...] = ()
    compatible: bool = True
    #: Set when the units name different physical things. The commit is blocked
    #: until one of the three honest resolutions below is available.
    reason: str = ""
    assumptions: Tuple[str, ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        return bool(self.invalidated)

    @property
    def blocks_commit(self) -> bool:
        return not self.compatible


def compare(before: str, after: str) -> UnitChange:
    """What changing the unit from `before` to `after` invalidates.

    Same unit in and out — a correction to the COUNT alone, "3 pieces" to "4
    pieces" — invalidates nothing about the unit and returns an empty change.
    The count still has to be rescaled, but that is arithmetic on a basis that
    still holds, which is the case this exists to distinguish from.
    """
    old, new = _canon(before), _canon(after)
    if not new or old == new:
        return UnitChange(before=old, after=new)

    incompatible = frozenset({old, new}) in INCOMPATIBLE_PAIRS if old else False
    return UnitChange(
        before=old, after=new,
        invalidated=DERIVED_FROM_UNIT,
        compatible=not incompatible,
        reason=(f"a {new} and a {old} are not the same amount of food"
                if incompatible else ""),
    )


def mass_range_for(unit: str, food: str = "") -> Optional[Tuple[float, float]]:
    """A plausible mass span for one of `unit`, or None when we have none.

    The third of §4's three ways to earn a commit back. A range is honest where
    a point estimate is not: "somewhere between 90 and 320 g" is a true
    statement about three pieces of chicken shish, and 200 g is a guess wearing
    a decimal point.

    Sources, in order of how much they know: the food's own piece weight, then
    the portion ontology's distribution for the measure. Neither covers every
    unit — "piece" of a dish nobody has written a row for returns None, and
    None means ask rather than invent.
    """
    canon = _canon(unit)
    try:
        from skills.nutrition.normalize import piece_weight
        est = piece_weight(food or "", canon)
        if est:
            grams, spread = est
            return (max(0.0, grams - spread), grams + spread)
    except Exception:
        pass
    try:
        from skills.nutrition.portions import distribution_for
        dist = distribution_for(canon, food or "")
        if dist is not None and dist.lower_g and dist.upper_g:
            return (float(dist.lower_g), float(dist.upper_g))
    except Exception:
        pass
    return None


def estimate_is_stale(before_calories, after_calories) -> bool:
    """Whether the "new" estimate is the old one wearing a new unit.

    The hazard specific to a correction turn: the interpreter sees the prior
    exchange in its context, and the easiest thing it can do with "actually
    they were pieces" is repeat the number it already gave. An identical
    calorie figure across a unit change that means a different amount of food
    is not an estimate — it is the previous answer, unrevised.

    This is mode-independent. A stale number must not commit on quick either;
    quick's licence is to accept an estimate, not to accept a number nobody
    made.
    """
    try:
        before, after = float(before_calories or 0), float(after_calories or 0)
    except (TypeError, ValueError):
        return False
    if before <= 0 or after <= 0:
        return False
    return abs(before - after) <= max(1.0, 0.01 * before)


def may_commit(change: UnitChange, *, mass_g: Optional[float] = None,
               serving_definition: Optional[str] = None,
               disclosed_range: Optional[Tuple[float, float]] = None) -> bool:
    """Whether a corrected item may be written (§4).

    Three ways to earn it, and they are the three the directive names: a mass
    we can stand behind, a product serving definition that fixes what one of
    the new units IS, or a range we are willing to show the user. A silent
    re-estimate is none of them — it is the same confident number the
    correction was telling us was wrong.
    """
    if not change.blocks_commit:
        return True
    if mass_g:
        return True
    if serving_definition:
        return True
    if disclosed_range and len(disclosed_range) == 2 and disclosed_range[1] > 0:
        return True
    return False


def question_for(change: UnitChange, food: str = "") -> str:
    """What to ask when the correction leaves us without a mass.

    Names both units, because the user's correction was about the difference
    between them and a question that does not mention it reads as though we
    did not hear.
    """
    if not change.blocks_commit:
        return ""
    name = (food or "that").strip()
    return (f"Were those {change.after}s whole {change.before}s, or "
            f"{change.after}s off one? The two are pretty different for "
            f"{name}.")
