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
  • from_tool_calls() — the ONE sanctioned scraper of the legacy stash keys.
    It backfills the typed view when the executor didn't publish (mocked
    executors in tests, direct callers), and it is where the executor's own
    tail builds the object today. When the input mutation is finally removed
    (P0.3b: branches populate CallResults natively), this function shrinks
    to nothing and no other code will notice.

Downstream rule from this slice on: cards, narration filters, and receipts
consume the ExecutionResult — never `inp.get("_...")` directly.
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


@dataclass(frozen=True)
class CallResult:
    """What one tool call actually did. `raw_input` is the executed input —
    transitional: it still carries the legacy stash keys and the committed
    macro sync, and card building reads quantities/macros from it until the
    executor populates typed fields natively (P0.3b)."""
    name: str
    raw_input: dict
    status: str                      # committed | blocked | failed
    result_text: str = ""
    entry_id: Optional[int] = None
    event_id: Optional[int] = None
    receipt: Optional[dict] = None
    sourcing: Optional[dict] = None

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
        out = []
        for c in self.calls:
            if not c.committed and c.status == "blocked":
                inp = c.raw_input or {}
                out.append(str(inp.get("food_name") or inp.get("food_hint")
                               or f"entry #{inp.get('entry_id')}").strip())
        return out


def from_tool_calls(tool_calls: list, results: Optional[dict] = None) -> ExecutionResult:
    """Build the typed view from executed tool calls. The ONE sanctioned
    reader of the legacy stash keys (see module docstring)."""
    from core.food_ledger import _call_failed
    calls = []
    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            continue
        inp = tc.get("input") or {}
        r = inp.get("_result")
        if not isinstance(r, str) and isinstance(results, dict):
            _r2 = results.get(tc.get("name"))
            r = _r2 if isinstance(_r2, str) else ""
        blocked = _call_failed(tc)
        calls.append(CallResult(
            name=str(tc.get("name") or ""),
            raw_input=inp,
            status="blocked" if blocked else "committed",
            result_text=r if isinstance(r, str) else "",
            entry_id=inp.get("_entry_id"),
            event_id=inp.get("_event_id"),
            receipt=inp.get("_receipt") if isinstance(inp.get("_receipt"), dict) else None,
            sourcing=inp.get("_sourcing") if isinstance(inp.get("_sourcing"), dict) else None,
        ))
    return ExecutionResult(calls=tuple(calls))
