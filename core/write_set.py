"""Write-set validation — the scribe's justification rules as CODE.

THE INVARIANT (the whole trust architecture in one line): no write without
justification in the user's turn. A log is justified by exactly four things:
  1. the item is NAMED in the message (or the message it answers),
  2. the turn carries a photo (vision names the items),
  3. an explicit add/repeat cue covers it (turn_supports_log),
  4. it answers a clarification Arnie asked (prior-message inheritance —
     folded in via effective_intent_message upstream).
Everything else is a phantom.

SHADOW MODE (v1, this module's only caller): validate the model's ACTUAL tool
calls after the real turn ran, log divergences, change nothing. The divergence
data tunes these rules until they're trustworthy enough to gate writes for
real (v2 — the scribe). Pure functions, no DB, no model calls.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from skills.logging_intent import turn_supports_log

_LOG_TOOLS = {"log_food", "log_exercise", "log_water", "log_body_weight"}
_EDIT_TOOLS = {"update_food_entry", "update_exercise_entry",
               "delete_food_entry", "delete_exercise_entry"}


@dataclass
class Verdict:
    tool: str
    item: str
    verdict: str   # justified | repeat_cue | suspicious_unnamed | suspicious_unknown_id | out_of_scope
    reason: str


def _tokens(text: str) -> set[str]:
    # Parentheticals are qualifiers (venue, prep) — never identity. "Grilled
    # salmon (Cafe Luxembourg)" must not match the Niçoise from the same
    # restaurant (the salmon incident, 2026-07-20).
    core = re.sub(r"\([^)]*\)", " ", (text or "").lower())
    return {w for w in re.split(r"[^a-z0-9а-яё]+", core) if len(w) >= 3}


def _named_in(item: str, message: str) -> bool:
    """Prefix-tolerant token overlap — 'barebell' names 'Barebells', 'coffee'
    names 'coffees'. Empty item (log_water etc.) counts as named."""
    item_toks = _tokens(item)
    if not item_toks:
        return True
    msg_toks = _tokens(message)
    return any(
        it == mt or it.startswith(mt) or mt.startswith(it)
        for it in item_toks for mt in msg_toks
    )


def validate_write_set(
    tool_calls: list,
    user_message: str,
    board_entries: Optional[list] = None,
    *,
    from_photo: bool = False,
    now_utc: Optional[datetime] = None,
) -> list[Verdict]:
    """Judge every proposed write against the justification rules.

    `user_message` should already be the gate-effective message (current turn
    combined with the prior one when the turn is a bare clarify-answer — the
    caller passes conversation.py's `_gate_user_message`). `board_entries` are
    today's food entries (parsed_food_name + timestamp), used to tell an
    unjustified re-fire of an on-board item (carryover shape) from an
    unjustified brand-new item (invention shape).
    """
    now = now_utc or datetime.utcnow()
    out: list[Verdict] = []
    board = board_entries or []

    for tc in tool_calls or []:
        name = tc.get("name") or ""
        inp = tc.get("input") or {}

        if name in _EDIT_TOOLS:
            # Edits are justified by construction (they target the board);
            # the only red flag is an id that doesn't exist there.
            eid = inp.get("entry_id")
            known = any(getattr(e, "id", None) == eid for e in board)
            out.append(Verdict(
                name, str(eid),
                "justified" if (known or not board) else "suspicious_unknown_id",
                "targets the board" if (known or not board)
                else "entry_id not on today's board — likely guessed"))
            continue

        if name not in _LOG_TOOLS:
            out.append(Verdict(name, "", "out_of_scope", "not a write"))
            continue

        item = (inp.get("food_name") or inp.get("exercise_name") or "").strip()

        if from_photo:
            out.append(Verdict(name, item, "justified", "photo turn — vision names the items"))
            continue
        if _named_in(item, user_message):
            out.append(Verdict(name, item, "justified", "named in the (gate-effective) message"))
            continue
        if turn_supports_log(user_message, item):
            out.append(Verdict(name, item, "repeat_cue", "explicit add/repeat cue covers it"))
            continue

        # Unjustified. Carryover shape (same item already on the board within
        # 90 min) vs invention shape (nowhere at all).
        recent_same = False
        for e in board:
            pn = re.sub(r"\([^)]*\)", " ",
                        (getattr(e, "parsed_food_name", "") or "").lower())
            ts = getattr(e, "timestamp", None)
            if pn.strip() and _named_in(item, pn) and ts is not None:
                try:
                    if (now - ts).total_seconds() < 5400:
                        recent_same = True
                        break
                except Exception:
                    pass
        out.append(Verdict(
            name, item, "suspicious_unnamed",
            "on-board <90min — carryover re-fire shape" if recent_same
            else "not named, no cue, no photo — invention shape"))
    return out


def summarize(verdicts: list[Verdict]) -> dict:
    """Compact per-turn summary for the shadow log line / divergence report."""
    counts: dict[str, int] = {}
    flagged: list[dict] = []
    for v in verdicts:
        counts[v.verdict] = counts.get(v.verdict, 0) + 1
        if v.verdict.startswith("suspicious"):
            flagged.append({"tool": v.tool, "item": v.item, "reason": v.reason})
    return {"counts": counts, "flagged": flagged}
