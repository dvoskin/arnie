"""Shadow comparison against the live enrichment path (work order step 10).

Before the resolver owns a single committed number, it runs beside the current
cascade on real traffic and the two answers are logged side by side. The
disagreement rate this produces is the promotion gate — the same discipline
the turn coordinator uses, applied to nutrition.

The one hard constraint: **no duplicate external calls.** The shadow reuses
the candidates the live path already fetched, so running it costs a few
microseconds of arithmetic and nothing else. A shadow that doubles USDA
traffic would be its own incident.

Inert unless NUTRITION_RESOLVER_SHADOW is set, and it can never affect the
committed result — it observes, it does not vote.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from skills.nutrition.candidates import Candidate
from skills.nutrition.models import (FoodResolutionRequest, profile_from_values)
from skills.nutrition.provenance import MatchGrade, SourceTier
from skills.nutrition.resolver import resolve, resolution_log
from skills.nutrition.scaling import Per100g, PerServing

logger = logging.getLogger(__name__)

#: Calorie gap that counts as a real divergence rather than rounding.
MATERIAL_DELTA = 0.10
MATERIAL_FLOOR = 25.0

_NUTRIENTS = ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium")


def shadow_enabled() -> bool:
    return (os.getenv("NUTRITION_RESOLVER_SHADOW", "") or "").strip().lower() \
        in ("1", "true", "yes")


def _from_per100g(source: str, tier: SourceTier, name: str, per100g: dict,
                  brand=None, grade=MatchGrade.CLOSE,
                  source_id=None) -> Optional[Candidate]:
    per100g = per100g or {}
    if not per100g.get("calories"):
        return None
    return Candidate(
        source=source, tier=tier, name=name or "",
        profile=profile_from_values(
            source, basis="per_100g", confidence=0.8, source_id=source_id,
            **{k: per100g.get(k) for k in _NUTRIENTS}),
        basis=Per100g(), brand=brand, source_id=source_id,
        reported_grade=grade)


def candidates_from_live(food_name: str, inp: dict, *, memory=None, usda=None,
                         off=None, web=None) -> list:
    """Re-express what the live path ALREADY fetched as resolver candidates.

    Nothing here reaches the network. Each live source keeps its own shape;
    this is the adapter, and the only place that knows those shapes.
    """
    out = []
    mem = _from_per100g("user_regular", SourceTier.USER_REGULAR, food_name,
                        (memory or {}).get("per100g"),
                        grade=MatchGrade.EXACT,
                        source_id=str((memory or {}).get("fdc_id") or "") or None)
    if mem is not None:
        out.append(mem)

    usda_row = usda or {}
    u = _from_per100g("usda", SourceTier.GENERIC_EXACT,
                      usda_row.get("description") or "",
                      usda_row.get("per100g"),
                      brand=usda_row.get("brand") or None,
                      grade=MatchGrade.CATEGORY,
                      source_id=str(usda_row.get("fdc_id") or "") or None)
    if u is not None:
        out.append(u)

    off_row = off or {}
    o = _from_per100g("off", SourceTier.BRANDED_EXACT,
                      off_row.get("name") or "", off_row.get("per100g"),
                      brand=off_row.get("brand"),
                      grade=(MatchGrade.EXACT if off_row.get("_match") == "exact"
                             else MatchGrade.CLOSE))
    if o is not None:
        out.append(o)

    web_row = web or {}
    if web_row.get("calories"):
        branded = bool(inp.get("is_packaged"))
        out.append(Candidate(
            source="web_label",
            tier=(SourceTier.BRANDED_EXACT if branded else SourceTier.ESTIMATED),
            name=str(web_row.get("name") or food_name),
            profile=profile_from_values(
                "web_label", basis="per_serving",
                confidence=float(web_row.get("confidence") or 0.6),
                estimated=not branded,
                **{k: web_row.get(k) for k in _NUTRIENTS}),
            basis=PerServing(serving_mass_g=web_row.get("serving_mass_g")),
            reported_grade=(MatchGrade.CLOSE if branded
                            else MatchGrade.CATEGORY)))

    if inp.get("calories"):
        tier = (SourceTier.USER_LABEL if inp.get("user_label")
                else SourceTier.PROVISIONAL)
        out.append(Candidate(
            source=("user_label" if inp.get("user_label") else "provisional"),
            tier=tier, name=food_name,
            profile=profile_from_values(
                ("user_label" if inp.get("user_label") else "provisional"),
                basis="per_serving",
                confidence=0.95 if inp.get("user_label") else 0.4,
                estimated=not inp.get("user_label"),
                **{k: inp.get("fats" if k == "fat" else k) for k in _NUTRIENTS}),
            basis=PerServing(),
            reported_grade=(MatchGrade.EXACT if inp.get("user_label")
                            else MatchGrade.CATEGORY)))
    return out


def _material(legacy_cal, new_cal) -> bool:
    if legacy_cal is None or new_cal is None:
        return legacy_cal != new_cal
    delta = abs(float(legacy_cal) - float(new_cal))
    if delta < MATERIAL_FLOOR:
        return False
    return delta / max(float(legacy_cal), float(new_cal), 1.0) >= MATERIAL_DELTA


def compare(food_name: str, inp: dict, legacy_result, *, memory=None,
            usda=None, off=None, web=None, mode: str = "moderate",
            turn_id: str = "") -> Optional[dict]:
    """Log the live answer against the resolver's. Returns the comparison (for
    tests) or None when not shadowing. NEVER raises, NEVER writes."""
    if not shadow_enabled():
        return None
    try:
        request = FoodResolutionRequest(
            food_name=food_name, raw_quantity=str(inp.get("quantity") or ""),
            brand=inp.get("brand"), mode=mode,
            is_packaged=bool(inp.get("is_packaged")))
        candidates = candidates_from_live(food_name, inp, memory=memory,
                                          usda=usda, off=off, web=web)
        new = resolve(request, candidates)

        legacy_cal = getattr(legacy_result, "calories", None)
        new_cal = new.nutrients.amount("calories")
        legacy_source = (getattr(legacy_result, "enrichment_source", None)
                         or getattr(legacy_result, "source", "") or "")
        diverged = _material(legacy_cal, new_cal)

        detail = resolution_log(request, new, turn_id=turn_id)
        logger.info(
            f"event=nutrition_shadow turn={turn_id or '-'} "
            f"food={food_name!r} "
            f"legacy_source={legacy_source or '-'} new_source={new.source} "
            f"legacy_cal={legacy_cal} new_cal={new_cal} "
            f"grade={new.match_grade} unknown={','.join(new.nutrients.unknown()) or '-'} "
            f"rejected={len(new.rejected_candidates)} "
            f"agree={'NO' if diverged else 'yes'}")
        return {"legacy_source": legacy_source, "legacy_calories": legacy_cal,
                "new_source": new.source, "new_calories": new_cal,
                "diverged": diverged, "resolution": detail}
    except Exception as e:
        logger.warning(f"nutrition shadow skipped: {e}")
        return None
