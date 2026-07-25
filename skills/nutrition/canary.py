"""Canary controls for the nutrition resolver (PR #29).

Today the resolver goes live by allowlist: name the user ids, and those users
get the new numbers. That works to five users and stops working at fifty, and
it has no answer at all to the question that follows the first widening —
"something looks wrong, turn it down" — because the only lever is editing a
list of ids.

So this adds the two things a rollout needs beyond a list.

**A cohort you can widen by percentage, deterministically.** The bucket comes
from a stable hash of the user id, not from a random draw, so a user does not
flap between the old and new system turn to turn. Flapping is worse than either
side: it makes every report irreproducible and every user's history internally
inconsistent.

Widening is monotonic by construction — a user in the 10% cohort is still in
the 25% cohort, because the bucket is a property of the id rather than of the
percentage. Going from 10 to 25 therefore adds users and never swaps them, and
rolling back from 25 to 10 removes exactly the ones that were added.

**A halt that does not need a human.** The readiness gates already know what
"unsafe" looks like. What was missing is anything that reads them while the
rollout is running and stops it. `evaluate()` turns a readiness report into a
typed decision, and `halted()` reads the resulting flag on the live path.

Two deliberate asymmetries:

*Halting is automatic; resuming is not.* An automatic resume would oscillate
against whatever caused the halt, and the halt is exactly the moment a person
should look. The flag is set by the operator or the deploy that clears it.

*A halt disables OWNERSHIP, not observation.* Shadow logging keeps running
through a halt, because the data explaining why it halted is produced by the
thing that halted.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

CANARY_VERSION = "canary_v1"

#: Buckets a user id can fall into. 1000 rather than 100 so a 0.5% canary is
#: expressible — the first live cohort should be able to be smaller than one
#: percent of users, and rounding it up to one is how a canary stops being one.
BUCKETS = 1000


class Verdict(str, Enum):
    HEALTHY = "healthy"
    WATCH = "watch"              # something moved; do not widen
    HALT = "halt"                # a zero-tolerance gate broke


@dataclass(frozen=True)
class HaltDecision:
    """Why the rollout should or should not continue.

    `reasons` are the gate names, not prose: the operator needs to know which
    threshold broke so they can look at the same number, and a sentence loses
    that.
    """
    verdict: Verdict = Verdict.HEALTHY
    reasons: Tuple[str, ...] = ()
    stage: str = ""
    checked: int = 0

    @property
    def should_halt(self) -> bool:
        return self.verdict is Verdict.HALT

    @property
    def may_widen(self) -> bool:
        return self.verdict is Verdict.HEALTHY

    def log_line(self) -> str:
        return (f"event=canary_evaluation verdict={self.verdict.value} "
                f"stage={self.stage or '-'} checked={self.checked} "
                f"reasons={','.join(self.reasons) or '-'}")


# ── cohort selection ──────────────────────────────────────────────────────────
def bucket_for(user_id) -> Optional[int]:
    """This user's stable bucket in [0, BUCKETS), or None for an unknown user.

    Hashed rather than `user_id % BUCKETS` because sequential ids are not
    uniformly distributed against anything you would later want to correlate —
    signup order, in particular, tracks tenure, and a canary that is secretly a
    cohort of the oldest accounts is measuring tenure and calling it safety.
    """
    if user_id is None:
        return None
    digest = hashlib.sha1(f"nutrition_resolver:{user_id}".encode("utf-8"))
    return int(digest.hexdigest()[:8], 16) % BUCKETS


def canary_percent() -> float:
    """The percentage of users the canary covers. 0 means allowlist-only."""
    raw = (os.getenv("NUTRITION_RESOLVER_CANARY_PCT", "") or "").strip()
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return 0.0
    return min(100.0, max(0.0, pct))


def in_canary(user_id) -> bool:
    """Whether this user is inside the percentage cohort."""
    pct = canary_percent()
    if pct <= 0:
        return False
    if pct >= 100:
        return True
    bucket = bucket_for(user_id)
    return bucket is not None and bucket < (pct / 100.0) * BUCKETS


def cohort_label(user_id) -> str:
    """What to stamp on a trace: which mechanism put this user on the new path.

    Recorded because "the canary looks worse than baseline" is meaningless
    without knowing that the allowlist is the team's own accounts, who log
    stranger food than anyone.
    """
    if halted():
        return "halted"
    from skills.nutrition.promotion import _allowlist, resolver_mode
    if resolver_mode() != "live":
        return "off" if resolver_mode() == "off" else "shadow"
    if user_id is not None and user_id in _allowlist():
        return "allowlist"
    if in_canary(user_id):
        return "canary"
    return "control"


# ── the halt flag ─────────────────────────────────────────────────────────────
def halted() -> bool:
    """Whether the rollout is currently stopped.

    Read on the live path, so it stays a plain environment read: an
    availability dependency here would mean the resolver goes dark whenever the
    thing storing the flag does.
    """
    raw = (os.getenv("NUTRITION_RESOLVER_HALT", "") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def owns_committed_values(user_id=None) -> bool:
    """The canary-aware version of promotion's gate.

    Ordering matters and is the whole contract:

        halted        → nobody, regardless of allowlist. A halt that the
                        allowlist could override is not a halt.
        not live      → nobody.
        allowlisted   → yes. An explicitly named user is always in.
        in canary     → yes.
        allowlist set → no. A configured allowlist with no canary means
                        allowlist-only, which is the pre-canary behaviour.
        otherwise     → yes, the unrestricted live case.
    """
    from skills.nutrition.promotion import MODE_LIVE, _allowlist, resolver_mode
    if halted():
        return False
    if resolver_mode() != MODE_LIVE:
        return False
    allow = _allowlist()
    if user_id is not None and user_id in allow:
        return True
    if in_canary(user_id):
        return True
    return not allow


# ── evaluation against the readiness gates ────────────────────────────────────
#: Gates whose failure halts the rollout on its own, over and above the
#: zero-tolerance ones readiness already marks `absolute`. A crash rate is not
#: zero-tolerance as a threshold — some floor of failure is survivable — but
#: exceeding it during a rollout means the new path is the thing crashing.
EXTRA_HALT_GATES = ("resolver_crash_rate",)


def halt_gates() -> frozenset:
    """The gates that halt, derived from readiness rather than restated.

    Listing them again here would be a second source of truth for "which
    failures are correctness violations", and the two would drift the first
    time a gate was added. `absolute` in readiness.GATES already means exactly
    this, so it is read rather than copied.
    """
    try:
        from skills.nutrition.readiness import GATES
        absolute = {name for name, spec in GATES.items()
                    if spec.get("absolute")}
    except Exception:
        absolute = set()
    return frozenset(absolute | set(EXTRA_HALT_GATES))


def evaluate(report: Mapping, *, stage: str = "") -> HaltDecision:
    """Turn a readiness report into a rollout decision.

    Reads the report rather than recomputing anything, so the number that halts
    a rollout is the same number the readiness CLI prints. Two systems computing
    "the crash rate" slightly differently is how an operator ends up unable to
    reproduce the thing that stopped their deploy.

    An `insufficient` gate is NOT a pass and NOT a halt: too little data to
    judge means do not widen, which is exactly WATCH.
    """
    gates = _gates_from(report)
    if not gates:
        # Nothing measured. Emphatically not healthy — an empty report is the
        # shape a broken log pipeline produces, and treating it as a green
        # light would make the pipeline failing look like the system passing.
        return HaltDecision(verdict=Verdict.WATCH, reasons=("no_metrics",),
                            stage=stage, checked=0)

    failed, unclear = [], []
    for name, verdict in gates.items():
        if verdict == "fail":
            failed.append(name)
        elif verdict in ("insufficient", "unmeasured"):
            unclear.append(name)

    breached = [name for name in failed if name in halt_gates()]
    if breached:
        return HaltDecision(verdict=Verdict.HALT, reasons=tuple(sorted(breached)),
                            stage=stage, checked=len(gates))
    if failed or unclear:
        return HaltDecision(verdict=Verdict.WATCH,
                            reasons=tuple(sorted(failed + unclear)),
                            stage=stage, checked=len(gates))
    return HaltDecision(verdict=Verdict.HEALTHY, stage=stage,
                        checked=len(gates))


def _gates_from(report: Mapping) -> dict:
    """{gate name: verdict} out of a readiness report.

    Only entries carrying a verdict count. `readiness.build_report` puts every
    metric in the same dict and sets `verdict: None` for the ones that are not
    gates — an agreement rate is deliberately ungated, and reading it as a
    passing gate would let a number nobody promised anything about vote on
    whether a rollout continues.
    """
    out = {}
    if not isinstance(report, Mapping):
        return out
    metrics = report.get("metrics")
    if not isinstance(metrics, Mapping):
        return out
    for name, value in metrics.items():
        verdict = value.get("verdict") if isinstance(value, Mapping) else value
        if verdict is None:
            continue
        out[name] = str(verdict)
    return out


def plan(report: Mapping = None, *, user_id=None) -> dict:
    """The current rollout posture, as one record for logging or a dashboard."""
    decision = evaluate(report or {})
    return {
        "mode": _mode(),
        "halted": halted(),
        "canary_pct": canary_percent(),
        "allowlist_size": len(_allow()),
        "cohort": cohort_label(user_id) if user_id is not None else "",
        "verdict": decision.verdict.value,
        "reasons": list(decision.reasons),
        "version": CANARY_VERSION,
    }


def _mode() -> str:
    from skills.nutrition.promotion import resolver_mode
    return resolver_mode()


def _allow() -> set:
    from skills.nutrition.promotion import _allowlist
    return _allowlist()
