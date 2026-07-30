"""Candidate sets: generation and collapse (build order 4, 5).

Clarification must never be asked directly from raw search results. Raw
results contain the same product three times under different artwork, and
asking "which of these five?" when three are nutritionally identical is
friction manufactured by the pipeline rather than by the food.

So: generate a normalized candidate set, collapse what is nutritionally the
same, and only then look at what remains. If one thing remains, there is no
question. If three remain and they differ by 190 calories, there is a good
one.

The collapse rule is the delicate part, and it cuts both ways:

  collapse    same product, same nutrition, different packaging artwork
  never       Core Power 26 g vs Core Power Elite 42 g

Over-collapsing hides a material choice and logs the wrong product silently.
Under-collapsing asks a question with duplicate answers, which reads as a
system that does not understand its own data.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Optional

from skills.nutrition.models import NutrientProfile
from skills.nutrition.provenance import MatchGrade, SourceTier
from skills.nutrition.staging import Quantity

#: Nutrition closer than this is the same food for grouping purposes — label
#: rounding and per-100g/per-serving conversions produce small differences
#: between records of an identical product.
NUTRIENT_SIGNATURE_TOLERANCE = {"calories": 10.0, "protein": 2.0,
                                "carbs": 3.0, "fat": 2.0}


@dataclass(frozen=True)
class ProductCandidate:
    """One thing the food might be, with its identity dimensions scored
    separately — because they are separately askable. A candidate can match
    the brand perfectly and the size not at all, and knowing which is which is
    what makes a targeted question possible."""
    candidate_id: str
    canonical_name: str
    brand: Optional[str] = None
    product_line: Optional[str] = None
    variant: Optional[str] = None
    package_size: Optional[Quantity] = None
    serving_basis: str = ""
    source: str = "provisional"
    tier: SourceTier = SourceTier.PROVISIONAL
    source_id: Optional[str] = None
    identity_score: float = 0.0
    brand_score: float = 0.0
    variant_score: float = 0.0
    size_score: float = 0.0
    serving_basis_score: float = 0.0
    overall_score: float = 0.0
    nutrient_profile: Optional[NutrientProfile] = None
    match_grade: str = MatchGrade.NONE
    #: Set when this candidate was reached through an alias or a likely
    #: transcription correction. NEVER silently rewritten as fact.
    via_alias: Optional[str] = None
    collapsed_from: tuple = ()

    def describe(self) -> str:
        """The same rule `FoodIdentity.describe` keeps: **the name is never
        omitted.** This dropped it whenever any qualifier existed, so an Open
        Food Facts hit named "Royo Everything Bagel" under brand "Royo"
        described itself as "Royo" — the maker, not the product. Harmless while
        nothing in production ever built a candidate; the moment the ask
        started carrying real ones (audit §8.1) it became the label on a
        clarification and on every candidate trace line.
        """
        from skills.nutrition.staging import FoodIdentity
        return FoodIdentity(canonical_name=self.canonical_name,
                            brand=self.brand, product_line=self.product_line,
                            variant=self.variant,
                            package_size=self.package_size).describe()

    @property
    def calories(self) -> Optional[float]:
        return (self.nutrient_profile.amount("calories")
                if self.nutrient_profile is not None else None)


# ── normalization ─────────────────────────────────────────────────────────────
_PUNCT = re.compile(r"[^a-z0-9 ]+")
_SPACE = re.compile(r"\s+")

#: Words that never distinguish one product from another.
_NOISE = {"the", "a", "an", "of", "with", "and", "brand", "original",
          "classic", "new", "pack", "bottle", "can", "bar", "box"}


def normalize_token(text: Optional[str]) -> str:
    if not text:
        return ""
    t = _PUNCT.sub(" ", str(text).lower())
    words = [w for w in _SPACE.sub(" ", t).strip().split() if w not in _NOISE]
    return " ".join(words)


def nutrient_signature(profile: Optional[NutrientProfile]) -> tuple:
    """A coarse fingerprint of the macros, bucketed at the tolerance. Two
    records of the same product round to the same signature; two genuinely
    different products do not.

    Unknown fields participate as None rather than 0 — a record that omits
    protein must not fingerprint as a zero-protein food."""
    if profile is None:
        return ()
    out = []
    for key, tol in NUTRIENT_SIGNATURE_TOLERANCE.items():
        v = profile.amount(key)
        out.append(None if v is None else round(v / tol))
    return tuple(out)


def grouping_key(candidate: ProductCandidate) -> tuple:
    """What makes two candidates the same food. Every dimension here is one
    that can change nutrition; artwork, packaging language and source are
    deliberately absent."""
    return (
        normalize_token(candidate.brand),
        normalize_token(candidate.product_line),
        normalize_token(candidate.variant),
        _size_key(candidate.package_size),
        normalize_token(candidate.serving_basis),
        nutrient_signature(candidate.nutrient_profile),
    )


def _size_key(size: Optional[Quantity]) -> tuple:
    if size is None:
        return ()
    return (round(float(size.amount), 2), normalize_token(size.unit))


def make_candidate_id(candidate: ProductCandidate) -> str:
    digest = hashlib.sha1(
        "|".join(str(p) for p in grouping_key(candidate)).encode("utf-8")
    ).hexdigest()[:12]
    return f"cand_{digest}"


# ── collapse ──────────────────────────────────────────────────────────────────
def collapse_candidates(candidates) -> list:
    """One entry per nutritionally distinct product.

    The survivor of a group is its highest-tier, highest-scoring member, and it
    remembers what it absorbed — so a trace can show that five raw results
    became two real choices, rather than looking like three were dropped.
    """
    groups = {}
    for c in candidates or []:
        groups.setdefault(grouping_key(c), []).append(c)

    out = []
    for key, members in groups.items():
        members.sort(key=lambda c: (int(c.tier), -c.overall_score))
        winner = members[0]
        if len(members) > 1:
            winner = replace(winner, collapsed_from=tuple(
                m.candidate_id for m in members[1:]))
        out.append(winner)
    out.sort(key=lambda c: -c.overall_score)
    return out


def materially_distinct(candidates, tolerance: float = 25.0,
                        scale: float = 1.0) -> list:
    """The candidates a user could actually be asked to choose between.

    Two survivors whose calories are within `tolerance` are not a real choice —
    picking either produces the same log, so the question would be friction
    with no payoff. Candidates whose calories are unknown always survive: we
    cannot claim they agree with anything.

    `scale` exists because the tolerance is in PORTION calories while a
    candidate's profile may be per 100 g. Two drinks 14 cal/100g apart look
    identical against a 25-cal floor, and are 58 cal apart over a 414 ml
    bottle — a real choice compared in the wrong unit. Callers holding
    per-100g candidates should pass grams/100.
    """
    kept = []
    for c in candidates or []:
        cal = c.calories
        if cal is None:
            kept.append(c)
            continue
        cal = cal * scale
        twin = next((k for k in kept
                     if k.calories is not None
                     and abs(k.calories * scale - cal) <= tolerance), None)
        if twin is None:
            kept.append(c)
    return kept


# ── scoring ───────────────────────────────────────────────────────────────────
def _overlap(a: str, b: str) -> float:
    ta, tb = set(a.split()), set(b.split())
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def score_candidate(candidate: ProductCandidate, *, requested_name: str,
                    requested_brand: Optional[str] = None,
                    requested_variant: Optional[str] = None,
                    requested_size: Optional[Quantity] = None
                    ) -> ProductCandidate:
    """Score each identity dimension on its own, then combine.

    Dimensions are kept separate rather than folded into one number because
    the question to ask depends on WHICH one is weak: a low size_score asks
    about the bottle, a low variant_score asks about the flavour.
    """
    name_score = _overlap(normalize_token(requested_name),
                          normalize_token(candidate.canonical_name
                                          or candidate.describe()))
    brand_score = (1.0 if not requested_brand
                   else _overlap(normalize_token(requested_brand),
                                 normalize_token(candidate.brand)))
    variant_score = (1.0 if not requested_variant
                     else _overlap(normalize_token(requested_variant),
                                   normalize_token(candidate.variant)))
    if requested_size is None or candidate.package_size is None:
        size_score = 0.5 if candidate.package_size is not None else 0.0
    else:
        size_score = (1.0 if _size_key(requested_size)
                      == _size_key(candidate.package_size) else 0.0)
    basis_score = 1.0 if candidate.serving_basis else 0.0

    # An alias hop is a real hypothesis, not a certainty — it costs
    # confidence so that a transcription guess never outranks a direct hit.
    alias_penalty = 0.85 if candidate.via_alias else 1.0
    overall = alias_penalty * (
        0.35 * name_score + 0.30 * brand_score + 0.15 * variant_score
        + 0.10 * size_score + 0.10 * basis_score)

    return replace(candidate, identity_score=round(name_score, 3),
                   brand_score=round(brand_score, 3),
                   variant_score=round(variant_score, 3),
                   size_score=round(size_score, 3),
                   serving_basis_score=round(basis_score, 3),
                   overall_score=round(overall, 3))


def build_candidate_set(candidates, *, requested_name: str,
                        requested_brand: Optional[str] = None,
                        requested_variant: Optional[str] = None,
                        requested_size: Optional[Quantity] = None) -> list:
    """Score → collapse → rank. The output is what a clarification may be
    built from; raw search results are not."""
    scored = [score_candidate(c, requested_name=requested_name,
                              requested_brand=requested_brand,
                              requested_variant=requested_variant,
                              requested_size=requested_size)
              for c in (candidates or [])]
    scored = [replace(c, candidate_id=c.candidate_id or make_candidate_id(c))
              for c in scored]
    return collapse_candidates(scored)
