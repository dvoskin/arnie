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

    entry = (await db.execute(
        select(FoodEntry).where(FoodEntry.id == int(entry_id))
    )).scalar_one_or_none()
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
                           idempotency: Optional[tuple] = None
                           ) -> Optional[IdentityRepairResult]:
    """Rebind ONE canonically owned row to a different food identity — or a
    specific product snapshot — and reprice it FROM LOCAL EVIDENCE at the row's
    existing quantity. Raises NotACanonicalRow (legacy keeps it),
    CorrectionRefused (no evidence-backed rung for the new identity — ask),
    or the firewall's CrossOwnerMutation. Returns None on an idempotent replay.

    Exactly-once in ONE transaction, the B-1.8b.1 lifecycle: reservation
    flushed, mutation + ledger event + claim completion share the commit.
    """
    from sqlalchemy import select

    from core.canonical_pricing import PricingRefused, price
    from core.canonical_pricing_inputs import assemble
    from db.models import DailyLog, FoodEntry
    from db.queries import MutationAuthority, update_food_entry
    from skills.nutrition.normalize import normalize_quantity

    entry = (await db.execute(
        select(FoodEntry).where(FoodEntry.id == int(entry_id))
    )).scalar_one_or_none()
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
    quantity_text = str(entry.quantity or "")
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

    changes = {
        "parsed_food_name": identity,
        "calories": float(priced.calories),
        "protein": priced.protein, "carbs": priced.carbs, "fats": priced.fats,
        "fiber": priced.fiber, "sugar": priced.sugar, "sodium": priced.sodium,
        # ⭐ THE RECEIPT IS REWRITTEN WHOLESALE — the food changed, so the
        # nutrition evidence, basis and factor are all the NEW ones. This is
        # the difference from a quantity repair, which moves the factor and
        # keeps the evidence.
        "pricing_rung": priced.rung.value,
        "nutrition_evidence_id": priced.evidence_id or None,
        "source_basis": priced.basis or None,
        "scaling_factor": priced.scaling_factor,
        "resolved_grams": priced.resolved_grams,
        "source_amount": priced.source_amount,
        "source_unit": priced.source_unit or None,
        "product_evidence_id": (int(product_evidence_id)
                                if product_evidence_id is not None else None),
    }
    if priced.micros is not None:
        import json
        changes["micronutrients_json"] = json.dumps(priced.micros)
    changes = {k: v for k, v in changes.items() if v is not None
               or k in ("nutrition_evidence_id", "product_evidence_id")}

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
