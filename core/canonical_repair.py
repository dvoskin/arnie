"""⭐ B-1.8a — THE REPAIR PRIMITIVE. PURE. A CORRECTION REUSES WHAT ARNIE KNEW.

    "actually 3 eggs"   against a committed 2-egg meal
        -> bind the row's own facts (receipt when present, macros always)
        -> ONE deterministic ratio
        -> every committed number × that ratio
        -> new receipt fields, provenance preserved

⛔⛔ NO PROVIDER, NO ARTIFACT, NO MODEL, NO DATABASE. This module computes; the
B-1.8b executor binds and writes. "2 eggs -> 3 eggs" must never rediscover USDA
— the committed macros ARE the persisted evidence, and the receipt says how
they were scaled. Repricing is arithmetic over facts already on the row.

⛔ THE RATIO IS DERIVED OR THE REPAIR IS REFUSED — never estimated. A
correction that cannot be computed deterministically from what was persisted
is a typed `RepairRefused`, and the caller decides what to ask the user. A
guessed ratio would be the estimate rung wearing a correction's clothes.

⚠ PRE-P17f ROWS CARRY NO RECEIPT — which today is EVERY production row. Their
quantity repair is the ratio path over committed macros: still deterministic,
still evidence-preserving (the macros were priced from evidence and scale as a
block), just without the receipt's extra reach (cross-dimension corrections).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

#: The row fields a repair rescales, macros and the extended panel alike.
#: Everything scales by the ONE ratio — a field scaling differently from its
#: neighbours would mean the correction changed the food, not the amount.
SCALED_FIELDS = ("calories", "protein", "carbs", "fats", "fiber", "sugar",
                 "sodium")


class RepairRefused(Exception):
    """This correction cannot be computed deterministically from what was
    persisted. Typed, so the caller can ASK rather than guess — the refusal
    names what was missing."""


@dataclass(frozen=True)
class RepairedQuantity:
    """What a quantity correction does to a committed row. Numbers only —
    the B-1.8b executor turns this into a mutation."""
    ratio: float
    #: field -> new value, for every SCALED_FIELDS present on the row.
    changes: dict
    #: micros dict rescaled by the same ratio, or None if the row had none.
    micros: Optional[dict]
    #: The receipt's next state: factor and resolved grams move WITH the
    #: correction; evidence ids and basis do NOT — the food did not change.
    receipt_updates: dict = field(default_factory=dict)
    #: How the ratio was derived, for the ledger event.
    method: str = ""


def _positive(value) -> Optional[float]:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out > 0 and out == out else None


def _ratio(old_q, new_q, *, resolved_grams=None) -> tuple:
    """(ratio, method, new_resolved_grams) — or raise `RepairRefused`.

    The dimension rules, cheapest and most exact first:

      GRAMS -> GRAMS      ratio = g_new / g_old        (exact masses only)
      COUNT -> COUNT      ratio = c_new / c_old, same unit — "2 eggs" and
                          "3 eggs" count the same thing; "2 bars" and
                          "3 bottles" do not, and unit identity is asked of
                          the ONE matcher the pricer uses
      COUNT -> GRAMS      needs the receipt's resolved_grams: the mass the
                          old count was priced AT. g_new / resolved_grams.
      GRAMS -> COUNT      the inverse, same requirement.

    ⛔ HEURISTIC MASSES DO NOT PARTICIPATE. `mass_is_exact` gates the gram
    paths: a piece-weight guess on the corrected quantity must not silently
    reprice a meal that was priced from evidence — the precedence P17c.2
    froze applies to corrections exactly as it applies to first pricing.
    """
    from skills.nutrition.scaling import unit_matches

    old_grams = _positive(getattr(old_q, "grams", None)) \
        if getattr(old_q, "mass_is_exact", False) else None
    new_grams = _positive(getattr(new_q, "grams", None)) \
        if getattr(new_q, "mass_is_exact", False) else None
    old_count = _positive(getattr(old_q, "count", None))
    new_count = _positive(getattr(new_q, "count", None))
    resolved = _positive(resolved_grams)

    if old_grams and new_grams:
        return new_grams / old_grams, "grams_ratio", None

    if old_count and new_count:
        old_unit = str(getattr(old_q, "unit", "") or "")
        if not unit_matches(new_q, old_unit):
            raise RepairRefused(
                f"the correction counts {getattr(new_q, 'unit', '')!r} and the "
                f"meal counted {old_unit!r} — a count may only correct a count "
                f"of the same thing")
        ratio = new_count / old_count
        return ratio, "count_ratio", (resolved * ratio if resolved else None)

    if old_count and new_grams and resolved:
        # The receipt knows what mass the old count was PRICED AT — the exact
        # cross-dimension bridge, from evidence already persisted.
        return new_grams / resolved, "receipt_grams_bridge", new_grams

    # GRAMS -> COUNT has no bridge: the receipt's resolved mass is the OLD
    # portion's total, and with no old count there is no grams-per-unit to
    # divide by. Refused, typed — the caller asks, never guesses.
    raise RepairRefused(
        "no deterministic ratio: the correction and the committed quantity "
        "share no dimension, and the row carries no receipt bridge "
        f"(old={getattr(old_q, 'unit_label', '')!r}, "
        f"new={getattr(new_q, 'unit_label', '')!r}, "
        f"resolved_grams={'present' if resolved else 'absent'})")


def reprice_quantity(*, entry, old_quantity, new_quantity) -> RepairedQuantity:
    """The quantity repair, computed. `entry` is the committed row (its macros
    and, when present, its P17f receipt); the two quantities are the caller's
    normalization of the stored text and the correction.

    ⭐ ONE RATIO, EVERY FIELD. The committed numbers were priced from evidence
    as a block and they move as a block — including micros, including the
    receipt's own scaling_factor, which is what keeps a twice-corrected meal
    repricing from ITS OWN history rather than compounding drift.
    """
    ratio, method, new_resolved = _ratio(
        old_quantity, new_quantity,
        resolved_grams=getattr(entry, "resolved_grams", None))
    if not (0 < ratio == ratio and ratio != float("inf")):
        raise RepairRefused(f"computed ratio {ratio!r} is not usable")

    changes = {}
    for name in SCALED_FIELDS:
        value = getattr(entry, name, None)
        if value is not None:
            changes[name] = round(float(value) * ratio, 2)

    micros = None
    raw = getattr(entry, "micronutrients_json", None)
    if raw:
        import json
        try:
            parsed = json.loads(raw)
            micros = {k: round(float(v) * ratio, 4)
                      for k, v in parsed.items()
                      if isinstance(v, (int, float))}
        except (ValueError, TypeError):
            # Unreadable micros are LEFT ALONE and reported — scaling a blob we
            # cannot parse would corrupt it; the macros still repair.
            logger.warning("repair: unreadable micros on entry %s left as-is",
                           getattr(entry, "id", "?"))
            micros = None

    receipt_updates = {}
    old_factor = _positive(getattr(entry, "scaling_factor", None))
    if old_factor:
        receipt_updates["scaling_factor"] = round(old_factor * ratio, 6)
    if new_resolved:
        receipt_updates["resolved_grams"] = round(new_resolved, 2)

    return RepairedQuantity(ratio=ratio, changes=changes, micros=micros,
                            receipt_updates=receipt_updates, method=method)

