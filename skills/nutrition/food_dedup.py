"""
Server-side guard against re-log-on-context-shift for food entries.

Demonstrated bug: Danny 2026-06-12 01:01 — user logs chicken+rice. At 01:59
user asks "Link my apple health" (totally new topic) and the model re-fires
log_food for the prior turn's chicken+rice while answering the Apple Health
question. The existing 5-min `_check_recent_duplicate` window is far too
tight to catch this (58 minutes elapsed). The dashboard daily total jumped
from 1,620 to 1,955 cal — 335 cal of phantom food.

This helper mirrors `skills/fitness/exercise_dedup.py`: pure function, no
DB access, snapshot-pre-turn-aware. The caller is `_dispatch` in
`handlers/tool_executor.py`, which passes today's food_entries list AND a
snapshot of entry IDs that existed BEFORE this tool batch ran. The dedup
ONLY matches against the snapshot — so a bulk post-factum paste (model
fires log_food once per item in one batch) is never self-blocked.

Window default: 90 minutes (5400s). Longer than exercise's 120s because:
  • Exercise re-logs cluster in tight bursts (Logged 4 exercises pattern).
  • Food re-logs surface MUCH later — Danny's was 58 minutes after the
    original. The model carries the chat-history "context" of a logged
    meal forward across many turns and occasionally re-fires.
  • Legitimate same-payload food re-eating (had ANOTHER 150g chicken)
    typically happens at meal intervals — 3+ hours apart — so a 90-min
    window catches the bug without false-positiving the next meal.

Match key: normalized name + normalized quantity + close calories (±15%).
The calorie tolerance absorbs USDA enrichment variance — the same "150g
chicken" might come out at 200-235 cal depending on the lookup branch.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, Optional


def normalize_food_name(name: Optional[str]) -> str:
    """Lowercase + whitespace-collapse. Same conservative normalization the
    exercise dedup helper uses — no fuzzy matching, no token splitting.
    Adding catalog-style aliasing is future work; this is the bare key."""
    if not name:
        return ""
    return " ".join(name.lower().split())


def normalize_quantity(qty: Optional[str]) -> str:
    """Lowercase + whitespace-collapse. Quantity strings are user-shaped
    ('150g', '1 cup', '1 wrap') — we don't try to parse units here, only
    compare textually. Two different unit phrasings of the same portion
    won't match and that's the right call (avoids false-positives)."""
    if qty is None:
        return ""
    return " ".join(str(qty).lower().split())


def _calories_close(a: Optional[float], b: Optional[float],
                    tol_pct: float = 0.15) -> bool:
    """±tol_pct relative tolerance. None on either side: treat as match
    (the macro lookup hasn't run yet on the incoming side). Both None:
    match. The intent is to allow USDA enrichment variance to not break
    the dedup — same 150g chicken might come out at 200-235 cal."""
    if a is None and b is None:
        return True
    if a is None or b is None:
        return True
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    if a == 0 and b == 0:
        return True
    bigger = max(abs(a), abs(b))
    if bigger == 0:
        return True
    return abs(a - b) / bigger <= tol_pct


def is_duplicate_food(
    *,
    food_name: Optional[str],
    quantity: Optional[str],
    calories: Optional[float],
    existing_entries: Iterable,
    now_utc: datetime,
    window_sec: int = 5400,  # 90 minutes
):
    """Return the most-recent matching food entry within window_sec, or None.

    Match key: normalized name + normalized quantity + close calories
    (±15%). All three must agree.

    Caller filters existing_entries to the pre-turn snapshot before passing
    in. That ensures (1) bulk post-factum paste with multiple distinct
    items all log, and (2) the model glitching and firing log_food twice
    in the SAME batch for the SAME payload IS caught (both calls see the
    same pre-existing set, and the first call's write isn't in the
    snapshot, so the second call's match-against-pre-existing won't find
    anything — but in practice the model rarely does this and the simpler
    snapshot semantics preserve back-compat with the existing 5-min check
    being replaced).
    """
    if not food_name:
        return None
    key_name = normalize_food_name(food_name)
    key_qty = normalize_quantity(quantity)

    cutoff = now_utc - timedelta(seconds=window_sec)
    candidates = []
    for e in existing_entries:
        ts = getattr(e, "timestamp", None)
        if ts is None:
            continue
        candidates.append((ts, e))
    candidates.sort(key=lambda pair: pair[0], reverse=True)

    for ts, e in candidates:
        if ts < cutoff:
            break
        if normalize_food_name(getattr(e, "parsed_food_name", "")) != key_name:
            continue
        if normalize_quantity(getattr(e, "quantity", None)) != key_qty:
            continue
        if not _calories_close(getattr(e, "calories", None), calories):
            continue
        return e
    return None


def format_dedup_result(dup, now_utc: datetime) -> str:
    """Tool-result string the executor returns on a dup hit.

    DATA ONLY — no model-facing directives. The behavioral guidance ("when
    something's already logged, acknowledge briefly and keep it natural, never
    announce a skip") lives in the SYSTEM PROMPT (core/prompts/arnie.py), NOT
    here: this string can be echoed verbatim to a user (Danny 2026-06-27 saw
    "YOUR REPLY: ..." and raw "[#1314]" tokens leak), so it carries facts and
    nothing that reads as instructions or internal machinery.

    Prefix 'Already on the board:' is the discriminator the deterministic
    confirmation uses to distinguish this from real Error/Skipped results and
    must stay stable. The entry id is carried as a bare '#id' (NOT the bracketed
    '[#id]' marker that leaked) so the model can still reference the row for an
    edit without echoing the internal-looking token.
    """
    qty = getattr(dup, "quantity", "") or ""
    cals = getattr(dup, "calories", None)
    cal_part = f", {round(cals)} cal" if cals is not None else ""
    age_sec = max(0, int((now_utc - dup.timestamp).total_seconds()))
    clock = dup.timestamp.strftime("%H:%M")
    age_part = (
        f"{age_sec}s ago" if age_sec < 90
        else f"{age_sec // 60} min ago"
    )
    qty_part = f"{qty}{cal_part}".strip().lstrip(",").strip()
    detail = f" ({qty_part})" if qty_part else ""
    return (
        f"Already on the board: {dup.parsed_food_name}{detail}, "
        f"logged {clock} ({age_part}) #{dup.id}."
    )
