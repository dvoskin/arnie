"""
Deep research turns — the agentic loop behind the `deep_research` tool.

When a user asks for a real-world PLAN that needs current outside facts
("I'm traveling tomorrow, build my eating strategy", "find gym options near
my hotel + where I get protein nearby", "plan my week around the race"),
one search round + a 700-token follow-up can't produce a ChatGPT-Plus-grade
answer. This module runs a bounded multi-round research loop:

    plan → search (several queries IN PARALLEL) → read → refine → search
    again if needed → synthesize an opinionated, cited plan in Arnie's voice.

Design constraints (v1):
  • WALL-CLOCK BUDGET is the hard constraint, not rounds: the live iOS
    clients (builds ≤218) time out the chat request at 30s
    (URLSessionConfiguration.timeoutIntervalForRequest), so the whole loop
    must land in ~22s. Budget is env-tunable (DEEP_RESEARCH_TIME_BUDGET) so
    it can rise when build 219 ships a longer timeout.
  • Queries within a round run CONCURRENTLY (asyncio.gather) — 3 searches
    cost one search's latency. This is what makes 2-3 rounds fit the budget.
  • Extended thinking is OFF by default (DEEP_RESEARCH_THINKING_BUDGET=0);
    at a 22s budget the tokens are better spent on searches. Flip the env
    when the client timeout rises.
  • Pure module: no DB access. The caller (tool executor) owns persistence,
    caps, and telemetry context. Never raises — degrades to a best-effort
    text answer.

The synthesis is composed directly in Arnie's voice with an opinionated
"My move:" close, so the outer follow-up only has to deliver it (see the
raised follow-up budget in core/conversation.py), not rebuild it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


# ── Config (env-tunable, read per-call so tests/Render can flip live) ─────────

def DEEP_MODEL() -> str:
    # The deep loop runs on the newest Sonnet — planning + synthesis quality is
    # the whole point. Falls back to the session default only if unset AND the
    # default env is set (keeps a single-env override possible).
    return os.getenv("DEEP_RESEARCH_MODEL", "claude-sonnet-5")


def TIME_BUDGET_S() -> float:
    # Research budget. The BINDING constraint is the iOS 30s request timeout
    # (builds ≤218): total turn ≈ pass-1 (~3-6s) + this loop + direct delivery
    # (no follow-up LLM pass — see conversation.py). The final synthesis call
    # generates INSIDE this window too (~10-15s measured at the synthesis token
    # cap), which is why the force-synthesis threshold reserves real headroom.
    # MEASURED 2026-07-07 (Sonnet 5, stubbed 2.5s searches): a 2-round run at
    # budget=18 landed 33.6s TOTAL — synthesis alone ~15s. 14 forces synthesis
    # after round one (~8s in), landing the loop ~22-25s. Raise via env once
    # build 219 ships the 90s client timeout.
    try:
        return float(os.getenv("DEEP_RESEARCH_TIME_BUDGET", "12"))
    except ValueError:
        return 12.0


def MAX_ROUNDS() -> int:
    try:
        return int(os.getenv("DEEP_RESEARCH_MAX_ROUNDS", "3"))
    except ValueError:
        return 3


def THINKING_BUDGET() -> int:
    # 0 = extended thinking off (default at the 22s budget).
    try:
        return int(os.getenv("DEEP_RESEARCH_THINKING_BUDGET", "0"))
    except ValueError:
        return 0


_MAX_PARALLEL_SEARCHES = 4      # per round — Tavily latency ~2-4s each, run together
_SYNTHESIS_MAX_TOKENS = 1100    # the final plan — a rich plan runs ~600-800 tokens;
                                # the cap bounds synthesis GENERATION TIME (~10-13s
                                # measured), which spends the same wall clock as the
                                # searches. Raise with the time budget in 219.
_SNIPPET_CHARS = 500            # per-result content kept for the loop (deeper than
                                # chat search's 300 — the loop READS, chat re-voices)


# ── Inner tool schema (self-contained — NOT the chat tool list) ───────────────

_INNER_TOOLS = [{
    "name": "web_search",
    "description": (
        "Search the live web. Call with up to four DIFFERENT queries in ONE "
        "response (they run in parallel). Use specific, dated queries "
        "('X hours July 2026', 'Y menu protein options') — not vague ones."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "One specific search query."},
        },
        "required": ["query"],
    },
}]


# ── Result payload ────────────────────────────────────────────────────────────

@dataclass
class DeepResult:
    """Outcome of one deep-research run. `plan` is the user-ready text (already
    in Arnie's voice, ||| bubble separators, 'My move:' close). Never empty on
    ok=True. `sources` are (title, url) picked up along the way."""
    ok: bool
    plan: str = ""
    sources: list = field(default_factory=list)   # [(title, url)]
    rounds: int = 0
    searches: int = 0
    elapsed_s: float = 0.0
    error: str = ""


# ── System prompt for the inner loop ─────────────────────────────────────────

_SYSTEM = """\
You are Arnie — a sharp, direct personal fitness & nutrition coach — in DEEP RESEARCH \
mode: the user asked for a real plan that needs current, specific outside facts, and \
you have a few search rounds to build it properly.

METHOD:
1. From the objective, decide the 2-4 facts you MUST verify (hours, menus, locations, \
schedules, prices, options). Fire those searches TOGETHER in one response.
2. Read the results. If a load-bearing fact is still missing or contradictory, search \
again (refined queries). Don't re-search what you already have.
3. Then STOP searching and write the plan.

THE PLAN (your final text response — this goes to the user nearly verbatim).
EXACT SHAPE, three parts separated by ||| (use ||| exactly twice, nowhere else):
  1. LEAD — one line, the single most useful read. No preamble.
  2. BODY — the plan as rich markdown: short sections with a **bold lead-in** each \
(day-by-day or theme-by-theme), blank line between sections, ~300 words max.
  3. CLOSE — one decisive line starting exactly "My move:" — the single best call, \
committed, not a menu of options. MANDATORY, never omitted.

BODY rules:
• Real specifics only: names, hours, addresses/areas, actual menu items, real numbers. \
**Bold** the load-bearing facts. If you couldn't verify something, say so plainly — \
NEVER fabricate a specific.
• Weave the user's context in (their goal, targets, training, injuries, schedule) — \
that's what makes this coaching, not a search summary.
• Attribute facts lightly inline where it matters: "(per their site)", "(hamptons.com)". \
No footnotes, no link dumps.
• Include the gotchas a good concierge would catch (closures, "walk-in only", timing \
conflicts, what to order instead).
• Arnie's voice: sentence case, direct, zero filler. No em dashes. Numbers are \
sacred — never invent macros/hours/prices.

Today for this user: {local_now}. Their timezone: {tz}.

FINAL CHECK before you send the plan: exactly two ||| separators, and the text after \
the second one starts with "My move:". A plan without that close is unfinished.
"""


# ── The loop ──────────────────────────────────────────────────────────────────

async def run_deep_research(
    objective: str,
    key_context: str = "",
    *,
    tz: str = "UTC",
    injuries: str = "",
    time_budget_s: Optional[float] = None,
    _chat_client=None,          # test seam: AsyncAnthropic-compatible
    _search_fn=None,            # test seam: async (query) -> SearchResult
) -> DeepResult:
    """Run the bounded research loop. Never raises."""
    t0 = time.monotonic()
    budget = time_budget_s if time_budget_s is not None else TIME_BUDGET_S()

    objective = (objective or "").strip()
    if not objective:
        return DeepResult(ok=False, error="empty objective")

    # Late imports keep this module import-light (it's loaded per-call).
    from core.timezones import safe_timezone
    if _search_fn is None:
        from core.search import search as _search
        _search_fn = lambda q: _search(q)  # noqa: E731
    if _chat_client is None:
        from core.llm import _get_anthropic
        _chat_client = _get_anthropic()

    try:
        local_now = datetime.now(safe_timezone(tz)).strftime("%A, %B %d %Y, %I:%M %p")
    except Exception:
        local_now = datetime.utcnow().strftime("%A, %B %d %Y, %I:%M %p UTC")

    system = _SYSTEM.format(local_now=local_now, tz=tz or "UTC")

    user_block = f"OBJECTIVE: {objective}"
    if (key_context or "").strip():
        user_block += f"\n\nUSER CONTEXT (fold this into the plan):\n{key_context.strip()}"
    if (injuries or "").strip():
        user_block += (
            f"\n\nLOGGED INJURIES: {injuries.strip()} — bias every recommendation "
            f"toward what's safe for them."
        )

    messages: list = [{"role": "user", "content": user_block}]
    sources: list = []
    rounds = 0
    searches = 0

    kwargs_base: dict = dict(model=DEEP_MODEL(), system=system)
    think = THINKING_BUDGET()
    if think > 0:
        # Opt-in (env DEEP_RESEARCH_THINKING_BUDGET>0). Off by default because at
        # the ~12s loop budget the tokens are better spent searching + writing.
        kwargs_base["thinking"] = {"type": "enabled", "budget_tokens": think}
    else:
        # EXPLICIT off. Sonnet 5 runs adaptive thinking when omitted, which would
        # silently spend hidden tokens against the synthesis max_tokens cap
        # (truncating the plan) and add unbudgeted latency to the loop.
        kwargs_base["thinking"] = {"type": "disabled"}

    try:
        while True:
            time_left = budget - (time.monotonic() - t0)
            # Reserve headroom for the synthesis generation itself (~6-10s):
            # another search round only starts if there's time for the round
            # AND the final write-up after it.
            out_of_time = time_left < 8.0
            out_of_rounds = rounds >= MAX_ROUNDS()

            kwargs = dict(kwargs_base, messages=messages)
            kwargs["max_tokens"] = _SYNTHESIS_MAX_TOKENS + (think if think > 0 else 0)
            if out_of_time or out_of_rounds:
                # Force synthesis: withhold tools and tell the model to answer
                # with what's gathered. The nudge rides the trailing user message
                # (the last round's tool results) as an extra text block; on a
                # first-call budget exhaustion the objective alone + no tools
                # already forces a direct answer.
                last = messages[-1]
                if last["role"] == "user" and isinstance(last["content"], list):
                    last["content"].append({
                        "type": "text",
                        "text": (
                            "Research time is up. Write the FINAL plan now from "
                            "what you have, following THE PLAN's exact three-part "
                            "shape: LEAD ||| BODY (markdown sections, unverified "
                            "gaps flagged plainly) ||| 'My move:' close. The close "
                            "is mandatory."
                        ),
                    })
            else:
                kwargs["tools"] = _INNER_TOOLS

            resp = await _chat_client.messages.create(**kwargs)

            tool_uses = [b for b in resp.content if getattr(b, "type", "") == "tool_use"]
            texts = [b.text for b in resp.content if getattr(b, "type", "") == "text"]

            if not tool_uses:
                plan = "\n".join(texts).strip()
                if not plan:
                    return DeepResult(ok=False, rounds=rounds, searches=searches,
                                      elapsed_s=time.monotonic() - t0,
                                      error="model returned empty synthesis")
                # Token-cap truncation guard: never ship a mid-sentence cut.
                # Drop the dangling partial bubble so the plan ends clean.
                if getattr(resp, "stop_reason", "") == "max_tokens" and "|||" in plan:
                    plan = plan.rsplit("|||", 1)[0].rstrip()
                return DeepResult(ok=True, plan=plan, sources=sources, rounds=rounds,
                                  searches=searches, elapsed_s=time.monotonic() - t0)

            # Execute this round's searches IN PARALLEL (capped).
            rounds += 1
            batch = tool_uses[:_MAX_PARALLEL_SEARCHES]
            queries = [(tu.id, (tu.input or {}).get("query", "")) for tu in batch]
            results = await asyncio.gather(
                *[_search_fn(q) for _, q in queries], return_exceptions=True,
            )
            searches += len(queries)

            result_blocks = []
            for (tu_id, q), sr in zip(queries, results):
                if isinstance(sr, Exception):
                    body = f"SEARCH FAILED for '{q}': {sr}"
                else:
                    lines = []
                    if getattr(sr, "answer", ""):
                        lines.append(f"ANSWER: {sr.answer}")
                    for r in (getattr(sr, "results", None) or [])[:4]:
                        title = (r.get("title") or "").strip()
                        url = (r.get("url") or "").strip()
                        content = (r.get("content") or "").strip().replace("\n", " ")
                        if url:
                            sources.append((title, url))
                        lines.append(f"• {title} ({url}): {content[:_SNIPPET_CHARS]}")
                    body = "\n".join(lines) or "(no results)"
                result_blocks.append({
                    "type": "tool_result", "tool_use_id": tu_id, "content": body,
                })
            # Any tool_use blocks beyond the parallel cap still need a result
            # (the API requires one per tool_use) — decline them explicitly.
            for tu in tool_uses[_MAX_PARALLEL_SEARCHES:]:
                result_blocks.append({
                    "type": "tool_result", "tool_use_id": tu.id,
                    "content": "Skipped (per-round search cap). Fold into the next round if essential.",
                })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": result_blocks})

    except Exception as e:
        logger.error(f"deep_research loop failed: {e}", exc_info=True)
        return DeepResult(ok=False, rounds=rounds, searches=searches,
                          elapsed_s=time.monotonic() - t0, error=str(e))
