"""⛔ A REPLY THAT CANNOT BE READ SAYS NOTHING ABOUT WHAT A FOOD MEANS.

Measured in production 2026-08-15, on the first shadow canary:

    WARNING event=entity_resolution_truncated foods=1
            — the whole batch abstains; a cut reply is not a shorter answer
    INFO    event=entity_identity_recorded attempted=1 recorded=0 absent=1

ONE food. `max_tokens` was `_TOKENS_PER_FOOD * len(names)` = 220 * 1, with
adaptive thinking left on — so the tokens reserved for JSON were spent on
reasoning nobody reads, and the reply was cut mid-object.

⚠ THE FOOD IT CUT WAS THE RUSSIAN ONE. If a longer reply is likelier for the
population this boundary exists to serve, the budget is not a detail: it is
the difference between serving 30.4% of real food and abstaining on it.

⭐ THE PRINCIPLE THESE GATES DEFEND *(Danny, 2026-08-15)*: retry may improve
TRANSPORT reliability, but retry must never turn an unusable semantic reply
into a negative classification. The retry is about getting a readable answer,
not voting on meaning. That is the claim most likely to rot quietly, so it is
asserted structurally rather than left as a comment.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

import skills.nutrition.entity_resolver as resolver


class _Reply:
    def __init__(self, text=None, stop_reason="end_turn", blocks=None):
        self.stop_reason = stop_reason
        if blocks is not None:
            self.content = blocks
        else:
            self.content = ([_Block("text", text)] if text is not None else [])


class _Block:
    def __init__(self, kind, text=""):
        self.type = kind
        self.text = text


def test_truncation_is_unusable_and_not_an_answer():
    with pytest.raises(resolver.UnusableReply):
        resolver._readable_text(_Reply(text='{"foods":[]}',
                                       stop_reason="max_tokens"))


def test_a_reply_with_only_a_thinking_block_is_unusable():
    """The exact shape `core/llm.py` warns about: adaptive thinking makes
    `content[0]` a thinking block, and a naive join returns `''` — which parses
    as nothing and could be mistaken for 'the model had no opinion'."""
    with pytest.raises(resolver.UnusableReply):
        resolver._readable_text(_Reply(blocks=[_Block("thinking", "")]))


def test_an_empty_content_list_is_unusable():
    with pytest.raises(resolver.UnusableReply):
        resolver._readable_text(_Reply(blocks=[]))


def test_a_readable_reply_returns_its_text():
    assert resolver._readable_text(_Reply(text='{"foods":[]}')) == '{"foods":[]}'


def test_the_budget_has_a_floor_that_covers_a_single_food():
    """⛔ THE ARITHMETIC THAT FAILED. `_TOKENS_PER_FOOD * 1` is 220, and 220 is
    what truncated a single Russian food in production. The per-food term is
    right for a batch and far too tight for a single, so the fix is a FLOOR."""
    assert resolver._MIN_TOKENS >= 1024
    budget = max(resolver._MIN_TOKENS, resolver._TOKENS_PER_FOOD * 1)
    assert budget >= 1024, "a single food still gets a batch-sized crumb"


def test_thinking_is_disabled_on_every_resolver_call():
    """⭐ THE REPOSITORY'S OWN CONTRACT, not a local choice. `core/llm.py` sets
    `thinking={"type": "disabled"}` on every tuned call and records it as
    verified on sonnet-5. This resolver was the one call site that never
    adopted it — and the one that truncated."""
    source = pathlib.Path(resolver.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "attr", None) == "create"]
    assert calls, "no messages.create call found — this gate lost its subject"
    for call in calls:
        kwargs = {k.arg for k in call.keywords if k.arg}
        assert "thinking" in kwargs, (
            f"the messages.create at line {call.lineno} does not disable "
            f"thinking; adaptive thinking eats the budget reserved for JSON "
            f"and the reply arrives truncated")


@pytest.mark.asyncio
async def test_an_unusable_batch_is_retried_one_food_at_a_time(monkeypatch):
    """Transport recovery: one unreadable food must not silence the others."""
    seen = []

    async def _ask(names):
        seen.append(list(names))
        if len(names) > 1:
            raise resolver.UnusableReply("truncated")
        # ⚠ THE KEY IS `surface`, NOT `name`. The first version of this
        # fixture used `name`, `_parse` discarded every entry as unasked, and
        # the gate failed against CORRECT code — a fixture that cannot address
        # its own row proves nothing, the same trap `61eec60` hit with
        # `user-confirmed`.
        return ('{"foods":[{"surface":"%s","state":"resolved",'
                '"entity":"tomato","meaning":"a tomato"}]}' % names[0])

    monkeypatch.setattr(resolver, "_ask_the_model", _ask)
    out = await resolver.interpret(["Помидор", "Творог 2%"])

    assert seen[0] == ["Помидор", "Творог 2%"], "the batch was never tried"
    assert seen[1:] == [["Помидор"], ["Творог 2%"]], (
        "an unusable batch must be re-asked ONE food at a time")
    assert out, "nothing was recovered from the singles"


@pytest.mark.asyncio
async def test_a_single_unusable_food_is_absence_and_never_a_verdict(monkeypatch):
    """⭐⭐ THE LOAD-BEARING GATE. A food whose reply cannot be read must
    contribute NOTHING — not an `unresolved` row, not a low-confidence guess.
    An `unresolved` state written here would be a NEGATIVE ANSWER derived from
    a transport failure, and `entity_id_for_surface` would then hand
    settlement that judgement as though a model had made it."""
    async def _always_unusable(names):
        raise resolver.UnusableReply("truncated")

    monkeypatch.setattr(resolver, "_ask_the_model", _always_unusable)
    assert await resolver.interpret(["Творог 3%"]) == []
    assert await resolver.interpret(["Помидор", "Творог 3%"]) == []


@pytest.mark.asyncio
async def test_a_single_food_is_not_retried_identically(monkeypatch):
    """Re-asking ONE food the same way is not a retry, it is the same call
    again — a paid round trip that cannot produce a different kind of answer."""
    calls = []

    async def _ask(names):
        calls.append(list(names))
        raise resolver.UnusableReply("truncated")

    monkeypatch.setattr(resolver, "_ask_the_model", _ask)
    await resolver.interpret(["Творог 3%"])
    assert len(calls) == 1, f"a single food was asked {len(calls)} times"


def test_the_retry_path_cannot_manufacture_a_state():
    """⛔ STRUCTURAL, because this is the rot that would be invisible. The
    retry may return parsed resolutions or nothing; it may not name a
    ResolutionState itself. A retry that could write `UNRESOLVED` would be
    converting 'we could not read the reply' into 'the model had no answer'."""
    source = inspect.getsource(resolver._retry_one_at_a_time)
    for forbidden in ("ResolutionState.", "UNRESOLVED", "confidence"):
        assert forbidden not in source, (
            f"the retry path references {forbidden!r} — retry is transport, "
            f"never a vote on meaning")
