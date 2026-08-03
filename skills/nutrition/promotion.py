"""Promoting the resolver to own committed nutrition (review 2026-07-25, step 3).

Until now there were two states: legacy commits, resolver observes. This adds
the third — resolver decides, legacy falls back — because an architecture that
chooses nutrition better changes nothing for a user until it owns the number
that gets saved.

The promotion is deliberately narrow. It replaces ONE thing: which candidate's
nutrients become the committed values. Everything downstream stays exactly as
it was — the micro-estimation fallback, card building, dedup, ledger events,
narration. That isolation is the point: if committed nutrition gets worse after
the flip, the resolver is the only thing that changed.

Three guards, in order of how much they matter:

  • an UNRESOLVED resolution never promotes. No candidate surviving validation
    means we know less than the cascade did, not more.
  • a resolution with no calories never promotes. The rest of the system treats
    calories as the anchor, and a profile without one cannot anchor it.
  • a resolution that would move calories by more than a sanity multiple of the
    legacy answer is logged loudly and still promoted — because that is often
    exactly the fix we want (290 → 80 on a Royo bagel) — but it is never
    silent, so a systematic regression is visible in one grep.

Rollout is by mode and optional user allowlist, mirroring the turn
coordinator's shape so there is one rollout idiom in the codebase rather than
two.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_LIVE = "live"

#: Calorie moves beyond this multiple get an extra loud line. Not a block —
#: large corrections are the entire reason the resolver exists.
LOUD_DELTA_MULTIPLE = 2.5


def plausibility_cap() -> float:
    """PLAUSIBILITY BACKSTOP (Phase 3). A VERIFIED identity can still carry a
    broken VALUE — a serving→grams unit slip ("1 cup rice" priced as ~1 gram → 1
    cal when the interpreter said 205) or a mis-bind moves the number an order of
    magnitude. Phase 2 measured the line: past ~5x the override is a unit/mis-bind
    error (the interpreter won 8/8 above 5x), while the useful 2-5x corrections
    (multi-can drinks, jerky) sit below it. So an override that moves calories >=
    this factor is refused even on EXACT/CLOSE identity, and the interpreter's
    baseline stands. FOOD_PLAUSIBILITY_CAP tunes it; <= 0 disables the backstop."""
    try:
        return float(os.getenv("FOOD_PLAUSIBILITY_CAP", "5.0"))
    except (TypeError, ValueError):
        return 5.0


def resolver_mode() -> str:
    """off | shadow | live.

    NUTRITION_RESOLVER_SHADOW stays honoured as shadow, so the flag already
    documented and deployed keeps working after this lands.
    """
    raw = (os.getenv("NUTRITION_RESOLVER_MODE", "") or "").strip().lower()
    if raw in (MODE_OFF, MODE_SHADOW, MODE_LIVE):
        return raw
    legacy = (os.getenv("NUTRITION_RESOLVER_SHADOW", "") or "").strip().lower()
    if legacy in ("1", "true", "yes"):
        return MODE_SHADOW
    # DEFAULT IS SHADOW, NOT OFF.
    #
    # Off meant the whole resolver — candidate scoring, identity validation,
    # basis-aware scaling, the serving-basis sanity checks — had never run on a
    # real turn. Everything built for it was unreachable, and every question
    # about "would the resolver have got this right?" was unanswerable.
    #
    # Shadow has NO side effects: `promote()` returns the legacy result
    # untouched unless the mode is live. What it buys is the comparison line
    # per turn, which is the only evidence that can justify promoting it —
    # and, with FOOD_TRACE on, it is visible the same day rather than after a
    # deliberate flag flip nobody remembers to make.
    return MODE_SHADOW


def _allowlist() -> set:
    raw = os.getenv("NUTRITION_RESOLVER_ALLOWLIST", "") or ""
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def owns_committed_values(user_id=None) -> bool:
    """True only when the resolver should decide what gets saved.

    Live mode, this user in the cohort, and the rollout not halted. The cohort
    logic lives in `canary` — allowlist, percentage bucket and the halt flag
    are one decision and splitting it across two modules is how an allowlist
    ends up able to override a halt.

    Falls back to the pre-canary rule if canary cannot be imported: a rollout
    control that fails closed on an import error would take the resolver dark
    for a reason unrelated to the resolver.
    """
    try:
        from skills.nutrition.canary import owns_committed_values as decide
        return decide(user_id)
    except Exception:                                # pragma: no cover
        if resolver_mode() != MODE_LIVE:
            return False
        allow = _allowlist()
        return (not allow) or (user_id in allow)


def shadow_enabled() -> bool:
    """Shadow logging runs in BOTH shadow and live mode. In live mode the
    comparison is still the record of what changed — turning it off at the
    moment of promotion would blind the rollout."""
    return resolver_mode() in (MODE_SHADOW, MODE_LIVE)


# ── resolution → FoodAnalysis ─────────────────────────────────────────────────
#: Authority tier → the confidence vocabulary the rest of the app already uses.
_CONFIDENCE_BY_TIER = {
    "user_label": "user-confirmed",
    "user_regular": "user-confirmed",
    "branded_exact": "exact",
    "generic_exact": "likely",
    "estimated": "estimated",
    "provisional": "estimated",
}

def _provenance_from(resolution, legacy):
    """The provenance record the RESOLUTION earned.

    Audit I-2. `to_food_analysis` routes through `analyze(...)` with every
    candidate set to None — deliberately, so derived fields are computed by one
    code path — then overwrites `source`, `confidence`, `enrichment_source` and
    `fdc_id`. It never rebuilt `provenance`, which `analyze` had just computed
    from no candidates at all. So a promoted row carried three answers about
    itself:

        .source                          off        receipt headline: OFF
        .confidence                      exact      card badge: not estimated
        .provenance.rung                 estimate   detail: "best estimate…"
        .provenance.macros_are_estimated True

    Three surfaces read three different fields, and this was live for every
    food log. `_stash_sourcing` also persists `provenance.as_dict()`, so the
    STORED record said `estimate` for exactly-matched branded rows, and
    `is_fallback` — the disclosure that a generic is standing in for a named
    product — could never fire on a promoted item.

    Identity facts come from `legacy.provenance`, which was computed against
    the real candidate set: promotion changes WHICH candidate's nutrients win,
    not what the food is, how the portion was sized, or where micros came from.
    """
    from skills.nutrition import authority as _authority

    prior = getattr(legacy, "provenance", None)
    food_class = str(getattr(prior, "food_class", "")
                     or _authority.FoodClass.GENERIC.value)
    try:
        klass = _authority.FoodClass(food_class)
    except ValueError:
        klass = _authority.FoodClass.GENERIC

    # BY LANE, through the ladder's own placement rule — not by tier.
    #
    # The lanes run concurrently and the ladder already prioritises them; a
    # tier-keyed table here would be a SECOND prioritisation, and the two
    # disagree in exactly the place it matters. A web_label answer carries tier
    # BRANDED_EXACT, so a tier mapping calls it `branded_exact` — "From the
    # product label" — while the ladder seats a web candidate on `manufacturer`,
    # "From the manufacturer's label". One answer, two sentences, decided by
    # which module was asked. That is audit T-3's defect reproduced in the fix
    # for I-2.
    rung = _authority.rung_for_lane(
        getattr(resolution, "source", "") or "", klass,
        match_grade=str(getattr(resolution, "match_grade", "") or ""))
    if not rung:
        # The lane seats nowhere for this class — USDA on a restaurant item,
        # a weak Open Food Facts hit. The numbers still committed, so the
        # honest record is that they are not a sourced answer.
        rung = "estimate"
    return _authority.provenance_for(
        rung=rung, food_class=food_class,
        portion_source=str(getattr(prior, "portion_source", "") or ""),
        micronutrient_source=str(getattr(prior, "micronutrient_source", "")
                                 or ""),
        confidence=float(getattr(resolution, "confidence", 0.0) or 0.0),
        # The resolver's own verdict, not a re-derivation: an ESTIMATED or
        # PROVISIONAL tier means the displayed macros really are a guess, and
        # anything above it means a label or database supplied them.
        macros_from_source=not bool(getattr(resolution, "is_estimate", True)))


def promotable(resolution) -> bool:
    """Whether this resolution is fit to own the committed values."""
    if resolution is None:
        return False
    if getattr(resolution, "source", "") in ("", "unresolved"):
        return False
    nutrients = getattr(resolution, "nutrients", None)
    if nutrients is None:
        return False
    calories = nutrients.amount("calories")
    return calories is not None and calories > 0


def to_food_analysis(resolution, *, food_name: str, quantity: str,
                     legacy=None):
    """Build a FoodAnalysis from a resolution.

    Routed through core.food_intelligence.analyze so every derived field —
    protein density, satiety, quality, the coaching note — is computed by the
    same code that computes it for every other path. Only the nutrient values,
    source and confidence come from the resolution.

    Unknown fields stay unknown: a resolution silent on sodium produces
    sodium=None, not 0, and the existing micro-estimation fallback may then
    fill it as a FLAGGED estimate. That is the pre-existing product behaviour
    and promotion does not change it.
    """
    from core.food_intelligence import analyze

    n = resolution.nutrients
    out = analyze(food_name, quantity,
                  n.amount("calories"), n.amount("protein"),
                  n.amount("carbs"), n.amount("fat"),
                  usda_candidate=None, memory_match=None, web_candidate=None)

    for field in ("fiber", "sugar", "sodium"):
        value = n.amount(field)
        if value is not None:
            setattr(out, field, value)

    tier = getattr(getattr(resolution, "tier", None), "label", "")
    out.source = resolution.source
    out.confidence = _CONFIDENCE_BY_TIER.get(tier, "estimated")
    out.enrichment_source = resolution.source
    if getattr(resolution, "source_id", None):
        out.fdc_id = resolution.source_id
    # ...and the fourth field describing the same fact (audit I-2). Left as
    # `analyze` computed it — from no candidates — it contradicted the three
    # above on every promoted row, and it is the one that gets PERSISTED.
    try:
        out.provenance = _provenance_from(resolution, legacy)
    except Exception:
        # A provenance we cannot rebuild is better left as it was than lost:
        # the numbers are still right, and this must never cost the commit.
        pass
    # Carry micros the legacy pass already resolved rather than discarding
    # them: the resolver does not fetch micro panels, so dropping them would
    # make promotion a regression on a dimension it never touched.
    if legacy is not None:
        if not out.micros and getattr(legacy, "micros", None):
            out.micros = legacy.micros
            out.micros_estimated = bool(getattr(legacy, "micros_estimated",
                                                False))
        for field in ("fiber", "sugar", "sodium"):
            if getattr(out, field, None) is None:
                inherited = getattr(legacy, field, None)
                if inherited is not None:
                    setattr(out, field, inherited)
    return out


def promote(resolution, *, food_name: str, quantity: str, legacy,
            user_id=None, turn_id: str = ""):
    """Return the analysis that should be committed.

    The legacy result when promotion is off, not applicable, or unfit; the
    resolution's analysis otherwise. Never raises — a failure here must fall
    back to the value the system would have committed anyway.
    """
    from core import food_trace
    food_trace.note(
        resolver_source=getattr(resolution, "source", "") or "",
        promoted=False)

    if not owns_committed_values(user_id):
        return legacy
    if not promotable(resolution):
        logger.info(
            f"event=nutrition_promotion turn={turn_id or '-'} "
            f"food={food_name!r} outcome=declined "
            f"reason={'no_resolution' if resolution is None else getattr(resolution, 'source', '-')}")
        return legacy
    # OWNERSHIP: the interpreter's reasoned value is the committed BASELINE (it
    # carries the legacy here); a lookup overrides it ONLY on a VERIFIED IDENTITY
    # match. A weak/CATEGORY resolution — or a `provisional` guess — has not
    # actually identified the food, so it must not overwrite the baseline. The
    # user's OWN data (memory / a label they confirmed) is trusted regardless of
    # grade; every other source must be EXACT or CLOSE.
    #
    # Root fix 0802 (project_arnie_resolver_override_rootcause_0802): the resolver,
    # live and owning committed values, was overriding CORRECT interpreter numbers
    # on ~19% of logs — shrimp 150->2450 (357g carbs), eggplant 33->1650, RU foods
    # 20-50x — by promoting weak/category matches. A lookup now earns the override
    # by proving identity, not by merely existing.
    _src = str(getattr(resolution, "source", "") or "").lower()
    _grade = str(getattr(resolution, "match_grade", "") or "").lower()
    _trusted = _src in ("user_label", "user_regular", "memory", "history")
    _verified = _trusted or ("exact" in _grade) or ("close" in _grade)
    if not _verified:
        logger.info(
            f"event=nutrition_promotion turn={turn_id or '-'} "
            f"food={food_name!r} outcome=declined "
            f"reason=unverified_identity src={_src or '-'} grade={_grade or '-'}")
        return legacy
    try:
        promoted = to_food_analysis(resolution, food_name=food_name,
                                   quantity=quantity, legacy=legacy)
    except Exception as e:
        logger.warning(f"nutrition promotion failed, keeping legacy: {e}")
        return legacy

    legacy_cal = getattr(legacy, "calories", None)
    new_cal = promoted.calories
    moved = _delta_ratio(legacy_cal, new_cal)
    # PLAUSIBILITY BACKSTOP (Phase 3): identity says WHICH food; it cannot vouch
    # for the VALUE. "White rice, cooked" was an EXACT match and still committed
    # 1 cal for a cup (a serving→grams slip priced ~1 gram; interpreter said 205,
    # prod fe#2705 on d117581 — P1's identity gate alone let it through). Past
    # the cap the override IS the error, so the reasoned baseline stands. The
    # user's OWN data is exempt: a value they confirmed wins at any ratio.
    _cap = plausibility_cap()
    if _cap > 0 and not _trusted and moved is not None and moved >= _cap:
        logger.warning(
            f"event=nutrition_promotion turn={turn_id or '-'} "
            f"food={food_name!r} outcome=declined reason=implausible_move "
            f"legacy_cal={legacy_cal} new_cal={new_cal} x={moved:.1f} "
            f"cap={_cap:g} src={_src or '-'} grade={_grade or '-'}")
        return legacy
    logger.info(
        f"event=nutrition_promotion turn={turn_id or '-'} "
        f"food={food_name!r} outcome=promoted "
        f"legacy_source={getattr(legacy, 'enrichment_source', None) or getattr(legacy, 'source', '-')} "
        f"new_source={promoted.source} legacy_cal={legacy_cal} "
        f"new_cal={new_cal} grade={resolution.match_grade} "
        f"unknown={','.join(resolution.nutrients.unknown()) or '-'}")
    food_trace.note(promoted=True)
    if moved is not None and moved >= LOUD_DELTA_MULTIPLE:
        # Often the correction we want (290 → 80 on a Royo bagel). Never
        # silent, so a systematic regression is one grep away.
        logger.warning(
            f"event=nutrition_promotion_large_move turn={turn_id or '-'} "
            f"food={food_name!r} legacy_cal={legacy_cal} new_cal={new_cal} "
            f"x={moved:.1f} new_source={promoted.source} "
            f"grade={resolution.match_grade}")
    return promoted


def _delta_ratio(a, b) -> Optional[float]:
    try:
        a, b = float(a or 0), float(b or 0)
    except (TypeError, ValueError):
        return None
    lo, hi = min(a, b), max(a, b)
    if lo <= 0:
        return None
    return hi / lo
