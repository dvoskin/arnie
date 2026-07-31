"""What actually happened to a proactive message.

`_send` returned `None` on every path it has: the kill switch, the allowlist,
APNs not configured, no registered device, a provider rejection, and a genuine
delivery. `_send_logged` then wrote a `conversation_logs` row regardless, so a
proactive row in history means "we reached the send function" and nothing more.

Three things were built on top of that row, and all three inherited its
ambiguity:

  * the rolling 24h cadence budget counts proactive rows, so a user whose
    pushes are all failing is rate-limited as though they were being reached;
  * the silence streak treats a failed send as contact;
  * engagement analysis cannot separate "we never spoke" from "we spoke and
    they ignored us" from "we tried and the provider refused".

This module is the vocabulary that fixes it. A send returns a `DeliveryResult`,
and the statuses are deliberately more than success/failure, because the
operational responses differ: a SUPPRESSED message was never meant to go, an
INVALID_DESTINATION needs the token revoked, a FAILED one may be worth
retrying, and only ACCEPTED means a provider took responsibility for it.

ACCEPTED is not DELIVERED. APNs accepting a push is a promise to try, not proof
a phone displayed it; keeping them separate leaves room for a receipt callback
later without redefining what `accepted` already means.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: Never left the building — a kill switch, an allowlist, a quiet-hours rule.
#: Not a failure: nothing was supposed to be sent.
SUPPRESSED = "suppressed"
#: Handed to a provider and acknowledged. The strongest thing a send can claim
#: on its own; only this counts as having reached the user for cadence.
ACCEPTED = "accepted"
#: A provider or receipt confirmed it arrived. Nothing sets this yet — it is
#: here so `accepted` is not quietly overloaded to mean it.
DELIVERED = "delivered"
#: Tried and refused. Retryable in principle.
FAILED = "failed"
#: There is nowhere to send: no device token, no address, a revoked token.
#: Distinct from FAILED because retrying cannot help and the fix is to stop
#: holding a dead destination.
INVALID_DESTINATION = "invalid_destination"

TERMINAL_SUCCESS = (ACCEPTED, DELIVERED)


@dataclass
class DeliveryResult:
    """The outcome of one attempt to reach a user on one channel."""
    status: str
    channel: str = ""
    provider: str = ""
    #: How many destinations accepted, for a fan-out channel like APNs where a
    #: user may hold several devices. One acceptance is enough to say the user
    #: was reached; zero is not.
    accepted_count: int = 0
    attempted_count: int = 0
    provider_message_id: Optional[str] = None
    failure_code: str = ""
    #: Never the raw provider body — it can carry tokens and addresses.
    detail: str = ""
    invalidated: list = field(default_factory=list)

    @property
    def reached_user(self) -> bool:
        """True only when a provider took responsibility for the message.

        This is the predicate history, cadence and silence streaks must use. A
        suppressed or failed send did not reach anyone, and counting it as
        contact is how a user with a dead token gets rate-limited into silence.
        """
        return self.status in TERMINAL_SUCCESS and self.accepted_count > 0

    @classmethod
    def suppressed(cls, reason: str, channel: str = "") -> "DeliveryResult":
        return cls(status=SUPPRESSED, channel=channel, detail=reason)

    @classmethod
    def accepted(cls, channel: str, provider: str = "", count: int = 1,
                 message_id: Optional[str] = None) -> "DeliveryResult":
        return cls(status=ACCEPTED, channel=channel, provider=provider,
                   accepted_count=count, attempted_count=count,
                   provider_message_id=message_id)

    @classmethod
    def failed(cls, channel: str, code: str = "", detail: str = "",
               attempted: int = 1) -> "DeliveryResult":
        return cls(status=FAILED, channel=channel, failure_code=code,
                   detail=detail[:300], attempted_count=attempted)

    @classmethod
    def no_destination(cls, channel: str, detail: str = "") -> "DeliveryResult":
        return cls(status=INVALID_DESTINATION, channel=channel,
                   detail=detail[:300])
