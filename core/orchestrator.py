"""Tool-caller orchestrator (I) — the proactive reliability core (Danny 2026-07-23:
"the small orchestrator who helps facilitate tool calls quickly and reliably").

A SMALL/FAST model whose ONLY job: read the user's message and emit the correct
tool call(s) — nothing else. No persona, no coaching. A tiny focused prompt is
dramatically more reliable at CALLING than one model juggling the ~46k-token coach,
and it decays far less deep into a session. The big model then voices the committed
results (the talker/scribe split, realized for tool-CALLING rather than extraction).

This is the PROACTIVE counterpart to the [[DID]] manifest rescue: instead of
catching a dropped call after the fact, a reliable small caller makes it up front.
It composes with the shipped work — B verifies, D confirms deterministically,
E (scoping) would hand it a small tool set, F would order the calls.

Default ON (ORCHESTRATOR, 2026-07-23) — validated by the deep-session A/B benchmark
(scripts/bench_deep_session.py): it cut the deep-session drop rate 47%->36% over 5
runs and caught every deep exercise set the baseline dropped. Revert: ORCHESTRATOR=false.
scribe.py (parallel Haiku extraction) is the precedent.
"""
import logging
import os
from typing import List

from core.llm import chat

logger = logging.getLogger(__name__)

# Haiku 4.5 — small + fast; the whole point is a cheap reliable caller.
_ORCH_MODEL = "claude-haiku-4-5-20251001"


def orchestrator_enabled() -> bool:
    # Default ON (2026-07-23) — the deep-session A/B benchmark (scripts/bench_deep_session.py)
    # showed it cut the deep-session drop rate 47%->36% (and every deep exercise set
    # baseline dropped, the orchestrator caught). Revert with ORCHESTRATOR=false.
    return os.getenv("ORCHESTRATOR", "true").lower() in ("true", "1", "yes")


def orchestrator_model() -> str:
    return os.getenv("ORCHESTRATOR_MODEL", _ORCH_MODEL) or _ORCH_MODEL


_ORCH_SYSTEM = (
    "You are Arnie's TOOL CALLER. Your ONLY job: read the user's latest message and, "
    "if it reports or asks for something a tool performs, emit the exact tool call(s) "
    "— and NOTHING else. No chat, no coaching, no confirmation text.\n"
    "RULES:\n"
    "- Log EVERY distinct thing the user reports: each food is its own log_food, each "
    "distinct set/movement its own log_exercise. Never collapse two foods into one, "
    "never drop the small one (a mint, 2 starburst, egg whites).\n"
    "- Use the EXACT quantities/amounts from the message.\n"
    "- A nutrition question about a specific product → search_food_database (or "
    "web_search for a brand/restaurant item).\n"
    "- If the message is chit-chat, a plan they have NOT done yet, or a question no "
    "tool answers, emit NO tool call.\n"
    "- Do not re-log something already stated as logged earlier in the context."
)


async def call_tools(user_message: str, extra_context: str = "") -> List[dict]:
    """Run the small tool-caller over the message. Returns the tool calls it emits
    (possibly empty). NEVER raises — any failure returns [] so the caller falls back
    to the normal pass. Uses the SAME tool registry as the main turn (tools=True)."""
    if not (user_message or "").strip():
        return []
    try:
        system = _ORCH_SYSTEM + (("\n\n" + extra_context) if extra_context else "")
        res = await chat(
            [{"role": "user", "content": user_message}],
            system, tools=True, max_tokens=600, model=orchestrator_model(),
        )
        calls = res.get("tool_calls") or []
        logger.info(f"event=orchestrator calls={[c.get('name') for c in calls]}")
        return calls
    except Exception as e:
        logger.warning(f"orchestrator call_tools failed: {e}")
        return []
