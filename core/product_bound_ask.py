"""⭐ P17-UA slice C / CF9 — A BOUND REFUSAL BECOMES AN ASK THAT HOLDS THE SNAPSHOT.

    scan 70004199 -> "2 bars"
        -> BoundUnpriceable (the label names no bar)
        -> THIS: open a canonical quantity operation whose stored item CARRIES
           the snapshot id, and ask in the label's terms:
               "The label gives nutrition per 55 g serving. Is each bar one
                55 g serving?"   [2 servings (110 g)]  [1 serving (55 g)]  free text
        -> the answer — a tap, "2 servings", "110 g" — settles the SAME bound
           snapshot canonically: no reacquisition, no MEMORY, no legacy.

Danny's hierarchy, source 4: the user's confirmation authorises the quantity
FOR THIS CONSUMPTION. Choosing "2 servings (110 g)" is the user STATING the
quantity in the label's own unit — precedence class 1 — so the settle prices
from the panel's own serving conversion. Nothing here translates bar into
serving on the user's behalf: the option says what it is, and the user picks.

Built on B-1's machinery, not beside it: the same `open_operation`, the same
`quantity_field` / `build_interaction`, the same `b1_answer_turn` answer path,
the same `settle`. The one new fact is `product_evidence_id` on the stored
item, which `assemble(bound=True)` reads. Reachable ONLY from a
BoundUnpriceable in the native stage.

⚠ NOT (yet) persisted as `user_confirmed` unit evidence: that refinement needs
the confirmation keyed to the operation before the entry exists (a
`produnit002` column) and its own answer semantics; the row's receipt still
names the snapshot and the panel conversion. Registered on the board.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)


def _label_options(*, field, serving_grams: float, unit: str,
                   stated_count: Optional[float]) -> tuple:
    """Options in the label's OWN terms. The user's stated count first (so
    "2 bars" is offered as "2 servings (110 g)"), then one serving. Every
    option is a MASS the label states — a user-stated exact quantity once
    chosen — never a bar->serving equivalence asserted by us."""
    from core.semantics import (CandidateSource, CanonicalQuantity,
                                ClarificationOption, Confidence, Dimension,
                                Provenance, SetQuantity)

    counts = []
    if stated_count and float(stated_count) > 0 and float(stated_count) != 1.0:
        counts.append(float(stated_count))
    counts.append(1.0)
    options = []
    for n in counts:
        grams = Decimal(str(serving_grams)) * Decimal(str(n))
        n_txt = (str(int(n)) if float(n).is_integer() else f"{n:g}")
        plural = "serving" if n == 1.0 else "servings"
        # The label is what a user would TYPE BACK on a text channel — the
        # answer path matches an offered label exactly — so it is the label's
        # own words ("2 servings"); the mass rides in the patch and the
        # introduction already states the serving size.
        label = f"{n_txt} {plural}"
        # THE SEMANTIC OBJECT IS THE PATCH, NOT THE LABEL: quantity = n x
        # unit "serving" (a COUNT of the label's own unit). The settle path
        # resolves it through the panel's serving conversion — sourced,
        # deterministic — so the row reads "2 servings", resolved_grams 110,
        # conversion off:<code>. `grams` rides as the derived mass for the
        # wire/receipt; the count is what was chosen.
        q = CanonicalQuantity(
            amount=Decimal(str(n)), unit_id="serving", dimension=Dimension.COUNT,
            count=Decimal(str(n)), grams=grams,
            provenance=Provenance.USER_SELECTED,
            confidence=Confidence(score=1.0, basis=f"label serving x {n_txt}"))
        options.append(ClarificationOption(
            label=label, option_id=f"opt_label_serving_{n_txt}",
            field_id=field.field_id,
            patch=SetQuantity(event_id=field.event_id, field_id=field.field_id,
                              quantity=q, provenance=Provenance.USER_SELECTED),
            source=CandidateSource.ONTOLOGY))
    return tuple(options)


def _question(*, food: str, unit_word: str, serving_grams: float,
              stated_quantity: str) -> str:
    g = f"{serving_grams:g}"
    if unit_word:
        return (f"Got the scanned {food}. The label gives nutrition per {g} g "
                f"serving — is each {unit_word} one {g} g serving?")
    return (f"Got the scanned {food}. The label gives nutrition per {g} g "
            f"serving, and I can't price {stated_quantity} from it — how many "
            f"servings, or how many grams?")


async def open_bound_quantity_ask(db, *, user, item: dict, coverage,
                                  turn_id: str, channel: str,
                                  locale: str = "en"):
    """Open the ask. Returns a `CanonicalAsk` (durable operation persisted,
    snapshot on the stored item) or None when the label offers nothing to
    ask with (no serving mass) — the caller then keeps the plain refusal.
    NEVER RAISES into the turn (the caller is `NativeExecutionStage.run`,
    which A8 forbids from holding a handler): a failure here is "no ask",
    logged, and the refusal stands."""
    try:
        return await _open(db, user=user, item=item, coverage=coverage,
                           turn_id=turn_id, channel=channel, locale=locale)
    except Exception:                                    # noqa: BLE001
        logger.warning("event=bound_ask_failed turn=%s — keeping the plain "
                       "refusal", turn_id, exc_info=True)
        return None


async def _open(db, *, user, item: dict, coverage, turn_id: str, channel: str,
                locale: str):
    from core.b1_quantity_operation import (CanonicalAsk, open_operation,
                                            _operation_id_for)
    from core.food_pipeline import stage_items
    from skills.nutrition import quantity_clarification as qc
    from skills.nutrition.normalize import normalize_quantity

    serving_grams = getattr(coverage, "serving_grams", None)
    pid = item.get("product_evidence_id")
    if not serving_grams or not pid:
        return None
    food = str(item.get("food_name") or item.get("food") or "").strip()
    quantity_text = str(item.get("quantity") or "").strip()
    unit_word = ""
    stated_count = None
    if quantity_text:
        try:
            nq = normalize_quantity(quantity_text, food)
            stated_count = getattr(nq, "count", None)
            unit_word = str(getattr(nq, "unit", "") or "").strip().rstrip("s")
        except Exception:                                # noqa: BLE001
            pass

    # the interpreter-shaped item B-1 stores and settles: the same food, the
    # same numbers, PLUS the binding — which is the whole point
    interpreter_item = {"food": food, "amount": stated_count or 1,
                        "unit": unit_word or "serving",
                        "calories": item.get("calories"),
                        "protein": item.get("protein"),
                        "carbs": item.get("carbs"), "fats": item.get("fats"),
                        "branded": True, "product_evidence_id": int(pid)}
    staged = stage_items({"items": [interpreter_item]}, turn_id=turn_id,
                         message=quantity_text or food, mode="strict")
    if not staged:
        return None
    staged_item = staged[0]

    # ⭐ A NEW SCAN SUPERSEDES AN OPEN ASK. Two awaiting operations for one
    # user would race for the next answer; the newer scan is the user's
    # current intent, so the older ask is cancelled (durably, with reason)
    # before this one is persisted. Nothing is written for the old ask.
    try:
        from core.b1_quantity_operation import cancel, owning
        prior = await owning(db, user)
        if prior is not None and prior.awaiting:
            await cancel(db, owned=prior, user=user,
                         reason="superseded by a new scan")
            logger.info("event=bound_ask_superseded old=%s", prior.operation_id)
    except Exception:                                    # noqa: BLE001
        logger.warning("could not check/cancel a prior ask", exc_info=True)

    operation_id = _operation_id_for(user, turn_id)
    field_probe = qc.quantity_field(operation_id=operation_id, revision=0,
                                    item=staged_item)
    options = _label_options(field=field_probe, serving_grams=float(serving_grams),
                             unit=unit_word, stated_count=stated_count)
    field = qc.quantity_field(operation_id=operation_id, revision=0,
                              item=staged_item, options=options)
    interaction = qc.build_interaction(
        operation_id=operation_id, revision=0, item=staged_item,
        options=field.options,
        introduction=_question(food=food or "that", unit_word=unit_word,
                               serving_grams=float(serving_grams),
                               stated_quantity=quantity_text or "that"),
        ask_preparation=False)
    try:
        await open_operation(db, user=user, interpreter_item=interpreter_item,
                             interaction=interaction, turn_id=turn_id,
                             cohort="scan_bound", locale=locale)
    except Exception:                                    # noqa: BLE001
        logger.warning("event=bound_ask_not_persisted turn=%s — keeping the "
                       "plain refusal", turn_id, exc_info=True)
        return None
    logger.info("event=bound_ask_opened operation=%s snapshot=%s food=%r "
                "stated=%r options=%d", operation_id, pid, food, quantity_text,
                len(field.options))
    return CanonicalAsk(operation_id=operation_id, revision=0,
                        interaction=interaction, locale=locale,
                        cohort="scan_bound", capability=channel or "")
