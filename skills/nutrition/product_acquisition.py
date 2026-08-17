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
from typing import Optional

logger = logging.getLogger(__name__)

#: The snapshot id acquired for THIS turn, or None. Set UNCONDITIONALLY at
#: ingress every turn — the `PRIOR_REPLY_UNSEEN` lesson: a reused task's stale
#: value from an earlier turn must never leak into this one.
SCANNED_PRODUCT_EVIDENCE: ContextVar[Optional[int]] = ContextVar(
    "SCANNED_PRODUCT_EVIDENCE", default=None)


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
