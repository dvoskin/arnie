"""Candidate retrieval (review 2026-07-25, work order step 4).

Retrieval and selection are separated here, and the separation is the point.

The current cascade is a ladder: try memory, then USDA, then OFF, then web,
first acceptable result wins. That makes fetch order equal winner priority,
which is how a USDA cousin outranks the product's own label — USDA was simply
asked first.

So this module only FETCHES. It ranks nothing, prefers nothing, and returns
everything it found with a declared tier and basis attached. resolver.py
scores afterwards. Sources are fetched concurrently, because with no priority
in the order there is no reason to serialize them.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

from skills.nutrition.models import (FoodResolutionRequest, NutrientProfile,
                                     profile_from_values)
from skills.nutrition.provenance import (MatchGrade, SourceTier,
                                         memory_authority)
from skills.nutrition.scaling import Per100g, PerServing, PerUnit, SourceBasis

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candidate:
    """One source's answer, unranked and unscaled.

    `basis` is what the numbers describe, so scaling.py can use them without
    the adapter having done any arithmetic of its own.
    """
    source: str
    tier: SourceTier
    name: str
    profile: NutrientProfile
    basis: SourceBasis
    brand: Optional[str] = None
    variant: Optional[str] = None
    source_id: Optional[str] = None
    reported_grade: str = MatchGrade.NONE
    #: The source's OWN serving panel — "35 g (12 pieces)" — and its mass.
    #: Kept beside `basis` rather than folded into it because a per-100g row
    #: still has a serving panel, and that panel is the only thing that knows
    #: how much one piece of THIS product weighs.
    serving_text: str = ""
    serving_mass_g: Optional[float] = None

    @property
    def calories(self) -> Optional[float]:
        return self.profile.amount("calories")


# ── adapters: fetch and describe, never rank ─────────────────────────────────
def user_label_candidate(request: FoodResolutionRequest) -> Optional[Candidate]:
    """Tier 1. We asked, they answered — that is the product."""
    if not request.has_user_label:
        return None
    return Candidate(
        source="user_label", tier=SourceTier.USER_LABEL,
        name=request.food_name, profile=request.user_label_values,
        basis=(PerUnit(as_served=True) if request.unit not in ("g", "ml")
               else Per100g()),
        brand=request.brand, variant=request.variant,
        reported_grade=MatchGrade.EXACT)


def provisional_candidate(request: FoodResolutionRequest) -> Optional[Candidate]:
    """The interpreter's own estimate. Always available, always last."""
    if request.provisional_values is None or request.provisional_values.is_empty:
        return None
    return Candidate(
        source="provisional", tier=SourceTier.PROVISIONAL,
        name=request.food_name, profile=request.provisional_values,
        basis=(PerUnit(as_served=True) if request.unit not in ("g", "ml")
               else Per100g()),
        brand=request.brand, variant=request.variant,
        reported_grade=MatchGrade.CATEGORY)


def regular_candidate(row, request: FoodResolutionRequest) -> Optional[Candidate]:
    """A stored food-memory row, at the authority it actually carries.

    This used to hard-code tier 2 / `MatchGrade.EXACT` on the strength of a
    docstring promising the caller had matched product, brand, variant AND
    serving basis. Nothing enforced that promise and the live caller did not
    keep it — the row is written automatically after every lookup, keyed on a
    normalized name. So the tier now comes from `memory_authority`, and only a
    row the user actually corrected is treated as theirs.

    A high token overlap is still not a match: "Royo bagel" must not resolve to
    an unrelated prior bagel because the words line up.
    """
    if row is None:
        return None
    per100 = getattr(row, "per100g", None) or {}
    if not per100.get("calories"):
        return None
    tier, grade, label = memory_authority(
        user_confirmed=bool(getattr(row, "user_confirmed", False)),
        origin_tier=str(getattr(row, "origin_tier", "") or ""),
        confidence=str(getattr(row, "confidence", "") or ""))
    # A cache is not more certain than what filled it. 0.95 was asserting the
    # confidence of a label read off the packet for a remembered name match.
    strength = 0.95 if tier is SourceTier.USER_REGULAR else 0.75
    profile = profile_from_values(
        label, basis="per_100g", confidence=strength,
        source_id=str(getattr(row, "fdc_id", "") or "") or None,
        **{k: per100.get(k) for k in
           ("calories", "protein", "carbs", "fat", "fiber", "sugar", "sodium")})
    return Candidate(
        source=label, tier=tier,
        name=getattr(row, "food_name", request.food_name), profile=profile,
        basis=Per100g(), brand=request.brand, variant=request.variant,
        reported_grade=grade)


def usda_candidates(rows) -> list:
    """Generic-food authority. Tier is GENERIC_EXACT; whether it deserves that
    grade for THIS request is the resolver's call, not USDA's."""
    out = []
    for row in (rows or [])[:8]:
        per100 = (row or {}).get("per100g") or {}
        if not per100.get("calories"):
            continue
        out.append(Candidate(
            source="usda", tier=SourceTier.GENERIC_EXACT,
            name=str(row.get("description") or ""),
            profile=profile_from_values(
                "usda", basis="per_100g", confidence=0.8,
                source_id=str(row.get("fdc_id") or "") or None,
                **{k: per100.get(k) for k in
                   ("calories", "protein", "carbs", "fat", "fiber", "sugar",
                    "sodium")}),
            basis=Per100g(),
            brand=str(row.get("brand") or "") or None,
            source_id=str(row.get("fdc_id") or "") or None,
            reported_grade=MatchGrade.CATEGORY,
            serving_text=str(row.get("serving_text") or ""),
            serving_mass_g=row.get("serving_mass_g")))
    return out


def off_candidate(hit) -> Optional[Candidate]:
    """Branded-label authority. A barcode or exact product match is tier 3 —
    above USDA for a packaged product, because it IS the product."""
    if not hit:
        return None
    per100 = (hit or {}).get("per100g") or {}
    if not per100.get("calories"):
        return None
    grade = (MatchGrade.EXACT if hit.get("_match") == "exact"
             else MatchGrade.CLOSE)
    return Candidate(
        source="off", tier=SourceTier.BRANDED_EXACT,
        name=str(hit.get("name") or ""),
        profile=profile_from_values(
            "off", basis="per_100g", confidence=0.85,
            **{k: per100.get(k) for k in
               ("calories", "protein", "carbs", "fat", "fiber", "sugar",
                "sodium")}),
        basis=Per100g(), brand=hit.get("brand"),
        reported_grade=grade,
        serving_text=str(hit.get("serving_text") or ""),
        serving_mass_g=hit.get("serving_mass_g"))


def web_label_candidate(hit, request: FoodResolutionRequest) -> Optional[Candidate]:
    """A label read off the web. Branded when it names the product; an
    estimate when it is a restaurant-item lookup."""
    if not hit or not hit.get("calories"):
        return None
    branded = bool(request.brand or request.is_packaged)
    return Candidate(
        source="web_label",
        tier=SourceTier.BRANDED_EXACT if branded else SourceTier.ESTIMATED,
        name=str(hit.get("name") or request.food_name),
        profile=profile_from_values(
            "web_label", basis="per_serving",
            confidence=float(hit.get("confidence") or 0.6),
            estimated=not branded,
            **{k: hit.get(k) for k in
               ("calories", "protein", "carbs", "fat", "fiber", "sugar",
                "sodium")}),
        # A branded label's serving is measured; a restaurant-item lookup's is
        # the dish as served, so a vague helping counts as one of them.
        basis=PerServing(serving_mass_g=hit.get("serving_mass_g"),
                         as_served=not branded),
        brand=request.brand,
        reported_grade=MatchGrade.CLOSE if branded else MatchGrade.CATEGORY,
        serving_text=str(hit.get("serving_text") or ""))


# ── the gather ────────────────────────────────────────────────────────────────
async def gather_candidates(request: FoodResolutionRequest, *,
                            usda_search=None, off_search=None,
                            web_lookup=None, regular_row=None) -> list:
    """Everything we can find, concurrently, in no particular order.

    Every fetcher is injected so the resolver is testable without a network
    and so retrieval policy (which sources to consult at all) stays with the
    caller. A source that fails is simply absent — one dead API must not take
    the turn down.
    """
    local = [c for c in (user_label_candidate(request),
                         regular_candidate(regular_row, request),
                         provisional_candidate(request)) if c is not None]

    async def _safe(coro_fn, label):
        """One source, bounded by the turn's budget and absent if it fails.

        Bounded HERE rather than in each source module: this is the one place
        every remote source passes through, and wiring the budget per module
        meant OpenFoodFacts honoured it while USDA and the web-label lookup did
        not — so a turn's ceiling was really a ceiling on one of three sources.

        A source that runs out of time is a MISS, not an error. The estimate is
        committed with its provenance intact, which is the degradation the
        deadline module promises.
        """
        if coro_fn is None:
            return None
        from core import deadline
        try:
            return await deadline.wait_for(coro_fn())
        except deadline.DeadlineExceeded:
            logger.info("event=candidate_source_skipped reason=turn_budget "
                        f"source={label}")
            return None
        except Exception as e:
            logger.warning(f"candidate source {label} failed: {e}")
            return None

    usda_raw, off_raw, web_raw = await asyncio.gather(
        _safe(usda_search, "usda"),
        _safe(off_search, "off"),
        _safe(web_lookup, "web_label"))

    remote = usda_candidates(usda_raw)
    for c in (off_candidate(off_raw), web_label_candidate(web_raw, request)):
        if c is not None:
            remote.append(c)
    return local + remote
