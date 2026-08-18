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
                           idempotency_claim_id: Optional[int] = None
                           ) -> CorrectionResult:
    """Repair the quantity of ONE canonically owned row. Raises
    `NotACanonicalRow` (route to legacy, untouched), `CorrectionRefused`
    (canonical, but not deterministically computable — ask), or the
    firewall's own `CrossOwnerMutation` if the binding was somehow wrong.
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

    # ── REPAIR: the primitive, over the row's own facts ─────────────────────
    food = str(entry.parsed_food_name or "")
    old_q = normalize_quantity(str(entry.quantity or ""), food)
    new_q = normalize_quantity(str(new_quantity_text or ""), food)
    try:
        repaired = reprice_quantity(entry=entry, old_quantity=old_q,
                                    new_quantity=new_q)
    except RepairRefused as exc:
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
        claim_id=idempotency_claim_id,
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
