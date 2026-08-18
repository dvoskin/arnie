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
    entry = await _locked_owned_row(db, user=user, entry_id=entry_id)

    new_identity = str(new_identity or "").strip()
    if not new_identity and product_evidence_id is None:
        raise CorrectionRefused("an identity repair needs a new identity or "
                                "a product snapshot to rebind to")
    old_identity = str(entry.parsed_food_name or "")
    return await _rebind(
        db, user=user, entry=entry, identity=new_identity or old_identity,
        product_evidence_id=product_evidence_id,
        new_quantity_text=new_quantity_text, idempotency=idempotency,
        claim_payload={"identity": new_identity,
                       "product_evidence_id": product_evidence_id})


async def _locked_owned_row(db, *, user, entry_id: int):
    """The row, FOR UPDATE, proven to be this user's and canonically owned.
    Every repair reads THROUGH this so whatever it derives from the row
    (the old identity, the old preparation) is derived under the lock — a
    correct lock over a stale read still loses the write (B-1.6a)."""
    from sqlalchemy import select
    from db.models import DailyLog

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
    return entry


async def _rebind(db, *, user, entry, identity: str,
                  product_evidence_id: Optional[int],
                  new_quantity_text: Optional[str],
                  idempotency: Optional[tuple],
                  claim_payload: dict) -> Optional[IdentityRepairResult]:
    """THE ONE REBIND TRANSACTION every semantic repair ends in: claim reserved
    (commit=False) -> price ONCE from local evidence at the effective quantity
    -> wholesale row replacement -> ledger event -> claim completed -> ONE
    commit. `identity` is already the NEW composed identity; the caller
    derived it under the row lock."""
    from core.canonical_pricing import PricingRefused, price
    from core.canonical_pricing_inputs import assemble
    from db.queries import MutationAuthority, update_food_entry
    from skills.nutrition.normalize import normalize_quantity

    entry_id = int(entry.id)
    claim_id = None
    if idempotency:
        from core.idempotency import claim_request
        turn_id, message = idempotency
        claim = await claim_request(
            db, channel="canonical", command="correction", user_id=int(user.id),
            client_key=str(turn_id), turn_id=str(turn_id),
            payload={"entry_id": entry_id, "message": message, **claim_payload},
            commit=False)
        if claim.replay:
            return None
        claim_id = claim.record_id

    # ── REBIND + REPRICE, from local evidence at the EXISTING quantity ──────
    old_identity = str(entry.parsed_food_name or "")
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
    # ⛔⛔ A NAMED SNAPSHOT IS A BINDING, AND A BINDING IS AN EVIDENCE
    # CONSTRAINT *(B-1.8c2.2, Danny)*. With product_evidence_id set, this
    # repair prices from THAT snapshot or refuses: memory, artifact and
    # estimate are never READ (assemble bound=True) and never RANKED
    # (price bound=True). Before c2.2 the ladder still ran MEMORY first, so a
    # user with a memory row for the same name would have had their explicit
    # product selection out-ranked by their own history — the tap thrown away
    # while the correction looked successful.
    bound = product_evidence_id is not None
    try:
        inputs = await assemble(
            db, user_id=int(user.id), entity=entity, preparation=preparation,
            identity=identity, item=item,
            basis_grams=getattr(consumed, "grams", None) if consumed else None,
            bound=bound)
        # ⛔ THE ESTIMATE RUNG IS WITHHELD. An identity repair may only land on
        # evidence; letting price() fall through to the interpreter's estimate
        # would be a re-guess. Nothing to price from -> refuse -> the turn asks.
        inputs["estimate"] = None
        priced = price(entity=identity, preparation=preparation,
                       consumed=consumed, bound=bound, **inputs)
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


# ══ B-1.8c2.3 — SetPreparation: PRESERVE THE ENTITY, REPLACE THE PREPARATION ═
#
#     SetPreparation(event, fried) on "Grilled chicken"
#         -> lock the canonical row (the old identity is read UNDER the lock)
#         -> split: entity "chicken", old prep "grilled"       (structural)
#         -> compose: name_with("chicken", "fried") = "chicken, fried"
#         -> _rebind: local evidence for chicken|fried, evidence-backed price
#            or refuse, wholesale receipt, one claim / one event / one commit
#
# ⛔ NOT name_with(old_name, "fried"): that yields "Grilled chicken, fried" —
# two preparations on one food, a key nothing matches, and a row that says
# both. The entity is what survives; the preparation is what changes.
# ⛔ The preparation must be in the REGISTERED vocabulary. An unknown id is a
# refusal, not "unknown" silently composed away by name_with.
# ⛔ The twin: "grilled chicken" + correction "chicken thigh" is an IDENTITY
# repair -> "chicken thigh", NOT "grilled chicken thigh". A new identity
# replaces wholesale; only SetPreparation preserves the entity.


async def correct_preparation(db, *, user, entry_id: int, preparation_id: str,
                              new_quantity_text: Optional[str] = None,
                              idempotency: Optional[tuple] = None
                              ) -> Optional[IdentityRepairResult]:
    """Replace ONE canonically owned row's preparation, keeping its entity,
    and reprice it from local evidence for entity+preparation. Raises
    NotACanonicalRow / CorrectionRefused; None on an idempotent replay."""
    from core.semantic_fields import spec_for
    from skills.nutrition.preparation_ontology import name_with

    prep = str(preparation_id or "").strip().lower()
    vocabulary = tuple(spec_for("preparation").vocabulary)
    if prep not in vocabulary:
        raise CorrectionRefused(
            f"preparation {preparation_id!r} is not in the registered "
            f"vocabulary {list(vocabulary)} — refusing to compose an unknown "
            f"preparation into an identity")

    entry = await _locked_owned_row(db, user=user, entry_id=entry_id)
    old_identity = str(entry.parsed_food_name or "")
    entity, old_prep = _split_identity_words(old_identity)
    if not entity:
        raise CorrectionRefused(
            f"entry {entry_id} has no entity to preserve ({old_identity!r})")
    identity = name_with(entity, prep)
    logger.info("event=canonical_preparation_repair entry=%s entity=%r prep "
                "%r -> %r identity=%r", entry_id, entity, old_prep, prep,
                identity)
    return await _rebind(
        db, user=user, entry=entry, identity=identity, product_evidence_id=None,
        new_quantity_text=new_quantity_text, idempotency=idempotency,
        claim_payload={"identity": identity, "preparation_id": prep,
                       "product_evidence_id": None})


# ══ B-1.8c2.2 — A TAP BINDS TO THE SNAPSHOT IT WAS OFFERED FROM ══════════════
#
#     tap -> stored SelectProductVariant (the interaction's patch_for)
#         -> reopen the exact universe (candidate_set_id / operation_id / user)
#         -> verify_selection: option == candidate == snapshot == entity
#         -> correct_identity(product_evidence_id=..., BOUND)
#            -> assemble(bound)  never reads memory / artifact / estimate
#            -> price(bound)     that snapshot, or PricingRefused
#         -> ONE canonical correction transaction (claim + row + ledger)
#
# ⛔ NOTHING HERE INVENTS. The universe was persisted by a producer that had
# exact evidence; this function only ENFORCES that the tap, the candidate and
# the snapshot agree, then hands the proven ids to the repair. A patch with
# product_evidence_id == 0 (a v1 payload) is UNBOUND and refused — it is never
# "helped" by looking up the newest snapshot for the entity.


class ProductSelectionRefused(CorrectionRefused):
    """The tap did not prove its triangle. Non-mutating by construction: it is
    raised before the claim is reserved and before any row is locked."""


async def select_product_variant(db, *, user, entry_id: int, patch,
                                 operation_id: str,
                                 candidate_set_id: Optional[str],
                                 new_quantity_text: Optional[str] = None,
                                 idempotency: Optional[tuple] = None
                                 ) -> Optional[IdentityRepairResult]:
    """Apply a stored SelectProductVariant to a canonically owned row.

    Raises ProductSelectionRefused when the triangle does not close (unbound
    patch, foreign candidate, option/candidate disagreement, snapshot missing
    or about another product, universe of another user/operation), then
    everything `correct_identity` raises. Returns None on an idempotent replay.
    """
    from skills.nutrition.product_variant_clarification import (
        NoExactUniverse, reopen, verify_selection)

    try:
        universe = await reopen(db, operation_id=str(operation_id),
                                user_id=int(user.id),
                                candidate_set_id=candidate_set_id)
        candidate = await verify_selection(db, patch=patch, universe=universe)
    except NoExactUniverse as exc:
        logger.info("event=product_selection_refused entry=%s operation=%s "
                    "reason=%s", entry_id, operation_id, exc)
        raise ProductSelectionRefused(str(exc)) from exc

    if not str(candidate.label or "").strip():
        # The row's parsed_food_name would otherwise be PRESERVED (omitted ->
        # preserved) while its receipt says off:<code> — a row naming one food
        # and priced as another. A candidate offered without a label is not
        # a candidate the user could have chosen knowingly.
        raise ProductSelectionRefused(
            f"candidate {candidate.candidate_id!r} has no label — refusing to "
            f"rebind the row's identity to an unnamed product")
    logger.info("event=product_selection_verified entry=%s entity=%s "
                "snapshot=%s candidate=%s set=%s", entry_id,
                candidate.entity_id, candidate.product_evidence_id,
                candidate.candidate_id, universe.candidate_set_id)
    return await correct_identity(
        db, user=user, entry_id=entry_id,
        new_identity=str(candidate.label or ""),
        product_evidence_id=int(candidate.product_evidence_id),
        new_quantity_text=new_quantity_text, idempotency=idempotency)


# ══ B-1.8d — UNDO IS A RESTORE, NOT A REPAIR ═════════════════════════════════
#
# ⛔ AN UNDO THAT REACHED THE REPAIR PATH WOULD RE-PRICE THE RESTORED FOOD. The
# ledger_undo plan lifts to an update_food_entry op naming the row; the native
# stage's correction route would happily hand that to correct_identity, which
# rebinds evidence and prices anew — so "undo" would compute a FRESH price for
# the old identity instead of putting back the recorded numbers. A restore
# writes the ledger's before-state VERBATIM under RECORDED_REPLAY. No pricing,
# no evidence, no claim of its own beyond the turn's.


async def restore_recorded_state(db, *, user, entry_id: int, before: dict,
                                 idempotency: Optional[tuple] = None
                                 ) -> Optional[dict]:
    """Write a recorded before-state back onto a canonical row, verbatim.
    Fields the before-state carries are restored; fields passed as None are
    CLEARED (a value the correction added must not survive its own undo).
    One transaction through update_food_entry(RECORDED_REPLAY).

    ⛔ EXACTLY-ONCE, THE B-1.8b.1 LIFECYCLE *(review P1)*: the first cut of
    this branch returned from the stage BEFORE any claim and passed no
    claim_id, so the same undo turn redelivered produced a SECOND restore
    mutation and event. Now: reserve (commit=False) -> restore -> update +
    ledger -> complete claim -> ONE COMMIT. Returns None on a replay.
    """
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

    claim_id = None
    if idempotency:
        from core.idempotency import claim_request
        turn_id, message = idempotency
        claim = await claim_request(
            db, channel="canonical", command="restore", user_id=int(user.id),
            client_key=str(turn_id), turn_id=str(turn_id),
            payload={"entry_id": int(entry_id), "before": before,
                     "message": message},
            commit=False)
        if claim.replay:
            return None
        claim_id = claim.record_id

    changes = {}
    for k, v in (before or {}).items():
        if k in ("entry_id", "source", "food_hint"):
            continue
        changes["parsed_food_name" if k == "food_name" else k] = v
    updated = await update_food_entry(
        db, entry.id, int(user.id), ledger_source="ledger_undo:canonical",
        claim_id=claim_id, authority=MutationAuthority.RECORDED_REPLAY,
        **changes)
    if updated is None:                                  # pragma: no cover
        raise CorrectionRefused(f"entry {entry_id} vanished mid-restore")
    logger.info("event=canonical_state_restored entry=%s fields=%d",
                entry.id, len(changes))
    return changes
