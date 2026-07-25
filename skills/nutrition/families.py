"""Product-family rules and failure states (build order 18, 19).

Some brands have predictable, structural ambiguity. "A Fairlife" is not
under-specified because the user was careless — it is under-specified because
Fairlife sells four product lines in three sizes with materially different
nutrition, and the brand name genuinely does not identify a product.

So the rules here encode the identity DIMENSIONS that materially distinguish a
brand's products, not conversational copy. "Which Fairlife bottle was it?" is
generated from `required_identity_fields = (product_line, package_size)`;
hard-coding the sentence per brand would mean a new brand needs new prose
rather than new data.

The second half is a distinction the current code cannot make: four different
things all present as "we don't have a good answer", and they deserve four
different behaviours.

    ambiguous     several plausible products — ask which
    no match      nothing trustworthy found — ask what the label says
    unavailable   the source failed — offer an estimate or the label
    unsupported   cannot be confidently represented at all — say so

Collapsing them means telling a user "I couldn't identify the product" when
USDA was simply down, which is both wrong and unactionable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CandidateResolutionFailure(str, Enum):
    NO_MATCH = "no_match"
    MULTIPLE_MATERIAL_MATCHES = "multiple_material_matches"
    SOURCE_UNAVAILABLE = "source_unavailable"
    INVALID_SERVING_BASIS = "invalid_serving_basis"
    UNSUPPORTED = "unsupported"

    @property
    def is_askable(self) -> bool:
        """Whether asking the user can actually resolve this. A dead API
        cannot be fixed by the user picking an option."""
        return self in (CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES,
                        CandidateResolutionFailure.NO_MATCH,
                        CandidateResolutionFailure.INVALID_SERVING_BASIS)


#: What to say, per failure. Kept here rather than per brand: the behaviour
#: differs by FAILURE KIND, not by product.
FAILURE_MESSAGES = {
    CandidateResolutionFailure.NO_MATCH:
        "I couldn't identify the exact product. What does the label show?",
    CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES:
        "I found more than one version with different nutrition.",
    CandidateResolutionFailure.SOURCE_UNAVAILABLE:
        "I can't reach the product database right now — I can estimate it or "
        "use the label values.",
    CandidateResolutionFailure.INVALID_SERVING_BASIS:
        "I found the product but its serving info doesn't add up. What does "
        "the label say per serving?",
    CandidateResolutionFailure.UNSUPPORTED:
        "I can't represent that one confidently. Tell me the calories and "
        "protein and I'll log it as stated.",
}


@dataclass(frozen=True)
class ProductFamilyRule:
    """The identity dimensions that materially distinguish a brand's products.

    `required_identity_fields` are the ones without which the product is not
    identified. `optional_fields` are recorded when known but never block —
    a flavour that does not move nutrition is not worth a turn.
    """
    brand: str
    required_identity_fields: tuple = ()
    optional_fields: tuple = ()
    aliases: tuple = ()
    note: str = ""

    def missing_from(self, identity) -> tuple:
        """Which required dimensions this identity still lacks. A barcode
        satisfies everything — it IS the product."""
        if getattr(identity, "barcode", None):
            return ()
        missing = []
        for name in self.required_identity_fields:
            if getattr(identity, name, None) in (None, ""):
                missing.append(name)
        return tuple(missing)


#: Brands whose ambiguity is structural. Adding one is data, not code.
PRODUCT_FAMILIES = {
    "fairlife": ProductFamilyRule(
        brand="Fairlife",
        required_identity_fields=("product_line", "package_size"),
        optional_fields=("variant",),
        aliases=("fair life", "fairlife nutrition plan", "core power"),
        note="Core Power 26g, Core Power Elite 42g and Nutrition Plan 30g "
             "differ by up to 190 cal and 16 g protein."),
    "chobani": ProductFamilyRule(
        brand="Chobani",
        required_identity_fields=("product_line", "variant", "package_size"),
        aliases=("chobani zero", "chobani complete"),
        note="Zero Sugar, Complete and Whole Milk differ materially; flavour "
             "moves sugar."),
    "quest": ProductFamilyRule(
        brand="Quest",
        required_identity_fields=("product_line",),
        optional_fields=("variant",),
        aliases=("quest nutrition",),
        note="Bars, chips and cookies are different foods entirely."),
    "premier protein": ProductFamilyRule(
        brand="Premier Protein",
        required_identity_fields=("product_line", "package_size"),
        optional_fields=("variant",)),
    "kind": ProductFamilyRule(
        brand="KIND",
        required_identity_fields=("variant",),
        note="Flavour drives nuts vs fruit vs chocolate — a material swing."),
    "rxbar": ProductFamilyRule(
        brand="RXBAR",
        required_identity_fields=("variant",),
        aliases=("rx bar",)),
    "starbucks": ProductFamilyRule(
        brand="Starbucks",
        required_identity_fields=("product_line", "package_size"),
        optional_fields=("variant",),
        note="Size is the dominant variable; milk choice is secondary."),
    "dunkin": ProductFamilyRule(
        brand="Dunkin'",
        required_identity_fields=("product_line", "package_size"),
        aliases=("dunkin donuts", "dunkin'")),
    "mcdonalds": ProductFamilyRule(
        brand="McDonald's",
        required_identity_fields=("product_line",),
        aliases=("mcdonald's", "mc donalds", "maccas")),
    "chipotle": ProductFamilyRule(
        brand="Chipotle",
        required_identity_fields=("product_line",),
        optional_fields=("variant",),
        note="Bowl vs burrito vs salad, then protein choice."),
    "thomas": ProductFamilyRule(
        brand="Thomas'",
        required_identity_fields=("product_line", "variant"),
        aliases=("thomas", "thomas english muffin")),
    "halo top": ProductFamilyRule(
        brand="Halo Top",
        required_identity_fields=("variant", "package_size")),
    "siggis": ProductFamilyRule(
        brand="Siggi's",
        required_identity_fields=("product_line", "package_size"),
        aliases=("siggis", "siggi")),
    "core power": ProductFamilyRule(
        brand="Core Power",
        required_identity_fields=("product_line", "package_size"),
        note="A Fairlife line, but users name it directly."),
    "m&m": ProductFamilyRule(
        brand="M&M's",
        required_identity_fields=("variant",),
        aliases=("m&ms", "m&m's", "mms", "peanut m&m"),
        note="Plain, Peanut, Peanut Butter and Almond differ by roughly 3x "
             "PER PIECE, so a piece count means nothing without the variant."),
    "barebells": ProductFamilyRule(
        brand="Barebells",
        required_identity_fields=("variant",),
        aliases=("bare bells", "barebell"),
        note="Flavour moves the macros; the Soft line differs again."),
}


def rule_for(brand: Optional[str], food_name: str = "") -> Optional[ProductFamilyRule]:
    """The family rule for this brand, matched on the brand or on an alias
    appearing in the food name."""
    haystack = f"{brand or ''} {food_name or ''}".lower()
    if not haystack.strip():
        return None
    best, best_len = None, 0
    for key, rule in PRODUCT_FAMILIES.items():
        for needle in (key, rule.brand.lower(), *rule.aliases):
            if needle and needle in haystack and len(needle) > best_len:
                best, best_len = rule, len(needle)
    return best


def required_dimensions(identity, food_name: str = "") -> tuple:
    """Which identity dimensions this product still needs, per its family.

    Returns () for a brand with no family rule — absence of a rule means we
    have no evidence the brand is structurally ambiguous, not that every
    unknown field is required.
    """
    rule = rule_for(getattr(identity, "brand", None), food_name)
    if rule is None:
        return ()
    return rule.missing_from(identity)


def classify_failure(*, candidates, source_errors: int = 0,
                     sources_attempted: int = 0,
                     invalid_serving_basis: bool = False,
                     tolerance: float = 25.0) -> Optional[CandidateResolutionFailure]:
    """Which of the four states we are actually in.

    Order matters. A dead source is checked BEFORE "no match", because "I
    couldn't identify the product" is a lie when we never got to look — and it
    sends the user to read a label they may not need.
    """
    if invalid_serving_basis:
        return CandidateResolutionFailure.INVALID_SERVING_BASIS
    if not candidates:
        if sources_attempted and source_errors >= sources_attempted:
            return CandidateResolutionFailure.SOURCE_UNAVAILABLE
        return CandidateResolutionFailure.NO_MATCH
    from skills.nutrition.candidate_sets import materially_distinct
    if len(materially_distinct(candidates, tolerance=tolerance)) > 1:
        return CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES
    return None


#: Which recovery each failure points at. The composer phrases it; this decides
#: WHAT the next useful action is, which is a different question from how to
#: say it.
_RECOVERY = {
    CandidateResolutionFailure.NO_MATCH:
        ("ask for the label calories and protein", True, True),
    CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES:
        ("ask which version it was", True, True),
    CandidateResolutionFailure.SOURCE_UNAVAILABLE:
        ("offer an estimate or the label values", False, False),
    CandidateResolutionFailure.INVALID_SERVING_BASIS:
        ("ask what the label says per serving", True, True),
    CandidateResolutionFailure.UNSUPPORTED:
        ("ask for calories and protein and log as stated", True, True),
}


def failure_intent(failure: CandidateResolutionFailure, options=()):
    """The structured failure, for the response layer to phrase.

    This module owns the TAXONOMY — what went wrong and what would fix it. It
    does not own Arnie's voice: hard-coding polished prose here means a tone
    change has to be made in every module that can fail, and it means a failure
    reads differently depending on which subsystem noticed it.

    `user_fixable` is the distinction that matters most. A dead API is not the
    user's problem to solve, and asking them to read a label they may not need
    is worse than saying we cannot check right now.
    """
    from core.food_response import FailureIntent
    recovery, fixable, asks = _RECOVERY.get(
        failure, _RECOVERY[CandidateResolutionFailure.NO_MATCH])
    return FailureIntent(
        code=failure.value, user_fixable=fixable, recovery_action=recovery,
        approved_message=failure_message(failure, options),
        requires_question=(asks and failure.is_askable))


def failure_message(failure: CandidateResolutionFailure,
                    options=()) -> str:
    """User-facing text, differing by failure kind. Options are appended only
    for the state where choosing actually resolves something."""
    base = FAILURE_MESSAGES.get(failure, FAILURE_MESSAGES[
        CandidateResolutionFailure.NO_MATCH])
    if failure is CandidateResolutionFailure.MULTIPLE_MATERIAL_MATCHES:
        if options:
            labels = " or ".join(str(o) for o in list(options)[:3])
            return f"{base} Was it {labels}?"
        # This failure REQUIRES an answer, so the message has to ask for one.
        # Without options the base sentence merely reported the problem and
        # left the user with nothing to do — a question the plan promised and
        # the text never delivered.
        return f"{base} Which one was it?"
    return base
