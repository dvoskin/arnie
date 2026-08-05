"""The one food-resolution path (review 2026-07-25, P0).

The staged-item architecture — StagedFoodItem, candidate sets, the
multi-dimensional ambiguity engine, the clarification policy, MealResolution —
was built, tested, and never put in the way of a real turn. Meanwhile the live
path kept using the interpreter's JSON and the calorie-only
`food_ledger.material_ambiguities()`. Two architectures, one of them
unreachable.

This is the seam that ends that. It takes what the interpreter produced and
runs it through the real machinery:

    interpreter output
      → StagedFoodItem[]            identity and quantity separated
      → ambiguities                 calorie/protein/carb/fat/identity/basis
      → learned preferences         applied as assumptions, never silently
      → ClarificationDecision       per-item ready/held, per-meal policy
      → approved commands           the only things that may execute

and, after execution, assembles the MealResolution that owns committed state.

Deliberately NOT a third path. It is called from inside `core.food_turn.run()`,
which is what the live turn already uses and what the coordinator's food stage
delegates to — so both callers get the same decisions, and promoting the
coordinator changes orchestration without changing food intelligence.

The pipeline never writes. It decides what may be written.
"""
from __future__ import annotations

import logging
import re
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

PIPELINE_VERSION = "food_pipeline_v1"


def pipeline_enabled() -> bool:
    """The staged-item pipeline owns the ask decision.

    Default ON: the modules are heavily tested and the fallback is total — any
    failure returns None and the caller keeps the legacy policy. Set
    FOOD_PIPELINE=false to pin the old calorie-only thresholds.
    """
    raw = (os.getenv("FOOD_PIPELINE", "true") or "").strip().lower()
    return raw not in ("false", "0", "no", "off")


@dataclass(frozen=True)
class FoodTurnDecision:
    """What the pipeline decided, before anything executes."""
    staged_items: Tuple[Any, ...] = ()
    clarification: Any = None
    approved_operations: Tuple[Mapping, ...] = ()
    meal_group_id: str = ""
    traces: Tuple[Any, ...] = ()
    pipeline_version: str = PIPELINE_VERSION

    @property
    def asks(self) -> bool:
        return bool(getattr(self.clarification, "questions", ()))

    @property
    def question(self):
        qs = getattr(self.clarification, "questions", ()) or ()
        return qs[0] if qs else None

    @property
    def holds_everything(self) -> bool:
        return bool(self.staged_items) and not self.approved_operations


# ── interpreter output → staged items ─────────────────────────────────────────
def stage_items(data: Mapping, *, turn_id: str, message: str = "",
                mode: str = "moderate") -> tuple:
    """Turn the interpreter's item list into StagedFoodItems.

    This is where identity stops being a string. `food` becomes a FoodIdentity
    with brand/line/variant where the interpreter supplied them, and the amount
    becomes a QuantityIntent that records whether the USER stated it or we
    inferred it — the distinction the old path collapsed and then could not ask
    about.
    """
    from skills.nutrition.staging import (FoodClass, FoodIdentity,
                                          QuantityIntent, StagedFoodItem,
                                          classify_food, make_meal_group_id,
                                          make_staged_item_id)
    from core.food_turn import _item_is_stated

    meal_group_id = make_meal_group_id(turn_id)
    items = []
    for ordinal, raw in enumerate(data.get("items") or []):
        if not isinstance(raw, Mapping):
            continue
        food = str(raw.get("food") or "").strip()
        if not food:
            continue
        brand = (str(raw.get("brand") or "").strip() or None)
        stated = _item_is_stated(dict(raw), message)
        amount = raw.get("amount")
        value = float(amount) if _is_number(amount) else None
        unit = str(raw.get("unit") or "").strip() or None
        # The amount lands in `stated_*` ONLY when the user gave it. An
        # interpreter-chosen amount goes to `inferred_*`, so everything
        # downstream can tell "they said one tablespoon" from "we picked one
        # tablespoon" — which the single pair of fields could not, and which is
        # why "a scoop" reached the user as an approved fact.
        quantity = QuantityIntent(
            stated_amount=(value if stated else None),
            stated_unit=(unit if stated else None),
            inferred_amount=(None if stated else value),
            inferred_unit=(None if stated else unit),
            descriptor=(None if stated else unit))
        items.append(StagedFoodItem(
            staged_item_id=make_staged_item_id(turn_id, ordinal, food),
            original_text=food, ordinal=ordinal,
            # THE INTERPRETER SAYS `branded`; THIS READ `is_packaged`. Two
            # names for one fact, and only the tool-call builder knew both —
            # `_log_call` translates branded -> is_packaged on the way to the
            # write, while staging looked for a key the interpreter never
            # emits. So every branded product staged as GENERIC, and Open Food
            # Facts is seated only for BRANDED/MANUFACTURED: the label ladder
            # could not run for the exact foods it exists to serve, and the
            # numbers fell back to USDA rows and portion estimates.
            food_class=classify_food(food, brand,
                                     bool(raw.get("is_packaged")
                                          or raw.get("branded"))),
            identity=FoodIdentity(canonical_name=food, brand=brand),
            quantity=quantity, meal_group_id=meal_group_id,
            # Read from THIS message, which is the only one that has it.
            vague_measure=(_vague_measure_in(message, food) or "")))
    return tuple(items), meal_group_id


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


# ── the ask/write join (audit §8.1) ───────────────────────────────────────────
def attach_candidates(items, item_candidates: Optional[Mapping]) -> tuple:
    """Seat the products the turn already looked up onto the items they belong to.

    THE MISSING PRODUCER. `StagedFoodItem.candidate_products` is declared, the
    codec encodes it, `answer_application` prices from it and every clarify
    path claims to be about it — and until this function existed nothing in
    production ever assigned it. So an ask crossed the turn boundary carrying
    an identity with no product behind it: `candidates=0`, `anchor=None`, and
    an answering turn whose only option was to re-interpret the string and
    re-run the enrichment ladder it had just run.

    Matched by the item's own text, which is the key the caller fetched under —
    the same lowercased food name `derive_variant_ambiguity` uses for spreads,
    so an item that got a spread gets its candidates too. An unmatched item is
    left exactly as it was: candidates are an improvement to a decision, never
    a precondition for one.
    """
    if not item_candidates:
        return items
    out = []
    for item in items or ():
        found = item_candidates.get((item.original_text or "").strip().lower())
        out.append(item.with_candidates(found) if found else item)
    return tuple(out)


# ── interpreter ambiguities → typed ambiguities ───────────────────────────────
def attach_ambiguities(items, data: Mapping, *, mode: str,
                       targets: Optional[Mapping] = None) -> tuple:
    """Lift the interpreter's reported ambiguities onto the items they concern.

    The old policy read one number — `impact_cal` — against a calorie-only
    threshold. The engine scores calorie, protein, carb, fat, identity risk and
    serving-basis risk, so an item that is calorie-tight and protein-wild is no
    longer waved through.

    TARGETS, OR THE SAME MEAL IS SCORED BY TWO DIFFERENT RULES.

    This function did not take them, and its siblings do: `derive_variant_
    ambiguity` and `derive_vague_quantities` both pass `targets` and therefore
    take `materiality`'s PROPORTIONAL branch, while everything lifted from the
    interpreter fell to the legacy absolute branch — 200 flat calories on
    moderate. One meal, one mode, one call to `decide()`, and an ambiguity the
    MODEL reported was judged by a different rule from one we derived beside
    it.

    The proportional system is the one that exists on purpose — `materiality`
    says so at length, and `DAY_FRACTIONS` / `MIN_ITEM_SHARE` /
    `DAY_SHARE_OVERRIDE` were swept against production. None of it had ever
    seen the ambiguities the interpreter actually reports, which are most of
    them.

    `None` still works and still means the absolute fallback, so a caller
    without targets is no worse off than before.
    """
    from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                            build_ambiguity)

    reported = [a for a in (data.get("ambiguities") or [])
                if isinstance(a, Mapping)]
    if not reported:
        return items

    by_ordinal = {i.ordinal: i for i in items}
    # The item's own size, so the fraction rule can run. A span of 90 calories
    # is most of a granola bar and a rounding error on a platter, and the
    # scorer cannot tell them apart without this.
    # IS THIS REALLY THE ONLY THING WE ARE UNSURE ABOUT? The prompt below said
    # so unconditionally, and it was routinely false: "had a Barebells bar and
    # some chicken and rice" listed "One cup of white rice" — a cup nobody
    # said — and then claimed the chicken was the only open question. A
    # sentence asserting certainty one line under our own guess is the worst
    # kind of wrong, because it tells the user not to look.
    _sole_estimate = sum(
        1 for i in (items or []) if not getattr(
            getattr(i, "quantity", None), "is_stated", False)) <= 1

    raw_by_ordinal = {}
    for ordinal, raw in enumerate(data.get("items") or []):
        if isinstance(raw, Mapping):
            raw_by_ordinal[ordinal] = raw

    grouped = {}
    for amb in reported:
        field_name = str(amb.get("field") or "").strip() or "consumed_quantity"
        target = _match_item(amb, items)
        if target is None:
            continue
        # ── NEVER ASK SOMEONE TO RESTATE WHAT THEY STATED ──────────────────
        #
        # When the user gave the amount, a HOW-MUCH question is already
        # answered, and re-asking it spends the one interruption we get on the
        # only field that was not in doubt. "5-6 fries" came back as "the small
        # side or the full share plate?" — offering a menu portion against a
        # counted one, which is the truffle-fries incident arriving from the
        # other side.
        #
        # What the interpreter is reporting here is real but is not a question:
        # a counted amount still carries spread because restaurant fries differ
        # in size, and the prompt already rules that a stated count is HIGH
        # confidence to be priced per piece, not re-portioned. So the span
        # stays on the item and keeps informing the estimate; it just stops
        # being something we interrupt for. Identity, prep and package-size
        # unknowns on the same item are untouched — those are not answered by
        # an amount.
        _amb_type = _AMBIGUITY_TYPES.get(field_name,
                                         AmbiguityType.CONSUMED_QUANTITY)
        if (_amb_type is AmbiguityType.CONSUMED_QUANTITY
                and getattr(getattr(target, "quantity", None),
                            "is_stated", False)):
            continue
        options = tuple(
            AmbiguityOption(str(o), confidence=0.5)
            for o in (amb.get("options") or [])[:4])
        grouped.setdefault(target.ordinal, []).append(build_ambiguity(
            staged_item_id=target.staged_item_id,
            ambiguity_type=_AMBIGUITY_TYPES.get(field_name,
                                                AmbiguityType.CONSUMED_QUANTITY),
            field_name=_FIELD_NAMES.get(field_name, field_name), mode=mode,
            calorie_span=float(amb.get("impact_cal") or 0),
            protein_span=float(amb.get("impact_protein") or 0),
            item_calories=_calories_for(raw_by_ordinal.get(target.ordinal) or {}),
            targets=dict(targets) if targets else None,
            options=options))

    return tuple(
        item.with_ambiguities(grouped[item.ordinal])
        if item.ordinal in grouped else item
        for item in items)


#: The interpreter's vocabulary for what is uncertain → the typed enum.
_AMBIGUITY_TYPES = {}
_FIELD_NAMES = {}


def _init_maps():
    from skills.nutrition.ambiguity import AmbiguityType
    _AMBIGUITY_TYPES.update({
        "consumed": AmbiguityType.CONSUMED_QUANTITY,
        "consumed_quantity": AmbiguityType.CONSUMED_QUANTITY,
        "amount": AmbiguityType.CONSUMED_QUANTITY,
        "portion": AmbiguityType.CONSUMED_QUANTITY,
        "size": AmbiguityType.PACKAGE_SIZE,
        "package": AmbiguityType.PACKAGE_SIZE,
        "product": AmbiguityType.PRODUCT_IDENTITY,
        "identity": AmbiguityType.PRODUCT_IDENTITY,
        "brand": AmbiguityType.PRODUCT_LINE,
        "variant": AmbiguityType.PRODUCT_VARIANT,
        "flavor": AmbiguityType.PRODUCT_VARIANT,
        "preparation": AmbiguityType.PREPARATION,
        "serving": AmbiguityType.SERVING_BASIS,
    })
    _FIELD_NAMES.update({
        "consumed": "consumed_fraction", "amount": "stated_amount",
        "portion": "estimated_mass_g", "size": "package_size",
        "package": "package_size", "product": "canonical_name",
        "identity": "canonical_name", "brand": "product_line",
        "variant": "variant", "flavor": "variant",
        "preparation": "preparation", "serving": "serving_basis",
    })


_init_maps()


def _match_item(amb: Mapping, items):
    """Which staged item an ambiguity is about.

    The interpreter names the food; matching on that is how the answer later
    binds to one row. An unmatched ambiguity is DROPPED rather than applied to
    the first item — a question about the wrong food is worse than no question.
    """
    named = str(amb.get("item") or amb.get("food") or "").strip().lower()
    if named:
        for item in items:
            if named in item.original_text.lower() \
                    or item.original_text.lower() in named:
                return item
        return None
    return items[0] if len(items) == 1 else None


# ── the decision ──────────────────────────────────────────────────────────────
def derive_variant_ambiguity(items, spreads, data=None, *, mode: str,
                             targets=None):
    """Raise an ambiguity when THE SHELF disagrees more than the model does.

    The model reports what it feels unsure about, and it is confident about a
    product it can name — "Muscle Milk vanilla shake" reads as settled. The
    database says that name spans 48 to 385 calories per 100 g, because it
    covers both the powder and the ready-to-drink bottle. Measured across three
    modes it committed 230, 170 and 160: three real products, silently picked
    differently each time, with nothing anywhere reporting a doubt.

    So this is not a second opinion about the model's confidence — it is the
    one signal the model structurally cannot have, since it does not know which
    products share the words it just wrote. Whether the spread is worth a
    question is the same `is_material` call every other unknown goes through.

    `spreads` is `{item_text_lower: {nutrient: per-100g span}}`, fetched by the
    caller because the lookup is async and this is not.
    """
    from skills.nutrition.ambiguity import AmbiguityType, build_ambiguity

    if not spreads:
        return items
    # A staged item carries no macros — it is a description of what was said,
    # not a costed row. The calories live on the interpreter's raw item, keyed
    # by ordinal, exactly as `derive_vague_quantities` reads them. Without this
    # every span computed to zero and the deriver silently never fired.
    raw_by_ordinal = {}
    for ordinal, raw in enumerate((data or {}).get("items") or []):
        if isinstance(raw, Mapping):
            raw_by_ordinal[ordinal] = raw
    out = []
    for item in items or ():
        spread = spreads.get((item.original_text or "").strip().lower())
        if not spread:
            out.append(item)
            continue
        # The interpreter already flagged this identity — its options and its
        # numbers are better than anything derived here.
        if any(a.ambiguity_type.is_identity for a in item.ambiguities):
            out.append(item)
            continue
        calories = float(_calories_for(raw_by_ordinal.get(item.ordinal) or {}) or 0)
        ceiling = float(spread.get("_max_per100") or 0)
        span_cal = span_pro = None
        if calories > 0 and ceiling > 0:
            # Proportional: the shelf's per-100g spread, expressed against the
            # portion actually logged.
            span_cal = calories * (float(spread.get("calories") or 0) / ceiling)
            protein_100 = float(spread.get("protein") or 0)
            if protein_100:
                span_pro = calories * (protein_100 / ceiling)
        if not span_cal:
            out.append(item)
            continue
        amb = build_ambiguity(
            staged_item_id=item.staged_item_id,
            ambiguity_type=AmbiguityType.PRODUCT_LINE,
            field_name="variant", mode=mode,
            calorie_span=span_cal, protein_span=span_pro,
            item_calories=calories,
            targets=dict(targets) if targets else None, options=())
        if amb is None or not getattr(amb, "is_material", True):
            out.append(item)
            continue
        out.append(item.with_ambiguities(list(item.ambiguities) + [amb]))
    return tuple(out)


def identity_ask_enabled() -> bool:
    """The identity ask ships OFF, like every new ASK path before it.

    `FOOD_ANSWER_APPLY`, `FOOD_FAST_PATH` and `STRUCTURED_FOOD` all landed on
    main switched off and were promoted on measured behaviour. This one is not
    ready for that promotion: the question SHAPE is settled (a prior shortens
    it to a confirm) but the firing rule is not — it needs the shelf to tell a
    flavour from product-line boilerplate, and where the shelf is thin it still
    trades a silent assumption for a question nobody needs.

    Off, `derive_assumed_identity` is a no-op and the lane behaves exactly as
    it does today, so the work lands on main without changing a single turn.
    """
    return (os.getenv("FOOD_IDENTITY_ASK", "false") or "").strip().lower() \
        in ("true", "1", "yes", "on")


def derive_assumed_identity(items, *, message: str, mode: str,
                            targets=None, variant_rows=None,
                            regulars=None) -> tuple:
    """We named a product they did not name (production, 2026-07-30 20:14).

    The user wrote *"I just had a happy wolf bar"*. The reply was *"Happy Wolf
    chocolate chip bar, logged."* — a flavour nobody stated, taken from their
    most-logged prior, asserted as fact. No question, no stated assumption, and
    nothing recorded: the turn's `reasoning_json` held no ambiguity and no
    assumption at all. Happy Wolf carries four flavours; Arnie itself said so
    two minutes later when asked.

    That breaks the standing rule twice over — **a prior shortens the question,
    it never removes it**, and **an assumption is a statement, not a silence**.

    The signal is the gap between what they SAID and what we WROTE. If the
    interpreter's identity carries words the user's own message does not, we
    chose them. That is the identity twin of `derive_vague_quantities`: there,
    the user was vague about an amount and we were precise; here, they were
    vague about a product and we were precise.

    **Token difference, deliberately — no flavour vocabulary anywhere.** A list
    of flavour words would be an English list, would go stale against every
    brand, and is the per-language catalog the directive forbids. "Words they
    did not write" needs no vocabulary and works in every script.

    THE GATE IS PRIOR SHAPE × SHELF WIDTH, which is what decides ask versus
    state:

      shelf visibly wide (two or more real siblings) -> identity_risk 1.0, and
          the clarification policy asks, offering the siblings by name.
      shelf unseen -> a moderate risk that will not clear the ask threshold, so
          the leading option becomes a STATED assumption via `_assume_leading`
          and a tap corrects it. Silence is never the outcome.

    Only branded items. A generic food gaining a category word ("chicken" ->
    "chicken breast") is normalisation, not an invented product, and treating
    it as one would interrogate people about groceries.
    """
    if not identity_ask_enabled():
        return items
    from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                            build_ambiguity)
    from skills.nutrition.staging import FoodAssumption, FoodClass

    said = _tokens(message)
    if not said:
        return items

    out = []
    for item in items or ():
        if item.food_class is not FoodClass.BRANDED:
            out.append(item)
            continue
        # The interpreter already reported an identity doubt — its options and
        # its numbers are better than anything derived here.
        if any(a.ambiguity_type.is_identity for a in item.ambiguities):
            out.append(item)
            continue
        rows = list((variant_rows or {}).get(
            (item.original_text or "").strip().lower()) or ())
        # THE SHELF DECIDES WHICH WORDS ARE A CHOICE. Without it this cannot
        # run at all: "caramel cashew Barebells bar" logged as "...Protein
        # Bar" adds the word "protein", and asking which protein it was is an
        # interrogation about the product line. A word every sibling carries
        # is the line; a word only some carry is the choice — and only the
        # shelf knows which is which. No stopword list could: "protein" is
        # boilerplate on a bar and the whole point on a shake.
        if len(rows) < 2:
            out.append(item)
            continue
        shared = set.intersection(*[_tokens(r.get("name") or "") for r in rows])

        # What we wrote, minus what they wrote, minus the brand they named,
        # minus everything the whole shelf shares.
        wrote = _tokens(item.original_text) | _tokens(item.identity.variant) \
            | _tokens(item.identity.product_line)
        invented = wrote - said - _tokens(item.identity.brand) - shared
        if not invented:
            out.append(item)
            continue
        # WHAT ACTUALLY DISTINGUISHES THEM. Offering "Happy Wolf Strawberry
        # Bar" beside "chocolate chip" is a question written by a database.
        # Every word the siblings SHARE is the product line, not the choice, so
        # it comes out — leaving the flavour, in the shelf's own words.
        # The siblings, named. An option list is what lets the policy ask a
        # question someone can answer in one word — and what `_assume_leading`
        # turns into a stated assumption when it decides not to ask.
        assumed = " ".join(w for w in (item.original_text or "").split()
                           if _tokens(w) & invented) or "that one"
        options = [AmbiguityOption(assumed, confidence=0.6)]
        # IS THIS THEIR USUAL? A prior does not settle the identity, but it
        # does change the SHAPE of the question: "chocolate chip like usual?"
        # is one word to answer, where a four-way menu is a form to fill in.
        # The rule is that a prior SHORTENS the question, never removes it.
        usual = _matching_regular(invented, regulars)

        # ONE PRODUCT UNDER TWO LABELS IS NOT A CHOICE. Open Food Facts
        # carries the same bar as "Caramel Cashew bar" and "Protein Bar
        # Caramel Cashew"; offering both asks the user to pick between a thing
        # and itself, which is friction manufactured by the pipeline rather
        # than by the food — the rule `collapse_candidates` already keeps for
        # scored candidates, applied here to names.
        seen_keys = {frozenset(invented)}
        for row in rows:
            label = _distinctive(str((row or {}).get("name") or ""), shared)
            key = frozenset(_tokens(label))
            if not label or not key or key in seen_keys:
                continue
            seen_keys.add(key)
            options.append(AmbiguityOption(label, confidence=0.2))
            if len(options) >= 4:
                break
        # Width measured on what is genuinely DISTINCT, not on row count. A
        # shelf that collapses to the one product we assumed does not disagree
        # with us, so it earns a stated assumption rather than a question.
        shelf_is_wide = len(options) >= 2
        named = [o.label for o in options[1:]]
        if usual:
            # A CONFIRM, not a menu. It still names that alternatives exist —
            # "the chocolate chip I usually have vs. one of their other
            # flavors" is the question that was owed, and a bare "chocolate
            # chip?" invites a yes to a fact nobody checked.
            prompt = f"{_lead(assumed)} like usual, or a different one?"
        elif named:
            prompt = f"Which one was it — {_or_list([assumed] + named)}?"
        else:
            prompt = ""
        amb = build_ambiguity(
            staged_item_id=item.staged_item_id,
            ambiguity_type=AmbiguityType.PRODUCT_VARIANT,
            field_name="variant", mode=mode,
            # Identity risk short-circuits materiality by design: choosing the
            # wrong flavour of a 110-calorie bar can cost nothing in calories
            # and still be the wrong product on their log. A prior earns the
            # question a cheaper SHAPE, never an exemption from being asked.
            identity_risk=(1.0 if (shelf_is_wide or usual) else 0.6),
            item_calories=None,
            targets=dict(targets) if targets else None,
            options=tuple(options),
            prompt=prompt)
        item = item.with_ambiguities(list(item.ambiguities) + [amb])

        # ── THE FLOOR: A CHOSEN IDENTITY IS ALWAYS STATED ──────────────────
        #
        # Attached to the ITEM, not left to the policy. `_assume_leading` only
        # runs on ambiguities the policy judged MATERIAL, so an identity we
        # invented but did not consider worth a question produced silence —
        # which is the production defect exactly. `decide()` collects
        # `item.assumptions` unconditionally, so this survives every branch.
        #
        # Composer input, not user-facing copy: the reply is written by the
        # composer under the [REPLY LANGUAGE] pin, so this reaches a Russian
        # user in Russian. (The assumption-text surface as a whole predates
        # this and is English throughout — see `_assume_leading` — and wants
        # the same language pass.)
        out.append(item.with_assumption(FoodAssumption(
            staged_item_id=item.staged_item_id, field_name="variant",
            assumed_value=assumed, alternatives=tuple(named),
            confidence=(0.5 if shelf_is_wide else 0.7),
            user_visible_text=(f"Went with the {assumed} — say the word if it "
                               f"was a different one."))))
    return tuple(out)


def _matching_regular(invented: set, regulars) -> Optional[str]:
    """The regular whose name contains every word we invented, if any.

    That containment is what makes it THEIR usual rather than a coincidence:
    we wrote "chocolate chip", and a regular called "Happy Wolf chocolate chip
    bar" accounts for both words. A regular sharing one word does not.
    """
    if not invented:
        return None
    for regular in (regulars or ()):
        if not isinstance(regular, Mapping):
            continue
        name = str(regular.get("name") or regular.get("food") or "")
        if name and invented <= _tokens(name):
            return name
    return None


def _lead(text: str) -> str:
    """Sentence-leading form, without touching the middle of a brand name."""
    text = (text or "").strip()
    return (text[:1].upper() + text[1:]) if text else text


def _distinctive(label: str, shared: set) -> str:
    """A sibling's name with the words every sibling shares removed.

    "Happy Wolf Strawberry Bar" against a shelf that is all Happy Wolf bars is
    "Strawberry". Falls back to the full label when removing the shared words
    would leave nothing — a product whose only distinguishing feature is one we
    cannot see is better offered whole than offered blank.
    """
    kept = [w for w in (label or "").split() if not (_tokens(w) <= shared)]
    return " ".join(kept).strip() or (label or "").strip()


def _or_list(labels) -> str:
    """"a, b or c" from real product names. Joins data; invents no words."""
    labels = [str(x).strip() for x in labels if str(x).strip()]
    if len(labels) < 2:
        return labels[0] if labels else ""
    return ", ".join(labels[:-1]) + f" or {labels[-1]}"


def derive_semantics(items, data: Mapping, *, message: str = "",
                     mode: str = "moderate", targets=None,
                     variant_spreads=None, variant_rows=None, regulars=None,
                     preferences=None, now=None):
    """Staged items → items that know what is UNRESOLVED about them.

    Extracted so both ask origins can produce the same evidence. `food_turn`
    has two, and they are not variants of one thing:

        the model proposed the ask   ("I had some chicken breast")
        the system overrode a log    (model said log; policy held it)

    Only the second ran this, because the pipeline is gated on a log op. So a
    turn where the MODEL noticed the uncertainty never acquired staged items,
    ambiguities, or anything else the canonical layer reads — measured on
    2026-08-05, when the B-1 canonical example itself took that path and the
    canonical predicate was never consulted, not even to decline.

    ONE function, so the two origins cannot drift into two definitions of
    "what is unresolved here". That drift is the whole reason there are four
    clarification producers to collapse.

    Every step is order-dependent and the order is `plan_turn`'s: what the
    model reported, then what it could not notice (invented precision), then
    what it cannot know (which product), then what WE introduced, then the
    user's own preferences.
    """
    items = attach_ambiguities(items, data, mode=mode, targets=targets)
    # The interpreter reports what IT noticed uncertain. It does not notice
    # having invented precision — "a scoop" arriving as "1 tbsp" looks like an
    # answer from where it stands. Derived from the user's own words, so the
    # review turn can disclose it as ours.
    items = derive_vague_quantities(items, data, message=message, mode=mode,
                                    targets=targets)
    # ...and the doubt the model cannot have: which of the products sharing
    # this name it actually was. Fetched by the caller — absent when the
    # caller did not pay for it, which is why `identity_evidence_fetched`
    # below exists.
    items = derive_variant_ambiguity(items, variant_spreads, data, mode=mode,
                                     targets=targets)
    # ...and the doubt we CREATED: a product specifier in our output that is
    # nowhere in their message. Derived from the two strings alone, so it
    # costs nothing and needs no vocabulary.
    items = derive_assumed_identity(items, message=message, mode=mode,
                                    targets=targets, variant_rows=variant_rows,
                                    regulars=regulars)
    return apply_preferences(items, preferences, now=now, mode=mode)


def identity_evidence_fetched(data: Mapping, variant_spreads) -> bool:
    """Did this turn PAY for the lookups that reveal a product-variant doubt?

    `derive_variant_ambiguity` can only find a variant question when the
    caller fetched the shelf. Absent that fetch, a branded item comes back
    looking unambiguous — which is indistinguishable from genuinely being so,
    and is exactly the kind of "we did not look" that must never read as "we
    know". A caller that skipped the fetch must treat every branded item as
    unverified rather than clear.

    Non-branded items need no fetch: `_variant_spreads` filters to branded and
    packaged names in the first place, so "chicken breast" is fully judged
    without one.
    """
    branded = [raw for raw in (data.get("items") or [])
               if isinstance(raw, Mapping)
               and (raw.get("branded") or raw.get("is_packaged"))]
    return not branded or bool(variant_spreads)


def plan_turn(data: Mapping, *, turn_id: str, message: str = "",
              mode: str = "moderate", round_number: int = 0,
              preferences=None, now: Optional[datetime] = None,
              targets: Optional[Mapping] = None,
              variant_spreads: Optional[Mapping] = None,
              item_candidates: Optional[Mapping] = None,
              variant_rows: Optional[Mapping] = None,
              regulars: Optional[Any] = None
              ) -> Optional[FoodTurnDecision]:
    """The whole pre-execution decision. Returns None on any failure, so the
    caller keeps its existing behaviour rather than losing the turn."""
    from core import food_trace
    from core.food_trace import Outcome, Stage

    try:
        from skills.nutrition.clarify_policy import decide
        from skills.nutrition.clarify_ui import build_traces

        with food_trace.stage(Stage.STAGE) as staging:
            items, meal_group_id = stage_items(data, turn_id=turn_id,
                                               message=message, mode=mode)
            # Staging work, not clarification work: this is the item learning
            # WHAT IT MIGHT BE, from rows the caller already paid for. It runs
            # before every deriver so an ambiguity, a question and the stored
            # resolution all describe the same product set.
            items = attach_candidates(items, item_candidates)
            staging.counts["items"] = len(items)
            staging.counts["candidates"] = sum(
                len(i.candidate_products or ()) for i in items)
            if not items:
                staging.outcome = Outcome.SKIPPED
        if not items:
            return None
        with food_trace.stage(Stage.CLARIFY) as clarifying:
            items = derive_semantics(
                items, data, message=message, mode=mode, targets=targets,
                variant_spreads=variant_spreads, variant_rows=variant_rows,
                regulars=regulars, preferences=preferences, now=now)
            decision = decide(list(items), mode=mode,
                              round_number=round_number)
            approved = _approved_operations(data, items, decision)
            clarifying.counts.update(
                ready=len(decision.ready_item_ids or ()),
                held=len(decision.held_item_ids or ()),
                questions=len(decision.questions or ()),
                assumptions=len(decision.assumptions or ()))
            # Where the turn stopped, from the clarifier's own point of view.
            # ASKED and HELD are different outcomes and the funnel needs both:
            # a question is a turn the user can finish, a hold is one they
            # cannot see a way to.
            if decision.questions:
                clarifying.outcome = Outcome.ASKED
            elif not approved and items:
                clarifying.outcome = Outcome.HELD

        traces = build_traces(items, decision=decision, mode=mode,
                              turn_id=turn_id)
        for trace in traces:
            logger.info(trace.log_line())

        # `items_ready`, not `items_committed`: this is the clarifier's approval
        # to write, recorded before the executor has written anything. A blocked
        # or failed write used to surface here as a commit. The executor sets the
        # committed and failed counts once it knows them (core/conversation.py).
        food_trace.note(
            meal_group_id=meal_group_id, mode=mode,
            items_staged=len(items),
            items_ready=len(decision.ready_item_ids or ()),
            items_held=len(decision.held_item_ids or ()),
            questions_asked=len(decision.questions or ()),
            assumptions_made=len(decision.assumptions or ()))

        return FoodTurnDecision(staged_items=items, clarification=decision,
                                approved_operations=approved,
                                meal_group_id=meal_group_id, traces=traces)
    except Exception as e:
        logger.warning(f"food pipeline skipped, legacy policy: {e}")
        food_trace.note(error=f"pipeline:{type(e).__name__}")
        return None


def apply_preferences(items, preferences, *, now=None, mode="moderate") -> tuple:
    """Fill identity gaps from what this user has confirmed before.

    A learned default is applied as an ASSUMPTION, never silently: the item
    records what was assumed and what the alternatives were, so a correction
    has something to contradict.
    """
    if not preferences:
        return items
    try:
        from skills.nutrition.preferences import (normalize_term,
                                                  resolve_from_preference)
        from skills.nutrition.staging import FoodAssumption
    except Exception:
        return items

    now = now or datetime.utcnow()
    by_term = {}
    for pref in preferences:
        by_term[normalize_term(getattr(pref, "trigger_term", ""))] = pref

    out = []
    for item in items:
        pref = by_term.get(normalize_term(item.original_text))
        fields = resolve_from_preference(pref, now=now, mode=mode) if pref else {}
        if not fields:
            out.append(item)
            continue
        resolved = item.resolving(**fields)
        out.append(resolved.with_assumption(FoodAssumption(
            staged_item_id=item.staged_item_id,
            field_name=next(iter(fields)), assumed_value=next(iter(fields.values())),
            confidence=getattr(pref, "confidence", 0.5),
            user_visible_text=(f"Went with your usual "
                               f"{pref.describe()} for the "
                               f"{item.original_text}."))))
    return tuple(out)


def _approved_operations(data: Mapping, items, decision) -> tuple:
    """The interpreter's calls, filtered to items the policy cleared.

    Filtered, not rebuilt: the call construction (units, ids, provenance,
    board binding) is already correct and re-deriving it here would be a second
    implementation to keep in step. What this adds is the veto.

    **This is not where the veto is enforced.** `data["_calls"]` is populated by
    the transcript fixtures and by the coordinator's food stage; the live turn
    reaches here with the interpreter's raw JSON, which has no `_calls` at all,
    so this returns empty and reports nothing about what was allowed. That gap
    is why the enforcement lives in `core.food_turn._apply_clarification_veto`,
    against the calls as actually constructed. What this function is for is the
    callers that DO hold their calls at decision time — for them it is the
    filter, and for everyone else it is a report.
    """
    ready = set(decision.ready_item_ids or ())
    if not ready:
        return ()
    ready_texts = {i.original_text.lower() for i in items
                   if i.staged_item_id in ready}
    approved = []
    for call in (data.get("_calls") or ()):
        name = str(((call or {}).get("input") or {}).get("food_name")
                   or "").strip().lower()
        if not name or name in ready_texts \
                or any(name in t or t in name for t in ready_texts):
            approved.append(call)
    return tuple(approved)


# ── after execution ───────────────────────────────────────────────────────────
# ── derived ambiguity: the user was vague and we were precise ────────────────
#: Measures a user says when they do not know the amount. Each maps to the
#: portion ontology's measure name, so the plausible range comes from the
#: ontology rather than from a second table here.
VAGUE_MEASURES = {
    "scoop": "scoop", "scoops": "scoop", "spoonful": "spoonful",
    "spoonfuls": "spoonful", "spoon": "spoonful", "handful": "handful",
    "handfuls": "handful", "drizzle": "drizzle", "splash": "drizzle",
    "dollop": "spoonful", "glug": "drizzle", "bit": "little",
    "little": "little", "some": "some", "few": "some", "couple": "some",
    "bowl": "bowl", "plate": "plate", "bite": "bite", "bites": "bite",
    "chunk": "some", "piece": "some", "smear": "spoonful",
}

#: The plausible range has to span at least this ratio before the vagueness is
#: worth a turn. A measure whose upper bound is under 1.6x its lower bound is
#: vague in wording and precise enough in fact.
VAGUE_SPREAD_RATIO = 1.6


_CLAUSE_SPLIT_RE = re.compile(r"\s*(?:,|\band\b|\bwith\b|\bplus\b|\+)\s*",
                              re.I)
_CLAUSE_STOPWORDS = frozenset({
    "a", "an", "the", "of", "some", "like", "had", "i", "my", "was", "were",
    "also", "just", "about", "and", "with", "for", "on", "in", "it", "that",
})


def _tokens(text: str) -> set:
    r"""Words, in any script.

    This was `[a-z0-9&]+` — ASCII letters only — so every Cyrillic, Greek,
    Hebrew, Arabic or CJK message tokenised to the EMPTY SET and every rule
    built on token overlap silently did nothing. `derive_assumed_identity`
    compares what the user wrote against what we wrote, so an empty set meant
    a Russian user could never be told we had chosen their product's flavour.
    Caught by running the rule in Russian, not by reading it: the identical
    blindspot was fixed in `reply_language_block` hours earlier, and it grew
    back in new code the same day.

    `\w` under Python 3's default unicode semantics takes every script, and
    ASCII behaviour is unchanged.
    """
    return {w for w in re.findall(r"\w+", (text or "").lower())
            if w not in _CLAUSE_STOPWORDS}


def _vague_measure_in(message: str, food: str) -> Optional[str]:
    """The vague measure the user used for THIS food, if any.

    Matched inside the CLAUSE that names the food, not anywhere in the message.
    "a scoop of peanut butter and 200g of chicken" contains "scoop", and
    attaching it to the chicken would ask about a portion the user stated
    exactly.

    Clause selection is by token overlap rather than by position, because
    position gets "peanut butter" wrong the moment the message also mentions
    "peanut M&Ms" — the first "peanut" belongs to the other food.
    """
    if not message or not food:
        return None
    food_tokens = _tokens(food)
    if not food_tokens:
        return None

    best, best_score = None, 0.0
    for clause in _CLAUSE_SPLIT_RE.split(message):
        clause_tokens = _tokens(clause)
        if not clause_tokens:
            continue
        overlap = food_tokens & clause_tokens
        if not overlap:
            continue
        score = len(overlap) / len(food_tokens | clause_tokens)
        if score > best_score:
            best, best_score = clause, score

    if best is None:
        return None
    for word, measure in VAGUE_MEASURES.items():
        if re.search(rf"\b{re.escape(word)}\b", best.lower()):
            return measure
    return None


def derive_vague_quantities(items, data: Mapping, *, message: str,
                            mode: str, targets: Optional[Mapping] = None
                            ) -> tuple:
    """Add an ambiguity where the USER was vague and the interpreter was not.

    The failure this exists for, from a shipped transcript: the user said "a
    scoop of peanut butter" and the review turn said "1 tbsp Peanut Butter",
    then asked "Does that look right?". A scoop of peanut butter is plausibly
    one tablespoon or three, a span of roughly 190 calories, and the user was
    invited to approve it without ever being shown that a number had been
    chosen for them.

    The interpreter reports ambiguities it noticed. It did not notice this one,
    because from its point of view it produced an answer. So the ambiguity is
    DERIVED here from two facts we already have: the user's own words, and the
    portion ontology's plausible range for the measure they used.
    """
    from skills.nutrition.ambiguity import (AmbiguityOption, AmbiguityType,
                                            build_ambiguity)
    from skills.nutrition.portions import distribution_for

    # IS THIS REALLY THE ONLY THING WE ARE UNSURE ABOUT? The prompt below said
    # so unconditionally, and it was routinely false: "had a Barebells bar and
    # some chicken and rice" listed "One cup of white rice" — a cup nobody
    # said — and then claimed the chicken was the only open question. A
    # sentence asserting certainty one line under our own guess is the worst
    # kind of wrong, because it tells the user not to look.
    _sole_estimate = sum(
        1 for i in (items or []) if not getattr(
            getattr(i, "quantity", None), "is_stated", False)) <= 1

    raw_by_ordinal = {}
    for ordinal, raw in enumerate(data.get("items") or []):
        if isinstance(raw, Mapping):
            raw_by_ordinal[ordinal] = raw

    out = []
    for item in items or ():
        # THE ITEM REMEMBERS, the message does not. Recorded when the item was
        # staged, so a meal clarified over several turns keeps the vagueness of
        # every food — not just the ones the latest message happens to name.
        # Falls back to re-derivation for items staged before this was carried.
        measure = (getattr(item, "vague_measure", "")
                   or _vague_measure_in(message, item.original_text))
        # A stated amount is the user's own number and is never second-guessed.
        if not measure or item.quantity.is_stated:
            out.append(item)
            continue
        # An ambiguity the interpreter already reported for this field wins —
        # it has the better options and the real impact numbers.
        if any(a.ambiguity_type is AmbiguityType.CONSUMED_QUANTITY
               for a in item.ambiguities):
            out.append(item)
            continue

        # Only when our unit DIFFERS from the user's word. "a plate of turkey"
        # arriving as 1 plate is vague but not CONVERTED — the vagueness is
        # inherent to the measure and the portion ontology discloses it. "a
        # scoop" arriving as 1 tbsp is a different measure than the one they
        # used, which is the silent conversion this exists to surface.
        our_unit = (item.quantity.inferred_unit or "").strip().lower()
        if our_unit and VAGUE_MEASURES.get(our_unit.rstrip("s")) == measure:
            out.append(item)
            continue

        distribution = distribution_for(measure, item.original_text)
        if distribution is None or not distribution.lower_g:
            out.append(item)
            continue
        if distribution.upper_g / max(distribution.lower_g, 1e-6) < \
                VAGUE_SPREAD_RATIO:
            out.append(item)
            continue

        calories = _calories_for(raw_by_ordinal.get(item.ordinal) or {})
        span = _span_from(distribution, calories)
        # Unequal confidences, deliberately. Equal ones read as a coin toss to
        # the clarification policy, which makes QUICK mode ask — and quick
        # exists precisely to accept this risk and commit with a stated
        # assumption instead.
        #
        # WHICH option carries the top confidence is the part that moves food.
        # The labels arrive ascending, so a positional `(0.6, 0.35, 0.2)` gave
        # the LOW end the most confidence and QUICK mode assumed the smallest
        # portion on offer — against the standing rule to bias high when unsure.
        # Assigned by role now: the median is the ontology's best estimate and
        # wins; the high end outranks the low one.
        labels = _measure_options(measure, distribution, item.original_text)
        weights = ((0.2, 0.6, 0.35) if len(labels) == 3 else (0.6, 0.35))
        options = tuple(
            AmbiguityOption(label, confidence=confidence)
            for label, confidence in zip(labels, weights))

        out.append(item.with_ambiguities(list(item.ambiguities) + [
            build_ambiguity(
                staged_item_id=item.staged_item_id,
                ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
                field_name="consumed_fraction", mode=mode,
                calorie_span=span, item_calories=calories, options=options,
                targets=dict(targets) if targets else None,
                confidence=getattr(distribution, "confidence", None),
                prompt=_vague_prompt(item.original_text, measure, labels,
                                     sole_estimate=_sole_estimate))]))
    return tuple(out)


def _vague_prompt(food: str, measure: str, options,
                  sole_estimate: bool = True) -> str:
    """Name what is uncertain, then ask about it.

    Two sentences rather than one long one. The lead says which food the
    question is about, so the ask itself can stay short and can use the user's
    own measure — "was the scoop closer to one or two tablespoons" reads like a
    person asking, where "was the peanut butter scoop closer to one tablespoon
    or two tablespoons" reads like a form validating a field.

    The lead is also the part that keeps the question bindable in a three-food
    meal: without it, "the scoop" could be any of them.
    """
    low, high = options[0], options[-1]
    food = (food or "").strip()
    # A HEDGE IS NOT A MEASURE. "Was the some closer to 30g or 200g?" is the
    # same defect as "One some of mustard" one layer over: the interpreter
    # hands back a hedge in the unit slot and every rule downstream treats a
    # unit as a noun to put an article in front of.
    lead = ("How much" if measure in _HEDGE_MEASURES
            else f"Was the {measure} closer")
    tail = (f" — closer to {_shared_unit(low, high)}?"
            if measure in _HEDGE_MEASURES
            else f" to {_shared_unit(low, high)}?")
    if not food:
        return f"{lead}{tail}"
    ask = (f"{lead} of the {food.lower()}{tail}"
           if measure in _HEDGE_MEASURES else f"{lead}{tail}")
    if sole_estimate:
        return f"The {food.lower()} is the only part I'm unsure about. {ask}"
    # Other amounts on this meal are ours too. Naming that is what earns the
    # question — the user is being asked about the one that moves the most,
    # not told the rest are settled.
    return f"I picked the other amounts myself. {ask}"


#: Words the interpreter puts in the unit slot that measure nothing. They can
#: never take "the ... closer to", which is a frame for a real measure.
_HEDGE_MEASURES = frozenset({"some", "a little", "little", "a bit", "bit",
                             "lots", "plenty", "a few", "few"})


def _shared_unit(low: str, high: str) -> str:
    """"one tablespoon" + "two tablespoons" → "one or two tablespoons".

    Saying the unit twice is the tell of generated text. Only collapses when
    the two options really do share a unit — "one tablespoon or half a cup"
    must keep both.
    """
    lo, hi = (low or "").split(), (high or "").split()
    # Exactly "<amount> <unit>" on the low side. Anything longer carries an
    # article or a qualifier that does not survive having its noun removed:
    # "half a cup" would collapse to "half a or one cup".
    # An article is not an amount: "a scoop" would collapse to "a or two
    # scoops", which reads as a typo rather than a choice.
    if len(lo) == 2 and len(hi) >= 2 and lo[0].lower() not in ("a", "an"):
        lo_unit, hi_unit = lo[-1], hi[-1]
        # Same unit, differing only by plural — the common case (tablespoon /
        # tablespoons), and the only one where dropping the first is lossless.
        if hi_unit in (lo_unit, f"{lo_unit}s") or lo_unit == f"{hi_unit}s":
            return f"{lo[0]} or {high}"
    return f"{low} or {high}"


def _calories_for(raw: Mapping) -> Optional[float]:
    for key in ("calories", "cal", "kcal"):
        value = raw.get(key)
        if isinstance(value, (int, float)) and value > 0:
            return float(value)
    return None


def _span_from(distribution, calories: Optional[float]) -> float:
    """What being wrong about this measure would cost, in calories.

    With the item's own calories we can scale the mass range directly. Without
    them the span is reported as the mass spread, which is the right ORDER of
    magnitude for a food at roughly 4 cal/g and is honest about being an
    estimate — a zero here would rank the vaguest portions as the least worth
    asking about.
    """
    spread = max(0.0, distribution.upper_g - distribution.lower_g)
    if calories and distribution.median_g:
        per_gram = calories / distribution.median_g
        return round(spread * per_gram, 1)
    return round(spread * 4.0, 1)


#: Grams per tablespoon, for the measures people answer in spoons.
_G_PER_TBSP = 15.0

_SPOKEN = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}


#: The unit a person can PICTURE, per portion-ontology category.
#:
#: Grams are what we PRICE in and what almost nobody SERVES in. "Closer to 60g
#: or 220g?" asks someone to convert before they can answer, and the answer is
#: not cheap to get wrong: a tapped option is recorded as the user's own figure
#: (`_item_is_stated` clears `estimated`, so the "(my estimate)" marker, the
#: card range and the disclosure all switch off). An option nobody can evaluate
#: therefore does not merely annoy — it launders a guess into ground truth.
#:
#: This table chooses only the WORDS. Every number behind them stays the
#: ontology's: each candidate is rendered, re-parsed through the same
#: `normalize_quantity` the log path uses, and kept only if it lands nearer its
#: own anchor than any other anchor. A rendering that does not survive that
#: round trip is dropped and the row falls back to grams, so no vocabulary here
#: can put a mass on the board that pricing would not have chosen itself.
_EVERYDAY_UNIT = {
    # Sold and portioned by weight at a counter, and the unit a US kitchen
    # scale and every recipe already speaks for these.
    "meat": "oz", "deli_meat": "oz", "bacon": "oz", "cheese": "oz",
    "nuts": "oz", "chips": "oz", "dried_fruit": "oz",
    # Served out of a measuring cup, a mug or a bowl.
    "rice": "cup", "pasta": "cup", "cereal": "cup", "soup": "cup",
    "berries": "cup", "greens": "cup", "leafy": "cup", "salad": "cup",
    "popcorn": "cup", "yogurt": "cup", "ice_cream": "cup",
}

#: Renderings offered per everyday unit, smallest first. Plain ASCII fractions
#: because that is what `normalize_quantity` parses; the round trip below is
#: what actually proves each one, so this list may be extended freely.
_UNIT_RENDERINGS = {
    "oz": ("1 oz", "2 oz", "3 oz", "4 oz", "5 oz", "6 oz", "8 oz",
           "10 oz", "12 oz", "16 oz"),
    "cup": ("1/4 cup", "1/3 cup", "1/2 cup", "2/3 cup", "3/4 cup", "1 cup",
            "1 1/4 cups", "1 1/2 cups", "2 cups", "2 1/2 cups", "3 cups"),
}


def _count_labels(distribution, food: str) -> tuple:
    """A countable food's bracket said as COUNTS of itself.

    The anchor-matching in `_everyday_labels` is the wrong instrument here.
    A burger's bracket is 169.5-565 g and none of those numbers is a whole
    burger; what a person can answer is "one or two". So the counts spanning
    the bracket are offered directly, named with the table's own singular key
    rather than the user's wording — "1 potatoes" is not a chip anyone taps.

    Nothing is invented: the count times the piece weight IS the bracket the
    ontology produced, and each label is re-parsed by the log path's own
    parser, so a label that would not price is never offered.
    """
    from skills.nutrition.normalize import (normalize_quantity, piece_key,
                                            piece_weight)
    from skills.nutrition.portions import Specificity
    # ONLY when the ontology itself decided this food is counted. Reading the
    # piece table directly instead offered "4 friess" and "8 chips" — foods
    # that HAVE a piece weight precisely because the piece is a sub-unit, which
    # is why `_piece_distribution` refuses them. The tier is the decision; this
    # only renders it.
    if getattr(distribution, "specificity", None) is not Specificity.PIECE:
        return ()
    noun = piece_key(food)
    weighed = piece_weight(food)
    if not noun or not weighed or not weighed[0]:
        return ()
    per = float(weighed[0])
    lo = max(1, int(round(distribution.lower_g / per)))
    hi = max(lo, int(round(distribution.upper_g / per)))
    out = []
    for n in range(lo, min(hi, lo + 3) + 1):
        label = f"{n} {noun if n == 1 else _plural(noun)}"
        try:
            if normalize_quantity(label, food).grams:
                out.append(label)
        except Exception:
            return ()
    return tuple(out) if len(out) >= 2 else ()


def _plural(noun: str) -> str:
    """English plural for a table key. Small because the keys are ordinary
    concrete nouns — but not `+ "s"`, which wrote "potatos" and "friess" onto
    chips the user is meant to tap."""
    if re.search(r"(?:s|x|z|ch|sh)$", noun):
        return noun + "es"
    if re.search(r"[^aeiou]o$", noun):
        return noun + "es"              # potato -> potatoes
    if re.search(r"[^aeiou]y$", noun):
        return noun[:-1] + "ies"        # berry -> berries
    return noun + "s"


def _everyday_labels(anchors: tuple, food: str) -> tuple:
    """`anchors` (ascending grams) said in a unit the user serves food in.

    Returns one label per anchor, or `()` when this food has no everyday unit,
    when a rendering will not parse, or when two anchors would land on the same
    words. The acceptance test is entirely derived — a label is kept only if its
    re-parsed mass is closer to its OWN anchor than to any neighbouring one, so
    there is no tolerance constant to tune and no way for a label to silently
    stand in for a portion the user did not mean.
    """
    from skills.nutrition.normalize import normalize_quantity
    from skills.nutrition.portions import food_category
    unit = _EVERYDAY_UNIT.get(food_category(food or ""))
    if not unit:
        return ()
    priced = []
    for label in _UNIT_RENDERINGS[unit]:
        try:
            grams = normalize_quantity(label, food).grams
        except Exception:
            grams = None
        if grams:
            priced.append((label, float(grams)))
    if not priced:
        return ()

    out = []
    for anchor in anchors:
        label, grams = min(priced, key=lambda lg: abs(lg[1] - anchor))
        # The whole acceptance rule: this rendering must be a better answer for
        # the anchor it was picked for than for any other anchor on the row.
        # A "4 oz" that is really nearer the high end is not a middle option.
        if min(anchors, key=lambda a: abs(grams - a)) != anchor:
            return ()
        out.append(label)
    return tuple(out) if len(set(out)) == len(out) else ()


def _measure_options(measure: str, distribution, food: str = "") -> tuple:
    """The plausible range, in the words the measure invites.

    Three points, not two. The low and high ends bound the question; the MIDDLE
    is the ontology's own median — the single most likely portion — and it was
    absent for as long as this function existed. Its slot was not: the caller
    has always zipped these labels against `(0.6, 0.35, 0.2)`, and the third
    confidence has been dead since it was written. Offering only the ends meant
    every tap logged a 10th- or 90th-percentile portion while the best answer
    available was never on screen.

    Spoons get spoons, and everything with an everyday unit gets that unit
    (`_everyday_labels`) — "was it closer to 2 or 8 oz?" is a question someone
    can answer from memory, and "closer to 60g or 220g?" is one they have to
    convert first, which is the difference between a clarification and a chore.
    Grams remain the fallback, and remain what all of this is measured in.
    """
    if measure in ("spoonful", "scoop", "drizzle") and \
            distribution.upper_g <= 80:
        low = max(1, int(round(distribution.lower_g / _G_PER_TBSP)))
        high = max(low + 1, int(round(distribution.upper_g / _G_PER_TBSP)))
        return (f"{_SPOKEN.get(low, low)} tablespoon"
                + ("" if low == 1 else "s"),
                f"{_SPOKEN.get(high, high)} tablespoons")
    # A food that comes in pieces is answered in pieces, before any other
    # rendering is considered. `distribution_for`'s piece tier already decided
    # this food is counted rather than measured; saying it in grams or ounces
    # would ask the user to weigh something they can simply count.
    _counted = _count_labels(distribution, food)
    if _counted:
        return _counted
    anchors = (distribution.lower_g, distribution.median_g,
               distribution.upper_g)
    if not (anchors[0] < anchors[1] < anchors[2]):
        # A median sitting on an end offers no third choice; keep the ends.
        return (f"{_g(distribution.lower_g)}", f"{_g(distribution.upper_g)}")
    return _everyday_labels(anchors, food) or (
        f"{_g(anchors[0])}", f"{_g(anchors[1])}", f"{_g(anchors[2])}")


def _g(grams: float) -> str:
    return f"{int(round(grams))}g"
