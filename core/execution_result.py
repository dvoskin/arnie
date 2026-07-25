"""Typed execution results (P0.3a, architecture review 2026-07-24).

A tool input currently plays too many roles at once: model command, DB write
input, enrichment seed, mutable execution state, card payload, and receipt —
the executor stashes `_result`, `_entry_id`, `_event_id`, `_receipt`,
`_sourcing`, `_card_*` onto it and downstream code scrapes those keys from
wherever it stands. This module is the strangler seam that ends that:

  • CallResult / ExecutionResult — ONE typed view of what a turn's tool
    batch actually did, per call: status, result text, committed row id,
    ledger event id, receipt, sourcing.
  • LAST_EXECUTION — the executor publishes the ExecutionResult here
    (contextvar, same ambient pattern as turn identity); run_turn reads it
    right after execute_tool_calls returns.
  • from_call_contexts() — the executor's NATIVE construction: each call's
    state comes from its own side-channel context (CALL_CTX), never from the
    command. The command is immutable end to end (P0.3e).
  • without_execution_state() — the honest view for a batch the real executor
    did not run (mocked executors in tests, direct callers): no ids invented,
    nothing scraped.

Downstream rule: cards, narration filters, and receipts consume the
ExecutionResult — never `inp.get("_...")`, which no longer exists.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Optional

# Published by execute_tool_calls at the end of every real batch; cleared at
# the start so a prior batch can never leak into a turn whose executor was
# mocked or failed early.
LAST_EXECUTION: ContextVar[Optional["ExecutionResult"]] = ContextVar(
    "LAST_EXECUTION", default=None)

# The SIDE CHANNEL for one call's execution state (P0.3d). The executor writes
# committed ids, receipts and sourcing here instead of onto the command it was
# handed — a command describes what to do, never what happened. Set fresh per
# call by execute_tool_calls; read straight back into the CallResult.
CALL_CTX: ContextVar[Optional[dict]] = ContextVar("CALL_CTX", default=None)


def stash(inp, key: str, value) -> None:
    """Record per-call execution state on the ambient call context.

    The command input is NEVER written (P0.3e — executor immutability
    complete). `inp` is still accepted so call sites read naturally and so a
    future per-command context can be keyed off it; it is not mutated."""
    try:
        ctx = CALL_CTX.get()
        if ctx is not None:
            ctx[key] = value
    except Exception:
        pass


@dataclass(frozen=True)
class CallResult:
    """What one tool call actually did. `raw_input` is the command as
    executed — read-only here, and free of execution state since P0.3e; card
    building still reads the committed macros the enrichment step synced onto
    it."""
    name: str
    raw_input: dict
    status: str                      # committed | blocked | failed
    result_text: str = ""
    entry_id: Optional[int] = None
    event_id: Optional[int] = None
    receipt: Optional[dict] = None
    sourcing: Optional[dict] = None
    card_sets: Optional[int] = None    # committed running totals for the
    card_reps: Optional[str] = None    # workout card (appended-set aware)

    @property
    def committed(self) -> bool:
        return self.status == "committed"


@dataclass(frozen=True)
class ExecutionResult:
    calls: tuple = ()

    @property
    def successful(self) -> tuple:
        return tuple(c for c in self.calls if c.committed)

    def ok_tool_calls(self) -> list:
        """The original tool-call dicts whose execution committed — the shape
        the say-contract / snapshot / batch helpers consume today."""
        return [{"name": c.name, "input": c.raw_input} for c in self.successful]

    def failed_names(self) -> list:
        """Every call that did not commit, named.

        The predicate used to be `status == "blocked"`, while `status` is
        documented as `committed | blocked | failed`. Anything landing on
        `failed` was therefore excluded from `ok_tool_calls()` for not
        committing AND from this list for not being blocked — so the item
        vanished from the card and from the notice both, with no user-visible
        trace and nothing in the log. Nothing sets `failed` today, which is
        precisely why it is worth closing now: the trap springs the first time
        a third status is introduced, and the symptom is a food silently
        missing from a meal.
        """
        return [name for name, _reason in self.failures()]

    def failures(self) -> list:
        """`(name, reason)` per non-committed call, reason read from that
        call's own result text rather than assumed. See FAILURE_REASONS."""
        from core.food_ledger import failure_reason
        out = []
        for c in self.calls:
            if c.committed:
                continue
            inp = c.raw_input or {}
            name = str(inp.get("food_name") or inp.get("food_hint")
                       or f"entry #{inp.get('entry_id')}").strip()
            out.append((name, failure_reason(c.result_text)))
        return out


def from_call_contexts(tool_calls: list, contexts: list,
                       results: Optional[dict] = None) -> ExecutionResult:
    """NATIVE construction (P0.3d): each call's execution state comes from its
    own side-channel context, positionally aligned with the batch. No command
    input is read for execution state — the command described intent, the
    context records what happened."""
    from core.food_ledger import FAILURE_PREFIXES
    calls = []
    for i, tc in enumerate(tool_calls or []):
        if not isinstance(tc, dict):
            continue
        ctx = contexts[i] if i < len(contexts) and isinstance(contexts[i], dict) else {}
        inp = tc.get("input") or {}
        r = ctx.get("result")
        if not isinstance(r, str) and isinstance(results, dict):
            _r2 = results.get(tc.get("name"))
            r = _r2 if isinstance(_r2, str) else ""
        blocked = isinstance(r, str) and r.startswith(FAILURE_PREFIXES)
        calls.append(CallResult(
            name=str(tc.get("name") or ""),
            raw_input=inp,
            status="blocked" if blocked else "committed",
            result_text=r if isinstance(r, str) else "",
            entry_id=ctx.get("entry_id"),
            event_id=ctx.get("event_id"),
            receipt=ctx.get("receipt") if isinstance(ctx.get("receipt"), dict) else None,
            sourcing=ctx.get("sourcing") if isinstance(ctx.get("sourcing"), dict) else None,
            card_sets=ctx.get("card_sets"),
            card_reps=ctx.get("card_reps"),
        ))
    return ExecutionResult(calls=tuple(calls))


def without_execution_state(tool_calls: list,
                            results: Optional[dict] = None) -> ExecutionResult:
    """The view for a batch the real executor did NOT run — a mocked executor
    in tests, or a direct caller. There is no execution state to report, so
    every call is reported as committed with whatever shared result text
    exists, and no ids/receipts are invented. (Replaced from_tool_calls(),
    the legacy stash scraper, once executor immutability landed.)"""
    calls = []
    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            continue
        _r = (results or {}).get(tc.get("name")) if isinstance(results, dict) else ""
        calls.append(CallResult(
            name=str(tc.get("name") or ""),
            raw_input=tc.get("input") or {},
            status="committed",
            result_text=_r if isinstance(_r, str) else "",
        ))
    return ExecutionResult(calls=tuple(calls))
