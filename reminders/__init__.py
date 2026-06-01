"""
Reminders / proactive follow-up decision layer.

This package owns the cross-cutting *decisions* behind proactive outreach —
eligibility, suppression, frequency, and context-aware follow-up timing — as
pure, testable functions. The APScheduler wiring and LLM generation stay in
scheduler/proactive_scheduler.py; that module is the cron driver that asks this
package "should I, and what" and then renders + sends via the platform adapters.

Submodules:
  eligibility  — may we message this user *right now*? (window, timezone,
                 live-conversation, linked-account de-dup)
  suppression  — have we already fired this one-shot slot? (nudges_sent helpers)
  pending      — context-aware follow-ups: given an unanswered question, decide
                 whether to re-ask now and with what tone (tier-scaled timing,
                 spacing, re-ask caps, cold-user cutoff).

Nothing here sends a message or touches the network; callers do that. Proactive
messaging remains globally gated by PROACTIVE_MESSAGING_ENABLED in the scheduler.
"""
from reminders import eligibility, suppression, pending  # noqa: F401

__all__ = ["eligibility", "suppression", "pending"]
