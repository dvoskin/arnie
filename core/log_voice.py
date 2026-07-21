"""
Fast, clean voicing for a completed log — the SINGLE reply on a food-log turn.

Replaces the heavy second `opus` pass (+ hold + day-total guard + catch-up) with
one sub-second Haiku read over the COMMITTED facts:

  • one source  → there is no double (the four-screenshot bug, 2026-07-21)
  • numbers handed in from the DB → the read can never state a phantom total
  • tiny focused prompt (not the 46k-token manual) → sub-second, and it can't
    ramble / repeat / contradict itself the way the big pass did

On ANY failure it returns None and the caller falls back to
`deterministic_confirmation`, so a log turn always answers.

Switches (read per-turn, no deploy needed to change):
  • FAST_LOG_VOICE=false        restores the legacy follow-up path instantly
  • FAST_LOG_VOICE_MODEL=<id>   override the model (default: claude-sonnet-5,
                                the same tier the follow-up split used before —
                                set claude-haiku-4-5-20251001 for max speed)
"""
import asyncio
import logging
import os
import re
from typing import Optional

from core.llm import chat

logger = logging.getLogger(__name__)

# Sonnet-5 by default — the voice the follow-up pass already used, and with the
# tiny focused prompt below it's still sub-second (the old slowness was the
# 46k-token manual, not the tier). Env-tunable for a faster/cheaper tier.
_DEFAULT_MODEL = "claude-sonnet-5"


def _model() -> str:
    return os.getenv("FAST_LOG_VOICE_MODEL", _DEFAULT_MODEL) or _DEFAULT_MODEL


def fast_log_voice_enabled() -> bool:
    return os.getenv("FAST_LOG_VOICE", "true").lower() in ("true", "1", "yes")


_SYSTEM = (
    "You are Arnie, a sharp, warm strength-and-nutrition coach texting a client. "
    "A log just posted to their day. Voice it in Arnie's texting voice.\n\n"
    "OUTPUT: exactly 1 or 2 short bubbles separated by |||. Each bubble is ONE "
    "texting-length sentence. No lists, no walls, never repeat a point.\n\n"
    "RULES:\n"
    "- Use ONLY the numbers in FACTS. Never invent, add to, or recompute a total.\n"
    "- Never use the ~ character. If a number is approximate, write \"about\" or "
    "just state it plainly.\n"
    "- Never use an em dash or en dash. Use a comma, a period, or a second bubble.\n"
    "- Sentence case. Emoji almost never, and never a joke emoji (no 😅). Usually none.\n"
    "- Dry, confident, specific. Never cutesy or hype: no \"party\", no \"huh\", "
    "no piled-on exclamation points.\n"
    "- ALWAYS name THIS log's own calories and protein (from the FACTS \"This item\" "
    "line) so the number is a receipt the user can verify. Don't list carbs or fat, "
    "and don't restate the day-total breakdown; the card shows those.\n"
    "- Bubble 1: a real read of what this does to their day. Bubble 2 (optional): "
    "one specific, concrete forward move.\n"
    "- Sound like a coach who knows them, never a tracker. Never send \"Logged.\", "
    "\"Got it\", or \"Done\" as a whole bubble.\n"
)


# ── output hygiene ────────────────────────────────────────────────────────────
_DASH_RE = re.compile(r"\s*[—–]\s*")   # em / en dash → comma
_WS_RE = re.compile(r"[ \t]{2,}")


def _clean(text: str) -> str:
    """Enforce the two banned characters and the 2-bubble cap even if the model
    slips. Cheap insurance so a stray — or ~ never reaches the user, and a blank
    line the model used instead of ||| still becomes a real second bubble."""
    if not text:
        return ""
    text = text.replace("~", "")
    text = _DASH_RE.sub(", ", text)
    # The model sometimes separates bubbles with a blank line instead of |||.
    text = re.sub(r"\n{2,}", "|||", text)
    bubbles = []
    for chunk in text.split("|||"):
        chunk = _WS_RE.sub(" ", chunk.replace("\n", " ")).strip()
        if chunk:
            bubbles.append(chunk)
    return "|||".join(bubbles[:2])


# ── facts assembly ────────────────────────────────────────────────────────────
def _n(x) -> int:
    try:
        return int(round(float(x)))
    except Exception:
        return 0


def _time_of_day(user) -> str:
    try:
        from datetime import datetime
        now = datetime.now()
        tz = getattr(user, "timezone", None)
        if tz:
            try:
                from zoneinfo import ZoneInfo
                now = datetime.now(ZoneInfo(tz))
            except Exception:
                pass
        h = now.hour
        if h < 11:
            return "morning"
        if h < 15:
            return "midday"
        if h < 18:
            return "afternoon"
        return "evening"
    except Exception:
        return ""


def build_log_facts(tool_calls, tool_results, log, user) -> str:
    """Assemble the committed-fact block the voicing reads. Numbers come straight
    from the refreshed `log` (recomputed from real rows) and the tool results, so
    the model has nothing to hallucinate."""
    tool_results = tool_results or {}
    prefs = getattr(user, "preferences", None)

    foods = [
        ((tc.get("input") or {}).get("food_name") or "").strip()
        for tc in (tool_calls or [])
        if tc.get("name") in ("log_food", "update_food_entry")
    ]
    foods = [f for f in foods if f]

    logged_line = str(
        tool_results.get("log_food") or tool_results.get("update_food_entry") or ""
    ).strip()

    cal = _n(getattr(log, "total_calories", 0) or 0)
    pro = _n(getattr(log, "total_protein", 0) or 0)
    cal_t = _n(getattr(prefs, "calorie_target", 0)) if prefs else 0
    pro_t = _n(getattr(prefs, "protein_target", 0)) if prefs else 0

    lines = ["FACTS:"]
    if foods:
        lines.append("Just logged: " + ", ".join(foods))
    # The tool result carries this item's own macros ("Logged: X, 250 cal, 2g
    # protein"); skip it on a dedup no-op so the read never claims a fresh log.
    if logged_line and not logged_line.startswith("Already on the board"):
        lines.append("This item: " + logged_line[:160])
    if cal_t:
        lines.append(
            f"Day total now: {cal} of {cal_t} cal ({max(0, cal_t - cal)} cal left)"
        )
    else:
        lines.append(f"Day total now: {cal} cal")
    if pro_t:
        lines.append(
            f"Protein now: {pro} of {pro_t} g ({max(0, pro_t - pro)} g to go)"
        )
    else:
        lines.append(f"Protein now: {pro} g")

    goal = (getattr(user, "primary_goal", None) or "").strip()
    if goal:
        lines.append(f"Their goal: {goal}")
    tod = _time_of_day(user)
    if tod:
        lines.append(f"Time of day: {tod}")

    lines.append("\nVoice this log now in 1 to 2 clean bubbles.")
    return "\n".join(lines)


async def voice_log(tool_calls, tool_results, log, user) -> Optional[str]:
    """The single reply for a food-log turn. Returns cleaned ||| bubble text, or
    None so the caller falls back to deterministic_confirmation.

    Two bounded attempts: a transient miss (timeout, empty text, an API hiccup) must
    NOT drop a simple log to the robotic template — the bar is voice_log answering
    >=95% of simple logs. Every failure is LOGGED: the old silent `except` hid
    exactly why this was returning None in prod (works locally, template in prod)."""
    try:
        facts = build_log_facts(tool_calls, tool_results, log, user)
    except Exception:
        logger.warning("voice_log: build_log_facts failed", exc_info=True)
        return None
    for attempt in (1, 2):
        try:
            res = await asyncio.wait_for(
                chat([{"role": "user", "content": facts}], _SYSTEM,
                     tools=False, max_tokens=220, model=_model()),
                timeout=8.0,
            )
            out = _clean((res.get("text") or "").strip())
            if out:
                return out
            logger.warning("voice_log empty text (attempt %d, model=%s)",
                           attempt, _model())
        except Exception as e:
            logger.warning("voice_log failed (attempt %d, model=%s): %s: %s",
                           attempt, _model(), type(e).__name__, e)
    return None
