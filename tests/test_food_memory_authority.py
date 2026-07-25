"""A cache of our own answer is not a user's confirmation.

`user_food_matches` is written automatically after every successful lookup, so
almost every row is a remembered lookup rather than anything the user vouched
for. Both candidate builders read only the nutrient columns and handed every row
`SourceTier.USER_REGULAR` with `MatchGrade.EXACT`, which laundered a generic
estimate into permanent user authority.

Traced on the shipped Peanut M&M's transcript:

  1. no branded candidate exists, so generic USDA wins at GENERIC_EXACT
  2. the winner is auto-cached into user_food_matches
  3. next mention, that row returns as USER_REGULAR — tier 2, above
     BRANDED_EXACT, so it outranks the real label once one exists
  4. the generic-fallback disclosure keys on the winner being at or below
     GENERIC_EXACT, so promoting the tier also HID the substitution
  5. promotion.py maps user_regular to the words "user-confirmed", reporting
     our own guess back as the user's own confirmation

Each numbered step has a test below.
"""
import pytest

from skills.nutrition.candidates import regular_candidate
from skills.nutrition.models import FoodResolutionRequest, profile_from_values
from skills.nutrition.provenance import MatchGrade, SourceTier, memory_authority


class _Row:
    """A user_food_matches row, as the candidate builder sees it."""

    def __init__(self, **kw):
        self.per100g = kw.pop("per100g", {"calories": 500, "protein": 10})
        self.food_name = kw.pop("food_name", "Peanut M&Ms")
        self.fdc_id = kw.pop("fdc_id", "12345")
        self.user_confirmed = kw.pop("user_confirmed", False)
        self.origin_tier = kw.pop("origin_tier", None)
        self.confidence = kw.pop("confidence", "likely")
        assert not kw, kw


def _request(name="Peanut M&Ms", **kw):
    return FoodResolutionRequest(food_name=name, raw_quantity="15 pieces", **kw)


# ── 1-3. the cache re-enters at the authority it actually has ─────────────────
def test_an_auto_cached_generic_is_not_a_user_regular():
    """The whole defect in one assertion. This row was created by the resolver
    caching its own generic answer; nobody confirmed anything."""
    out = regular_candidate(_Row(origin_tier="generic_exact"), _request())
    assert out.tier is SourceTier.GENERIC_EXACT, out.tier
    assert out.tier > SourceTier.BRANDED_EXACT, (
        "a cached generic must not outrank a real product label")


def test_a_remembered_lookup_does_not_claim_to_be_an_exact_match():
    """MatchGrade.EXACT means product, brand, variant AND serving basis were
    confirmed. A row keyed on a normalized name confirms none of those, and at
    EXACT its disagreement counts as decisive evidence against a real match."""
    out = regular_candidate(_Row(origin_tier="generic_exact"), _request())
    assert out.reported_grade == MatchGrade.CLOSE, out.reported_grade


def test_a_food_the_user_actually_corrected_is_still_theirs():
    """The tier ORDER was never wrong — only the assignment. A food the user
    weighed or corrected genuinely does beat a database, and must keep doing
    so, or corrections stop sticking."""
    out = regular_candidate(_Row(user_confirmed=True), _request())
    assert out.tier is SourceTier.USER_REGULAR
    assert out.reported_grade == MatchGrade.EXACT


def test_a_branded_database_hit_keeps_branded_authority():
    """Not everything cached is generic. An OpenFoodFacts hit on a good match
    is a branded record and should re-enter as one — the fix must not flatten
    every cache to the floor."""
    out = regular_candidate(_Row(origin_tier="branded_exact"), _request())
    assert out.tier is SourceTier.BRANDED_EXACT


def test_a_legacy_row_with_no_origin_floors_to_generic():
    """Rows written before origin_tier existed. Absent evidence of where the
    numbers came from, the safe reading is "a database lookup", not "the user
    told us"."""
    out = regular_candidate(_Row(origin_tier=None), _request())
    assert out.tier is SourceTier.GENERIC_EXACT


def test_an_origin_label_cannot_claim_user_authority_by_itself():
    """Defence in depth. If a row carries origin_tier='user_regular' without
    the confirmation flag to back it, the label loses — otherwise a single bad
    backfill re-opens the laundering path it was written to close."""
    out = regular_candidate(_Row(origin_tier="user_regular",
                                 user_confirmed=False,
                                 confidence="likely"), _request())
    assert out.tier is SourceTier.GENERIC_EXACT


def test_the_legacy_confirmed_string_still_counts():
    """The correction path wrote confidence='user-confirmed' while leaving the
    boolean False for its whole history. Those rows ARE user corrections and
    must not be demoted by the fix."""
    out = regular_candidate(_Row(confidence="user-confirmed"), _request())
    assert out.tier is SourceTier.USER_REGULAR


def test_a_cache_is_no_more_confident_than_what_filled_it():
    """0.95 asserted the confidence of a label read off the packet."""
    cached = regular_candidate(_Row(origin_tier="generic_exact"), _request())
    confirmed = regular_candidate(_Row(user_confirmed=True), _request())
    assert cached.profile.get("calories").confidence < 0.95
    assert confirmed.profile.get("calories").confidence == 0.95


# ── 4. laundering the tier also hid the substitution ─────────────────────────
def _resolve_with(memory_row):
    """Resolve a named product whose only candidate is the remembered row."""
    from skills.nutrition.resolver import resolve
    cand = regular_candidate(memory_row, _request())
    return resolve(_request(is_packaged=True), [cand])


def test_a_laundered_cache_no_longer_suppresses_the_generic_disclosure():
    """The compounding half of the bug. The generic-fallback disclosure fires
    when the winning tier is at or below GENERIC_EXACT — so promoting a cached
    generic to tier 2 removed the very sentence that would have revealed it."""
    out = _resolve_with(_Row(origin_tier="generic_exact"))
    assert any("generic data" in a for a in out.assumptions), out.assumptions


def test_a_real_user_correction_is_not_disclosed_as_generic():
    """The disclosure must stay honest in both directions — telling a user
    their own corrected number came from generic data is its own defect."""
    out = _resolve_with(_Row(user_confirmed=True))
    assert not any("generic data" in a for a in out.assumptions), out.assumptions


# ── 5. the words shown to the user follow the tier ────────────────────────────
def test_our_own_guess_is_never_reported_as_user_confirmed():
    """promotion.py maps user_regular to "user-confirmed". While a cached
    generic won at tier 2, the app told the user their own guess was something
    they had confirmed."""
    from skills.nutrition.promotion import _CONFIDENCE_BY_TIER

    cached = regular_candidate(_Row(origin_tier="generic_exact"), _request())
    word = _CONFIDENCE_BY_TIER[cached.tier.label]
    assert word != "user-confirmed", word


# ── the two builders must not be able to disagree ─────────────────────────────
def test_the_live_adapter_and_the_gather_path_agree():
    """Two modules deciding the same authority separately is how a fix reaches
    one path and not the other. Both call memory_authority; this pins that."""
    from skills.nutrition.shadow import candidates_from_live

    row = {"per100g": {"calories": 500, "protein": 10},
           "fdc_id": "12345", "user_confirmed": False,
           "origin_tier": "generic_exact", "confidence": "likely"}
    live = [c for c in candidates_from_live("Peanut M&Ms", {}, memory=row)
            if c.source != "usda"][0]
    gathered = regular_candidate(_Row(origin_tier="generic_exact"), _request())
    assert live.tier is gathered.tier
    assert live.reported_grade == gathered.reported_grade


@pytest.mark.parametrize("confirmed,origin,expected", [
    (True,  "",              SourceTier.USER_REGULAR),
    (False, "branded_exact", SourceTier.BRANDED_EXACT),
    (False, "generic_exact", SourceTier.GENERIC_EXACT),
    # Kept AT their own tier, not floored up to generic. A cache of an LLM
    # estimate is still an estimate, and promoting it to "a database said so"
    # is the same laundering this file exists to close, one notch quieter.
    # SourceTier.is_estimate then keeps marking it downstream.
    (False, "estimated",     SourceTier.ESTIMATED),
    (False, "provisional",   SourceTier.PROVISIONAL),
    # Unknown label: floors to generic, matching legacy rows, which really did
    # come from a USDA or OFF lookup. That is evidence for "a database
    # answered" and none at all for "the user told us".
    (False, "nonsense",      SourceTier.GENERIC_EXACT),
])
def test_the_authority_table(confirmed, origin, expected):
    """The whole mapping in one place, so a change to it has to be deliberate."""
    tier, _grade, _label = memory_authority(user_confirmed=confirmed,
                                            origin_tier=origin)
    assert tier is expected


def test_the_floor_only_ever_lowers_authority():
    """The floor exists to stop a row claiming MORE than it earned. If it ever
    raises one, it has become a laundering path itself."""
    for label in ("user_label", "user_regular", "branded_exact",
                  "generic_exact", "estimated", "provisional", "", "junk"):
        tier, _g, _l = memory_authority(user_confirmed=False, origin_tier=label)
        assert tier >= SourceTier.BRANDED_EXACT, (label, tier)
