"""⛔⛔ CF5c — ONE SCAN AUTHORITY *(Danny, 2026-08-19)*.

A scan attachment is the strongest identity statement a user can make. Four
production-shaped routes were found around the guards that were supposed to
honour it, and each fix added another local guard:

    ios:D3B7757E   implicit ratio correction of a board row   (CF5b)
    mixed turn     attachment read as binding                 (CF5b review 2)
    undecidable    the decision itself failed open            (CF5b review 3)
    zero-op        early return before any decision ran       (this)

The pattern is the finding: guards placed where the damage SURFACED, each
re-deriving "is this bound?" from whatever it had to hand. So the decision
becomes ONE SEMANTIC AUTHORITY with three physical touch points, and every
other guard is stripped to a backstop that reads the disposition and fails
closed on a shape that cannot be:

    PRE-PLAN     an attached scan suppresses confirm replay and pending-prior
                 consumption. A scan is a fresh exact statement; it is not an
                 answer to an open question, and it must not be absorbed by a
                 replay of some earlier confirmed meal.
                     -> `suppresses_replay_and_prior()`

    POST-PLAN    the disposition is decided from the COMPLETE plan — the
                 operations AND the clarification's items — never from the
                 approved writes alone. `FoodValidationStage` approves only
                 the READY items of an ask, so a two-food clarification can
                 expose exactly one approved operation; counting those would
                 bind a scan to a turn that names two foods.
                     -> `decide_from_plan(plan)`

    EXECUTION    the decision is consumed before every early return, every
                 correction route and every legacy route. BOUND means exactly
                 one `log_food`; every other shape refuses.
                     -> `require_shape(ops)` / `disposition()`

THE DISPOSITIONS, and none of them is "carry on":

    None                 no scan on this turn — nothing to protect
    BOUND                binds the single food this turn settles
    SKIPPED_MULTI_ITEM   attached, several foods — it binds nothing, and the
                         turn proceeds exactly as an unscanned turn would
    UNDECIDABLE          attached and the disposition could not be established
                         — an UNKNOWN about authority, which refuses

⚠ `UNDECIDABLE` is not `SKIPPED_MULTI_ITEM`. "It binds nothing" is a decision;
"I could not tell" is the absence of one, and every downstream reader would
mistake the second for the first — which is precisely how review round 3's
fail-open restored the original bug.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

#: Operations that name a food on the board. A scan names ONE product, so the
#: count of these decides whether it can bind at all. Declared once, here,
#: because a second copy at a guard site is a second definition of "bound".
FOOD_OPS = frozenset({"log_food", "update_food_entry", "delete_food_entry"})

#: The clarification fields that leave QUANTITY as the only open question. An
#: ask limited to these on a single bound product is the CF9 case: the durable
#: ask holds the snapshot and the answer settles bound.
QUANTITY_FIELDS = frozenset({"quantity", "amount", "portion", "size",
                             "serving", "servings"})


class ScanAuthorityRefusal(Exception):
    """A scanned turn whose shape cannot be honoured. Raised BEFORE any write,
    any claim and any legacy route — non-mutating by construction — and
    answered in user-grade words at the entrypoint's canonical-refusal seam.
    Typed apart by `reason` so the copy can say what actually happened."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(
            f"scanned turn refused ({reason})"
            + (f": {detail}" if detail else "")
            + " — nothing written, no legacy")


def scan_attached() -> bool:
    """A barcode rode this turn. NOT a binding."""
    try:
        from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
        return SCANNED_PRODUCT_EVIDENCE.get() is not None
    except Exception:                                    # noqa: BLE001
        return False


def snapshot_id() -> Optional[int]:
    try:
        from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE
        return SCANNED_PRODUCT_EVIDENCE.get()
    except Exception:                                    # noqa: BLE001
        return None


def disposition() -> Optional[str]:
    """The decided disposition, or None when no scan rode this turn.

    ⛔ An ATTACHED scan that has not been decided reads as UNDECIDABLE, not as
    "not bound": a reader that cannot distinguish "binds nothing" from "no
    decision was made" is the fail-open this module exists to delete."""
    from skills.nutrition.product_acquisition import (ATTACHED, BOUND,
                                                      CONSUMED, SCAN_BINDING,
                                                      SKIPPED_MULTI_ITEM,
                                                      UNDECIDABLE)
    state = SCAN_BINDING.get()
    if state is None:
        # No state at all. If an id is attached, the decision never ran.
        return UNDECIDABLE if scan_attached() else None
    kind = getattr(state, "kind", None)
    if kind in (BOUND, SKIPPED_MULTI_ITEM, UNDECIDABLE, CONSUMED):
        return kind
    if kind == ATTACHED:
        return UNDECIDABLE
    return UNDECIDABLE


def is_bound() -> bool:
    """The ONE question, one answer. Never re-derived from operation shape."""
    from skills.nutrition.product_acquisition import BOUND
    return disposition() == BOUND


# ── PRE-PLAN ────────────────────────────────────────────────────────────────

def suppresses_replay_and_prior() -> bool:
    """⛔ A SCAN IS A FRESH EXACT STATEMENT, NOT AN ANSWER.

    An attached scan suppresses BOTH the confirm replay and the pending-prior
    consumption, and it does so on ATTACHMENT rather than on binding — the
    disposition is not decided yet at plan time, and the whole point is that
    the earlier question must not shape this turn's plan.

    `ConfirmReplayPlanStage` was the hole: "yes" to an open confirm replays
    the stashed items VERBATIM, so scan + "yes" would log some earlier
    confirmed food and then attach this scan's snapshot to it — one product's
    nutrition committed under another product's name, the P1 identity failure
    through a door upstream of every identity guard."""
    return scan_attached()


# ── POST-PLAN ───────────────────────────────────────────────────────────────

def foods_in_plan(plan) -> int:
    """How many foods this turn is ABOUT, read off the complete plan.

    ⛔ THE COMPLETE PLAN, NOT THE APPROVED WRITES. `FoodValidationStage`
    approves only the READY items of an ask — a two-food clarification can
    expose exactly one approved operation, and counting those would bind a
    scan to a turn naming two foods. The clarification's own item list is the
    other half of the truth, so the count is the MAX of the two views: the
    most foods any view of this turn shows. Conservative in the safe
    direction — more foods means the scan binds nothing."""
    views = []
    ops = tuple(getattr(plan, "operations", ()) or ())
    views.append(sum(1 for op in ops
                     if isinstance(op, dict) and op.get("name") in FOOD_OPS))
    for amb in tuple(getattr(plan, "ambiguities", ()) or ()):
        if isinstance(amb, dict):
            items = [i for i in (amb.get("items") or []) if isinstance(i, dict)]
            views.append(len(items))
    return max(views) if views else 0


def decide_from_plan(plan) -> Optional[str]:
    """THE decision. Called once, from the validation stage, which is the
    first place the COMPLETE plan is known. Returns the disposition, or None
    when no scan rode this turn.

    Fails closed: any failure to decide on a SCANNED turn records
    `UNDECIDABLE` rather than leaving the state ATTACHED, so every downstream
    reader sees an unknown instead of mistaking it for "binds nothing"."""
    from skills.nutrition.product_acquisition import (BOUND, SCAN_BINDING,
                                                      SKIPPED_MULTI_ITEM,
                                                      UNDECIDABLE, ScanBinding)
    sid = snapshot_id()
    if sid is None:
        return None
    try:
        count = foods_in_plan(plan)
        kind = BOUND if count == 1 else (
            SKIPPED_MULTI_ITEM if count >= 2 else UNDECIDABLE)
        if count == 0:
            logger.info("event=scan_authority_no_food snapshot=%s — a scanned "
                        "turn whose plan names no food at all", sid)
    except Exception:                                    # noqa: BLE001
        logger.warning("scan authority: the plan could not be counted",
                       exc_info=True)
        kind = UNDECIDABLE
    SCAN_BINDING.set(ScanBinding(kind, sid))
    logger.info("event=scan_authority_decided state=%s(%s) foods=%s",
                kind, sid, locals().get("count", "?"))
    return kind


# ── EXECUTION ───────────────────────────────────────────────────────────────

def require_shape(ops) -> None:
    """⛔ CONSUMED BEFORE EVERY EARLY RETURN, CORRECTION ROUTE AND LEGACY
    ROUTE. BOUND means EXACTLY ONE `log_food`; every other shape refuses.

    This is enforcement, not decision: it reads the disposition and checks the
    shape against it. It never counts its way to a different answer.

      UNDECIDABLE          -> refuse. An unknown about authority is not a
                              licence to proceed.
      BOUND + 1 log_food   -> proceed; the snapshot binds that item.
      BOUND + anything     -> refuse. A correction, a delete, a mixed plan or
                              several logs under a BOUND disposition is an
                              impossible shape: the gate said one food and the
                              executor is holding something else.
      BOUND + no ops       -> NOT refused here. The caller decides between the
                              CF9 durable ask (one product, quantity the only
                              unknown) and a typed refusal — it has the
                              clarification and this function does not.
      SKIPPED_MULTI_ITEM   -> proceed unchanged. The turn behaves exactly as
                              an unscanned turn would; that is the decision.
      None                 -> proceed. No scan, nothing to protect.
    """
    from skills.nutrition.product_acquisition import BOUND, UNDECIDABLE
    state = disposition()
    if state is None:
        return
    if state == UNDECIDABLE:
        raise ScanAuthorityRefusal(
            "undecidable",
            "a barcode rode this turn and whether it binds could not be "
            "established")
    if state != BOUND:
        return
    ops = list(ops or ())
    food = [op for op in ops
            if isinstance(op, dict) and op.get("name") in FOOD_OPS]
    if not ops:
        return                                   # the caller owns this branch
    logs = [op for op in food if op.get("name") == "log_food"]
    if len(ops) != 1 or len(logs) != 1:
        raise ScanAuthorityRefusal(
            "impossible_shape",
            f"BOUND requires exactly one log_food; this turn holds "
            f"{[op.get('name') for op in ops]}")


def quantity_only_ask_item(clarification) -> Optional[dict]:
    """The single item of a clarification whose ONLY open question is
    quantity, or None. The CF9 case: one consumed product, the amount
    unknown — a durable ask holding the snapshot, not a refusal.

    Anything else — several items, an identity or preparation question
    alongside, a clarification that names no item — is "another ambiguity"
    and the caller refuses instead."""
    if not isinstance(clarification, dict):
        return None
    items = [i for i in (clarification.get("items") or []) if isinstance(i, dict)]
    if len(items) != 1:
        return None
    fields = [str(a.get("field") or "").strip().lower()
              for a in (clarification.get("ambiguities") or [])
              if isinstance(a, dict)]
    if not fields or not all(f in QUANTITY_FIELDS for f in fields):
        return None
    return items[0]


def consume() -> None:
    """The binding has been settled or handed to an ask that holds it."""
    try:
        from skills.nutrition.product_acquisition import consume_binding
        consume_binding()
    except Exception:                                    # noqa: BLE001
        logger.warning("scan authority: consume failed", exc_info=True)
