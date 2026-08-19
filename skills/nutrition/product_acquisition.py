"""⭐ P17f.5 — EXACT-PRODUCT ACQUISITION. THE ONLY PLACE A BARCODE MEETS A NETWORK.

    iOS scan -> raw barcode (SEPARATE from prose) -> THIS module, at INGRESS
             -> exact OFF fetch -> append immutable snapshot -> snapshot id
             -> bound to the turn's single food item
             -> settlement LOADS the snapshot locally. Zero provider calls.

⛔⛔ ACQUISITION MAY ADD EVIDENCE; SETTLEMENT MAY ONLY READ EVIDENCE. This module
is imported by the API ingress and by nothing on the settle path — enforced by
test, because "the wire must not reopen network-at-settlement" is the exact
boundary P17 spent a tranche closing.

⛔ THE BARCODE IS NEVER RECONSTRUCTED FROM PROSE. There is no text parsing in
this module and must never be: the scan message ("I scanned a barcode — ...")
remains presentation/context only, and a client that did not send the code
separately has not sent a code.

⚠ FAILURE IS ALWAYS None, NEVER AN ERROR. A dead OFF, a malformed code, an
unknown product — the meal continues UNBOUND and prices exactly as it does
today. Acquisition is an enrichment of the turn, not a gate on it.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: The snapshot id acquired for THIS turn, or None. Set UNCONDITIONALLY at
#: ingress every turn — the `PRIOR_REPLY_UNSEEN` lesson: a reused task's stale
#: value from an earlier turn must never leak into this one.
SCANNED_PRODUCT_EVIDENCE: ContextVar[Optional[int]] = ContextVar(
    "SCANNED_PRODUCT_EVIDENCE", default=None)

#: ⛔⛔ ATTACHMENT IS NOT BINDING *(CF5b review, 2026-08-18)*.
#: `SCANNED_PRODUCT_EVIDENCE` says a barcode was ATTACHED to this turn. It does
#: NOT say the scan BOUND to the food being settled — a scan names ONE product,
#: so a turn about several foods binds nothing at all. Reading the attachment
#: as if it were a binding is how a guard meant for bound turns changed a turn
#: it had bound nothing to. MEASURED against the real executor:
#:
#:     log "1 bag" (210 kcal); then, with a scan attached, a MIXED turn
#:     [update(bag -> "9 chips"), log(soup)]. The scan binds NOTHING (two
#:     foods) — but the correction guard read the ATTACHMENT and raised, and
#:     `_apply_portion_correction`'s bare except left `changes` untouched, so
#:     the row was written "9 chips" beside the WHOLE BAG's 210 kcal.
#:     Unbound, the identical turn correctly rescales to 90.1 kcal.
#:
#: A portion and a value allowed to disagree — the class this codebase fixed
#: once already. So the DECISION is represented explicitly, in ONE place, and
#: every downstream guard reads THIS rather than re-deriving it:
#:
#:     None                 no scan on this turn
#:     ATTACHED             a barcode was acquired; no decision made yet
#:     BOUND(snapshot_id)   the scan binds the single food this turn settles
#:     SKIPPED_MULTI_ITEM   attached, but several foods — it binds nothing
#:     CONSUMED             the binding has been settled or handed to an ask
#:
#: Operation counting is a planner INPUT to the decision, made once in
#: `NativeExecutionStage.run`; it is never a second definition of "bound".
@dataclass(frozen=True)
class ScanBinding:
    """What the scan attached to this turn actually did."""
    kind: str
    snapshot_id: Optional[int] = None

    @property
    def is_bound(self) -> bool:
        return self.kind == "bound"

    def __str__(self) -> str:                            # for log lines
        return (f"{self.kind}({self.snapshot_id})" if self.snapshot_id
                else self.kind)


ATTACHED = "attached"
BOUND = "bound"
SKIPPED_MULTI_ITEM = "skipped_multi_item"
CONSUMED = "consumed"
#: ⛔ CF5c — "I could not tell" is NOT "it binds nothing". The second is a
#: decision every downstream reader may act on; the first is the absence of
#: one, and a reader that conflates them proceeds on an unknown about
#: AUTHORITY. Recorded explicitly so `core.scan_authority` can refuse it.
UNDECIDABLE = "undecidable"

SCAN_BINDING: ContextVar[Optional[ScanBinding]] = ContextVar(
    "SCAN_BINDING", default=None)


def begin_turn() -> None:
    """Clear BOTH the attachment and the binding decision, unconditionally,
    at ingress — the PRIOR_REPLY_UNSEEN lesson applied to the decision as
    well as the id. A stale "bound" from an earlier scan would otherwise be
    read as THIS turn's binding, which is the same leak one level up. Called
    at ingress before anything else, and by tests that need a clean turn."""
    SCANNED_PRODUCT_EVIDENCE.set(None)
    SCAN_BINDING.set(None)


def attach(snapshot_id: Optional[int]) -> None:
    """A barcode was acquired for this turn. ATTACHED, not yet bound."""
    if snapshot_id is None:
        return
    SCANNED_PRODUCT_EVIDENCE.set(int(snapshot_id))
    SCAN_BINDING.set(ScanBinding(ATTACHED, int(snapshot_id)))


def decide_binding(*, bound: bool) -> Optional[ScanBinding]:
    """The ONE decision point: does this turn's scan bind? Called once, from
    the execution stage, which is the first place the turn's operations are
    known. Returns the new state (None when no scan is attached)."""
    current = SCAN_BINDING.get()
    snapshot_id = (current.snapshot_id if current is not None
                   else SCANNED_PRODUCT_EVIDENCE.get())
    if snapshot_id is None:
        return None
    # A turn whose attachment was set without `attach()` still decides: the
    # ID is the attachment's truth, the STATE is the binding's. Deriving the
    # missing ATTACHED here keeps the decision total rather than silently
    # leaving a scanned turn undecided.
    state = ScanBinding(BOUND if bound else SKIPPED_MULTI_ITEM, snapshot_id)
    SCAN_BINDING.set(state)
    logger.info("event=scan_binding_decided state=%s", state)
    return state


def consume_binding() -> None:
    """The binding has been settled, or handed to an ask that holds the
    snapshot. It is no longer live for this turn's later stages."""
    current = SCAN_BINDING.get()
    if current is not None and current.is_bound:
        SCAN_BINDING.set(ScanBinding(CONSUMED, current.snapshot_id))


def scan_is_bound() -> bool:
    """True only when the scan attached to this turn actually BOUND. The one
    reader of the disposition, so "is this turn bound" has a single answer."""
    try:
        state = SCAN_BINDING.get()
    except Exception:                                    # noqa: BLE001
        return False
    return bool(state is not None and state.is_bound)


async def acquire_product_evidence(db, barcode, *, serving_unit: str = "",
                                   package_unit: str = "") -> Optional[int]:
    """Fetch the exact product ONCE, persist the snapshot, return its id.

    ⭐ FETCH FIRST, LOCAL FALLBACK SECOND. A live fetch captures the provider's
    current facts as a fresh immutable snapshot (append-only — identical facts
    dedupe, changed facts insert). When the provider is unreachable, the NEWEST
    local snapshot for this code still binds: yesterday's evidence is evidence,
    and a network flake must not turn a scanned product into an estimate.
    """
    from skills.nutrition.product_store import (append_product_evidence,
                                                canonical_code,
                                                latest_product_evidence)

    code = canonical_code(barcode)
    if not code or not (6 <= len(code) <= 14):
        return None

    record = None
    try:
        from skills.nutrition.off import fetch_product

        record = await fetch_product(code)
    except Exception:                                    # noqa: BLE001
        logger.warning("acquisition: OFF fetch failed for %s", code,
                       exc_info=True)

    if record is not None:
        try:
            row = await append_product_evidence(
                db, record=record, serving_unit=serving_unit,
                package_unit=package_unit)
            if row is not None:
                logger.info("event=product_acquired code=%s snapshot=%s "
                            "rev=%s", code, row.id, row.provider_revision)
                # ⭐ P17-UA — deterministic unit enrichment AT ACQUISITION:
                # if the record's structured serving/quantity text names a
                # consumer unit (sources 2/3), persist that fact beside the
                # snapshot. If it does not, nothing is persisted and the
                # bound path will ASK (source 4). Failure here binds nothing
                # extra and costs nothing.
                try:
                    from skills.nutrition.off import consumer_unit_alias_from_off
                    from skills.nutrition.product_store import append_unit_evidence
                    alias = consumer_unit_alias_from_off(record)
                    if alias is not None:
                        unit, ups, provenance, ref = alias
                        await append_unit_evidence(
                            db, product_evidence_id=int(row.id),
                            consumer_unit=unit, units_per_serving=ups,
                            provenance=provenance, source_reference=ref)
                except Exception:                        # noqa: BLE001
                    logger.warning("acquisition: unit enrichment failed for %s",
                                   code, exc_info=True)
                return int(row.id)
        except Exception:                                # noqa: BLE001
            logger.warning("acquisition: persist failed for %s", code,
                           exc_info=True)

    try:
        existing = await latest_product_evidence(db, code)
    except Exception:                                    # noqa: BLE001
        logger.warning("acquisition: local lookup failed for %s", code,
                       exc_info=True)
        return None
    if existing is not None:
        logger.info("event=product_acquired code=%s snapshot=%s source=local",
                    code, existing.id)
        return int(existing.id)
    return None
