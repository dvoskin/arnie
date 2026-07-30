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


def with_turn_obligations(messages: list) -> list:
    """The request's messages, with the note appended to the newest user turn.

    Copy-on-write: the caller's list and its dicts are never mutated, because
    `messages` is reused after the call — the self-heal retry and the follow-up
    pass both extend it, and an appendix that leaked into those would compound
    once per pass.

    Handles both content shapes: a plain string, and the block list a photo
    turn carries (the note becomes one more text block). Anything else — no
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
    content = last.get("content")
    if isinstance(content, str):
        patched = dict(last)
        patched["content"] = (content + "\n\n" + OBLIGATIONS_NOTE
                              if content.strip() else OBLIGATIONS_NOTE)
    elif isinstance(content, list):
        patched = dict(last)
        patched["content"] = list(content) + [
            {"type": "text", "text": OBLIGATIONS_NOTE}]
    else:
        return messages
    return messages[:-1] + [patched]
