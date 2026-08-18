"""THE CANONICAL LANE PRICES ITS OWN FOOD.

    ResolvedFields (entity + preparation + quantity)
        -> memory | product | artifact | estimate      one rung wins
        -> deterministic ranking                        ~0 ms, already proven
        -> PricedFood
        -> ResolvedMeal -> canonical commit

WHY THIS EXISTS, MEASURED IN PRODUCTION 2026-08-07/08. Canonical settlement
rented its pricing from `handlers.tool_executor._analyze_food` — one import,
the ONLY thing the canonical spine took from the legacy pipeline. Everything
slow or wrong lived on the far side of it:

    settle.commit      (canonical)        17 ms
    pricing.ranking    (deterministic)     0 ms
    settle.pricing     (legacy)        8,171 ms of an 8,225 ms tap
    legacy ladder      -> Mackerel 80 g committed at 0.0 kcal / 0 g protein
    legacy qualify     -> "Chicken, fried" 120 g priced 295 then 329 kcal

The canonical parts were free and correct. So this does not optimise
`_analyze_food`; it retires it from the canonical lane.

NOT A PORT. The legacy ladder's behaviour is evidence of what NOT to inherit —
it produced a silently zero-calorie row and two different prices for one
identity. The legitimate capabilities are re-expressed here behind canonical
contracts, reusing the machinery that was never the problem: `scaling` for
portion basis, `get_user_food_match` for memory, `best_candidate` for the
deterministic winner.

⭐ THE ZERO RULE, and why it needs no food list.

A zero-calorie row is either a fact or a corruption, and the difference is
NOT the food — it is where the number came from:

    zero FROM EVIDENCE      legitimate. Black coffee is really ~0 kcal, and
                            entry 2820 is a correct row.
    zero FROM A FAILURE     corruption. Mackerel is not zero; entry 2932 is a
                            silent under-count of someone's day.

So evidence-backed rungs may return zero and the estimate rung may not. A
curated list of "foods that are allowed to be zero" would be a food-name
branch, and wrong for the first zero-calorie food nobody listed.

AND A FOOD WE CANNOT PRICE IS NOT COMMITTED. When no rung can produce a
defensible number, this returns None and settlement declines. An error the
user can see beats a row that quietly reads zero — the whole reason the
mackerel defect survived is that nothing looked wrong.
"""
from __future__ import annotations

import dataclasses
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Rung(str, Enum):
    """WHICH KIND OF EVIDENCE PRICED THIS FOOD, in descending authority.

    Recorded on the result because "how confident are we" and "where did the
    number come from" are different questions, and the audit only ever
    answers the second one honestly.
    """
    #: This user has logged this exact food before and it was trusted.
    MEMORY = "memory"
    #: A branded/product record — authoritative for its own product, and
    #: admissible WITHOUT semantic qualification because a barcode or product
    #: identity is not an ambiguous string match.
    PRODUCT = "product"
    #: Qualified structured evidence from the committed artifact, ranked
    #: deterministically. The generic-food path.
    ARTIFACT = "artifact"
    #: A bounded deterministic estimate. May never be zero.
    ESTIMATE = "estimate"


#: The rungs whose numbers come from EVIDENCE about this food. Only these may
#: legitimately price something at zero.
EVIDENCE_BACKED = frozenset({Rung.MEMORY, Rung.PRODUCT, Rung.ARTIFACT})


@dataclass(frozen=True)
class PricedFood:
    """What one food costs, and what said so."""
    calories: float
    protein: float
    carbs: float
    fats: float
    fiber: Optional[float] = None
    sugar: Optional[float] = None
    sodium: Optional[float] = None
    micros: Optional[dict] = None
    micros_estimated: bool = False

    rung: Rung = Rung.ESTIMATE
    #: WHICH RECORD WON. The determinism gate reads this: the same canonical
    #: input against the same artifact must select the same evidence_id, not
    #: merely land on the same calorie number by coincidence.
    evidence_id: str = ""
    #: The basis the numbers were scaled FROM (per 100 g, per serving, …),
    #: kept so a later correction has something to correct against — the
    #: defect `resolution` was added to the ledger to fix.
    basis: str = ""
    assumptions: tuple = ()
    # ── P17f — THE SCALING RESOLUTION, CARRIED TO THE ROW ────────────────────
    # USDA nutrition and a USDA piece weight are TWO CLAIMS, and "actually that
    # was 3 eggs" needs both to reprice deterministically instead of
    # rediscovering the nutrition. Optional and omitted-when-absent, never
    # defaulted: a price with no conversion must not look like one with an
    # unnamed conversion.
    scaling_factor: Optional[float] = None
    #: The mass a sourced conversion supplied, when the portion had none.
    resolved_grams: Optional[float] = None
    conversion_evidence_ids: tuple = ()
    #: What ONE of the source basis IS: (1.0, "bar"), (100.0, "g").
    source_amount: Optional[float] = None
    source_unit: str = ""

    @property
    def estimated(self) -> bool:
        return self.rung is Rung.ESTIMATE

    @property
    def evidence_backed(self) -> bool:
        return self.rung in EVIDENCE_BACKED

    def is_defensible(self) -> bool:
        """May this be committed?

        THE ONE RULE THAT WOULD HAVE STOPPED ENTRY 2932. A zero from evidence
        is a fact; a zero from an estimate is a pricing failure wearing a
        number. There is no food-name check here and there must never be one.
        """
        if self.calories > 0:
            return True
        return self.evidence_backed


class PricingRefused(Exception):
    """No rung could price this food defensibly.

    Raised rather than returned so a caller cannot accidentally treat it as a
    zero-calorie meal — which is precisely how the legacy path failed.
    """


def refuse_or_return(priced: Optional[PricedFood], *, food_name: str
                     ) -> PricedFood:
    """The single exit through which every price must pass.

    Centralised so "never commit an indefensible price" is one line that every
    rung inherits, rather than a check each rung remembers.
    """
    if priced is None:
        logger.warning("event=pricing_refused food=%s reason=no_rung",
                       food_name)
        raise PricingRefused(f"no rung could price {food_name!r}")
    if not priced.is_defensible():
        logger.warning(
            "event=pricing_refused food=%s reason=zero_without_evidence "
            "rung=%s — a zero from a failed estimate is a silent under-count, "
            "not a fact about the food", food_name, priced.rung.value)
        raise PricingRefused(
            f"{food_name!r} priced at zero from {priced.rung.value}, which is "
            f"not evidence")
    logger.info("event=canonical_priced food=%s rung=%s kcal=%.0f evidence=%s",
                food_name, priced.rung.value, priced.calories,
                priced.evidence_id or "-")
    return priced


# ══ THE EVIDENCE THE PRICER CONSUMES ════════════════════════════════════════
#
# EVERY RUNG IS HANDED ITS EVIDENCE. Nothing here retrieves: no provider
# client, no model call, no `await` on a network. That is not a style rule —
# it is Gate B, and it is what makes a canonical settle survive with provider
# and resolver access poisoned. Acquisition belongs to adapters upstream, the
# same boundary `preparation_activation` already holds for materiality.


@dataclass(frozen=True)
class MemoryEvidence:
    """This user has logged this food before and the match was trusted.
    Straight from `user_food_matches` — measured at 133 ms in production, and
    the reason a warm settle is already fast."""
    per100g: dict
    source_id: str = ""
    confidence: float = 0.9


@dataclass(frozen=True)
class ProductEvidence:
    """An EXACT authoritative product: barcode, GTIN, or a provider record
    identified by one.

    Admissible without semantic qualification because a barcode is not an
    ambiguous string match — it names one product. A FUZZY OFF NAME MATCH IS
    NOT THIS, and must never be constructed here: `_match: "exact"` once said
    so about a pizza.
    """
    identifier: str
    #: Numbers PER 100 G. Optional since P17b: a label may state only a serving.
    per100g: Optional[dict] = None
    #: ⭐ P17b — NUMBERS PER ONE SERVING, the label's own basis. "1 bar =
    #: 200 kcal" is authoritative AS STATED, and routing it through grams to
    #: rebuild a per-100 g figure adds two lossy transformations to reach a
    #: number the label already gave. When this is set the rung declares
    #: `PerServing`, and `per100g` is not consulted.
    per_serving: Optional[dict] = None
    #: What one serving WEIGHS. A CONVERSION INPUT, never a nutrition basis —
    #: pairing it with `per100g` numbers and calling that "per serving" would
    #: price two bars at 728 kcal against a label that says 400.
    serving_grams: Optional[float] = None
    #: The unit one serving IS ("bar", "bottle"). Identity, so a count can be
    #: proven to count the same thing the evidence describes.
    serving_unit: str = ""
    #: ⭐ P17e — what one PACKAGE is called ("bottle", "tub"), when package and
    #: serving are different things. Identity for the package path; a count of
    #: this unit is count x servings_per_package servings.
    package_unit: str = ""
    servings_per_package: Optional[float] = None
    source_id: str = ""

    def __post_init__(self):
        """⛔⛔ BOTH BASES MAY EXIST, AND IF THEY DO THEY MUST AGREE *(P17b.1)*.

        Manufacturer data routinely states per-serving AND per-100 g. Silently
        preferring one would let a contradictory record price differently
        depending on which field a future reader happened to consult — and the
        disagreement would never surface, because each number looks fine alone.

        With a serving mass in hand the two are the SAME CLAIM twice, so they
        are checked against each other here: at construction, which is the
        earliest a producer can be told it is wrong, and long before the number
        reaches a meal. Tolerance is 10% — panels round, and rounding is not a
        contradiction.
        """
        if not (self.per100g and self.per_serving and self.serving_grams):
            return
        try:
            grams = float(self.serving_grams)
        except (TypeError, ValueError):
            return
        if grams <= 0:
            return
        # ⛔⛔ EVERY OVERLAPPING FIELD, NOT JUST CALORIES *(review, 2026-08-17)*.
        # The first version compared calories alone, so a record whose calories
        # reconciled and whose PROTEIN said 10 on one basis and 40 on the other
        # was accepted as "internally consistent" — and whichever basis a future
        # reader happened to consult would decide the macros. A reconciliation
        # that checks one field licenses the rest.
        #
        # ⚠ `is not None`, NEVER TRUTHINESS: a legitimate 0.0 g of fat must
        # participate in the check rather than skip it.
        for field_name in ("calories", "protein", "carbs", "fat", "fiber",
                           "sugar", "sodium"):
            per100 = self.per100g.get(field_name)
            per_serv = self.per_serving.get(field_name)
            if per100 is None or per_serv is None:
                continue
            implied = float(per100) * grams / 100.0
            # An absolute floor keeps a rounding-scale field (0.4 vs 0.5 g) from
            # failing a 10% relative test it can never pass.
            if abs(implied - float(per_serv)) <= max(0.10 * abs(implied), 0.5):
                continue
            raise ValueError(
                f"{self.identifier}: per-serving says {per_serv} {field_name} "
                f"but per-100 g implies {implied:.1f} for {grams} g — one "
                f"record cannot hold two different claims about one food")


@dataclass(frozen=True)
class ArtifactEvidence:
    """Qualified structured candidates for (entity, preparation), read from the
    committed pricing artifact.

    QUALIFIED CANDIDATES, NOT A CHOSEN WINNER. The artifact stores the evidence
    a model judged admissible; `best_candidate` — deterministic, measured at
    0 ms — still picks. Storing the winner would move ranking authority into a
    model, which is the opposite of the fix.
    """
    candidates: tuple = ()
    fingerprint: str = ""


@dataclass(frozen=True)
class EstimateEvidence:
    """The interpreter's own numbers. The last rung, and the only one that may
    not price at zero.

    ⭐ IT CARRIES THE QUANTITY IT DESCRIBED. An estimate is not a per-portion
    constant — it is a statement about a SPECIFIC amount made before the user
    answered. Treating it as final breaks B-1.75's whole contract: measured in
    the suite, 50 g and 100 g both committed 200.0 kcal, so the answered
    quantity stopped being the authority the moment the artifact missed.

    `basis_grams` is the mass the estimate described, so answering reprices it.
    Without it the number is unscalable and the estimate is used as-is — which
    is honest only when no basis was ever stated.
    """
    calories: Optional[float] = None
    protein: Optional[float] = None
    carbs: Optional[float] = None
    fat: Optional[float] = None
    basis_grams: Optional[float] = None


def _profile(values: dict, *, source: str, source_id: str,
             confidence: float, estimated: bool, basis: str = "per_100g"):
    """A profile on a STATED basis, with unknown fields left UNKNOWN.

    `profile_from_values` drops None, so a missing sodium stays missing rather
    than becoming a confident zero — the same distinction the zero rule makes
    one level up.

    ⚠ `basis` IS PROVENANCE, NOT THE SCALING INPUT. `scale_profile` reads the
    SourceBasis object it is handed and overwrites this label with
    `per_portion`, so getting it wrong would not misprice anything — it would
    lie about what the numbers were before they were scaled, which is the field
    an audit reads. It defaults to per-100 g because three of the four rungs
    genuinely are.
    """
    from skills.nutrition.models import profile_from_values

    return profile_from_values(
        source=source, basis=basis, confidence=confidence,
        estimated=estimated, source_id=source_id,
        **{k: v for k, v in (values or {}).items()})


# ══ P17a — THE RUNG DECLARES WHAT ITS EVIDENCE DESCRIBES ════════════════════
#
# ⛔⛔ THE DEFECT WAS AN INVERSION, AND IT WAS STRUCTURAL. `price()` used to
# decide the basis by asking WHICH RUNG it was holding:
#
#       if rung is ESTIMATE:  PerServing(...)      <- no evidence authority
#       else:                 Per100g()            <- all three evidence rungs
#
# So the ONE rung that may not price at zero, and whose numbers are a model's,
# was the only rung that could express a serving basis — while MEMORY, PRODUCT
# and ARTIFACT were forced through per-100 g and could not price a count at all.
# `ProductEvidence.serving_grams` existed for exactly this and was DEAD: one
# occurrence in the whole repository, its own declaration.
#
# That is why "2 eggs" was priceable only by GUESSING, which `decide()` then
# correctly refused — the 12.6 .. 36.5 recoverable-ownership band P16b measured,
# stated as source.
#
# ⭐ SO THE BUILDER DECLARES THE BASIS, AND THE PRICER JUST SCALES. Authority
# ("who supplied the nutrition") and basis ("what amount do these numbers
# describe") are two axes, and this is where they stop being one.
#
# ⛔ A `basis or Per100g()` FALLBACK IS FORBIDDEN FOR NEW EVIDENCE. Every rung
# below states its basis EXPLICITLY — the migration adapts existing evidence
# rather than defaulting it, because a default makes "missing metadata" silently
# mean "per 100 g", and per-100 g is exactly the assumption that has to stop
# being free.



# ⛔⛔ THE CONVERSION ENGINE IS NOT HERE, AND MUST NOT COME BACK *(review,
# 2026-08-17)*. `SourcedMeasure`, `measure_from_panel` and `mass_from_measures`
# were defined in this module beside the pricer, each with its own notion of
# whether two units matched. That is a SECOND conversion architecture next to
# the scaling one — and the question "can this portion be scaled against this
# evidence" has to have exactly ONE answer, because P17g's predicate must ask
# the very question the pricer answers. Two engines are how coverage and pricing
# come to disagree, which is the defect `has_mass` exists to prevent.
#
# They now live in `skills.nutrition.scaling`, which already owned `_factor` and
# `unit_matches`. This module consumes them and defines none of them.
from skills.nutrition.scaling import (  # noqa: E402
    SourcedMeasure, mass_from_measures, measure_from_panel)


# ⛔ NO UNIT VOCABULARY LIVES IN THIS MODULE. `_measure_unit_text` and the size
# words sit in `skills.nutrition.scaling` beside `unit_matches` — the first
# draft put a copy here, which was BOTH a second unit authority (the exact
# two-engines smell every review of this tranche has caught) AND a literal
# string collection inside the pricer, which the zero-rule AST gate rightly
# forbids: this module must never hold name lists that could grow into
# food-name branches.
def _candidate_measures(winner: dict) -> tuple:
    """Every sourced measure the WINNING record states about itself.

    Two shapes, because USDA states them two ways and both are the record's own
    claim:

      * a BRANDED serving panel — `serving_text` + `serving_mass_g`
      * `foodPortions` — "1 large" = 50 g, "1 fillet" = 154 g, "1 cup" = 134 g,
        which is the only place generic foods carry a measure at all

    ⛔ THE WINNER'S, AND ONLY THE WINNER'S. A measure taken from a record that
    did not price this food would be a second source's claim wearing the first
    one's authority — the same defect class as a fuzzy name match building
    PRODUCT.
    """
    out = []
    # ⛔⛔ NO FALLBACK VERSION (P17c.3a). `dataset_version` comes from the
    # artifact or it is absent, and absent means NOT AUTHORITATIVE. A literal
    # "committed_artifact" would have been stamped into every durable conversion
    # record as the thing a correction cites, while also asserting immutability
    # about a version nobody identified.
    release = str(winner.get("dataset_version") or "")
    provenance = {
        "dataset_id": "usda_fdc",
        "dataset_version": release,
        "record_key": str(winner.get("fdc_id") or ""),
        "record_version": str(winner.get("publication_date") or ""),
        "data_type": str(winner.get("data_type") or ""),
        # Only claimed once the version it refers to is actually named.
        "immutable_within_version": bool(release),
    } if winner.get("fdc_id") else {}
    panel = measure_from_panel(winner.get("serving_text"),
                               winner.get("serving_mass_g"),
                               source_id=f"usda:{winner.get('fdc_id')}",
                               **provenance)
    if panel:
        out.append(panel)
    for measure in (winner.get("measures") or ()):
        try:
            grams = float(measure.get("grams"))
            amount = float(measure.get("amount") or 1.0)
        except (TypeError, ValueError):
            continue
        from skills.nutrition.scaling import _measure_unit_text
        unit_text = _measure_unit_text(
            str(measure.get("unit_text") or "").strip().lower(),
            winner.get("description"))
        # ⚠ THE AMOUNT IS READ, NOT ASSUMED. USDA states "2 tbsp = 30 g" as
        # amount=2; treating the gram weight as per-unit would double it.
        if grams > 0 and amount > 0 and unit_text:
            # ⭐ THE PORTION'S OWN ID MAKES THE RECORD KEY EXACT. An fdc_id
            # names a FOOD; a food states several portions, and the conversion
            # cites the one it used — "1 large" is not "1 cup".
            portion_id = measure.get("portion_id")
            out.append(SourcedMeasure(
                unit_text=unit_text, grams_per_unit=grams / amount,
                source_id=f"usda:{winner.get('fdc_id')}",
                dataset_id="usda_fdc",
                dataset_version=str(measure.get("dataset_version") or release),
                record_key=(f"{winner.get('fdc_id')}#portion:{portion_id}"
                            if portion_id else str(winner.get("fdc_id") or "")),
                record_version=str(measure.get("publication_date") or ""),
                data_type=str(measure.get("data_type")
                              or winner.get("data_type") or ""),
                source_fingerprint=str(measure.get("fingerprint") or ""),
                immutable_within_version=bool(
                    measure.get("dataset_version") or release)))
    return tuple(out)


def _product_measures(ev: "ProductEvidence") -> tuple:
    """A product's own serving panel as a conversion, when it states one.

    ⚠ `serving_unit` IS REQUIRED. A mass with no unit cannot be matched against
    what the user counted, and matching it against ANY count is exactly how "one
    piece of a roll" becomes "one whole roll".
    """
    measure = measure_from_panel(ev.serving_unit, ev.serving_grams,
                                 source_id=ev.identifier)
    return (measure,) if measure else ()


def _apply(profile, factor: float):
    """Scale every field by ONE factor and stamp the result `per_portion`.

    Mirrors `scale_profile`'s body deliberately: that function takes a basis and
    re-derives the factor, and by this point the resolver has already
    established one — possibly via a conversion the original portion could not
    reach. Asking for the factor twice is how the second ask refuses what the
    first allowed.
    """
    from skills.nutrition.models import NutrientProfile
    from skills.nutrition.scaling import _round

    return NutrientProfile(values={
        name: value.with_value(_round(value.value * factor, name),
                               basis="per_portion")
        for name, value in (profile.values or {}).items()})


def _basis_name(source_basis) -> str:
    """What the row will say it scaled FROM, ASKED OF THE BASIS ITSELF.

    ⛔ A CLASS-NAME TABLE HERE WAS A SECOND REGISTRY *(fixed on review,
    2026-08-17)*. Every basis in `scaling` already publishes `.basis`, so mapping
    type names duplicated the contract — and a basis added there later would
    have priced correctly while being PERSISTED as `per_portion`, silently
    corrupting the one field a later correction reads.

    `None` means it scaled from nothing: the evidence already described the
    portion eaten. A basis object with no `.basis` is a bug, and says so.
    """
    if source_basis is None:
        return "per_portion"
    name = getattr(source_basis, "basis", "")
    if not name:
        raise ValueError(
            f"{type(source_basis).__name__} declares no `.basis` identifier, so "
            f"the row cannot record what it scaled from")
    return name


def _from_memory(ev: MemoryEvidence):
    from skills.nutrition.scaling import Per100g

    # `user_food_matches` stores per-100 g and nothing else. Stated, not defaulted.
    return (_profile(ev.per100g, source="memory", source_id=ev.source_id,
                     confidence=ev.confidence, estimated=False),
            Rung.MEMORY, ev.source_id or "memory", dict(ev.per100g or {}),
            Per100g(), ())


def _from_product(ev: ProductEvidence):
    """⛔⛔ `serving_grams` IS A CONVERSION INPUT, NOT A NUTRITION BASIS — and
    the first draft of P17a got this wrong in a way worth recording.

    `ProductEvidence.per100g` holds numbers PER 100 G. Declaring
    `PerServing(serving_mass_g=55)` over them reads "these numbers describe one
    serving", so two bars would scale 364 kcal/100 g by a factor of 2 and commit
    728 kcal where the label says 400. The basis must describe THE NUMBERS
    ALONGSIDE IT, never merely a fact that happens to be true about the food.

    ⭐ P17b — SO THE BASIS FOLLOWS THE NUMBERS, AND ONLY THE NUMBERS.
    `per_serving` set means the label stated a serving, and the rung declares
    `PerServing`. `per100g` set means it stated per-100 g. Neither set means
    this rung has NO NUMBERS, and it FAILS CLOSED — returning None drops it and
    the ladder continues, rather than manufacturing a basis for an empty dict.
    """
    from skills.nutrition.scaling import Per100g, PerServing

    if ev.per_serving:
        # ⛔ `as_served=True` says the serving is the LABEL'S, so a count of
        # servings may multiply it. `serving_mass_g` still travels: without it a
        # gram-stated portion cannot resolve against this basis and
        # `scale_profile` REFUSES — which is correct, not a gap to paper over.
        return (_profile(ev.per_serving, source="product",
                         source_id=ev.identifier, confidence=0.95,
                         estimated=False, basis="per_serving"),
                Rung.PRODUCT, ev.identifier, dict(ev.per_serving),
                # ⛔ NO `as_served` ON A MANUFACTURER LABEL *(P17b.1)*. That
                # flag means "the dish AS SERVED" — a restaurant estimate or a
                # saved regular, where one helping genuinely IS one serving
                # however loosely described. A packet states a MEASURED serving,
                # and setting the flag widened `countable` so ANY compatible
                # count could multiply it. Identity now does that work instead.
                PerServing(serving_mass_g=ev.serving_grams,
                           servings_per_package=ev.servings_per_package,
                           unit_id=ev.serving_unit,
                           package_unit_id=ev.package_unit),
                _product_measures(ev))
    if ev.per100g:
        return (_profile(ev.per100g, source="product", source_id=ev.identifier,
                         confidence=0.95, estimated=False),
                Rung.PRODUCT, ev.identifier, dict(ev.per100g), Per100g(),
                _product_measures(ev))
    return None


class IdentityCompositionFailed(Exception):
    """The ranker cannot be told which identity it is ranking.

    NOT a `PricingRefused`. It fails ONE RUNG, deliberately: the ladder
    continues and the meal still prices from the estimate rung. Refusing the
    whole meal would trade a preparation mismatch for a lost log.
    """


def _ranker_query(entity: str, preparation: str) -> str:
    """The composed identity — and a REFUSAL rather than a bare fallback.

    ⭐ THIS FAILS CLOSED, and the first version did not. It fell back to
    `entity` on any error, which reintroduced the exact defect this function
    exists to close: evidence loaded under `beef|grilled`, then ranked by the
    query "Beef", then a raw-ground-beef row selected out of a prepared
    candidate set. A fallback that restores the failure mode is not a
    fallback; it is the bug behind an `except`.

    So: if the identity carries a preparation and the composed query does not
    NAME it, this raises. The rung loop treats that as a rung that failed and
    moves on — which is the file's own rule, that a rung which cannot rank is
    a rung that cannot price, applied rather than merely written down.

    The unregistered case takes the same exit on purpose. `name_with` returns
    the bare name for a preparation the ontology does not hold, so the query
    could not express the identity the evidence was keyed under; ranking it
    anyway is the mismatch, not a lenient special case. In practice such a key
    is absent from the artifact and the rung never had evidence to begin with.
    """
    from skills.nutrition.pricing_artifact import priced_identity, split_identity

    try:
        _, prep = split_identity(entity, preparation)
        composed = priced_identity(entity, preparation)
    except Exception as exc:  # cannot even tell whether a preparation is held
        raise IdentityCompositionFailed(
            f"identity composition raised for {entity!r}") from exc

    if prep and prep not in (composed or "").lower():
        raise IdentityCompositionFailed(
            f"{entity!r}/{preparation!r} keys under preparation {prep!r} but "
            f"composes to {composed!r}, which does not name it — ranking "
            f"prepared evidence by this query could select a different "
            f"preparation")
    return composed or entity


# ── THE RUNG MAY NOT DISAPPEAR QUIETLY ────────────────────────────────────
#
# Measured 2026-08-13: five committed identities produced NO winner, so this
# rung returned None and `price()` fell through to a lower one — with no
# error, no log and no metric. Evidence had been retrieved, mechanically
# qualified, semantically annotated and in two cases signed by a person, and
# the turn priced from an estimate anyway. Nothing in the system could report
# that, which is why it survived a full migration undetected.
#
# ⭐ THE FIX FOR THE FIVE IS NOT THE FIX FOR THE CLASS. Morphological folding
# repairs the cases we found; another naming mismatch upstream would
# reproduce the identical silence tomorrow. So the FAILURE ITSELF is named
# and emitted: having candidates and returning nothing is now an event, and a
# gate asserts it fires. An absent answer must never be indistinguishable
# from an answered one.
ARTIFACT_RANKER_NO_WINNER = "artifact_candidates_present_but_ranker_returned_none"
ARTIFACT_WINNER_UNPRICEABLE = "artifact_winner_carries_no_per100g"


def _from_artifact(ev: ArtifactEvidence, *, query: str):
    """Qualified candidates -> the deterministic winner.

    `best_candidate` is the ranker production already uses and the one the
    trace measured at 0 ms. Passing it ONLY qualified candidates is the whole
    change: the legacy path ranked over raw rows, which is how one identity
    priced 295 kcal and then 329.

    Returns None when this rung cannot answer — and says so out loud first.
    """
    from core.food_intelligence import best_candidate

    candidates = list(ev.candidates or ())
    winner, _conf = best_candidate(query, candidates)
    if not winner:
        if candidates:
            logger.warning(
                "event=%s query=%r candidates=%d fdc_ids=%s",
                ARTIFACT_RANKER_NO_WINNER, query, len(candidates),
                ",".join(str(c.get("fdc_id") or "?") for c in candidates[:8]))
        return None
    per100g = winner.get("per100g") or {}
    if not per100g:
        logger.warning("event=%s query=%r fdc_id=%s",
                       ARTIFACT_WINNER_UNPRICEABLE, query,
                       winner.get("fdc_id"))
        return None
    fdc = str(winner.get("fdc_id") or "")
    # ⚠ PER-100 G BECAUSE THE ARTIFACT'S `per100g` KEY SAYS SO, not by default.
    # When P17c lands sourced PIECE->grams measures beside these candidates,
    # THIS is the line that starts returning a PerUnit/PerServing basis — and
    # `price()` will not need to change for it to work.
    from skills.nutrition.scaling import Per100g

    return (_profile(per100g, source="usda", source_id=fdc,
                     confidence=0.85, estimated=False),
            Rung.ARTIFACT, f"usda:{fdc}" if fdc else "usda", dict(per100g),
            Per100g(), _candidate_measures(winner))


def _from_estimate(ev: EstimateEvidence):
    """The bounded fallback, REPRICED against the answer when it can be.

    The estimate described `basis_grams`; the user answered something else. So
    it is scaled like any other basis rather than being handed through — the
    difference between "answering reprices the meal" and "answering changes
    the label on the same number".
    """
    if ev.calories is None:
        return None
    from skills.nutrition.scaling import PerServing

    profile = _profile({"calories": ev.calories, "protein": ev.protein,
                        "carbs": ev.carbs, "fat": ev.fat},
                       source="estimate", source_id="", confidence=0.4,
                       estimated=True)
    # ⛔ NO BASIS MEANS DO NOT SCALE — AND THAT IS A THIRD STATE, NOT A DEFAULT.
    # Without a stated basis there is nothing to scale FROM: the estimate is
    # already a statement about a portion, so it stands as given. Collapsing
    # this into Per100g() would reprice every basis-less estimate as though its
    # calories described 100 g, which is the silent-default failure this whole
    # contract exists to remove.
    basis = (PerServing(serving_mass_g=float(ev.basis_grams), as_served=True)
             if ev.basis_grams else None)
    return profile, Rung.ESTIMATE, "", {}, basis, ()


def price(*, entity: str, preparation: str = "", consumed=None,
          memory: Optional[MemoryEvidence] = None,
          product: Optional[ProductEvidence] = None,
          artifact: Optional[ArtifactEvidence] = None,
          estimate: Optional[EstimateEvidence] = None,
          bound: bool = False) -> PricedFood:
    """What this food costs. SYNCHRONOUS, and deliberately so.

    A synchronous signature is the strongest possible statement of Gate B:
    there is no `await` here, so no provider or model call can hide in the
    normal settle path. Evidence arrives already gathered.

    RUNG ORDER IS AUTHORITY ORDER — memory, product, artifact, estimate — and
    the first rung that can produce numbers wins. `refuse_or_return` is the
    single exit, so no rung can smuggle out an indefensible price.
    """
    from skills.nutrition.models import MACRO_FIELDS
    # ⭐ NO BASIS TYPES IMPORTED HERE ANY MORE, AND THAT IS THE POINT OF P17a.
    # `price()` cannot name a basis, so it cannot pick one — the rung builders
    # do, and this function only applies what they declared. Nor does it own
    # conversion: `resolve_scaling` is the single resolver (P17c.1).
    from skills.nutrition.scaling import ScalingRefused, resolve_scaling

    # A NON-POSITIVE PORTION IS NOT A MEAL. Scaling 165 kcal/100 g by zero
    # grams yields a legitimate-looking zero from an EVIDENCE-backed rung, so
    # `is_defensible` would wave it through — the mackerel defect returning
    # through a different door. The degenerate thing here is the portion, not
    # the food, so it is refused before any rung runs.
    if consumed is not None:
        _mass = getattr(consumed, "grams", None)
        if _mass is not None and float(_mass) <= 0:
            logger.warning("event=pricing_refused food=%s reason=portion_mass "
                           "grams=%s", entity, _mass)
            raise PricingRefused(f"{entity!r} has a non-positive portion mass")

    # ⭐ SCALING HAPPENS INSIDE THE LOOP, so an unscalable rung FALLS THROUGH.
    #
    # It used to run after a winner was chosen, which made "this rung's basis
    # cannot be massed" fatal to the whole meal. Measured adversarially: a
    # count-only answer ("1 breast") has no grams, `scale_profile` refuses a
    # per-100 g basis, and a perfectly good estimate on the next rung never
    # got its turn — the meal was refused instead of priced at 280 kcal. A
    # rung that cannot be scaled has simply failed; the ladder continues.
    #
    # `ScalingRefused` is also not `PricingRefused`, so escaping here would
    # bypass the narrow handler in `b1_answer_turn` and take the whole turn
    # down — worse than the zero-calorie row this P1 exists to delete.
    priced = None
    # ⛔⛔ B-1.8c2.2 — `bound=True` IS AN EVIDENCE CONSTRAINT, NOT A PRIORITY
    # *(Danny)*. A typed exact product selection CONSTRAINS the evidence
    # universe to that one snapshot; it does not merely raise PRODUCT's rank.
    #
    #     bound=False   MEMORY -> PRODUCT -> ARTIFACT -> ESTIMATE   (unchanged)
    #     bound=True    the specified PRODUCT snapshot ONLY
    #                   -> scalable: price · not scalable: REFUSE. No fallback.
    #
    # Because: the user tapped "Core Power Elite 42 g"; if that label cannot
    # scale the stated amount, the truth is "we cannot price the product you
    # selected" — never "so we priced your old memory row instead", which
    # would throw the exact clarification away while looking successful.
    if bound:
        if product is None:
            raise PricingRefused(
                f"{entity!r} is bound to an exact product but no product "
                f"evidence was supplied — a binding with no snapshot is not a "
                f"binding")
        rungs = ((product, _from_product),)
    else:
        rungs = ((memory, _from_memory), (product, _from_product),
                 (artifact, lambda e: _from_artifact(
                     e, query=_ranker_query(entity, preparation))),
                 (estimate, _from_estimate))
    for ev, build in rungs:
        if ev is None:
            continue
        try:
            chosen = build(ev)
        except Exception:
            logger.warning("rung failed for %s", entity, exc_info=True)
            continue
        if not chosen:
            continue
        profile, rung, evidence_id, raw_per_basis, source_basis, measures = chosen
        before = profile.amount("calories")

        # ⭐ P17a — THE PRICER NO LONGER DECIDES THE BASIS FROM THE RUNG. It
        # scales what the evidence SAYS IT IS. `source_basis is None` means the
        # evidence already describes the portion eaten and must not be scaled;
        # every other case goes through the one scaling engine, which refuses an
        # incompatible basis rather than guessing.
        #
        # This is what makes P17c/P17d additive: a producer that returns a
        # PerUnit or PerServing basis starts pricing counts correctly WITHOUT
        # another edit here.
        # ⚠ NAMED ONLY WHEN IT ACTUALLY SCALED. With no `consumed` nothing is
        # scaled, and the row said `per_portion` before this change — labelling
        # it `per_100g` here would rewrite the provenance of every unscaled row
        # while claiming to be a no-op refactor.
        basis_name = "per_portion"
        scaling = None
        if consumed is not None and source_basis is not None:
            # ⭐⭐ P17c.1 — ONE RESOLVER ANSWERS "CAN THIS PORTION MEET THIS
            # BASIS", and the pricer no longer orchestrates a fallback of its
            # own. `resolve_scaling` tries the basis, and only on a refusal
            # consults the sourced measures — so a portion that priced before
            # prices identically now, and P17g's predicate can ask the SAME
            # function rather than re-deriving scalability a second time.
            try:
                resolution = resolve_scaling(source_basis, consumed, measures)
            except ScalingRefused as exc:
                logger.info(
                    "event=rung_unscalable food=%s rung=%s basis=%s — %s",
                    entity, rung.value, _basis_name(source_basis), exc)
                continue
            # ⛔⛔ CF4 — EXACT PRODUCT x HEURISTIC MASS != AUTHORITATIVE
            # SETTLEMENT *(Danny, P17 scan/binding)*. A bound item has exact
            # NUTRITION authority (the label) but that says nothing about
            # QUANTITY authority: "2 cups" of a peanut bar normalizes to 260 g
            # from a vessel table, and scaling the label by an invented mass
            # would commit an exact-looking number nobody measured. Nutrition
            # authority != quantity authority. Under `bound` the resolver's
            # verdict is binding: user-stated exact, the label's own units, or
            # a sourced conversion — a heuristic path REFUSES (ASK / REFUSE
            # upstream), it does not fall to another rung.
            if bound and not resolution.authoritative:
                raise PricingRefused(
                    f"{entity!r} is bound to an exact product but the stated "
                    f"quantity {getattr(consumed, 'unit_label', '') or getattr(consumed, 'unit', '')!r} "
                    f"only scales by a heuristic ({resolution.path}) — exact "
                    f"nutrition x estimated mass is not an authoritative "
                    f"settlement; ask for the amount in the label's units")
            # ⛔ SCALED THROUGH THE RESOLVER'S OWN FACTOR, not by re-deriving
            # one. Calling `scale_profile` again here would ask `_factor` a
            # second time with the ORIGINAL portion — which is exactly the
            # refusal the resolver just worked around.
            profile = _apply(profile, resolution.factor)
            basis_name = resolution.basis_name or _basis_name(source_basis)
            scaling = resolution
            if resolution.resolved_grams is not None:
                logger.info(
                    "event=sourced_measure_resolved food=%s rung=%s count=%s "
                    "unit=%r grams=%.1f conversion=%s", entity, rung.value,
                    getattr(consumed, "count", None),
                    getattr(consumed, "unit_label", "")
                    or getattr(consumed, "unit", ""),
                    resolution.resolved_grams,
                    "yes" if resolution.conversion is not None else "unsourced")

        # ⭐ THE FULL MICRONUTRIENT SET SURVIVES, scaled by the same factor.
        #
        # `NutrientProfile` models only six micros (MICRO_FIELDS), but a USDA
        # row carries ~22 — calcium, iron, the vitamins — and legacy stored all
        # of them in `micronutrients_json`. Reading micros back off the profile
        # alone would silently drop about nineteen from every canonical row.
        # So they are scaled from the RAW per-basis dict, by the factor the
        # profile itself moved by, which keeps one scaling authority.
        after = profile.amount("calories")
        factor = (float(after) / float(before)) if (before and after) else 1.0
        micros = {k: round(float(v) * factor, 4)
                  for k, v in (raw_per_basis or {}).items()
                  if k not in MACRO_FIELDS and k not in ("fiber", "sugar",
                                                         "sodium")
                  and isinstance(v, (int, float))}
        # What ONE of the declared basis is — ASKED OF THE BASIS, because the
        # zero-rule AST gate rightly forbids string comparisons in this module:
        # a name selector here is the seed of a food-name branch, and the first
        # draft of this block was exactly that (`basis_name == "per_100g"`).
        _amt, _unit = (source_basis.source_quantity()
                       if source_basis is not None
                       and hasattr(source_basis, "source_quantity")
                       else (None, ""))
        priced = PricedFood(
            calories=float(profile.amount("calories") or 0.0),
            protein=profile.amount("protein"),
            carbs=profile.amount("carbs"),
            fats=profile.amount("fat"),
            fiber=profile.amount("fiber"), sugar=profile.amount("sugar"),
            sodium=profile.amount("sodium"),
            micros=micros or None, micros_estimated=(rung is Rung.ESTIMATE),
            rung=rung, evidence_id=evidence_id, basis=basis_name,
            scaling_factor=(scaling.factor if scaling else None),
            resolved_grams=(scaling.resolved_grams if scaling else None),
            conversion_evidence_ids=(tuple(scaling.evidence_ids)
                                     if scaling else ()),
            source_amount=_amt, source_unit=_unit)
        # AN INDEFENSIBLE PRICE IS ALSO A FAILED RUNG. Continuing is what turns
        # "the estimate was zero" into "try the next thing" rather than
        # "refuse the meal".
        if priced.is_defensible():
            break
        priced = None

    return refuse_or_return(priced, food_name=entity)
