"""⭐ P17-UA slice C / CF9 — A BOUND REFUSAL BECOMES AN ASK THAT HOLDS THE SNAPSHOT.

    scan 70004199 -> "2 bars"
        -> BoundUnpriceable (the label names no bar)
        -> THIS: open a canonical quantity operation whose stored item CARRIES
           the snapshot id, and ask in the label's terms, NAMING THE UNKNOWN:
               "Got the scanned Barebells … The label gives nutrition per 55 g
                serving, but doesn't say whether a bar is one serving — how
                much did you have?"
                    [110 g — 2 servings]   [55 g — 1 serving]   free text
        -> the answer — a tap, "2 servings", "110 g" — settles the SAME bound
           snapshot canonically: no reacquisition, no MEMORY, no legacy.

Danny's hierarchy, source 4: the user's confirmation authorises the quantity
FOR THIS CONSUMPTION. Choosing "110 g — 2 servings" is the user STATING the
quantity in the label's own unit — precedence class 1 — so the settle prices
from the panel's own serving conversion. Nothing here translates bar into
serving on the user's behalf: the option says what it is, and the user picks.

⛔ THE CHIPS LEAD WITH THE LABEL'S BASE UNIT *(Danny, 2026-08-18, after the
first two-turn canary)*. The question used to ask "is each bar one 55 g
serving?" (a per-bar yes/no) while the chips read "2 servings" / "1 serving"
(totals) — the affirmative answer to the QUESTION lexically matched the chip
that logged HALF the food, and it looked confirmed. Serving-counts also read
badly for a bag, a bottle or a scoop. So the display text is the mass first,
"110 g — 2 servings", and the semantic `value` stays "2 servings" so a
text-channel user still types the label's words back (`_option_for_label`
matches `send_value`, which is `value` when set).

⚠ SCOPE OF PROOF *(review, 2026-08-18)*: the bound-ask PATH is proven for
GRAM-BASED labels only. `_open` gates on `coverage.serving_grams`; a per-ml
snapshot reaches this module only if the predicate reports a gram serving.
The ml chip DISPLAY is helper-proven (`_label_base_unit`, `_label_options`,
`_question` with base_unit="ml") and is display-ready; the liquid path
(per-ml ProductEvidence -> coverage -> BoundUnpriceable -> ask -> ml chips ->
settle) is NOT proven end to end and is registered under P17-UE (CF10) —
liquids do not ship a claim here.

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
                   stated_count: Optional[float],
                   base_unit: str = "g") -> tuple:
    """Options in the label's OWN terms. The user's stated count first (so
    "2 bars" is offered as "110 g — 2 servings"), then one serving. Every
    option is a MASS the label states — a user-stated exact quantity once
    chosen — never a bar->serving equivalence asserted by us. `base_unit` is
    the label's own basis ("g", or "ml" for a liquid) and leads the chip."""
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
        # DISPLAY leads with the label's base unit — the one thing that is
        # unambiguous for every product and never asserts bar = serving; the
        # semantic VALUE is the label's own words ("2 servings"), which is
        # what a user TYPES BACK on a text channel — `_option_for_label`
        # matches `send_value` (= value when set) exactly, so both routes
        # keep working while the chip says what it is.
        words = f"{n_txt} {plural}"
        label = f"{float(grams):g} {base_unit} — {words}"
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
            label=label, value=words, option_id=f"opt_label_serving_{n_txt}",
            field_id=field.field_id,
            patch=SetQuantity(event_id=field.event_id, field_id=field.field_id,
                              quantity=q, provenance=Provenance.USER_SELECTED),
            source=CandidateSource.ONTOLOGY))
    return tuple(options)


def _question(*, food: str, unit_word: str, serving_grams: float,
              stated_quantity: str, base_unit: str = "g") -> str:
    """The ask, in the label's terms, NAMING THE UNKNOWN and asking for the
    TOTAL — so the chips (totals) answer the question that was asked. Never
    a per-unit yes/no: "is each bar one serving?" invited "yes", and "yes"
    read as the one-serving chip."""
    g = f"{serving_grams:g}"
    if unit_word:
        return (f"Got the scanned {food}. The label gives nutrition per {g} "
                f"{base_unit} serving, but doesn't say whether a {unit_word} "
                f"is one serving — how much did you have?")
    unit_name = "millilitres" if base_unit == "ml" else "grams"
    return (f"Got the scanned {food}. The label gives nutrition per {g} "
            f"{base_unit} serving, and I can't price {stated_quantity} from "
            f"it — how much did you have, in servings or {unit_name}?")


async def _label_base_unit(db, product_evidence_id) -> str:
    """The label's own basis unit for the chips: "ml" when the persisted
    snapshot states its serving in millilitres (a liquid label; OFF's
    `nutrition_data_per='100ml'`), else "g". A LOCAL read of the record —
    never a fetch — and any failure is "g", the common case.

    ⚠ DISPLAY-READY, PATH-UNPROVEN for liquids (see the module docstring):
    `_open` still receives `serving_grams` from coverage. Until P17-UE proves
    the per-ml path, this can only ever return "ml" for a snapshot that ALSO
    reached coverage as a gram serving — the honest description is "the
    chips will say ml when the record says ml", not "liquids are supported"."""
    try:
        from db.models import ProductEvidenceRecord
        row = await db.get(ProductEvidenceRecord, int(product_evidence_id))
        if row is not None and getattr(row, "serving_ml", None) and not \
                getattr(row, "serving_mass_g", None):
            return "ml"
    except Exception:                                    # noqa: BLE001
        pass
    return "g"


async def open_bound_quantity_ask(db, *, user, item: dict, coverage,
                                  turn_id: str, channel: str,
                                  locale: str = "en"):
    """Open the ask. Returns a `CanonicalAsk` (durable operation persisted,
    snapshot on the stored item) or None when the label offers nothing to
    ask with (no serving mass) — the caller then keeps the plain refusal.
    Ordinary failure is "no ask", logged, and the plain refusal stands (the
    caller is `NativeExecutionStage.run`, which A8 forbids from holding a
    handler). ⛔ `BoundAskNotSingular` PROPAGATES *(CF5c-B3)*: it means a
    second ask could not be prevented, and "keep the plain refusal" would
    leave an unknown number of awaiting operations behind it — the entrypoint
    answers it in words, nothing is written."""
    try:
        return await _open(db, user=user, item=item, coverage=coverage,
                           turn_id=turn_id, channel=channel, locale=locale)
    except BoundAskNotSingular:
        raise
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

    operation_id = _operation_id_for(user, turn_id)

    # ⛔⛔ CF5c-B3 — IDEMPOTENT AND SINGLE-OWNER *(Danny, 2026-08-19)*. Three
    # defects lived here:
    #   · the check-and-cancel of a prior ask sat in a bare `except` that
    #     CONTINUED, so a failure to supersede still opened a second ask —
    #     two awaiting operations racing for the next answer;
    #   · a same-turn RETRY found ITS OWN ask as the "prior", cancelled it,
    #     and then collided on the same operation id;
    #   · nothing at the database enforced "at most one awaiting ask per
    #     user", so two workers could each pass the check and both insert.
    # Now:
    #   1. the SAME operation already open  -> return THAT ask (idempotent).
    #   2. a DIFFERENT awaiting ask         -> supersede it; if that fails,
    #                                          REFUSE — never open beside it.
    #   3. the insert races and loses       -> reload and return the winner.
    #   4. the DB holds a partial unique index: one active awaiting operation
    #      per (user, domain) — the constraint the code was pretending to be.
    # ⛔ NO PRE-READ SHORTCUT *(review of 2db22e1, round 2)*. An earlier cut
    # looked up the user's open operation here and, on a same-id match,
    # returned it after checking only the SNAPSHOT id — before the
    # interaction was built, so it could not compare semantics. A retry that
    # rebuilt a DIFFERENT question for the same turn and snapshot was reused
    # as if identical. Reuse is decided in exactly ONE place: `open_operation`
    # holds both the built interaction and the stored row and compares their
    # FINGERPRINTS; this wrapper then verifies the snapshot on what it
    # returns. One path, one comparison — the same for bound and ordinary.

    base_unit = await _label_base_unit(db, pid)
    field_probe = qc.quantity_field(operation_id=operation_id, revision=0,
                                    item=staged_item)
    options = _label_options(field=field_probe, serving_grams=float(serving_grams),
                             unit=unit_word, stated_count=stated_count,
                             base_unit=base_unit)
    field = qc.quantity_field(operation_id=operation_id, revision=0,
                              item=staged_item, options=options)
    interaction = qc.build_interaction(
        operation_id=operation_id, revision=0, item=staged_item,
        options=field.options,
        introduction=_question(food=food or "that", unit_word=unit_word,
                               serving_grams=float(serving_grams),
                               stated_quantity=quantity_text or "that",
                               base_unit=base_unit),
        ask_preparation=False)
    from core.b1_quantity_operation import (FingerprintUnreadable, OpenedElsewhere,
                                            PriorAskNotReleased,
                                            StoredFingerprintVersionMismatch)
    # ⛔ OPEN / REUSE / RACE ARE RESOLVED AT THE SHARED SEAM *(review of
    # 22b9e7a)*: `open_operation` is the one insert site for every B-1 ask.
    # It reuses the SAME operation id if already awaiting, releases a
    # different prior (refusing by VALUE when the repository says the release
    # did not take), and on a lost insert race reuses ONLY when the winner IS
    # this operation. A winner from another turn is a different product's
    # question — `OpenedElsewhere` — and is NEVER rendered as this one: the
    # first cut returned "whichever ask currently owns the user", which could
    # put product B's question in product A's reply.
    try:
        opened = await open_operation(
            db, user=user, interpreter_item=interpreter_item,
            interaction=interaction, turn_id=turn_id,
            cohort="scan_bound", locale=locale, capability=channel or "")
    except PriorAskNotReleased as exc:
        raise BoundAskNotSingular(f"could not supersede: {exc}") from exc
    except OpenedElsewhere as exc:
        raise BoundAskNotSingular(f"another ask owns this user: {exc}") from exc
    except FingerprintUnreadable as exc:
        raise BoundAskNotSingular(f"stored ask unreadable: {exc}") from exc
    except StoredFingerprintVersionMismatch as exc:
        # ⛔ P17 Phase 2: the stored ask was fingerprinted under other rules.
        # Not comparable, and never recomputed under today's — refuse.
        raise BoundAskNotSingular(f"stored ask not comparable: {exc}") from exc
    except Exception:                                    # noqa: BLE001
        logger.warning("event=bound_ask_not_persisted turn=%s — keeping the "
                       "plain refusal", turn_id, exc_info=True)
        return None
    # ⛔ RENDER WHAT PERSISTED, AND IT MUST BE THIS SNAPSHOT *(review of
    # 2db22e1)*. On a reuse `opened.interaction` is the STORED interaction
    # (fingerprint-checked at the seam); the wrapper previously returned the
    # object it had just built, so a same-turn race could persist snapshot A
    # and render B. Exact snapshot match is required for a bound ask; absence
    # is not a match.
    stored_pid = (opened.item or {}).get("product_evidence_id")
    if stored_pid is None or int(stored_pid) != int(pid):
        raise BoundAskNotSingular(
            f"operation {operation_id} persisted snapshot {stored_pid!r}, "
            f"this scan is {pid}")
    logger.info("event=bound_ask_%s operation=%s snapshot=%s food=%r "
                "stated=%r options=%d",
                "opened" if opened.created else "reused", operation_id, pid,
                food, quantity_text, len(field.options))
    # ⛔ RENDER FROM PERSISTED AUTHORITY, INCLUDING THE CAPABILITY *(P17
    # Phase 2)*. Rendering depends on capability (whether the options are IN
    # the sentence), so a reuse must render under the capability the ask was
    # BUILT for — reading the live channel here would let a retry from a
    # different client re-render a stored question in a shape it was never
    # asked in. `opened.capability` is the stored one; on a fresh open it IS
    # this channel, because that is what was just persisted.
    return CanonicalAsk(operation_id=opened.operation_id,
                        revision=opened.revision,
                        interaction=opened.interaction,
                        locale=opened.locale, cohort=opened.cohort,
                        capability=opened.capability or "")


class BoundAskNotSingular(Exception):
    """CF5c-B3 — the bound ask could not be made the ONE awaiting operation
    for this user: the open operation could not be read, a prior ask could
    not be superseded, or the insert race resolved to nothing. Non-mutating;
    the caller answers it as a refusal rather than opening a second ask
    beside an unknown."""


