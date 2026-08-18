"""⭐ B-1.8b — THE CORRECTION EXECUTOR. A canonical row, repaired by its owner.

    "actually 3 eggs"
        -> the turn carries ONE update_food_entry naming a canonical row
        -> bind: the row's creating source is canonical:*  (the ledger says so)
        -> repair: the primitive computes ONE ratio from the row's own facts
        -> merge: stated fields replace, omitted fields PRESERVE, conflicting
           fields refuse (semantic repair is B-1.8c)
        -> write: update_food_entry(authority=CANONICAL_OWNER,
                  ledger_source=canonical:correction) — ONE transaction:
                  row + totals + `updated` event with the full before-state
        -> never legacy. A refusal here PROPAGATES; it does not fall through.

⛔⛔ THIS IS THE FIRST PATH TO EXERCISE THE AUTHORITY THE FIREWALL RESERVES.
`MutationAuthority.CANONICAL_OWNER` has been permitted on canonical rows since
the salmon-overwrote-chicken incident and has never had a caller. The firewall
itself is UNTOUCHED: this module is the owner the firewall was written to let
through, and legacy's INFERRED_INTERPRETATION is still refused exactly as
before.

⛔ NO PROVIDER, NO ARTIFACT, NO MODEL. The primitive is arithmetic over the
row; this module adds only the binding and the write. "2 eggs -> 3 eggs" never
rediscovers USDA — the crucial proof, per the GO ruling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: The mutation lane and its owner, on the ledger. `MealIntent.CORRECTION`
#: names it and nothing has ever written it — until this module.
CORRECTION_SOURCE = "canonical:correction"


class CorrectionRefused(Exception):
    """This correction cannot be applied canonically and MUST NOT fall back to
    legacy — a legacy write on a canonical row is the dual-authority the
    firewall exists to refuse. Typed and reasoned so the turn can ASK."""


class NotACanonicalRow(Exception):
    """The named row is not canonically owned. Not a refusal — routing: a
    legacy-owned row keeps its legacy correction path, untouched."""


@dataclass(frozen=True)
class CorrectionResult:
    entry_id: int
    ratio: float
    method: str
    changes: dict
    quantity_text: str


def _merge_quantity_text(old_text: str, old_q, new_q) -> str:
    """⛔⛔ THE FIELD-MERGE CONTRACT *(Danny)*: stated -> replace; OMITTED ->
    PRESERVE; conflicting -> refused upstream by the primitive.

    "2 large eggs" corrected by "actually 3 eggs" is 3 LARGE eggs. Writing the
    correction's bare words would silently drop `large` — the canonical
    semantics would collapse to whatever the user happened to say last, and a
    later repair would find a row that had forgotten its own size.
    """
    new_words = str(getattr(new_q, "unit_label", "") or "").strip()
    old_size = str(getattr(old_q, "size_descriptor", "") or "").strip()
    new_size = str(getattr(new_q, "size_descriptor", "") or "").strip()
    if old_size and not new_size and getattr(new_q, "count", None):
        # Re-insert the preserved size after the number: "3 eggs" -> "3 large
        # eggs". Purely textual — the SEMANTIC preservation happened in the
        # primitive, which priced the row's existing size; this keeps the
        # displayed quantity honest about it.
        amount = str(getattr(new_q, "amount", "") or "").rstrip("0").rstrip(".")
        unit = str(getattr(new_q, "unit", "") or "").strip()
        if amount and unit and new_words.lower().startswith(amount.lower()):
            return f"{amount} {old_size} {unit}".strip()
    return new_words or old_text


async def _lock_row(db, entry_id: int):
    """The repository's shared row lock — see db.queries.lock_food_entry. The
    shared-lock gate forbids taking the SELECT-FOR-UPDATE lock anywhere in
    core/, and it is right: B-1.6 retraction and B-1.8 repair need the
    identical guarantee, so it lives in one place."""
    from db.queries import lock_food_entry
    return await lock_food_entry(db, entry_id)


async def creating_source_of(db, entry_id: int) -> Optional[str]:
    from db.queries import creating_source
    return await creating_source(db, int(entry_id))


async def correct_quantity(db, *, user, entry_id: int, new_quantity_text: str,
                           idempotency: Optional[tuple] = None
                           ) -> Optional[CorrectionResult]:
    """Repair the quantity of ONE canonically owned row. Raises
    `NotACanonicalRow` (route to legacy, untouched), `CorrectionRefused`
    (canonical, but not deterministically computable — ask), or the
    firewall's own `CrossOwnerMutation` if the binding was somehow wrong.

    ⭐ `idempotency=(turn_id, message)` MAKES THE CORRECTION EXACTLY-ONCE, IN
    ONE TRANSACTION *(B-1.8b.1)*. The claim is RESERVED (flushed under a
    savepoint, never independently committed), the row is repaired and
    written, and `update_food_entry` completes the claim immediately before
    its single commit — claim + mutation + ledger event land together or roll
    back together. Returns None when the claim says this exact turn already
    corrected the row: the caller replays, writes nothing.
    """
    from sqlalchemy import select

    from core.canonical_repair import RepairRefused, reprice_quantity
    from db.models import DailyLog, FoodEntry
    from db.queries import MutationAuthority, update_food_entry
    from skills.nutrition.normalize import normalize_quantity

    entry = await _lock_row(db, entry_id)
    if entry is None:
        raise CorrectionRefused(f"entry {entry_id} does not exist")
    log = (await db.execute(
        select(DailyLog).where(DailyLog.id == entry.daily_log_id)
    )).scalar_one_or_none()
    if log is None or int(log.user_id) != int(user.id):
        raise CorrectionRefused(f"entry {entry_id} is not this user's")

    # ── BIND: the ledger names the owner ────────────────────────────────────
    owner = await creating_source_of(db, entry.id)
    if not (owner and str(owner).startswith("canonical:")):
        raise NotACanonicalRow(
            f"entry {entry_id} was created by {owner!r} — legacy keeps it")

    # ── RESERVE: the claim, inside THIS transaction ─────────────────────────
    claim_id = None
    if idempotency:
        from core.idempotency import claim_request

        turn_id, message = idempotency
        claim = await claim_request(
            db, channel="canonical", command="correction", user_id=int(user.id),
            client_key=str(turn_id), turn_id=str(turn_id),
            payload={"entry_id": int(entry_id), "quantity": new_quantity_text,
                     "message": message},
            commit=False)                          # <- the whole point
        if claim.replay:
            return None
        claim_id = claim.record_id

    # ── REPAIR: the primitive, over the row's own facts ─────────────────────
    food = str(entry.parsed_food_name or "")
    old_q = normalize_quantity(str(entry.quantity or ""), food)
    new_q = normalize_quantity(str(new_quantity_text or ""), food)
    try:
        repaired = reprice_quantity(entry=entry, old_quantity=old_q,
                                    new_quantity=new_q)
    except RepairRefused as exc:
        # ⛔ A REFUSAL UNWINDS THE RESERVATION. The claim was only flushed, so
        # rolling back leaves NO claim behind — the user's corrected retry is
        # not blocked by a claim guarding work that never happened.
        if claim_id is not None:
            await db.rollback()
        raise CorrectionRefused(str(exc)) from exc

    # ── MERGE: stated replaces, omitted preserves ───────────────────────────
    quantity_text = _merge_quantity_text(str(entry.quantity or ""), old_q, new_q)

    # ── WRITE: the owner mutates what it owns, in ONE transaction ───────────
    changes = dict(repaired.changes)
    changes["quantity"] = quantity_text
    if repaired.micros is not None:
        import json
        changes["micronutrients_json"] = json.dumps(repaired.micros)
    # The receipt moves WITH the correction — factor and resolved mass — and
    # the evidence ids and basis do NOT: the food did not change.
    changes.update(repaired.receipt_updates)

    updated = await update_food_entry(
        db, entry.id, int(user.id),
        ledger_source=CORRECTION_SOURCE,
        claim_id=claim_id,                # completed in the SAME transaction
        authority=MutationAuthority.CANONICAL_OWNER,
        **changes)
    if updated is None:                                  # pragma: no cover
        raise CorrectionRefused(f"entry {entry_id} vanished mid-correction")

    logger.info("event=canonical_corrected entry=%s ratio=%.4f method=%s "
                "quantity=%r", entry.id, repaired.ratio, repaired.method,
                quantity_text)
    return CorrectionResult(entry_id=entry.id, ratio=repaired.ratio,
                            method=repaired.method, changes=changes,
                            quantity_text=quantity_text)


# ══ B-1.8c — IDENTITY / PRODUCT-VARIANT REPAIR: REBIND EVIDENCE, THEN PRICE ══
#
# ⭐ THE SHAPE, FIXED BY RECON. An identity correction reaches the executor
# today as update_food_entry(entry_id, food_name=..., calories=..., ...): the
# interpreter re-estimates and hands over NUMBERS. Accepting those numbers is
# the guess-repricing this whole tranche exists to refuse — a correction must
# reuse what Arnie KNOWS, not what the model just guessed. So an identity
# repair takes ONLY the new identity, keeps the row's existing quantity (the
# field-merge contract: omitted -> preserved), and REBINDS the row to local
# evidence through the same assemble() -> price() seam settlement uses.
#
# ⛔⛔ EVIDENCE-BACKED RUNG OR REFUSE. If the rebind lands on ESTIMATE, that is
# not a canonical repair — it is a re-guess wearing a correction's clothes, and
# the honest answer is CorrectionRefused so the turn can ask or route.
#
# ⛔ NO PROVIDER, NO MODEL. assemble() is LOAD-NEVER-BUILD; a scan-bound
# product may be rebound by its snapshot id, a generic food by the committed
# artifact or the user's own memory. Nothing here fetches.
#
# ⚠ SelectProductVariant / SetPreparation exist as canonical primitives with NO
# live producer yet (the board says PRODUCT_VARIANT needs a real registration
# before it is canonical). This slice does not invent one: it repairs identity
# via the same evidence sources settlement already prices from.


@dataclass(frozen=True)
class IdentityRepairResult:
    entry_id: int
    old_identity: str
    new_identity: str
    rung: str
    evidence_id: str
    changes: dict


def _split_identity_words(identity: str) -> tuple:
    from skills.nutrition.pricing_artifact import split_identity
    return split_identity(str(identity or "").strip())


async def correct_identity(db, *, user, entry_id: int, new_identity: str,
                           product_evidence_id: Optional[int] = None,
                           new_quantity_text: Optional[str] = None,
                           idempotency: Optional[tuple] = None
                           ) -> Optional[IdentityRepairResult]:
    """Rebind ONE canonically owned row to a different food identity — or a
    specific product snapshot — and reprice it FROM LOCAL EVIDENCE at the row's
    existing quantity. Raises NotACanonicalRow (legacy keeps it),
    CorrectionRefused (no evidence-backed rung for the new identity — ask),
    or the firewall's CrossOwnerMutation. Returns None on an idempotent replay.

    Exactly-once in ONE transaction, the B-1.8b.1 lifecycle: reservation
    flushed, mutation + ledger event + claim completion share the commit.

    ⛔⛔ IDENTITY + QUANTITY IS ONE TRANSACTION, NOT TWO *(review P1)*. The
    first cut chained correct_identity (commit) then correct_quantity (commit)
    — so "actually chicken thigh, and make it 200 g" could crash between them
    with the identity changed, the claim COMPLETED, and the quantity still old;
    the retry then found a completed claim and refused. That broke the
    B-1.8b.1 invariant this module had just paid for. Now `new_quantity_text`
    is priced AT THAT QUANTITY against the rebound evidence — one calculation,
    one row mutation, one `updated` event, one claim, one commit.

    ⛔⛔ THE REBIND IS WHOLESALE, INCLUDING EXPLICIT ABSENCE *(review P1)*.
    Every evidence-owned and nutrition-panel field is REPLACED by the new
    price — and a field the new evidence does not supply is CLEARED (written
    as None), never left over from the old food. The first cut dropped None
    values, so a rebind was an overlay: new calories over old fiber, old
    sodium, old basis evidence, old conversion ids, old resolved mass — a row
    describing two foods at once. Absence is a legitimate write.
    """
    from sqlalchemy import select

    from core.canonical_pricing import PricingRefused, price
    from core.canonical_pricing_inputs import assemble
    from db.models import DailyLog, FoodEntry
    from db.queries import MutationAuthority, update_food_entry
    from skills.nutrition.normalize import normalize_quantity

    entry = await _lock_row(db, entry_id)
    if entry is None:
        raise CorrectionRefused(f"entry {entry_id} does not exist")
    log = (await db.execute(
        select(DailyLog).where(DailyLog.id == entry.daily_log_id)
    )).scalar_one_or_none()
    if log is None or int(log.user_id) != int(user.id):
        raise CorrectionRefused(f"entry {entry_id} is not this user's")

    owner = await creating_source_of(db, entry.id)
    if not (owner and str(owner).startswith("canonical:")):
        raise NotACanonicalRow(
            f"entry {entry_id} was created by {owner!r} — legacy keeps it")

    new_identity = str(new_identity or "").strip()
    if not new_identity and product_evidence_id is None:
        raise CorrectionRefused("an identity repair needs a new identity or "
                                "a product snapshot to rebind to")

    claim_id = None
    if idempotency:
        from core.idempotency import claim_request
        turn_id, message = idempotency
        claim = await claim_request(
            db, channel="canonical", command="correction", user_id=int(user.id),
            client_key=str(turn_id), turn_id=str(turn_id),
            payload={"entry_id": int(entry_id), "identity": new_identity,
                     "product_evidence_id": product_evidence_id,
                     "message": message},
            commit=False)
        if claim.replay:
            return None
        claim_id = claim.record_id

    # ── REBIND + REPRICE, from local evidence at the EXISTING quantity ──────
    old_identity = str(entry.parsed_food_name or "")
    identity = new_identity or old_identity
    entity, preparation = _split_identity_words(identity)
    # Field-merge: a stated quantity replaces, an omitted one preserves — and
    # either way the price is computed ONCE, at that quantity, on the rebound
    # evidence. No second pass, no second commit.
    quantity_text = (str(new_quantity_text).strip() if new_quantity_text
                     else str(entry.quantity or ""))
    consumed = normalize_quantity(quantity_text, identity) if quantity_text else None
    item = {"food_name": identity, "quantity": quantity_text}
    if product_evidence_id is not None:
        item["product_evidence_id"] = int(product_evidence_id)
    try:
        inputs = await assemble(
            db, user_id=int(user.id), entity=entity, preparation=preparation,
            identity=identity, item=item,
            basis_grams=getattr(consumed, "grams", None) if consumed else None)
        # ⛔ THE ESTIMATE RUNG IS WITHHELD. An identity repair may only land on
        # evidence; letting price() fall through to the interpreter's estimate
        # would be a re-guess. Nothing to price from -> refuse -> the turn asks.
        inputs["estimate"] = None
        priced = price(entity=identity, preparation=preparation,
                       consumed=consumed, **inputs)
    except PricingRefused as exc:
        if claim_id is not None:
            await db.rollback()
        raise CorrectionRefused(
            f"no local evidence-backed rung can price {identity!r} at "
            f"{quantity_text!r} — an identity repair must rebind to evidence, "
            f"never re-estimate ({exc})") from exc

    import json
    conversion_ids = list(getattr(priced, "conversion_evidence_ids", ()) or ())
    changes = {
        "parsed_food_name": identity,
        "quantity": quantity_text,
        "calories": float(priced.calories),
        "protein": priced.protein, "carbs": priced.carbs, "fats": priced.fats,
        # ── the panel: replaced, ABSENT = CLEARED ───────────────────────────
        "fiber": priced.fiber, "sugar": priced.sugar, "sodium": priced.sodium,
        "micronutrients_json": (json.dumps(priced.micros)
                                if priced.micros is not None else None),
        # ── the receipt: replaced WHOLESALE, ABSENT = CLEARED ───────────────
        "pricing_rung": priced.rung.value,
        "nutrition_evidence_id": priced.evidence_id or None,
        "source_basis": priced.basis or None,
        "basis_evidence_id": None,      # no basis-evidence producer yet; a
                                        # stale one from the OLD food is wrong
        "conversion_evidence_ids_json": (json.dumps(conversion_ids)
                                         if conversion_ids else None),
        "scaling_factor": priced.scaling_factor,
        "resolved_grams": priced.resolved_grams,
        "source_amount": priced.source_amount,
        "source_unit": priced.source_unit or None,
        "product_evidence_id": (int(product_evidence_id)
                                if product_evidence_id is not None else None),
        # ── row METADATA that describes the OLD food *(stale-metadata audit)* ─
        # A wine -> chicken rebind must not keep the wine's alcohol; an
        # estimate -> artifact rebind is no longer an estimate; the old NOVA
        # class describes a food this row no longer is. Reset to what the new
        # price says, or to absent.
        "estimated_flag": priced.rung.value == "estimate",
        "micros_estimated": bool(priced.micros_estimated),
        "alcohol_units": None,
        "processing_level": None,
    }
    # ⛔ NOTHING IS FILTERED. Every key above reaches update_food_entry, and
    # for the owner authority a present None is a CLEAR. Filtering None here is
    # exactly how the first cut became a partial overlay.

    updated = await update_food_entry(
        db, entry.id, int(user.id),
        ledger_source=CORRECTION_SOURCE, claim_id=claim_id,
        authority=MutationAuthority.CANONICAL_OWNER, **changes)
    if updated is None:                                  # pragma: no cover
        raise CorrectionRefused(f"entry {entry_id} vanished mid-correction")

    logger.info("event=canonical_identity_corrected entry=%s %r -> %r rung=%s "
                "evidence=%s", entry.id, old_identity, identity,
                priced.rung.value, priced.evidence_id)
    return IdentityRepairResult(entry_id=entry.id, old_identity=old_identity,
                                new_identity=identity, rung=priced.rung.value,
                                evidence_id=priced.evidence_id or "",
                                changes=changes)


# ══ B-1.8d — UNDO IS A RESTORE, NOT A REPAIR ═════════════════════════════════
#
# ⛔ AN UNDO THAT REACHED THE REPAIR PATH WOULD RE-PRICE THE RESTORED FOOD. The
# ledger_undo plan lifts to an update_food_entry op naming the row; the native
# stage's correction route would happily hand that to correct_identity, which
# rebinds evidence and prices anew — so "undo" would compute a FRESH price for
# the old identity instead of putting back the recorded numbers. A restore
# writes the ledger's before-state VERBATIM under RECORDED_REPLAY. No pricing,
# no evidence, no claim of its own beyond the turn's.


async def restore_recorded_state(db, *, user, entry_id: int,
                                 before: dict) -> dict:
    """Write a recorded before-state back onto a canonical row, verbatim.
    Fields the before-state carries are restored; fields passed as None are
    CLEARED (a value the correction added must not survive its own undo).
    One transaction through update_food_entry(RECORDED_REPLAY)."""
    from sqlalchemy import select

    from db.models import DailyLog, FoodEntry
    from db.queries import MutationAuthority, update_food_entry

    entry = (await db.execute(select(FoodEntry).where(
        FoodEntry.id == int(entry_id)))).scalar_one_or_none()
    if entry is None:
        raise CorrectionRefused(f"entry {entry_id} does not exist")
    log = (await db.execute(select(DailyLog).where(
        DailyLog.id == entry.daily_log_id))).scalar_one_or_none()
    if log is None or int(log.user_id) != int(user.id):
        raise CorrectionRefused(f"entry {entry_id} is not this user's")

    changes = {}
    for k, v in (before or {}).items():
        if k in ("entry_id", "source", "food_hint"):
            continue
        changes["parsed_food_name" if k == "food_name" else k] = v
    updated = await update_food_entry(
        db, entry.id, int(user.id), ledger_source="ledger_undo:canonical",
        authority=MutationAuthority.RECORDED_REPLAY, **changes)
    if updated is None:                                  # pragma: no cover
        raise CorrectionRefused(f"entry {entry_id} vanished mid-restore")
    logger.info("event=canonical_state_restored entry=%s fields=%d",
                entry.id, len(changes))
    return changes
