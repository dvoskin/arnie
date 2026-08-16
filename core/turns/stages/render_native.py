"""Native rendering (P0.2 Phase 5).

Renders from the committed snapshot and nothing else. The rule the food lane
established, now enforced structurally: the reply's numbers are the ones in
the database after the write, so a refused CAS update or a dedup-blocked log
cannot be narrated as success.

Two shapes:
  • an ASK renders the clarification the policy engine chose — before any
    commit, which is why it never touches the snapshot;
  • a COMMIT renders through core.food_ledger.render_committed, which already
    owns say-safety (a model sentence carrying a database-dependent claim is
    replaced by the deterministic line) and the follow-up whitelist.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

RENDERER_VERSION = "turn_renderer_v1"


def _clarification_text(clarification) -> str:
    if clarification is None:
        return ""
    if isinstance(clarification, str):
        return clarification
    if isinstance(clarification, dict):
        return str(clarification.get("say") or clarification.get("question") or "")
    return ""


def _transaction_snapshot(snapshot, operations):
    """The food-shaped view of a committed turn, built from snapshot totals —
    never from the plan's own numbers."""
    from core.food_ledger import build_snapshot, compute_batch

    totals = snapshot.day_totals or {}
    remaining = snapshot.remaining_targets or {}
    day_cal = int(totals.get("calories") or 0)
    day_protein = int(totals.get("protein") or 0)
    # Targets are reconstructed from committed totals + what's left, so the
    # renderer has one source of truth instead of re-reading preferences.
    cal_target = day_cal + int(remaining.get("calories") or 0)
    protein_target = day_protein + int(remaining.get("protein") or 0)

    committed = _committed_operations(operations, snapshot)

    # ⛔⛔ THE COMMITTED NUMBERS WIN OVER THE PROPOSED ONES.
    #
    # `compute_batch("commit", ...)` sums `op["input"]["calories"]` — the
    # MODEL'S proposal. That was survivable while the only writer was the
    # legacy executor, which syncs committed macros back onto the input. It is
    # not survivable now: canonical settlement prices from the artifact and
    # never touches the input, so the exact failure available was
    #
    #     operation says   mackerel 180 cal
    #     artifact settles row at   305 cal
    #     day total shows           305
    #     the reply says   "Mackerel logged, 180 cal"
    #
    # — the renderer narrating the proposal over the committed row, which is
    # the one thing this whole migration says it must never do.
    #
    # ⚠ AND THE FALLBACK IS UNCHANGED. A receipt is present only when the
    # writer recorded one, so the legacy path takes exactly the branch it
    # always took. `build_snapshot` reads only LABELS from `committed`; every
    # number it renders comes from these two scalars.
    # ⛔ READ, NEVER RE-DERIVE. The first version of this branch SUMMED the
    # per-call receipts and C3 failed it correctly: "a fourth owner is how the
    # prose and the card came to disagree by one". `MealCommitResult.meal_totals`
    # is already the committed truth — `_read_back` computes it from the rows —
    # so the renderer takes it whole.
    settled = getattr(getattr(snapshot, "execution", None), "meal_totals", None)
    if settled:
        batch_cal = int(round(float(settled.get("calories") or 0.0)))
        batch_protein = int(round(float(settled.get("protein") or 0.0)))
    else:
        batch_cal, batch_protein = compute_batch("commit", committed, 0, 0)
    return build_snapshot(committed, batch_cal, batch_protein,
                          day_cal, day_protein, cal_target, protein_target)


def _identity(name, inp) -> tuple:
    """What makes two calls the same write. Name alone is not enough: a batch
    of two log_food calls, one blocked, would otherwise narrate both."""
    inp = inp or {}
    return (name,
            str(inp.get("food_name") or inp.get("food_hint") or "").strip().lower(),
            str(inp.get("entry_id") or ""))


def _committed_operations(operations, snapshot) -> list:
    """The operations a matching call actually committed. Anything the
    executor refused — dedup-blocked, stale CAS, missing entry — is dropped,
    because naming it in the reply is a lie with committed-looking numbers."""
    calls = getattr(getattr(snapshot, "execution", None), "calls", None) or ()
    committed = set()
    for c in calls:
        if getattr(c, "committed", False):
            committed.add(_identity(getattr(c, "name", ""),
                                    getattr(c, "raw_input", None)))
    return [op for op in operations
            if _identity(op.get("name"), op.get("input")) in committed]


class NativeRenderStage:
    """Snapshot in, text out. Never reads the plan's numbers, and never
    invents a reply for a turn that wrote nothing."""

    async def run(self, request, context=None, route=None, plan=None,
                  validation=None, snapshot=None):
        from core.platform import Response

        disposition = getattr(validation, "disposition", "")
        if disposition == "ask":
            text = _clarification_text(getattr(validation, "clarification", None))
            return Response.from_text(text) if text else None
        if disposition != "execute" or snapshot is None:
            return None

        ops = list(getattr(validation, "approved_operations", ()) or ())
        # Nothing committed → say nothing. The day line alone ("You're at
        # 1500 with 700 left") reads as a confirmation of a write that was
        # entirely refused, so the turn is handed back instead.
        if ops and not _committed_operations(ops, snapshot):
            return None
        try:
            from core.food_ledger import render_committed
            snap = _transaction_snapshot(snapshot, ops)
            text = render_committed(getattr(plan, "narration_hint", ""),
                                    "", "", snap)
        except Exception as e:
            logger.warning(f"native render fell back to totals: {e}")
            text = ""
        if not text.strip():
            return None
        return Response.from_text(text)
