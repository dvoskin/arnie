"""A correction is a typed operation on a resolved food (plan cause B).

The update path takes the interpreter's mutated STRING and re-searches it. So a
correction that changes nothing about what the food IS still went through
identity re-resolution — or, when the name happened to stay the same, through
nothing at all, and the model's freshly-invented macros were written straight to
the row's columns.

Both failures are the same missing thing: the entry was written from a
resolution — a source, a per-100g basis, an anchor — and none of it was kept, so
a correction had nothing to correct against. From the plan:

    preparation / form  apply the form to the same resolved food
    identity            full re-resolve; disclose when it cannot be priced
    portion             **arithmetic on the stored basis, no lookup**
    macros              the user's numbers win, no lookup

This module owns the PORTION arm, which is the one production kept producing
evidence for — "Update the sun chips to just 9 chips please", "Okay make that
3/4 of that cube lol". It is deliberately the same shape as
`answer_application`: settle the changed field on a stored resolution, price
from numbers already in hand, and return None the moment anything is missing.
The caller's fallback for None is exactly what it does today.

THREE ARMS, EACH FOR A POPULATION PROD PRODUCED, weakest evidence last:

    apply_portion                   a mass at both ends, or a stored basis
    apply_count_correction          the same object counted twice
    apply_serving_count_correction  the panel enumerates what the correction
                                    names — "1 small snack bag" -> "1 burger"

**The old portion is derived, not stored.** An entry keeps its committed
calories and a quantity string; the mass behind that string was thrown away.
With the per-100g basis the created event now carries, the mass comes back as
arithmetic — 210 committed calories at 536 cal/100 g is a 39 g portion — which
is what lets "1 bag" become "9 chips" without a lookup. Without the basis there
is nothing to scale and this declines; a guessed ratio here would put a number
on the board that no source ever produced.

The macros arm is not here because it needs no code: the user's numbers already
win at the call site. The identity and preparation arms stay with the executor's
re-resolution — see the module's caller for what is and is not routed.
"""
from __future__ import annotations

import logging
from typing import Mapping, Optional

logger = logging.getLogger(__name__)

#: Macros a portion scales. Fiber, sugar and sodium scale identically and are
#: carried when the basis knows them — a correction that rescales the calories
#: and leaves the sodium is a row describing two different portions.
_SCALED = ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium")

#: Column names, which differ from the nutrient names in exactly one place.
_COLUMN = {"fat": "fats"}


def _num(value) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out


def _grams(raw_quantity: str, food_name: str,
           serving_text: str = "") -> Optional[float]:
    """The mass a quantity string describes, or None.

    `normalize_quantity` is the repo's one answer to this and already knows
    piece weights, vessels and volume conversions. A second table here would be
    a second answer.

    THE PRODUCT'S OWN PANEL FIRST, when the portion is a count. "28 g (about 15
    chips)" says one chip of THIS product is 1.9 g, and `PIECE_WEIGHTS_G`
    describes foods — no table of food-shaped averages knows a Sun Chip from a
    tortilla chip, and its head-noun rule declines on a branded name anyway
    ("Sun Chips Harvest Cheddar" is a cheddar, not a chip). Same helper the
    resolver uses to anchor a count at write time; this is that answer applied
    one turn later.
    """
    text = (raw_quantity or "").strip()
    if not text:
        return None
    try:
        from skills.nutrition.normalize import (count_units_compatible,
                                                normalize_quantity,
                                                serving_unit_mass)
        quantity = normalize_quantity(text, food_name or "")
        count = _num(quantity.count)
        panel = serving_unit_mass(serving_text or "") if serving_text else None
        # THE PANEL FIRST, as this function's docstring has always said. The
        # code checked `quantity.grams` first, which only agreed with the
        # docstring while no generic weight existed for these names.
        if count and count > 0 and panel:
            unit_mass, panel_unit = panel[0], panel[1]
            # The panel's unit has to answer the portion's. "9 chips" against a
            # panel of "15 chips" is the same object; "9 chips" against "1 bar"
            # is not, and scaling one by the other turns a portion into a
            # package.
            if _num(unit_mass) and count_units_compatible(
                    quantity.unit or "", panel_unit or ""):
                return float(unit_mass) * float(count)
        grams = _num(quantity.grams)
        if grams and grams > 0:
            # A PRODUCT THAT PUBLISHES A COUNTING PANEL OWNS ITS OWN PIECE, and
            # a food-shaped average is not a stand-in for it. "Sour Gummy Mini
            # Burgers" with a panel of "15 PIECES" is headed by "burgers", so
            # the generic 226 g hamburger weight matched it (113 g after the
            # "Mini" modifier) and priced one gummy sweet at 395 cal.
            #
            # That panel names a count and no mass, so there is nothing here to
            # scale by — which is the correct answer, not a reason to reach for
            # a different food's weight. Declining hands it to
            # `apply_count_correction`, whose whole subject is a panel that
            # counts pieces: one burger is a fifteenth of the row, 9.3 cal.
            #
            # This docstring's own claim — "its head-noun rule declines on a
            # branded name anyway" — was true only until `PIECE_WEIGHTS_G` grew
            # these rows. It is now enforced rather than assumed.
            if count and count > 0 and serving_text and not panel:
                logger.info(
                    "event=correction_apply outcome=declined "
                    "reason=product_counts_its_own_pieces food=%r panel=%r",
                    food_name, serving_text)
                return None
            return grams
    except Exception:
        return None
    return None


def portion_from_basis(per100: Mapping, *, calories: Optional[float]
                       ) -> Optional[float]:
    """How much was eaten, from what it cost and what it costs per 100 g.

    The entry never stored its mass. It stored the committed calories, and the
    created event now stores the per-100g row they were computed from, so the
    portion is recoverable exactly rather than re-guessed from its wording.
    """
    per_100 = _num((per100 or {}).get("calories"))
    total = _num(calories)
    if not per_100 or per_100 <= 0 or not total or total <= 0:
        return None
    return (total / per_100) * 100.0


def rescale(per100: Mapping, grams: float) -> Optional[dict]:
    """The macros for `grams` of a per-100g row, as entry columns."""
    per_100_cal = _num((per100 or {}).get("calories"))
    if not per_100_cal or per_100_cal <= 0 or not grams or grams <= 0:
        return None
    factor = float(grams) / 100.0
    out = {}
    for nutrient in _SCALED:
        value = _num((per100 or {}).get(nutrient))
        if value is None:
            # Unknown stays unknown. A missing sodium is not a zero sodium —
            # the same rule the nutrient types keep, applied to a rescale.
            continue
        out[_COLUMN.get(nutrient, nutrient)] = round(value * factor, 1)
    return out or None


def scale_by_ratio(committed: Mapping, ratio: float) -> Optional[dict]:
    """The committed row's own numbers at a new fraction of the portion.

    The fallback when there is no stored basis but both portions are
    mass-comparable — or when the user states a fraction of what is already
    there ("make that 3/4"). Arithmetic on numbers that were once resolved
    beats a fresh guess about the same food.
    """
    if not ratio or ratio <= 0:
        return None
    out = {}
    for nutrient in _SCALED:
        column = _COLUMN.get(nutrient, nutrient)
        value = _num((committed or {}).get(column))
        if value is None:
            continue
        out[column] = round(value * float(ratio), 1)
    return out or None


class ScanBoundCorrectionRefused(RuntimeError):
    """⛔⛔ CF5b — defence in depth *(Danny, 2026-08-18)*. A scan-bound turn
    reached correction application. This module scales a row by RATIO or by
    a stored basis — heuristic mass either way for a count like "bar" — and
    on the production turn that motivated this class it multiplied an exact
    label by 2.000 and committed 800 kcal, discarding the snapshot silently.
    The primary router (the planner-side lift) makes this unreachable; this
    invariant means an upstream misclassification commits NOTHING: raised
    before any arithmetic, zero mutation, and the snapshot is named in the
    message so it is never silently discarded again."""

    def __init__(self, snapshot_id, food_name: str):
        self.snapshot_id = snapshot_id
        self.food_name = food_name
        super().__init__(
            f"scan-bound turn (snapshot {snapshot_id}) reached correction "
            f"application for {food_name!r} — refused, nothing scaled")


def _refuse_if_scan_bound(food_name: str) -> None:
    """⛔ READS THE BINDING DECISION, NOT THE ATTACHMENT *(CF5b review)*. A
    mixed multi-food turn carries a scan that bound NOTHING; refusing there
    changed a correction this guard has no business touching — measured: the
    row took "9 chips" beside the whole bag's 210 kcal, where unbound it
    correctly rescales to 90.1."""
    try:
        from core.scan_authority import is_bound, snapshot_id
        bound = is_bound()
        sid = snapshot_id()
    except Exception as exc:                             # noqa: BLE001
        # ⛔ FAIL CLOSED *(CF5c cleanup)*. This used to `return` — a backstop
        # advertised as fail-closed that fell open the moment it could not
        # read the authority. An unreadable authority is an UNKNOWN about
        # binding, and correction arithmetic under an unknown binding is the
        # exact write this guard exists to stop.
        logger.warning("event=correction_apply outcome=refused "
                       "reason=authority_unreadable food=%r", food_name,
                       exc_info=True)
        raise ScanBoundCorrectionRefused(
            None, food_name) from exc
    if bound:
        logger.warning("event=correction_apply outcome=refused "
                       "reason=scan_bound snapshot=%s food=%r", sid, food_name)
        raise ScanBoundCorrectionRefused(sid, food_name)


def apply_portion(*, food_name: str, old_quantity: str, new_quantity: str,
                  committed: Mapping, per100: Optional[Mapping] = None,
                  serving_text: str = "") -> Optional[dict]:
    """New macros for a portion correction on the SAME food, or None.

    Two routes, better one first:

    1. **From the stored basis.** The per-100g row the entry was written from,
       scaled to the corrected mass. Exact, and independent of what the old
       portion was worded as.
    2. **By ratio.** No basis stored (older rows), but both portions resolve to
       a mass — so the row's own committed numbers scale by their ratio.

    None whenever neither route is available. That is the honest outcome for
    "1 bag" -> "a couple handfuls" with no basis to anchor either end, and the
    caller falls back to what it does today.
    """
    _refuse_if_scan_bound(food_name)
    new_grams = _grams(new_quantity, food_name, serving_text)
    if new_grams is None:
        return None

    if per100 and _num((per100 or {}).get("calories")):
        scaled = rescale(per100, new_grams)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied route=basis "
                        "food=%r grams=%.1f cal=%s", food_name, new_grams,
                        scaled.get("calories"))
            return scaled

    old_grams = _grams(old_quantity, food_name, serving_text)
    if old_grams:
        scaled = scale_by_ratio(committed, new_grams / old_grams)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied route=ratio "
                        "food=%r ratio=%.3f cal=%s", food_name,
                        new_grams / old_grams, scaled.get("calories"))
            return scaled

    logger.info("event=correction_apply outcome=declined reason=no_basis "
                "food=%r old=%r new=%r", food_name, old_quantity, new_quantity)
    return None


def apply_count_correction(*, food_name: str, old_quantity: str,
                           new_quantity: str, committed: Mapping
                           ) -> Optional[dict]:
    """"1 bar" -> "half a bar", priced by counting. No mass, no basis, no lookup.

    THE GROUND-TRUTH POPULATION. Verified on the first post-deploy log
    (2026-07-30 20:14, ev#519, "Happy Wolf chocolate chip bar", `basis:
    regular`): when the user's own regular or their read of a label answers the
    food, `_analyze_food` takes the override path and **no lane runs** — so
    there is no per-100g row, and `resolution` is correctly stored as null.
    That is honest, and it left the whole repeat-logging population with no
    arithmetic at all: mass is unknown at both ends, so `apply_portion`
    declines and the model's re-guess stands.

    It does not need mass. One bar and half a bar are the same object counted
    twice, so the ratio of the counts prices it exactly — from numbers the user
    themselves established.

    `count_units_compatible` is the whole safety property, and it is not
    decoration: without it "1 bar" against "60 g" would divide a count by a
    mass and scale a 110-calorie bar to 2,750. It rejects a bare unit and a
    cross-dimension pair, so a portion can never become a package.
    """
    _refuse_if_scan_bound(food_name)
    try:
        from skills.nutrition.normalize import (count_units_compatible,
                                                normalize_quantity)
        old = normalize_quantity((old_quantity or "").strip(), food_name or "")
        new = normalize_quantity((new_quantity or "").strip(), food_name or "")
        old_n, new_n = _num(old.count), _num(new.count)
        if not old_n or not new_n or old_n <= 0 or new_n <= 0:
            return None
        if not count_units_compatible(old.unit or "", new.unit or ""):
            return None
        scaled = scale_by_ratio(committed, new_n / old_n)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied route=count "
                        "food=%r ratio=%.3f cal=%s", food_name, new_n / old_n,
                        scaled.get("calories"))
        return scaled
    except Exception as e:
        logger.warning(f"count correction unavailable: {e}")
        return None


def _counts_a_piece(unit_word: str, food_name: str, panel_unit: str) -> bool:
    """Whether this unit counts PIECES of the source rather than servings of it.

    The old side of a serving-count correction has to be a count of whole
    servings, so every way of naming a piece disqualifies it: the panel's own
    word ("2 pieces"), the product's own noun ("2 burgers"), and the partitive
    nouns that presuppose a whole they were cut from ("2 wedges", "2 chunks").

    The last one is not covered by the first two — "chunk" is interchangeable
    with nothing and names no product — and without it "2 chunks" would be read
    as two servings and priced by dividing the row in half.
    """
    from skills.nutrition.normalize import (is_partitive_unit,
                                            unit_counts_the_pieces)
    return (unit_counts_the_pieces(unit_word, food_name, panel_unit)
            or is_partitive_unit(unit_word))


def _committed_servings(committed: Mapping, per100: Optional[Mapping],
                        serving_text: str) -> Optional[float]:
    """How many of the source's servings the committed macros actually are.

    Only when the panel weighs a serving AND a per-100g basis is stored — then
    the row's own mass is recoverable and the answer is arithmetic. None
    otherwise, which means "not checkable here", not "one".
    """
    # `_serving_count` by its private name deliberately: it is the branch's own
    # uppercase-panel fix, three sessions are building on it right now, and
    # renaming it here would merge clean into their new call sites and break
    # them at runtime. `core.food_intelligence` already reads it this way.
    from skills.nutrition.normalize import _serving_count, serving_unit_mass
    panel = serving_unit_mass(serving_text or "")
    count = _serving_count(serving_text or "")
    if not panel or not count:
        return None
    serving_mass = _num(panel[0]) * _num(count[0])
    grams = portion_from_basis(per100 or {},
                               calories=_num((committed or {}).get("calories")))
    if not serving_mass or serving_mass <= 0 or not grams:
        return None
    return grams / serving_mass


def apply_serving_count_correction(*, food_name: str, old_quantity: str,
                                   new_quantity: str, committed: Mapping,
                                   serving_text: str,
                                   per100: Optional[Mapping] = None
                                   ) -> Optional[dict]:
    """"1 small snack bag" -> "1 burger", priced off the panel's own count.

    THE THIRD POPULATION, and the one prod 2026-08-03 produced. le#936
    corrected fe#2721 to "1 burger" with no calorie key, both arms above
    declined, and the row kept the 15-piece bag's 140 cal against one gummy
    burger. Neither could help: `apply_portion` needs a mass and "15 PIECES"
    names no grams, and `apply_count_correction` needs compatible units — "bag"
    and "burger" are not.

    Nothing was missing but the join. The panel says one serving is 15 pieces;
    the new unit is the product's own noun, so it counts those pieces; the old
    quantity was one serving. One burger is therefore a fifteenth of what is on
    the row — arithmetic on numbers already in hand, no lookup, no guess.

    THE PREMISE IS THAT THE COMMITTED ROW IS `old` WHOLE SERVINGS, and it is
    the only thing here that is assumed rather than read, so it is fenced on
    every side:

      * the count must be one the user actually stated. "whatever was left"
        parses to amount=1.0 by default, and reading that as one serving would
        invent a denominator out of a shrug.
      * it must be whole. Half a bag is not a whole number of servings and
        `old * per_serving` would not be a whole number of pieces either.
      * it must be a unit count, not a helping. "2 handfuls" has a count and a
        mass estimate, and neither is a serving.
      * its unit must not name a piece — else this divides by the serving a
        second time. "1 piece" -> "1 burger" is the same object and belongs to
        the arm above, not to a fifteenth of the row.
      * and where the premise is CHECKABLE it is checked, not assumed. A panel
        that also weighs a serving plus a stored basis gives the row's real
        serving multiple, and it must agree with the count. Sun Chips' own
        "28 g (about 15 chips)" against a 210-cal bag is 1.4 servings, not 1 —
        so "1 bag" there is 21 chips, and this declines rather than calling it
        15. That case is already priced correctly by mass one arm up; what
        matters is that a disagreement is never resolved in favour of the
        wording.
    """
    _refuse_if_scan_bound(food_name)
    try:
        from skills.nutrition.models import COUNT_BASIS_UNIT
        from skills.nutrition.normalize import (_serving_count,
                                                normalize_quantity,
                                                unit_counts_the_pieces)

        panel = _serving_count(serving_text or "")
        if not panel:
            return None
        per_serving, panel_unit = _num(panel[0]), panel[1]
        if not per_serving or per_serving <= 0:
            return None

        # THE NEW UNIT MUST COUNT THE PANEL'S PIECES, or the ratio below counts
        # one thing and divides by another.
        new = normalize_quantity((new_quantity or "").strip(), food_name or "")
        new_n = _num(new.count)
        if not new_n or new_n <= 0:
            return None
        if not unit_counts_the_pieces(new.unit or "", food_name or "",
                                      panel_unit):
            return None

        # THE OLD QUANTITY MUST BE A WHOLE NUMBER OF THE SOURCE'S SERVINGS.
        old = normalize_quantity((old_quantity or "").strip(), food_name or "")
        old_n = _num(old.count)
        if not old_n or old_n <= 0 or old_n != int(old_n):
            return None
        if old.user_stated_amount is None:
            return None
        if old.count_basis != COUNT_BASIS_UNIT:
            return None
        if _counts_a_piece(old.unit or "", food_name or "", panel_unit):
            return None

        actual = _committed_servings(committed, per100, serving_text or "")
        if actual is not None and abs(actual - old_n) > 0.1 * old_n:
            logger.info("event=correction_apply outcome=declined "
                        "reason=serving_multiple_disagrees food=%r stated=%s "
                        "derived=%.2f", food_name, old_n, actual)
            return None

        pieces = old_n * per_serving
        scaled = scale_by_ratio(committed, new_n / pieces)
        if scaled is not None:
            logger.info("event=correction_apply outcome=applied "
                        "route=serving_count food=%r pieces=%.1f ratio=%.4f "
                        "cal=%s", food_name, pieces, new_n / pieces,
                        scaled.get("calories"))
        return scaled
    except Exception as e:
        logger.warning(f"serving-count correction unavailable: {e}")
        return None
