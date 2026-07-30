"""A hidden obligations note, appended to the user's newest message at request
time — Danny's observation, made mechanism.

The observation: Arnie is markedly more reliable when the user's own message
says "make sure you call the tool". The standing rule already exists in the
system prompt, so the words are not what changed — the *placement* is. Deep in
a session the system prompt is thousands of tokens behind the newest turn, and
the deep-session benchmark measured exactly this decay: tool calls the model
narrates but never makes (`bench_deep_session.py`; the orchestrator cut those
drops 47%→36%, not to zero). Text adjacent to the message being answered does
not decay with depth, which is why the user typing the reminder works.

So this module puts the obligation where the user's reminder goes, on every
legacy-lane pass — and the user never has to type it again.

**What this is not.** Not a guard: the self-heal/stall/undercount stack reacts
after a failed turn, this makes the failure less likely to happen at all. Not a
heuristic: nothing decides *when* to append — the note is constant and always
on (a classifier choosing "turns that need reminding" would be a new judgment
call, and the whole point is to stop relying on judgment for obligations). Not
stored: the appendix exists only in the outbound request. The conversation log
keeps what the user actually said.

The note is written as a bracketed system block, the same convention as
[SESSION STATE] and [COACH SCREEN], and says explicitly that it is not from
the user — the model must never quote it back or treat it as something the
user asked.
"""
from __future__ import annotations

import os

#: The note. Constant by design — see module docstring. Kept short: it rides
#: every legacy turn, so every word is a recurring cost.
OBLIGATIONS_NOTE = (
    "[TURN OBLIGATIONS — system note, not written by the user; never mention "
    "or quote it]\n"
    "- If this message reports something already done — completed sets, "
    "cardio, water, a weigh-in, a walk, food — CALL the matching log tool in "
    "THIS reply. Describing a log without calling the tool is a failure.\n"
    "- If it corrects or removes an earlier entry, call the matching "
    "update/delete tool — do not just acknowledge.\n"
    "- Claim an action happened only after its tool call ran."
)


def obligations_enabled() -> bool:
    """Kill switch. Default ON: this is placement of an existing rule, not a
    behaviour change a rollout has to earn — the rule is already in the system
    prompt, and the reactive stack (self-heal, stall, undercount) still stands
    behind it. TURN_OBLIGATIONS=false reverts without a deploy."""
    return os.getenv("TURN_OBLIGATIONS", "true").lower() not in (
        "false", "0", "no", "off")


def with_turn_obligations(messages: list, extra_blocks=()) -> list:
    """The request's messages, with the appendix on the newest user turn.

    The appendix is `extra_blocks` (state facts, below) followed by the
    obligations note — facts first, so the obligation to act reads against the
    state it acts on.

    Copy-on-write: the caller's list and its dicts are never mutated, because
    `messages` is reused after the call — the self-heal retry and the follow-up
    pass both extend it, and an appendix that leaked into those would compound
    once per pass.

    Handles both content shapes: a plain string, and the block list a photo
    turn carries (the appendix becomes one more text block). Anything else — no
    messages, no trailing user turn, an unrecognised content type — returns
    the list unchanged; this must never be able to break a turn.
    """
    if not obligations_enabled():
        return messages
    if not messages:
        return messages
    last = messages[-1]
    if not isinstance(last, dict) or last.get("role") != "user":
        return messages
    appendix = "\n\n".join([b for b in extra_blocks if b] + [OBLIGATIONS_NOTE])
    content = last.get("content")
    if isinstance(content, str):
        patched = dict(last)
        patched["content"] = (content + "\n\n" + appendix
                              if content.strip() else appendix)
    elif isinstance(content, list):
        patched = dict(last)
        patched["content"] = list(content) + [
            {"type": "text", "text": appendix}]
    else:
        return messages
    return messages[:-1] + [patched]


# ── state facts, each a pure function of what the turn already loaded ─────────
#
# The same placement rule as the note: a fact the model must honor THIS turn
# rides with the turn. Every builder is deterministic — no classifier decides
# whether a turn "needs" a block; a block is present exactly when its state
# exists — and returns "" when it does not, which the appendix joiner drops.


def open_question_block(prior) -> str:
    """The open clarification, stated to the turn that has to answer it.

    The structured lane already sees this (cause A's held line). The LEGACY
    lane — where an escaped answer actually lands — did not: "It's the same
    one" reached a model that had no idea a question was open, and chatted
    past it. `prior` is the same pending payload the lane loads.
    """
    if not isinstance(prior, dict):
        return ""
    question = str(prior.get("question") or "").strip()
    if not question:
        return ""
    lines = ["[OPEN QUESTION — system note, not written by the user]",
             f"You asked and they have not answered yet: \"{question[:200]}\""]
    original = str(prior.get("original") or "").strip()
    if original:
        lines.append(f"It was about their report: \"{original[:150]}\"")
    held = [i for i in (prior.get("items") or []) if isinstance(i, dict)
            and i.get("food")]
    if held:
        parts = []
        for it in held[:4]:
            bit = str(it["food"])
            amount, unit = it.get("amount"), str(it.get("unit") or "")
            if amount is not None:
                bit += f" ({amount} {unit})".rstrip() if unit else f" ({amount})"
            cal = it.get("calories")
            if isinstance(cal, (int, float)):
                bit += f" — {int(cal)} cal as read"
            parts.append(bit)
        lines.append("Held reading, waiting on the answer: " +
                     "; ".join(parts))
    lines.append("If this message answers it, act on the answer — do not "
                 "re-ask, and do not treat the held food as new information.")
    return "\n".join(lines)


def last_action_block(board) -> str:
    """What was just written, with row ids — the rows a correction binds to.

    Corrections failed by re-interpreting prose ("the shrimp" → a fresh
    search) because the row being corrected lived nowhere near the message.
    Only RECENT rows ride here: the full board is already in the system
    context, and the point of this block is recency — the writes this message
    is most plausibly about. 180 minutes is a size cap on an existing list,
    not a judgment about the message.
    """
    rows = [r for r in (board or [])
            if isinstance(r, dict) and r.get("id") is not None
            and isinstance(r.get("mins_ago"), int) and r["mins_ago"] <= 180]
    if not rows:
        return ""
    rows.sort(key=lambda r: r["mins_ago"])
    lines = ["[RECENT WRITES — system note, not written by the user]"]
    for r in rows[:3]:
        qty = f" {r['qty']}" if r.get("qty") else ""
        lines.append(f"- entry {r['id']}: {r.get('food', '?')}{qty}, "
                     f"{int(r.get('cal') or 0)} cal — {r['mins_ago']} min ago")
    lines.append("A correction or elaboration about these targets the entry "
                 "id — update or delete it; never log it again as new food.")
    return "\n".join(lines)


def reply_language_block(user_text: str) -> str:
    """Pin the reply to the language of the message. Every turn, every language.

    THERE IS NOTHING TO DETECT. This fired only when the message contained
    non-Latin letters, which reads as "the block is for Russian users" and is
    the EN-keyed blindspot wearing different clothes: a Spanish, French,
    Portuguese or Indonesian user writes in Latin script and got no block at
    all, so cause E was addressed for exactly the languages whose alphabet
    happened to differ from ours. The 07-29 window found the Russian half
    because Russian users were the ones in it.

    A script test cannot tell English from Spanish, so no script test can carry
    this rule. But the rule needs no test: "reply in the language they wrote
    in" is TRUE on an English turn — it is a no-op there — and stating it
    unconditionally costs one line and removes the whole class of blindspot.
    That is the directive's shape (typed obligation, not per-language
    catalogs), and the reason there is no list of languages anywhere here.

    The anti-momentum clause is the other half of the original defect: a
    history thick with one language kept pulling replies back into it after
    the user had switched. The CURRENT message decides, every turn.
    """
    if not (user_text or "").strip():
        return ""
    return ("[REPLY LANGUAGE — system note, not written by the user]\n"
            "Reply entirely in the language of the user's CURRENT message — "
            "the whole reply, including any headers, labels, units and "
            "scaffolding. Earlier messages in this conversation do not decide "
            "it; the current one does, every turn.")


def time_block(user) -> str:
    """The user's clock and their logging day, stated rather than derived.

    Behind the midnight-rollover incident, the UTC complaints, and the
    yesterday's-turkey data loss: the model reasoned about "yesterday" and
    "this morning" against server time. A free-text timezone that zoneinfo
    cannot parse yields no block rather than a wrong one (the Marina crash,
    inverted).
    """
    tz_name = str(getattr(user, "timezone", "") or "").strip()
    if not tz_name:
        return ""
    try:
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        now_local = datetime.now(ZoneInfo(tz_name))
    except Exception:
        return ""
    rollover = 0
    try:
        rollover = max(0, min(23, int(os.getenv("LOGGING_DAY_ROLLOVER_HOUR",
                                                "0"))))
    except Exception:
        rollover = 0
    logging_day = now_local.date()
    if rollover and now_local.hour < rollover:
        logging_day = (now_local - timedelta(days=1)).date()
    lines = ["[TIME — system note, not written by the user]",
             f"User-local time: {now_local.strftime('%a %H:%M')} ({tz_name}). "
             f"Today's logging day: {logging_day.isoformat()}."]
    if rollover:
        lines.append(f"The logging day rolls over at {rollover:02d}:00 "
                     f"user-local — before that, food belongs to "
                     f"the previous day.")
    lines.append("Resolve \"yesterday\", \"this morning\" and \"last night\" "
                 "against this clock, never server time.")
    return "\n".join(lines)


def units_block(user) -> str:
    """Storage vs display conventions, so a unit never gets guessed.

    Weight is stored in kg regardless of what the user sees; exercise weight
    columns are kg. Silent unit confusion has produced wrong logged loads and
    wrong readbacks.
    """
    pref = str(getattr(getattr(user, "units_preference", ""), "value",
                       getattr(user, "units_preference", "")) or "").strip()
    if not pref:
        return ""
    display = "imperial (lb, oz, ft)" if pref == "imperial" else "metric (kg, g, cm)"
    return ("[UNITS — system note, not written by the user]\n"
            f"Display units: {display}. Storage is ALWAYS metric — weights "
            "in kg, food masses in g. Convert on the way in and out; never "
            "store a pound value in a kg field.")
