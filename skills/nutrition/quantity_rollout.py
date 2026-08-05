"""The B-1 rollout gate: may the canonical quantity path TAKE OWNERSHIP?

One question, asked once, at one moment: before a `PendingOperation` is
created. That timing is the whole design.

WHY IT IS A PRE-OWNERSHIP GATE AND NOT A FEATURE FLAG
-----------------------------------------------------
A flag read on every turn would be read again on the ANSWER turn — and an
answer turn that finds the flag newly off would have to do something with a
meal the user is halfway through clarifying. Every available something is bad:
fall back to the legacy interpreter (which is how an answer becomes a second
meal, the measured defect B-1 exists to remove), silently drop the pending
operation (the meal vanishes), or ask again from scratch.

So the gate is evaluated ONCE. Once a canonical operation exists it owns that
meal to a terminal state — repair, cancellation, or commit — regardless of
what this module would say a second later. Narrowing the cohort or tripping
the halt stops NEW operations and strands nothing in flight. `core.b1_gate`'s
C10 test is the executable form of that rule; this module is only the "may we
start" half, and it deliberately has no "should we continue" function for a
caller to reach for.

CONTROLS, highest precedence first
----------------------------------
    B1_QUANTITY_HALT       kill switch; stops new ownership fleet-wide
    B1_QUANTITY_ALLOWLIST  comma-separated user ids — the first live cohort
    B1_QUANTITY_PERCENT    deterministic cohort, monotonic when widened

The percentage bucket comes from a stable hash of the user id under this
feature's OWN salt, so widening adds users and never swaps them, and the
cohort is uncorrelated with the resolver canary's. Sharing that salt would
have made B-1's 5% exactly the resolver's 5%, and every B-1 measurement would
carry resolver-V2 as a hidden covariate.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

#: Names this rollout's cohort. Never share a salt between features.
SALT = "b1_quantity"


def halted() -> bool:
    """The kill switch. Checked FIRST, so no allowlist entry can outrank it —
    an allowlist that could override a halt is not a halt."""
    return (os.getenv("B1_QUANTITY_HALT", "") or "").strip().lower() in (
        "1", "true", "yes", "on")


def allowlist() -> set:
    raw = os.getenv("B1_QUANTITY_ALLOWLIST", "") or ""
    out = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def percent() -> float:
    """Share of ELIGIBLE users the cohort covers. 0 means allowlist-only,
    which is the correct first live state."""
    raw = (os.getenv("B1_QUANTITY_PERCENT", "") or "").strip()
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, pct))


def in_cohort(user_id) -> bool:
    from skills.nutrition.canary import BUCKETS, bucket_for

    pct = percent()
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    bucket = bucket_for(user_id, salt=SALT)
    return bucket is not None and bucket < (pct / 100.0) * BUCKETS


def may_take_ownership(user_id) -> bool:
    """May the canonical quantity path own a NEW operation for this user?

    Call this before creating the pending operation and never after. Failing
    closed is correct here in a way it is not for the answer turn: refusing to
    START leaves the user on the path they are already on.
    """
    if user_id is None:
        return False
    try:
        if halted():
            return False
        return int(user_id) in allowlist() or in_cohort(user_id)
    except Exception:      # a rollout control may never cost a turn
        logger.warning("b1 rollout gate failed; staying legacy", exc_info=True)
        return False


def cohort_label(user_id) -> str:
    """Which mechanism put this user on the new path — stamped on every trace.

    "the canary looks worse than baseline" is meaningless without knowing that
    the allowlist is the team's own accounts, who log stranger food than
    anyone. `control` is claimed only when something is actually restricting
    the rollout: with no allowlist and no percentage there is no control group,
    everyone is treatment, and labelling them control made an earlier report
    compare a path against itself.
    """
    try:
        if halted():
            return "halted"
        if user_id is not None and int(user_id) in allowlist():
            return "allowlist"
        if in_cohort(user_id):
            return "cohort"
        if percent() > 0 or allowlist():
            return "control"
        return "off"
    except Exception:
        return "unknown"


def state() -> dict:
    """What `/health` publishes, so Stage 1 can verify the switch is OFF
    before anything is enabled — rather than inferring it from silence.

    `effective` leads, matching every other entry on that endpoint: one word
    that answers "what is production doing", with the numbers behind it for
    the reader who needs to know WHY. `allowlist_size` is a SIZE and never the
    ids — the endpoint is public.
    """
    pct, allow = percent(), allowlist()
    if halted():
        effective = "halted"
    elif allow and pct <= 0:
        effective = "allowlist"
    elif pct > 0:
        effective = f"cohort_{pct:g}pct"
    else:
        effective = "off"
    return {"effective": effective, "halted": halted(), "percent": pct,
            "allowlist_size": len(allow),
            "env_set": any(os.getenv(v) is not None for v in (
                "B1_QUANTITY_HALT", "B1_QUANTITY_ALLOWLIST",
                "B1_QUANTITY_PERCENT"))}
