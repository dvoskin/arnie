"""WHICH LANE OWNS THIS FOOD TURN — one function, asked once.

Until now the answer had TWO owners. `conversation.py` decided whether the
client could render a canonical interaction and passed the verdict in;
`try_take_ownership` separately asked the rollout gate whether the user was in
the cohort. Both answer the same question — "is this turn canonical?" — and a
predicate with two owners drifts. It had already started to: the capability
half was computed by the caller and the cohort half by the callee, so no
single place could be read to find out what the system would do.

    canonical_food_enabled(user_id=…, channel=…)  ->  LaneDecision

THE DECISION IS TYPED, NOT A BOOL. A caller needs three things from it and a
bool carries one: whether the turn is canonical, WHY (for telemetry and for
the operator asking why their turn went legacy), and — when it is canonical —
what the client can actually do with the payload. Returning a bool forced the
other two to be recomputed elsewhere, which is how the second owner appeared.

ONE GATE, ONE MOMENT. This is asked before a `PendingOperation` exists and
never after. Once a canonical operation owns a meal it owns it to a terminal
state regardless of what this function would say a second later — narrowing
the cohort or tripping the halt stops NEW work and strands nothing in flight.
`core.b1_gate`'s C10 test is the executable form of that rule.

WHAT THIS IS NOT
----------------
It is NOT the slice predicate. "Does B-1 have a quantity worth asking about"
is a per-slice question about the MATERIAL (`quantity_clarification.
is_eligible`), and it changes every time a slice is added. This function is
about the USER and the CLIENT, and it is the same question for B-1, B-1.5 and
B-2. Merging them would make every new slice a rollout change.

NO `build` PARAMETER, DELIBERATELY — AND IT IS A PROMOTION BLOCKER
------------------------------------------------------------------
The obvious signature is `canonical_food_enabled(user_id, channel, build)`,
and it is the right one. It is not written yet because NOTHING CARRIES A
CLIENT BUILD: no header, no field, nothing reaches the backend. Adding the
parameter now would mean accepting a value that is always None and pretending
a check exists — the same defect as a frozen enum member with no producer.

What it costs today: `_CHANNEL_CAPABILITY` claims `ios` is `ID_ADDRESSED`,
which is a claim about the whole platform rather than about the app in the
user's hand. An older build that cannot decode `interaction` receives
`ask_copy(capability=ID_ADDRESSED)` — the introduction ALONE, with the options
carried only in the payload it cannot read. The user sees "How much chicken
breast?" and nothing to pick from. Free text still works, so nothing is lost;
but the options are invisible and their usage rate reads zero.

Harmless while the allowlist is one user on a known build. NOT harmless at
promotion, which is exactly when every old build in the wild arrives at once.
Closing it needs an iOS-side version header and a plumb-through to here, and
that is recorded in the directive as a promotion blocker rather than left as
a comment someone finds later.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


class LaneReason:
    """WHY a turn went to the lane it did. Strings, closed by convention and
    pinned by a test — a client never branches on these, but an operator reads
    them and a dashboard groups by them."""
    CANONICAL = "canonical"
    NO_USER = "no_user"
    HALTED = "halted"
    NOT_IN_COHORT = "not_in_cohort"
    CLIENT_INCAPABLE = "client_incapable"
    GATE_FAILED = "gate_failed"


@dataclass(frozen=True)
class LaneDecision:
    """Which lane owns this turn, why, and what the client can do."""
    canonical: bool
    reason: str
    cohort: str = ""
    #: `ID_ADDRESSED` or `LABEL_TEXT` when canonical; None when not. Carried
    #: so the caller does not re-derive it from the channel — that derivation
    #: existing twice is what this module was written to remove.
    capability: Optional[str] = None

    @property
    def legacy(self) -> bool:
        return not self.canonical


def canonical_food_enabled(*, user_id, channel) -> LaneDecision:
    """Does the canonical food spine own this user's turn?

    ORDER IS PRECEDENCE, and the halt is first for the reason it exists: an
    allowlist entry that could outrank a kill switch is not a kill switch.

        halt  ->  cohort  ->  client capability

    FAILS TO LEGACY, ALWAYS. Every error path returns the lane the user is
    already on. A rollout control may never cost someone a logged meal.
    """
    from skills.nutrition import quantity_rollout as qr

    if user_id is None:
        return LaneDecision(False, LaneReason.NO_USER)

    try:
        cohort = qr.cohort_label(user_id)
        if qr.halted():
            return LaneDecision(False, LaneReason.HALTED, cohort=cohort)
        if not qr.may_take_ownership(user_id):
            return LaneDecision(False, LaneReason.NOT_IN_COHORT, cohort=cohort)

        capability = _capability_of(channel)
        if capability is None:
            # AN EXCLUSION, NOT A DOWNGRADE. A client that cannot read the
            # canonical payload stays WHOLLY legacy. Sending it the canonical
            # question rendered as prose would keep the sentence parser alive
            # inside its own replacement.
            return LaneDecision(False, LaneReason.CLIENT_INCAPABLE,
                                cohort=cohort)
        return LaneDecision(True, LaneReason.CANONICAL, cohort=cohort,
                            capability=capability)
    except Exception:
        logger.warning("canonical lane gate failed; staying legacy",
                       exc_info=True)
        return LaneDecision(False, LaneReason.GATE_FAILED)


def capability_for(channel) -> Optional[str]:
    """WHAT THIS CLIENT CAN DO — the lane's single reading of the table, for
    callers that need the capability WITHOUT the rollout gate.

    The product-bound ask is one: it runs inside general settlement, under
    ITS allowlist, and must not also inherit the B-1 quantity cohort — two
    rollouts coupled by accident. It still may not read the table itself
    (`test_one_module_owns_the_channel_capability_table`), because three
    readings of one fact is what recorded a question as `id_addressed` while
    showing it as label text.
    """
    return _capability_of(channel)


def _capability_of(channel) -> Optional[str]:
    """Imported inside the call to keep the module graph acyclic —
    `b1_quantity_operation` imports this one."""
    from core.b1_quantity_operation import (channel_capability,
                                            client_renders_interactions)

    if not client_renders_interactions(channel):
        return None
    return channel_capability(channel)
