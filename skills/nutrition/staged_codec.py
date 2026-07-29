"""Serialisation for the staged item graph, so a resolution outlives its turn.

A clarification is a question about an item we have *already resolved*. By the
time we ask "was that about two tablespoons?", the lane has classified the food,
scored candidate products, picked a per-100g basis, priced it and recorded which
assumptions it made to get there. All of that lives in a `StagedFoodItem`.

None of it survived the turn. The pending row persisted the user's original
wording, the question text, and a `staged_item_id` — a *reference to an object
that no longer exists*. So the answering turn had a pointer to nothing, fell
back to re-interpreting the raw message, and re-ran the entire enrichment ladder
from zero. That is the mechanism behind every symptom in the plan's cause A: the
ask that said "around 580 cal" and the answer that logged 8 g of protein; the
16-second answer turn re-pricing a cheesecake priced one turn earlier; and the
sopressata that came back thirteen hours later as "Dollar pizza slices, plain",
because a cold re-interpretation reached for the user's most common pizza and
discarded the fact they had stated in the same thread.

`StagedFoodItem` already knows this is the failure mode — its own docstring says
nothing downstream may re-derive identity or quantity from `original_text`,
"that re-derivation is what makes a clarification answer land on the wrong row".
And the apply-the-answer half is already written and pure: `answering()`,
`resolving()` and `_applying()`. The only thing missing between them was a way
to write the object down and read it back.

**Rules this codec keeps, because the types they belong to are built on them.**

*Unknown stays unknown.* `NutrientProfile` omits fields it does not know rather
than zero-filling them, and a field absent here decodes back to absent. A codec
that defaults on the way out would turn "we never learned the sodium" into
"the sodium is zero" — the exact class of confident nonsense the nutrient types
exist to prevent.

*Stated stays stated.* `QuantityIntent` keeps `stated_*` and `inferred_*` apart
so a number we chose can never be reported as one the user gave, and
`PreparationIntent.stated` records whether "fried" came from them or from us.
Collapsing either on a round trip would launder an assumption into a fact —
which is §4.2b's finding, one turn later.

*Decoding is total.* A malformed or future payload returns `None`, never raises.
Losing a staged resolution costs one re-interpretation, which is exactly today's
behaviour; raising would cost the turn. `STAGED_CODEC_VERSION` is checked on the
way in so a shape change degrades to that fallback instead of decoding a stale
payload into the wrong fields.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

from skills.nutrition.ambiguity import AmbiguityOption, AmbiguityType, FoodAmbiguity
from skills.nutrition.candidate_sets import ProductCandidate
from skills.nutrition.models import NutrientProfile
from skills.nutrition.provenance import NutrientValue, SourceTier
from skills.nutrition.staging import (FoodAssumption, FoodClass, FoodIdentity,
                                      NutrientDeltaRange, PreparationIntent,
                                      Quantity, QuantityIntent,
                                      ResolutionStatus, StagedFoodItem)

#: Bumped whenever a field's MEANING changes. Additive fields do not need it —
#: they decode to their defaults — but a renamed or re-purposed one does, and
#: the cost of getting that wrong is silently applying an answer to a
#: misread resolution.
STAGED_CODEC_VERSION = "staged_v1"

#: Values JSON round-trips without changing type. `FoodAssumption.assumed_value`
#: and `AmbiguityOption.payload` are `Any`, and in practice carry scalars — a
#: candidate id, a quantity, a fraction. Anything else is dropped rather than
#: stringified, because a payload that decodes to a *different* type than it
#: encoded is worse than one that decodes to None: the parser would act on it.
_JSON_SCALARS = (str, int, float, bool, type(None))


def _plain(value: Any) -> Any:
    """A JSON-safe copy, or None. Containers are walked so a dict of scalars
    survives; anything else is refused."""
    if isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return None


def _num(value: Any) -> Optional[float]:
    """A float, or None. Never 0.0 as a stand-in for absent."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _drop_none(d: dict) -> dict:
    """Absent keys rather than null ones — smaller rows, and it makes the
    "unknown stays unknown" rule visible in the stored payload itself."""
    return {k: v for k, v in d.items() if v is not None}


# ── leaves ────────────────────────────────────────────────────────────────────
def _enc_quantity(q: Optional[Quantity]) -> Optional[dict]:
    if q is None:
        return None
    return {"amount": q.amount, "unit": q.unit}


def _dec_quantity(d) -> Optional[Quantity]:
    if not isinstance(d, Mapping):
        return None
    amount = _num(d.get("amount"))
    if amount is None:
        return None
    return Quantity(amount=amount, unit=str(d.get("unit") or ""))


def _enc_nutrient_value(v: NutrientValue) -> dict:
    return _drop_none({
        "value": v.value, "unit": v.unit, "source": v.source,
        "confidence": v.confidence,
        # The basis is the field a per-100g row and a per-serving row differ
        # by, and reinterpreting one as the other is how a panel becomes
        # nonsense. It is never omitted.
        "basis": v.basis,
        "source_id": v.source_id,
        "estimated": v.estimated})


def _dec_nutrient_value(d) -> Optional[NutrientValue]:
    if not isinstance(d, Mapping):
        return None
    value = _num(d.get("value"))
    if value is None:
        return None
    return NutrientValue(
        value=value, unit=str(d.get("unit") or ""),
        source=str(d.get("source") or ""),
        confidence=_num(d.get("confidence")) or 0.5,
        basis=str(d.get("basis") or "per_serving"),
        source_id=(str(d["source_id"]) if d.get("source_id") is not None
                   else None),
        estimated=bool(d.get("estimated")))


def _enc_profile(p: Optional[NutrientProfile]) -> Optional[dict]:
    """Not `NutrientProfile.as_dict()` — that returns plain numbers and drops
    basis, source and confidence, which is exactly the provenance an answering
    turn needs in order NOT to look the food up again."""
    if p is None:
        return None
    return {k: _enc_nutrient_value(v) for k, v in (p.values or {}).items()}


def _dec_profile(d) -> Optional[NutrientProfile]:
    if not isinstance(d, Mapping):
        return None
    values = {}
    for k, raw in d.items():
        v = _dec_nutrient_value(raw)
        if v is not None:
            values[str(k)] = v
    return NutrientProfile(values=values)


# ── identity, quantity, preparation ───────────────────────────────────────────
def _enc_identity(i: FoodIdentity) -> dict:
    return _drop_none({
        "canonical_name": i.canonical_name, "brand": i.brand,
        "product_line": i.product_line, "variant": i.variant,
        "package_size": _enc_quantity(i.package_size),
        "barcode": i.barcode})


def _dec_identity(d) -> FoodIdentity:
    if not isinstance(d, Mapping):
        return FoodIdentity()
    def _s(key):
        v = d.get(key)
        return str(v) if v is not None else None
    return FoodIdentity(
        canonical_name=_s("canonical_name"), brand=_s("brand"),
        product_line=_s("product_line"), variant=_s("variant"),
        package_size=_dec_quantity(d.get("package_size")),
        barcode=_s("barcode"))


def _enc_quantity_intent(q: QuantityIntent) -> dict:
    return _drop_none({
        # stated_* and inferred_* are encoded as the two separate pairs they
        # are. Merging them on the way out is the "a scoop" bug.
        "stated_amount": q.stated_amount, "stated_unit": q.stated_unit,
        "inferred_amount": q.inferred_amount, "inferred_unit": q.inferred_unit,
        "consumed_fraction": q.consumed_fraction,
        "container_count": q.container_count,
        "estimated_mass_g": q.estimated_mass_g,
        "descriptor": q.descriptor,
        "mass_confidence": q.mass_confidence,
        "mass_range_g": (list(q.mass_range_g)
                         if q.mass_range_g is not None else None)})


def _dec_quantity_intent(d) -> QuantityIntent:
    if not isinstance(d, Mapping):
        return QuantityIntent()
    rng = d.get("mass_range_g")
    mass_range = None
    if isinstance(rng, (list, tuple)) and len(rng) == 2:
        lo, hi = _num(rng[0]), _num(rng[1])
        if lo is not None and hi is not None:
            mass_range = (lo, hi)
    def _s(key):
        v = d.get(key)
        return str(v) if v is not None else None
    return QuantityIntent(
        stated_amount=_num(d.get("stated_amount")),
        stated_unit=_s("stated_unit"),
        inferred_amount=_num(d.get("inferred_amount")),
        inferred_unit=_s("inferred_unit"),
        consumed_fraction=_num(d.get("consumed_fraction")),
        container_count=_num(d.get("container_count")),
        estimated_mass_g=_num(d.get("estimated_mass_g")),
        descriptor=_s("descriptor"),
        mass_confidence=_num(d.get("mass_confidence")),
        mass_range_g=mass_range)


def _enc_preparation(p: PreparationIntent) -> dict:
    return _drop_none({
        "method": p.method,
        # Whether THEY said it. §4.2b: a preparation we inferred may not come
        # back looking like one they stated, or it becomes a standing default
        # and then part of the identity key.
        "stated": p.stated,
        "modifiers": list(p.modifiers) if p.modifiers else None})


def _dec_preparation(d) -> PreparationIntent:
    if not isinstance(d, Mapping):
        return PreparationIntent()
    mods = d.get("modifiers")
    return PreparationIntent(
        method=(str(d["method"]) if d.get("method") is not None else None),
        stated=bool(d.get("stated")),
        modifiers=tuple(str(m) for m in mods) if isinstance(mods, (list, tuple))
        else ())


# ── assumptions ───────────────────────────────────────────────────────────────
def _enc_delta(r: NutrientDeltaRange) -> dict:
    return {"calories": r.calories, "protein": r.protein,
            "carbs": r.carbs, "fat": r.fat}


def _dec_delta(d) -> NutrientDeltaRange:
    if not isinstance(d, Mapping):
        return NutrientDeltaRange()
    return NutrientDeltaRange(
        calories=_num(d.get("calories")) or 0.0,
        protein=_num(d.get("protein")) or 0.0,
        carbs=_num(d.get("carbs")) or 0.0,
        fat=_num(d.get("fat")) or 0.0)


def _enc_assumption(a: FoodAssumption) -> dict:
    return _drop_none({
        "staged_item_id": a.staged_item_id, "field_name": a.field_name,
        "assumed_value": _plain(a.assumed_value),
        "alternatives": [_plain(x) for x in (a.alternatives or ())] or None,
        "confidence": a.confidence,
        "nutrition_impact": _enc_delta(a.nutrition_impact),
        "user_visible_text": a.user_visible_text or None})


def _dec_assumption(d) -> Optional[FoodAssumption]:
    if not isinstance(d, Mapping):
        return None
    alts = d.get("alternatives")
    return FoodAssumption(
        staged_item_id=str(d.get("staged_item_id") or ""),
        field_name=str(d.get("field_name") or ""),
        assumed_value=_plain(d.get("assumed_value")),
        alternatives=tuple(_plain(x) for x in alts)
        if isinstance(alts, (list, tuple)) else (),
        confidence=_num(d.get("confidence")) or 0.5,
        nutrition_impact=_dec_delta(d.get("nutrition_impact")),
        user_visible_text=str(d.get("user_visible_text") or ""))


# ── candidates ────────────────────────────────────────────────────────────────
def _enc_candidate(c: ProductCandidate) -> dict:
    return _drop_none({
        "candidate_id": c.candidate_id, "canonical_name": c.canonical_name,
        "brand": c.brand, "product_line": c.product_line, "variant": c.variant,
        "package_size": _enc_quantity(c.package_size),
        "serving_basis": c.serving_basis or None,
        "source": c.source,
        # The anchor. An `fdc_id` / OFF code is what makes the stored
        # resolution a claim about a PRODUCT rather than about a word, and it
        # is what lets the answering turn skip the ladder entirely.
        "source_id": c.source_id,
        "tier": int(c.tier),
        "identity_score": c.identity_score, "brand_score": c.brand_score,
        "variant_score": c.variant_score, "size_score": c.size_score,
        "serving_basis_score": c.serving_basis_score,
        "overall_score": c.overall_score,
        "nutrient_profile": _enc_profile(c.nutrient_profile),
        "match_grade": str(c.match_grade),
        "via_alias": c.via_alias,
        "collapsed_from": list(c.collapsed_from) or None})


def _dec_candidate(d) -> Optional[ProductCandidate]:
    if not isinstance(d, Mapping):
        return None
    cid = str(d.get("candidate_id") or "")
    if not cid:
        return None
    try:
        tier = SourceTier(int(d.get("tier") or SourceTier.PROVISIONAL))
    except (ValueError, TypeError):
        tier = SourceTier.PROVISIONAL
    collapsed = d.get("collapsed_from")
    def _s(key):
        v = d.get(key)
        return str(v) if v is not None else None
    return ProductCandidate(
        candidate_id=cid,
        canonical_name=str(d.get("canonical_name") or ""),
        brand=_s("brand"), product_line=_s("product_line"),
        variant=_s("variant"),
        package_size=_dec_quantity(d.get("package_size")),
        serving_basis=str(d.get("serving_basis") or ""),
        source=str(d.get("source") or "provisional"),
        tier=tier, source_id=_s("source_id"),
        identity_score=_num(d.get("identity_score")) or 0.0,
        brand_score=_num(d.get("brand_score")) or 0.0,
        variant_score=_num(d.get("variant_score")) or 0.0,
        size_score=_num(d.get("size_score")) or 0.0,
        serving_basis_score=_num(d.get("serving_basis_score")) or 0.0,
        overall_score=_num(d.get("overall_score")) or 0.0,
        nutrient_profile=_dec_profile(d.get("nutrient_profile")),
        match_grade=str(d.get("match_grade") or "none"),
        via_alias=_s("via_alias"),
        collapsed_from=tuple(str(x) for x in collapsed)
        if isinstance(collapsed, (list, tuple)) else ())


# ── ambiguities ───────────────────────────────────────────────────────────────
def _enc_option(o: AmbiguityOption) -> dict:
    return _drop_none({"label": o.label, "confidence": o.confidence,
                       "payload": _plain(o.payload),
                       "candidate_id": o.candidate_id})


def _dec_option(d) -> Optional[AmbiguityOption]:
    if not isinstance(d, Mapping):
        return None
    return AmbiguityOption(
        label=str(d.get("label") or ""),
        confidence=_num(d.get("confidence")) or 0.0,
        payload=_plain(d.get("payload")),
        candidate_id=(str(d["candidate_id"])
                      if d.get("candidate_id") is not None else None))


def _enc_ambiguity(a: FoodAmbiguity) -> dict:
    return _drop_none({
        "ambiguity_id": a.ambiguity_id, "staged_item_id": a.staged_item_id,
        "ambiguity_type": a.ambiguity_type.value,
        "field_name": a.field_name,
        "candidate_values": [_enc_option(o) for o in (a.candidate_values or ())]
        or None,
        # The spans are what make a question justifiable — they are the
        # difference between "we're unsure" and "being wrong costs 190 cal".
        # A re-ask that lost them could not weigh itself.
        "calorie_span": a.calorie_span, "protein_span": a.protein_span,
        "carb_span": a.carb_span, "fat_span": a.fat_span,
        "confidence": a.confidence,
        "materiality_score": a.materiality_score,
        "clarification_prompt": a.clarification_prompt or None,
        "identity_risk": a.identity_risk,
        "serving_basis_risk": a.serving_basis_risk,
        "item_calories": a.item_calories})


def _dec_ambiguity(d) -> Optional[FoodAmbiguity]:
    if not isinstance(d, Mapping):
        return None
    try:
        atype = AmbiguityType(str(d.get("ambiguity_type") or ""))
    except ValueError:
        return None
    opts = d.get("candidate_values")
    return FoodAmbiguity(
        ambiguity_id=str(d.get("ambiguity_id") or ""),
        staged_item_id=str(d.get("staged_item_id") or ""),
        ambiguity_type=atype,
        field_name=str(d.get("field_name") or ""),
        candidate_values=tuple(
            o for o in (_dec_option(x) for x in opts) if o is not None)
        if isinstance(opts, (list, tuple)) else (),
        calorie_span=_num(d.get("calorie_span")),
        protein_span=_num(d.get("protein_span")),
        carb_span=_num(d.get("carb_span")),
        fat_span=_num(d.get("fat_span")),
        confidence=_num(d.get("confidence")) or 0.0,
        materiality_score=_num(d.get("materiality_score")) or 0.0,
        clarification_prompt=str(d.get("clarification_prompt") or ""),
        identity_risk=_num(d.get("identity_risk")) or 0.0,
        serving_basis_risk=_num(d.get("serving_basis_risk")) or 0.0,
        item_calories=_num(d.get("item_calories")))


# ── the item ──────────────────────────────────────────────────────────────────
def encode_item(item: StagedFoodItem) -> dict:
    """The staged item as a JSON-safe dict — the whole resolution, not a
    reference to it."""
    return _drop_none({
        "v": STAGED_CODEC_VERSION,
        "staged_item_id": item.staged_item_id,
        "original_text": item.original_text,
        "ordinal": item.ordinal,
        "food_class": item.food_class.value,
        "identity": _enc_identity(item.identity),
        "quantity": _enc_quantity_intent(item.quantity),
        # The user's own vague word, recorded on the turn whose message
        # contained it. A meal clarified over two turns is exactly the case
        # `vague_measure` exists for, so it has to cross the boundary.
        "vague_measure": item.vague_measure or None,
        "preparation": _enc_preparation(item.preparation),
        "candidate_products": [_enc_candidate(c)
                               for c in (item.candidate_products or ())] or None,
        "ambiguities": [_enc_ambiguity(a)
                        for a in (item.ambiguities or ())] or None,
        "resolution_status": item.resolution_status.value,
        "assumptions": [_enc_assumption(a)
                        for a in (item.assumptions or ())] or None,
        "meal_group_id": item.meal_group_id or None})


def decode_item(d) -> Optional[StagedFoodItem]:
    """Rebuild the item, or None. Never raises: a resolution we cannot read is
    a resolution we do not have, and the caller's fallback for that is the
    re-interpretation it does today."""
    if not isinstance(d, Mapping):
        return None
    if str(d.get("v") or "") != STAGED_CODEC_VERSION:
        return None
    sid = str(d.get("staged_item_id") or "")
    if not sid:
        return None
    try:
        try:
            food_class = FoodClass(str(d.get("food_class") or ""))
        except ValueError:
            food_class = FoodClass.UNKNOWN
        try:
            status = ResolutionStatus(str(d.get("resolution_status") or ""))
        except ValueError:
            status = ResolutionStatus.UNRESOLVED
        cands = d.get("candidate_products")
        ambs = d.get("ambiguities")
        assumps = d.get("assumptions")
        try:
            ordinal = int(d.get("ordinal") or 0)
        except (TypeError, ValueError):
            ordinal = 0
        return StagedFoodItem(
            staged_item_id=sid,
            original_text=str(d.get("original_text") or ""),
            ordinal=ordinal,
            food_class=food_class,
            identity=_dec_identity(d.get("identity")),
            quantity=_dec_quantity_intent(d.get("quantity")),
            vague_measure=str(d.get("vague_measure") or ""),
            preparation=_dec_preparation(d.get("preparation")),
            candidate_products=tuple(
                c for c in (_dec_candidate(x) for x in cands) if c is not None)
            if isinstance(cands, (list, tuple)) else (),
            ambiguities=tuple(
                a for a in (_dec_ambiguity(x) for x in ambs) if a is not None)
            if isinstance(ambs, (list, tuple)) else (),
            resolution_status=status,
            assumptions=tuple(
                a for a in (_dec_assumption(x) for x in assumps)
                if a is not None)
            if isinstance(assumps, (list, tuple)) else (),
            meal_group_id=str(d.get("meal_group_id") or ""))
    except Exception:
        return None


def encode_items(items) -> list:
    return [encode_item(i) for i in (items or ())]


def decode_items(raw) -> tuple:
    """Decode a list of items, dropping any that will not read. A partial
    recovery is still better than a cold turn: the items that survive keep
    their resolutions and only the rest re-interpret."""
    if not isinstance(raw, (list, tuple)):
        return ()
    return tuple(i for i in (decode_item(x) for x in raw) if i is not None)
