"""The one scaling engine (review 2026-07-25, work order step 6).

Every source adapter currently scales its own numbers, which means the
per-100g→portion arithmetic exists in several places with several sets of
assumptions. Forward-scaling mistakes have already caused incidents.

So: no adapter scales anything. Each declares what its numbers describe —

    Per100g()                       per 100 g
    Per100ml()                      per 100 ml
    PerServing(serving_mass_g=43)   one serving, with its mass
    PerUnit(unit_mass_g=54)         one piece/slice, with its mass

— and this module does the only multiplication in the system.

Scaling is refused, not guessed, when the bases cannot be reconciled: a
per-serving panel with no serving mass cannot answer "how much in 86 g". A
refusal surfaces as an unknown, which the validators and the clarification
ladder can act on. A guess surfaces as a confident wrong number.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, replace
from typing import Optional, Union

from skills.nutrition.models import NormalizedQuantity, NutrientProfile

logger = logging.getLogger(__name__)


class ScalingRefused(ValueError):
    """The bases cannot be reconciled. Not an error to swallow — the caller
    must record an unknown rather than substitute an estimate."""


# ── what a source's numbers describe ──────────────────────────────────────────
@dataclass(frozen=True)
class Per100g:
    basis = "per_100g"

    def source_quantity(self):
        """What ONE of this basis IS — the source side of a pricing receipt."""
        return 100.0, "g"


@dataclass(frozen=True)
class Per100ml:
    basis = "per_100ml"

    def source_quantity(self):
        return 100.0, "ml"


@dataclass(frozen=True)
class PerServing:
    """One serving, ideally with its mass.

    `as_served` says whose serving it is. A branded label or a USDA row defines
    a MEASURED serving — 43 g, 240 ml — and a vague helping is not one of them.
    A restaurant-item estimate, a provisional guess or the user's own saved
    regular defines the dish AS SERVED, so one helping of it genuinely is one
    serving however loosely the user described the helping.

    Without that flag the two collapse, and "one plate" reads as one serving of
    a packaged label whose serving mass we never knew.

    ⛔⛔ `unit_id` IS WHAT A COUNT MUST MATCH BEFORE IT MAY MULTIPLY *(P17b.1,
    2026-08-17)*. A label states "1 BAR = 200 kcal"; without the unit named, a
    count of two BOTTLES multiplies it just as happily, because
    `count_is_serving_compatible` answers about the COUNT alone and can never
    see what the source is counting. Set it and the count path demands identity;
    leave it unset and behaviour is exactly as before.

    ⭐ P17e — `servings_per_package` IS NOW CONSUMED, and the package relation is
    DATA on this basis rather than a branch anywhere: a count of the PACKAGE
    unit multiplies by it. "1 bottle" of a 2-servings-per-bottle label is 2
    servings; "half a bottle" is 1. ⛔ BOTH HALVES OF THE RELATION ARE REQUIRED:
    a package unit with no stated servings-per-package REFUSES rather than
    quietly assuming one package = one serving — that equality is a fact some
    labels state and others contradict, never a default.
    """
    serving_mass_g: Optional[float] = None
    serving_ml: Optional[float] = None
    servings_per_package: Optional[float] = None
    as_served: bool = False
    #: What ONE serving IS — "bar", "bottle", "large egg". Identity, not prose.
    unit_id: str = ""
    #: What ONE PACKAGE is called — "bottle", "tub", "bag" — when the package
    #: is a DIFFERENT thing from the serving. Identity for the package path.
    package_unit_id: str = ""
    basis = "per_serving"

    def source_quantity(self):
        return 1.0, (self.unit_id or "serving")


@dataclass(frozen=True)
class PerUnit:
    """One piece, slice, bagel, bar. `unit_mass_g` is what makes it scalable
    against a mass; without it, only whole-unit counts work.

    `as_served` carries the same meaning as on PerServing: the unit is whatever
    the user described, not a measured piece."""
    unit_mass_g: Optional[float] = None
    as_served: bool = False
    unit_id: str = ""
    basis = "per_unit"

    def source_quantity(self):
        return 1.0, (self.unit_id or "unit")


@dataclass(frozen=True)
class SourcedMeasure:
    """"One <unit> weighs N grams", ACCORDING TO THE RECORD THAT IS PRICING.

    ⛔⛔ IT LIVES HERE, NOT IN `canonical_pricing`, AND THAT IS THE POINT
    *(moved on review, 2026-08-17)*. The first version put this shape and its
    matching logic beside the pricer, which grew a SECOND conversion engine next
    to the scaling one — with its own regex for "is this the same unit". Two
    definitions of unit compatibility eventually disagree, and the one that
    matters most is the one P17g will ask: `decide()` has to be able to pose the
    same question the pricer answers, or coverage and pricing drift apart. That
    drift is the entire defect `has_mass` was written to prevent.

    ⛔ A CONVERSION ON THE CONSUMED QUANTITY, NEVER A BASIS ON THE EVIDENCE.
    Per-100 g numbers plus "1 large egg = 50 g" means `2 eggs -> 100 g -> the
    per-100 g rung scales normally`. Declaring `PerUnit(unit_mass_g=50)` over
    those numbers would instead claim they DESCRIBE one egg.
    """
    unit_text: str
    grams_per_unit: float
    source_id: str = ""
    #: ⭐ P17c.1 — PROVENANCE ENOUGH TO BECOME A CANONICAL `BasisConversion`.
    #: This shape is a PROVIDER-ADAPTER, not a second conversion vocabulary: it
    #: is what USDA/OFF hand over, and `as_basis_conversion` turns it into the
    #: contract `core.semantics` already defines. Without these fields it could
    #: not, because that contract REFUSES a cross-basis conversion with no
    #: source — "an unsourced factor is an invented density".
    dataset_id: str = ""
    #: ⛔⛔ THE PROVIDER'S REAL RELEASE — "15.3", not a placeholder *(P17c.3a)*.
    #: An earlier draft defaulted this to the literal "committed_artifact", and
    #: that string would have been baked into 259 durable conversion records as
    #: the thing a correction cites. USDA publishes explicit FDC releases and the
    #: RECORD DOES NOT CARRY ONE — probed, not assumed — so it must be supplied
    #: at hydration and may NEVER be derived from today's date.
    dataset_version: str = ""
    record_key: str = ""
    record_version: str = ""
    immutable_within_version: bool = False
    #: Which USDA table this came from. Foundation updates ~twice yearly,
    #: Branded monthly, SR Legacy is final — different update models, so the
    #: subtype belongs INSIDE the evidence rather than in pricing policy.
    data_type: str = ""
    #: A hash of the exact normalized facts committed. `fdc_id + usda_fdc` does
    #: not describe WHAT ARNIE SAW at build time when the upstream row can move.
    source_fingerprint: str = ""

    def as_basis_conversion(self):
        """The canonical `ConversionEvidence` this measure licenses, or None.

        ⛔⛔ FAIL CLOSED, AND NO FALLBACK VERSION. `ConversionEvidence` refuses a
        cross-basis factor with no source — "an unsourced factor is an invented
        density" — and a source whose VERSION we never identified is barely
        better. Asserting `immutable_within_version=True` about a version we
        could not name is the weakest link in an audit trail, so an absent
        `dataset_version` yields NO authoritative conversion at all.
        """
        if not (self.dataset_id and self.dataset_version and self.record_key):
            return None
        from decimal import Decimal

        # ⚠ THE CLASS IS `ConversionEvidence`. "BasisConversion" is what it gets
        # called in discussion, and importing that name is an ImportError at the
        # first call rather than at import time — a failure that would have
        # surfaced in production, not in review.
        from core.semantics import (ConversionEvidence, ServingBasis,
                                    SourceReference)
        return ConversionEvidence(
            from_basis=ServingBasis.COUNT, to_basis=ServingBasis.MASS,
            factor=Decimal(str(self.grams_per_unit)),
            source=SourceReference(
                dataset_id=self.dataset_id,
                dataset_version=self.dataset_version,
                record_key=self.record_key,
                record_version=self.record_version,
                immutable_within_version=self.immutable_within_version),
            policy_version="p17c.1")


def _consumed_unit(consumed) -> str:
    """WHAT THE USER COUNTED, as a unit rather than as prose.

    ⛔⛔ DISPLAY WORDING IS NOT IDENTITY *(P17c.2)*. `unit_label` deliberately
    holds the user's raw phrasing — production normalization of "2 eggs" stores
    `unit="eggs"` and `unit_label="2 eggs"` — so preferring the label asked
    whether "2 eggs" was the same unit as "large egg" instead of whether "egg"
    was. The synthetic tests hid it by setting both to the same word.

    Canonical unit first, the user's own stated unit next, raw wording last and
    only as weak evidence. A mass/volume token is not a countable unit at all.
    """
    for candidate in (getattr(consumed, "unit", ""),
                      getattr(consumed, "user_stated_unit", ""),
                      getattr(consumed, "unit_label", "")):
        word = str(candidate or "").strip().lower()
        if word and word not in ("g", "gram", "grams", "ml", "milliliter",
                                 "milliliters", "oz", "kg", "l"):
            return word
    return ""


def unit_matches(consumed, unit_id: str) -> bool:
    """Does the user's counted unit name the SAME thing the source counts?

    ⭐ ONE AUTHORITY, DELIBERATELY. The sourced-measure conversion in
    `canonical_pricing` asks the same question about a serving panel, and two
    implementations of "is this the same unit" would eventually disagree — which
    is the predicate/pricer drift the whole tranche is built to avoid.

    Word-boundary and singular-or-plural, and NARROW ON PURPOSE: "piece" must
    not match "bar", because knowing a whole bar weighs 55 g says nothing about
    what one piece of it weighs.
    """
    want = _consumed_unit(consumed)
    target = str(unit_id or "").strip().lower()
    if not want or not target:
        return False
    # ⛔⛔ SINGULARISE BOTH SIDES, AND THE REAL NORMALIZER IS WHY. The first
    # version appended an optional "s" to the search term only, so it could
    # match "egg" inside "eggs" but NOT "eggs" against "large egg" — and
    # production normalization of "2 eggs" yields unit="eggs" while USDA states
    # "large egg". The synthetic tests used the singular on both sides and never
    # saw it. A unit matcher that cannot fold a plural is a unit matcher that
    # silently refuses every real count.
    want_tokens = _unit_tokens(want)
    target_tokens = _unit_tokens(target)
    return bool(want_tokens & target_tokens)


def _unit_tokens(text: str) -> set:
    """Singularised word tokens of a unit phrase. "large egg" -> {large, egg}."""
    return {token[:-1] if len(token) > 3 and token.endswith("s") else token
            for token in re.findall(r"[^\W\d_]+", text.lower(), re.UNICODE)}


#: A serving panel states a COUNT and a unit: "2 cookies", "1 bar", "1 large
#: egg". The count matters — 30 g for "2 cookies" is 15 g per cookie.
_PANEL = re.compile(r"^\s*(\d+(?:\.\d+)?)?\s*(.+?)\s*$")


def measure_from_panel(serving_text, serving_mass_g, source_id="", **provenance):
    """A `SourcedMeasure` from a provider's own serving panel, or None.

    ⚠ PROVENANCE TRAVELS HERE TOO. A serving PANEL is exactly as sourced as a
    `foodPortions` row — same record, same dataset — and the first version took
    provenance on one path and not the other, so a panel-derived measure was
    silently non-authoritative while an otherwise identical portion-derived one
    was not.
    """
    try:
        grams = float(serving_mass_g)
    except (TypeError, ValueError):
        return None
    if grams <= 0:
        return None
    match = _PANEL.match(str(serving_text or "").strip().lower())
    if not match or not match.group(2):
        return None
    count = float(match.group(1)) if match.group(1) else 1.0
    if count <= 0:
        return None
    return SourcedMeasure(unit_text=match.group(2),
                          grams_per_unit=grams / count, source_id=source_id,
                          **provenance)


def mass_from_measures(consumed, measures) -> Optional[float]:
    """The mass a BARE COUNT implies, per a sourced measure that counts the
    SAME unit — or None, which leaves the portion exactly as unpriceable.

    ⭐ IT ASKS `unit_matches`, THE SAME FUNCTION THE COUNT PATHS ASK. This used
    to carry its own regex, which is how a codebase ends up with two answers to
    one question.

    ⛔ NEVER A FALLBACK GUESS. If no measure names the unit the user counted,
    this returns None and the rung declines. Inventing a mass here is exactly
    the "a model guesses 1 serving ~ X grams, therefore canonical owns it" the
    directive forbids — the conversion is evidence or it is nothing.
    """
    if consumed is None or getattr(consumed, "grams", None) is not None:
        return None
    count = getattr(consumed, "count", None)
    if not count:
        return None
    # ⚠ A PART OF A UNIT IS NOT ONE OF IT. "half a bar" may not take the whole
    # bar's mass, for the same reason the PerServing path refuses it.
    if getattr(consumed, "unit_is_fraction", False):
        return None
    want = _consumed_unit(consumed)
    if not want:
        return None
    measure = _matching_measure(consumed, measures)
    return float(count) * measure.grams_per_unit if measure else None


def _matching_measure(consumed, measures):
    """The FIRST sourced measure whose unit is the one the user counted.

    Split out so `mass_from_measures` and `resolve_scaling` cannot disagree
    about WHICH measure applied — one returning the mass and the other naming a
    different record as its provenance would be a citation that does not match
    the number it justifies.
    """
    if consumed is None or getattr(consumed, "count", None) in (None, 0):
        return None
    if getattr(consumed, "unit_is_fraction", False):
        return None
    want = _consumed_unit(consumed)
    if not want:
        return None
    stated_size = str(getattr(consumed, "size_descriptor", "")
                      or "").strip().lower()
    stated_sizes = _SIZE_TOKENS & _unit_tokens(stated_size)
    # ⛔⛔⛔ CF20 ROUND 2 — FAIL CLOSED ON A SIZE WE CANNOT REPRESENT *(Danny)*.
    # `_SIZE_WORDS` (what a user may state) and `_SIZE_TOKENS` (what this
    # matcher can compare) are two vocabularies, and ten entries live in the
    # first and not the second: mini, tiny, regular, standard, double, king,
    # personal, grande, tall, venti. For those the intersection is EMPTY, the
    # guard below never fired, and "1 mini bar" bound a full-size `bar` panel —
    # 60 g for a mini one, reported authoritative. The size was read,
    # understood, and then silently discarded by the layer that had to act.
    #
    # ⭐ A QUESTION WE CANNOT EVALUATE MUST NOT BE ANSWERED YES. Without a token
    # for `mini` there is no way to ask "is this record about a mini bar", so
    # no record can satisfy the claim. Refusing drops to the heuristic path,
    # which is non-authoritative and declines canonically: a lost admission,
    # never a wrong number. Hoisted out of the loop because this is a property
    # of the REQUEST, not of any candidate.
    if stated_size and not stated_sizes:
        return None
    for measure in measures or ():
        if not unit_matches(consumed, measure.unit_text):
            continue
        # ⛔ A STATED SIZE MUST NOT BIND TO A DIFFERENT ONE. "2 medium eggs"
        # shares the token "egg" with a "large egg" measure, and without this
        # guard the entity match would price medium eggs at 46 g each while
        # citing a record about large ones. An UNSTATED size may bind — the
        # measure is then the record's own reference portion — but a stated
        # size that conflicts is a different claim, not a loose match.
        #
        # ⛔⛔⛔ CF20 — AND "DIFFERENT" MEANS IDENTITY, NOT CONTAINMENT. This
        # read `stated_size not in measure_sizes`, i.e. token MEMBERSHIP, so a
        # stated "large" was IN `extra large (9" or longer)`'s size tokens
        # {extra, large} and bound to it. That record sits EARLIER in the USDA
        # portion list than the real `large (8" to 8-7/8" long)`, so the correct
        # measure was never reached: one large banana priced at 152 g instead of
        # 136 g, +11.8%, reported authoritative, citing a record about a
        # different piece. `extra large` is a different size from `large` in
        # exactly the way `medium` is.
        #
        # ⚠ COMPARED AS SETS BECAUSE THE STATED SIZE IS NOW A PHRASE. Since
        # CF20's producer half, `size_descriptor` can be "extra large", and
        # `"extra large" in {extra, large}` is False — the two halves must move
        # together or the fix for one breaks the other.
        #
        # ⛔⛔⛔ CF20 ROUND 2 — AND SILENCE IS NOT AGREEMENT *(Danny)*. This read
        # `if stated_sizes and measure_sizes and ...`, so a measure stating NO
        # size skipped the comparison entirely: "2 large eggs" bound a bare
        # `egg` = 50 g panel, and did so even when the real `large egg` = 61 g
        # record sat right behind it in the same tuple. The user named a size,
        # the record was silent about size, and silence was read as agreement.
        #
        # ⭐ THE ASYMMETRY IS THE RULE, NOT AN OVERSIGHT. An UNSTATED size may
        # still bind — no size was claimed, so the record's own reference
        # portion is the honest answer. The converse does not hold: once a size
        # IS claimed, a record that cannot speak to it cannot satisfy it. So
        # `measure_sizes` is no longer a precondition for comparing, and an
        # empty one now FAILS the identity test rather than skipping it.
        measure_sizes = _SIZE_TOKENS & _unit_tokens(measure.unit_text)
        if stated_sizes and stated_sizes != measure_sizes:
            continue
        return measure
    return None


#: Size words a portion's unit_text may carry. Mirrors the size vocabulary the
#: normalizer captures into `size_descriptor`. THE ONLY COPY — the pricer's
#: zero-rule AST gate forbids string collections there, and a second copy here
#: would be a second unit authority anyway.
_SIZE_TOKENS = frozenset({"small", "medium", "large", "jumbo", "extra",
                          "x", "xl", "big"})


def _subject_noun(description: str) -> str:
    """The record's head noun: "Egg, whole, cooked, fried" -> "egg"."""
    head = str(description or "").split(",")[0].strip().lower()
    words = [w for w in re.findall(r"[^\W\d_]+", head) if w]
    return words[-1] if words else ""


def _measure_unit_text(unit_text: str, description: str) -> str:
    """The unit a measure counts, with the record's IMPLICIT subject restored.

    ⛔⛔ FOUND END-TO-END AGAINST THE HYDRATED ARTIFACT, NOT IN REVIEW. USDA
    states the egg portion as `modifier="large"`, `measureUnit="undetermined"` —
    a bare SIZE with no entity noun, because the subject is the record itself.
    So `unit_matches("eggs", "large")` failed, the sourced conversion never
    fired, and "2 eggs" — THE TRANCHE'S NAMESAKE — silently fell back to the
    piece-weight heuristic with `authoritative=False`. Green tests throughout:
    the synthetic panels all said "large egg", never "large".

    ⚠ THE SUBJECT IS APPENDED ONLY TO A BARE SIZE DESCRIPTOR. Appending it to a
    real unit noun would let "2 salmon" match an "oz" measure and price two
    salmon at 56 grams.
    """
    tokens = set(re.findall(r"[^\W\d_]+", str(unit_text or "").lower()))
    if tokens and tokens <= _SIZE_TOKENS:
        subject = _subject_noun(description)
        if subject:
            return f"{unit_text} {subject}"
    return unit_text


SourceBasis = Union[Per100g, Per100ml, PerServing, PerUnit]

_SPEC_BASES = {"per_100g": Per100g, "per_100ml": Per100ml}


def basis_from_spec(kind: str, *, as_served: bool = False,
                    serving_mass_g: Optional[float] = None,
                    serving_ml: Optional[float] = None,
                    servings_per_package: Optional[float] = None,
                    unit_id: str = "") -> SourceBasis:
    """Build a basis from a declared kind. One factory, because the same four
    lines had been rewritten in the readiness report (twice) and the gold
    harness, and a basis field added in one place stayed missing in the others.

    ⛔⛔ AND THAT IS EXACTLY WHAT HAPPENED TO `unit_id` *(caught on review,
    2026-08-17)*. It was added to `PerServing` and `PerUnit` as the field that
    proves a count counts the right thing, and this factory — whose entire
    reason for existing is the sentence above — kept building bases WITHOUT it.
    Every basis it produced would have silently lost its identity gate, which is
    the same dead-field defect P17c found one layer upstream in the artifact
    builder. A canonical factory must round-trip every load-bearing field.
    """
    if kind in _SPEC_BASES:
        return _SPEC_BASES[kind]()
    if kind == "per_serving":
        return PerServing(serving_mass_g=serving_mass_g, serving_ml=serving_ml,
                          servings_per_package=servings_per_package,
                          as_served=as_served, unit_id=unit_id)
    return PerUnit(unit_mass_g=serving_mass_g, as_served=as_served,
                   unit_id=unit_id)


def _factor(basis: SourceBasis, consumed: NormalizedQuantity) -> float:
    """How many of the source's units the user ate."""
    grams = consumed.grams
    ml = consumed.milliliters
    count = consumed.count

    if isinstance(basis, Per100g):
        if grams is None:
            raise ScalingRefused(
                "per-100g values need a mass, and this portion has none")
        return grams / 100.0

    if isinstance(basis, Per100ml):
        if ml is None:
            # Water-density fallback is a real assumption, not a conversion.
            # Refuse rather than silently treat 100 g of oil as 100 ml.
            raise ScalingRefused(
                "per-100ml values need a volume, and this portion has none")
        return ml / 100.0

    # A count is only a multiplier for these two bases when it counts the SAME
    # unit the source describes. "One plate of pasta" arrives as count=1 beside
    # a 400 g estimate; reading that as one serving of a packaged label discards
    # the estimate and reports a container as a package. Either the count counts
    # discrete units, or the source's serving is itself the helping.
    countable = (consumed.count is not None
                 and (consumed.count_is_serving_compatible
                      or getattr(basis, "as_served", False)))

    if isinstance(basis, PerServing):
        if grams is not None and basis.serving_mass_g:
            return grams / float(basis.serving_mass_g)
        if ml is not None and basis.serving_ml:
            return ml / float(basis.serving_ml)
        # ⭐ P17e — THE PACKAGE PATH, DRIVEN BY THE BASIS'S OWN DATA. A count of
        # the PACKAGE unit is count x servings_per_package servings. Checked
        # BEFORE the serving-unit path because a package_unit_id exists exactly
        # when package and serving are different things — and a "bottle" count
        # against a "scoop" serving must not fall through to the serving gate
        # and be refused as a unit mismatch.
        if (basis.package_unit_id and count is not None
                and unit_matches(consumed, basis.package_unit_id)):
            if consumed.unit_is_fraction:
                raise ScalingRefused(
                    f"one {consumed.unit} of a {basis.package_unit_id} is a "
                    f"PART of the package, and its size is not stated")
            if not basis.servings_per_package:
                # ⛔ ONE PACKAGE = ONE SERVING IS A FACT, NOT A DEFAULT. Some
                # labels state it; others state 2, or 2.5. Assuming it here
                # would silently halve every multi-serving bottle.
                raise ScalingRefused(
                    f"this source names the package ({basis.package_unit_id!r})"
                    f" but not how many servings it holds — the relation must "
                    f"be stated, never assumed")
            return float(count) * float(basis.servings_per_package)
        # A FRACTION OF THE DISH IS NOT ONE OF THE DISH. `countable` asks
        # whether the count may multiply this source's serving, and both of its
        # inputs answer about the COUNT alone — neither can see that the source
        # has no idea how many pieces the thing came in. Prod 2026-08-03
        # fe#2719: a restaurant lookup for a special roll, no serving panel,
        # count=1 unit="piece" — multiplied the WHOLE ROLL by one and committed
        # 460 cal over the interpreter's own correct 130-190.
        #
        # Gated on the source stating NO panel, which is what makes it narrow.
        # "15 pieces" against "35 g (12 pieces)" is untouched: that panel knows
        # what one piece weighs, so a mass resolves above and the count is
        # never the multiplier. `unit_is_fraction` is likewise false when the
        # unit IS the product ("6 slices" of turkey deli slice).
        _no_panel = basis.serving_mass_g is None and basis.serving_ml is None
        # ⛔⛔ IDENTITY BEFORE MULTIPLICATION *(P17b.1)*. Reached only when the
        # mass and volume paths could not reconcile the bases themselves — a
        # gram portion needs no name match, because the mass IS the common
        # ground. Here there is only a count, so the source must say what it
        # counts and the count must be of that thing.
        if basis.unit_id:
            if not unit_matches(consumed, basis.unit_id):
                raise ScalingRefused(
                    f"this source states its serving as {basis.unit_id!r}, and "
                    f"{consumed.unit_label or consumed.unit!r} is not that — a "
                    f"count may only multiply the unit the evidence describes")
            # A PART OF THE UNIT IS NOT ONE OF THE UNIT, panel or no panel.
            # Knowing a whole bar weighs 55 g does not say what one piece of it
            # weighs, so a stated serving mass must NOT license a fraction.
            if consumed.unit_is_fraction:
                raise ScalingRefused(
                    f"one {consumed.unit} of a {basis.unit_id} is a PART of the "
                    f"serving this source describes, and its size is not stated")
        if countable and not (consumed.unit_is_fraction and _no_panel):
            return float(count)
        if consumed.unit_is_fraction and _no_panel and count is not None:
            raise ScalingRefused(
                f"this source states no serving panel, so one "
                f"{consumed.unit} of it cannot be priced as a whole serving")
        if count is not None:
            raise ScalingRefused(
                "per-serving values need a serving mass; this portion is an "
                "estimated helping, not a count of the label's servings")
        raise ScalingRefused(
            "per-serving values need a serving mass or a serving count")

    if isinstance(basis, PerUnit):
        # ⛔⛔ THE SAME IDENTITY GATE AS PerServing, AND ITS ABSENCE HERE WAS A
        # REAL HOLE *(found on review, 2026-08-17)*. `unit_id` was added to this
        # class and then never consulted, so "every count multiplication proves
        # the count is of the unit the evidence describes" was true of one path
        # and false of the other — which is worse than not having the field,
        # because the field made it look handled.
        if basis.unit_id and count is not None:
            if not unit_matches(consumed, basis.unit_id):
                raise ScalingRefused(
                    f"this source states its unit as {basis.unit_id!r}, and "
                    f"{consumed.unit_label or consumed.unit!r} is not that — a "
                    f"count may only multiply the unit the evidence describes")
            if consumed.unit_is_fraction:
                raise ScalingRefused(
                    f"one {consumed.unit} of a {basis.unit_id} is a PART of the "
                    f"unit this source describes, and its size is not stated")
        if countable:
            return float(count)
        if grams is not None and basis.unit_mass_g:
            return grams / float(basis.unit_mass_g)
        if count is not None:
            raise ScalingRefused(
                "per-unit values need a known unit mass; this portion is an "
                "estimated helping, not a count of the label's units")
        raise ScalingRefused(
            "per-unit values need a count or a known unit mass")

    raise ScalingRefused(f"unknown source basis: {basis!r}")


@dataclass(frozen=True)
class ScalingResolution:
    """HOW a portion was reconciled with a source's basis, and by what.

    ⭐⭐ ONE RESOLVER, AND P17g IS WHY. The predicate must be able to ask "is
    there a local authoritative scalable path for this item" and get the SAME
    answer the pricer will act on. If coverage re-implements that question it
    will drift from pricing — the precise defect the blunt `has_mass` rule was
    written to prevent, and the one that made count-only foods unpriceable in
    the first place.
    """
    factor: float
    basis_name: str
    #: The mass a sourced measure supplied, when the portion had none.
    resolved_grams: Optional[float] = None
    #: The canonical `ConversionEvidence` that licensed it, when the measure
    #: carried provenance. Persisted by P17f so a correction can reprice
    #: deterministically instead of rediscovering the nutrition.
    conversion: object = None
    evidence_ids: tuple = ()
    #: ⛔⛔ MAY THIS RESOLUTION SUPPORT CANONICAL OWNERSHIP? False when the
    #: factor rests on a HEURISTIC normalized mass (a piece-weight table, a
    #: vessel guess, an ontology default) or on a measure with no provenance.
    #: The number is still produced — an estimate may use it — but MEMORY,
    #: PRODUCT and ARTIFACT may not be settled on it.
    authoritative: bool = True
    #: How the factor was reached, for the audit and for the log.
    path: str = "basis"


def resolve_scaling(source_basis: SourceBasis, consumed: NormalizedQuantity,
                    measures=()) -> ScalingResolution:
    """THE ONE PLACE A PORTION MEETS A BASIS. Raises `ScalingRefused`.

    ⛔⛔ PRECEDENCE, FROZEN *(Danny, P17c.2, 2026-08-17)*. "Sourced measure is a
    last resort" was too broad, and it quietly handed the decision to whichever
    layer produced a number first:

        1  USER-STATED EXACT QUANTITY     "100 g", "6 oz"     mass_is_exact
        2  DIRECT COMPATIBLE BASIS        2 bars vs a per-bar label
        3  SOURCED ConversionEvidence     USDA: 1 large egg = 50 g
        4  HEURISTIC NORMALIZED MASS      piece_weight, vessel, ontology
                                          -> NEVER canonical authority

    ⭐ THE CASE THAT MADE THIS NECESSARY: `normalize_quantity("2 eggs")` already
    returns grams=100 from a PIECE-WEIGHT TABLE. Under the old ordering
    `_factor` succeeded on that immediately and the USDA conversion was never
    consulted — so P17 would have been DECORATIVE on exactly the foods it was
    built for, and if USDA said 56 g/egg the heuristic 50 g would have won
    merely by arriving first.

    ⚠ NORMALIZATION MAY ESTIMATE WHAT THE USER PROBABLY MEANT. IT MAY NOT
    OUTRANK EVIDENCE WHEN CANONICAL OWNERSHIP IS BEING DECIDED.
    """
    name = getattr(source_basis, "basis", "")

    # 1 — an exact user-stated measurement is the authority. A sourced
    # conversion must not reinterpret a quantity the user actually measured.
    if getattr(consumed, "mass_is_exact", False):
        return ScalingResolution(factor=_factor(source_basis, consumed),
                                 basis_name=name, path="user_stated_exact")

    # 2 — a basis that consumes the portion WITHOUT needing a mass: a count of
    # the label's own units. Tested by stripping any heuristic mass, so that a
    # piece-weight prior cannot masquerade as a direct match.
    massless = replace(consumed, grams=None, milliliters=None)
    try:
        return ScalingResolution(factor=_factor(source_basis, massless),
                                 basis_name=name, path="direct_basis")
    except ScalingRefused:
        pass

    # 3 — a sourced conversion, which OUTRANKS the heuristic mass below.
    measure = _matching_measure(massless, measures)
    if measure is not None:
        grams = float(massless.count) * measure.grams_per_unit
        conversion = measure.as_basis_conversion()
        return ScalingResolution(
            factor=_factor(source_basis, replace(consumed, grams=grams)),
            basis_name=name, resolved_grams=grams, conversion=conversion,
            evidence_ids=(measure.source_id,) if measure.source_id else (),
            # ⛔ AN UNSOURCED FACTOR IS AN INVENTED DENSITY. It may still price
            # an estimate; it may never settle a canonical rung.
            authoritative=conversion is not None,
            path="sourced_conversion" if conversion is not None
            else "unsourced_measure")

    # 4 — whatever normalization produced. It scales, but it is an ASSUMPTION,
    # and `authoritative` says so out loud rather than in a comment.
    return ScalingResolution(factor=_factor(source_basis, consumed),
                             basis_name=name, authoritative=False,
                             path=f"heuristic:{consumed.normalization_source}")


def can_scale(source_basis: SourceBasis, consumed: NormalizedQuantity,
              measures=(), *, authoritative_only: bool = True) -> bool:
    """`resolve_scaling` asked as a yes/no. THE PREDICATE'S ENTRY POINT — it
    exists so P17g cannot accidentally define scalability a second time.

    ⛔ `authoritative_only` DEFAULTS TRUE, because the predicate's question is
    not "can a number be produced" but "may canonical OWN this". A heuristic
    piece weight answers the first and must never answer the second.
    """
    try:
        resolution = resolve_scaling(source_basis, consumed, measures)
    except ScalingRefused:
        return False
    return resolution.authoritative or not authoritative_only


def scale_profile(profile: NutrientProfile, source_basis: SourceBasis,
                  consumed: NormalizedQuantity) -> NutrientProfile:
    """The portion's numbers. Every field scales by the SAME factor — a field
    scaling differently from its neighbours means the basis was wrong, and
    that is a bug to surface, not to route around.

    Provenance survives: each value keeps its source, and its basis becomes
    `per_portion` so nothing downstream can rescale it a second time.
    """
    factor = _factor(source_basis, consumed)
    if factor < 0:
        raise ScalingRefused("negative portion")
    scaled = {}
    for name, value in (profile.values or {}).items():
        scaled[name] = value.with_value(
            _round(value.value * factor, name), basis="per_portion")
    return NutrientProfile(values=scaled)


def scaling_spans(profile: NutrientProfile, source_basis: SourceBasis,
                  consumed: NormalizedQuantity) -> dict:
    """Per-field spans implied by the portion's mass uncertainty.

    What "six thin deli slices" actually costs if we are wrong about the
    slices — for every macro, not just calories. A mass doubt scales protein
    exactly as it scales energy, and the calorie-only version reported
    protein_span=0 on every portion ambiguity, which told the ask ladder that
    protein was certain when the mass was not (PR #31 calibration).

    Returns {} when there is nothing uncertain to report.
    """
    if consumed.uncertainty_g is None or consumed.grams is None:
        return {}
    out = {}
    for field in ("calories", "protein"):
        if profile.amount(field) is None:
            continue
        span = _span_for(profile, source_basis, consumed, field)
        if span:
            out[field] = span
    return out


def _span_for(profile: NutrientProfile, source_basis: SourceBasis,
              consumed: NormalizedQuantity, field: str) -> Optional[float]:
    try:
        low = NormalizedQuantity(
            amount=consumed.amount, unit=consumed.unit,
            grams=max(0.0, consumed.grams - consumed.uncertainty_g),
            milliliters=consumed.milliliters, count=consumed.count)
        high = NormalizedQuantity(
            amount=consumed.amount, unit=consumed.unit,
            grams=consumed.grams + consumed.uncertainty_g,
            milliliters=consumed.milliliters, count=consumed.count)
        lo = scale_profile(profile, source_basis, low).amount(field)
        hi = scale_profile(profile, source_basis, high).amount(field)
    except ScalingRefused:
        return None
    if lo is None or hi is None:
        return None
    return round(abs(hi - lo), 1)


def scaling_uncertainty(profile: NutrientProfile, source_basis: SourceBasis,
                        consumed: NormalizedQuantity) -> Optional[float]:
    """The calorie span alone. Kept as the narrow entry point callers already
    use; `scaling_spans` is the one that sees protein."""
    if consumed.uncertainty_g is None or consumed.grams is None:
        return None
    cal = profile.amount("calories")
    if cal is None:
        return None
    try:
        # `replace` rather than a fresh construction: rebuilding field by field
        # dropped whatever the portion knew that this function does not name,
        # and a lost `count_basis` turns a scalable count into a refusal.
        low = replace(
            consumed, grams=max(0.0, consumed.grams - consumed.uncertainty_g))
        high = replace(
            consumed, grams=consumed.grams + consumed.uncertainty_g)
        lo = scale_profile(profile, source_basis, low).amount("calories")
        hi = scale_profile(profile, source_basis, high).amount("calories")
    except ScalingRefused:
        return None
    if lo is None or hi is None:
        return None
    return round(abs(hi - lo), 1)


def _round(value: float, name: str) -> float:
    """Calories to whole numbers, everything else to a tenth. Storing
    247.30000000000004 g of protein is not precision."""
    return round(value) if name == "calories" else round(value, 1)
