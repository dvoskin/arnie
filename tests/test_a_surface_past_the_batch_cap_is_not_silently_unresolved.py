"""⛔ A SURFACE PAST THE BATCH CAP WAS NEVER ASKED, AND NOTHING COULD TELL.

Observed 2026-09-03: twenty surfaces into `interpret`, twelve results out, no
log line. `names = list(asked.values())[:_MAX_BATCH]` kept the first twelve
and dropped the rest before any model call — so the eight past the cap were
absent from the result exactly the way a transport failure leaves a food
absent, and the turn's `absent=` count carried both without distinction.

That is the system-wide invariant (`docs/CANONICAL_MIGRATION_DIRECTIVE.md`)
one layer up:

    AN ABSENT ANSWER MUST NEVER BE REPRESENTABLE AS A NEGATIVE ANSWER.

A surface the producer silently declined to consider must not be
representable as one it considered and could not resolve. The cap is now a
chunk size: every surface reaches a model call, a failed chunk is named at
WARNING and does not silence the others, and the retry stays inside the chunk
that was unreadable. The model is stubbed throughout — what is under test is
the CONTRACT, not the judgement.
"""
from __future__ import annotations

import ast
import json
import logging
import pathlib

import pytest

import skills.nutrition.entity_resolver as resolver
from skills.nutrition.entity_resolution import ResolutionState, surface_key

# Distinct foods, more than the cap plus three, so the population the old
# slice dropped is present. Sized from the cap rather than hard-coded, so the
# gates follow the cap if it moves.
_FOODS = [
    "Помидор", "Творог 2%", "Куриная грудка", "Гречка", "Огурец", "Кефир 1%",
    "Яйцо", "Сметана 15%", "Хлеб бородинский", "Банан", "Овсянка", "Лосось",
    "Рис", "Брокколи", "Миндаль", "Йогурт греческий", "Сыр адыгейский",
    "Яблоко", "Морковь", "Фасоль",
]


def _surfaces(count):
    assert count <= len(_FOODS), "the cap grew past the fixture — extend _FOODS"
    surfaces = _FOODS[:count]
    assert len({surface_key(s) for s in surfaces}) == count, "fixture collides"
    return surfaces


def _answer(names):
    """A readable reply resolving every food it was asked about, each to an
    entity derived from ITS OWN surface — so an answer that lands on the wrong
    food is detectable, not just an answer that is missing."""
    return json.dumps({"foods": [{"surface": name, "state": "resolved",
                                  "entity": surface_key(name),
                                  "meaning": "a food"} for name in names]},
                      ensure_ascii=False)


def _recording(monkeypatch, reply=_answer):
    calls = []

    async def _ask(names):
        calls.append(list(names))
        return reply(names, len(calls))

    monkeypatch.setattr(resolver, "_ask_the_model", _ask)
    return calls


# ── every surface reaches a call ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_every_surface_past_the_cap_is_asked_once_and_answered(
        monkeypatch, caplog):
    """The observed defect, inverted: cap + 3 in, cap + 3 out, and the log
    says a second call was made. No call may exceed the cap, and every answer
    must be the answer for its own food — the chunks are asked in order as
    consecutive runs, not re-sampled."""
    calls = _recording(monkeypatch, lambda names, _n: _answer(names))
    cap = resolver._MAX_BATCH
    surfaces = _surfaces(cap + 3)

    with caplog.at_level(logging.INFO, logger=resolver.logger.name):
        out = await resolver.interpret(surfaces)

    asked = [name for call in calls for name in call]
    assert sorted(asked) == sorted(surfaces), "a surface was never asked"
    assert len(asked) == len(surfaces), "a surface was asked more than once"
    assert max(len(call) for call in calls) <= cap, "a call exceeded the cap"
    assert calls == [surfaces[:cap], surfaces[cap:]], (
        "the chunks are not consecutive runs of the surfaces in order")

    assert sorted(r.surface_form for r in out) == sorted(surfaces), (
        "a surface past the cap is missing from the result")
    assert all(r.canonical_entity_id == surface_key(r.surface_form)
               for r in out), "an answer landed on a different food"
    assert any("event=entity_resolution_chunked" in m and "chunks=2" in m
               for m in caplog.messages), (
        "more than one call was made and the log did not say so — the "
        "silence is the half of the defect that made it invisible")


@pytest.mark.asyncio
async def test_exactly_the_cap_is_still_one_call(monkeypatch, caplog):
    """The no-transition case. A batch that FITS the cap is one call carrying
    every surface, exactly as before, and the log does not claim chunking."""
    calls = _recording(monkeypatch, lambda names, _n: _answer(names))
    surfaces = _surfaces(resolver._MAX_BATCH)

    with caplog.at_level(logging.INFO, logger=resolver.logger.name):
        out = await resolver.interpret(surfaces)

    assert calls == [surfaces], (
        f"{len(calls)} call(s) for a batch that fits the cap; expected one "
        f"carrying all {len(surfaces)} surfaces")
    assert sorted(r.surface_form for r in out) == sorted(surfaces)
    assert not any("event=entity_resolution_chunked" in m
                   for m in caplog.messages), "one call was logged as chunked"


@pytest.mark.asyncio
async def test_one_past_the_cap_is_a_second_call_of_one(monkeypatch):
    """The boundary itself: the cap + 1 surface is not dropped and not
    squeezed into an over-cap call — it is a second call of one."""
    calls = _recording(monkeypatch, lambda names, _n: _answer(names))
    cap = resolver._MAX_BATCH
    surfaces = _surfaces(cap + 1)

    out = await resolver.interpret(surfaces)

    assert calls == [surfaces[:cap], [surfaces[cap]]]
    assert sorted(r.surface_form for r in out) == sorted(surfaces)


# ── a failed chunk is absent and named, never a verdict, never contagious ────

@pytest.mark.asyncio
@pytest.mark.parametrize("failing", [1, 2])
async def test_a_failed_chunk_is_absent_and_named_and_the_other_survives(
        monkeypatch, caplog, failing):
    """⭐⭐ THE LOAD-BEARING GATE, in both directions. The chunk the provider
    dropped contributes NOTHING — no row, so no `unresolved` verdict derived
    from a transport failure — and its surfaces are NAMED in the warning, so
    the absence is explicit. The chunk that answered keeps its answers: a
    complete, readable reply about other foods is not made worthless by a
    failure elsewhere, and `ensure_resolved` stores per row, so what landed
    stays landed and only the failed surfaces are re-asked next turn."""
    def _reply(names, n):
        if n == failing:
            raise RuntimeError("provider down")
        return _answer(names)

    calls = _recording(monkeypatch, _reply)
    cap = resolver._MAX_BATCH
    surfaces = _surfaces(cap + 3)
    chunks = {1: surfaces[:cap], 2: surfaces[cap:]}
    failed, survived = chunks[failing], chunks[3 - failing]

    with caplog.at_level(logging.WARNING, logger=resolver.logger.name):
        out = await resolver.interpret(surfaces)

    assert len(calls) == 2, "a failed chunk stopped the others being asked"
    assert sorted(r.surface_form for r in out) == sorted(survived), (
        "the chunk that answered was discarded, or the failed one leaked")
    assert not any(r.surface_form in failed for r in out)
    assert all(r.state is not ResolutionState.UNRESOLVED for r in out), (
        "a transport failure became a negative verdict")

    warnings = [rec.getMessage() for rec in caplog.records
                if rec.levelno >= logging.WARNING]
    assert any("event=entity_resolution_unavailable" in m
               and f"chunk={failing}/2" in m
               and all(name in m for name in failed)
               for m in warnings), (
        f"the surfaces that got no answer are not named; warnings={warnings}")


@pytest.mark.asyncio
async def test_an_unusable_chunk_is_retried_within_its_own_chunk(monkeypatch):
    """Transport recovery stays chunk-scoped: an unreadable second chunk is
    re-asked one food at a time, and the first chunk — which answered — is
    not asked again."""
    cap = resolver._MAX_BATCH
    surfaces = _surfaces(cap + 3)
    first, rest = surfaces[:cap], surfaces[cap:]

    def _reply(names, _n):
        if names == rest:
            raise resolver.UnusableReply("truncated")
        return _answer(names)

    calls = _recording(monkeypatch, _reply)

    out = await resolver.interpret(surfaces)

    assert calls == [first, rest] + [[name] for name in rest], (
        "the retry re-asked foods outside the chunk that failed, or skipped "
        "one inside it")
    assert sorted(r.surface_form for r in out) == sorted(surfaces), (
        "the retry did not recover every food of the unreadable chunk")


@pytest.mark.asyncio
async def test_a_chunk_cannot_answer_for_another_chunks_food(monkeypatch):
    """Each call parses against what IT asked. A later chunk echoing a food
    from an earlier chunk — with a different verdict — is an unasked surface
    for that call and is discarded; the earlier verdict stands, once."""
    cap = resolver._MAX_BATCH
    surfaces = _surfaces(cap + 3)
    echoed = surfaces[0]

    def _reply(names, n):
        payload = json.loads(_answer(names))
        if n == 2:
            payload["foods"].append({"surface": echoed, "state": "distinct",
                                     "entity": "an echo", "meaning": "echo"})
        return json.dumps(payload, ensure_ascii=False)

    calls = _recording(monkeypatch, _reply)

    out = await resolver.interpret(surfaces)

    assert len(calls) == 2, "the echo was never delivered — a vacuous gate"
    rows = [r for r in out if r.surface_form == echoed]
    assert len(rows) == 1, f"{len(rows)} rows for one surface"
    assert rows[0].canonical_entity_id == surface_key(echoed), (
        "a later chunk's echo overrode the verdict of the chunk that asked")


# ── structural: the cap is a size, never a bound ─────────────────────────────

def test_the_cap_is_a_chunk_size_and_never_bounds_a_subscript():
    """⛔ STRUCTURAL, because this is the regression that would be silent. A
    subscript bounded by `_MAX_BATCH` can only ever keep a prefix and drop the
    rest — `[:_MAX_BATCH]` was the whole defect. Partitioning belongs to a
    function that takes the cap as a SIZE."""
    source = pathlib.Path(resolver.__file__).read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Subscript):
            continue
        bound_by = {n.id for n in ast.walk(node.slice)
                    if isinstance(n, ast.Name)}
        assert "_MAX_BATCH" not in bound_by, (
            f"line {node.lineno}: `_MAX_BATCH` bounds a subscript — a prefix, "
            f"which is the shape that dropped eight surfaces on 2026-09-03")


# ── the consumer-side proof: what the CALLER receives, through the store ─────

import pytest_asyncio  # noqa: E402

from skills.nutrition import entity_resolution as er  # noqa: E402
from tests.test_a_full_day_of_food import app_db, seeded  # noqa: E402,F401


class _Block:
    type = "text"

    def __init__(self, text):
        self.text = text


class _Reply:
    def __init__(self, text):
        self.content, self.stop_reason = [_Block(text)], "end_turn"


class _Client:
    """Answers each call for the foods THAT CALL asked about, and fails the
    call numbers it is told to — so the reply follows the request rather than
    being one fixed payload, which a chunked producer would expose."""

    def __init__(self, failing=()):
        self.asked, self.failing, self.messages = [], set(failing), self

    async def create(self, **kw):
        self.asked.append(kw)
        if len(self.asked) in self.failing:
            raise RuntimeError("provider down")
        names = json.loads(kw["messages"][0]["content"])["foods"]
        return _Reply(_answer(names))


@pytest_asyncio.fixture
async def store(app_db, seeded):           # noqa: F811
    import db.database as D
    async with D.AsyncSessionLocal() as session:
        yield session


@pytest.mark.asyncio
async def test_the_caller_receives_an_answer_for_every_surface(store,
                                                               monkeypatch):
    """The complaint, verbatim: the caller received fewer results than
    surfaces. Through `ensure_resolved` and the real store, cap + 3 surfaces
    in must be cap + 3 identities out, each with its own row."""
    client = _Client()
    monkeypatch.setattr(resolver, "_get_client", lambda: client)
    surfaces = _surfaces(resolver._MAX_BATCH + 3)

    got = await resolver.ensure_resolved(store, surfaces)

    assert len(client.asked) == 2, "the surfaces past the cap were never asked"
    assert set(got) == set(surfaces), (
        f"the caller received {len(got)} identities for {len(surfaces)} "
        f"surfaces; missing={sorted(set(surfaces) - set(got))}")
    for surface in surfaces:
        assert got[surface], f"{surface!r} came back without an identity"
        assert await er.resolve(store, surface) is not None, (
            f"{surface!r} was answered but has no row")


@pytest.mark.asyncio
async def test_a_failed_chunk_leaves_no_row_not_an_unresolved_one(store,
                                                                   monkeypatch):
    """⛔ THE INVARIANT AT THE STORE. A surface whose chunk failed has NO ROW —
    the honest absence `ensure_resolved` documents — and not an `unresolved`
    row, which would be a transport failure recorded as the model's verdict
    and would survive as one until the contract expired. The chunk that
    answered is stored, so next turn only the failed surfaces are missing."""
    client = _Client(failing={2})
    monkeypatch.setattr(resolver, "_get_client", lambda: client)
    cap = resolver._MAX_BATCH
    surfaces = _surfaces(cap + 3)
    answered, failed = surfaces[:cap], surfaces[cap:]

    got = await resolver.ensure_resolved(store, surfaces)

    assert len(client.asked) == 2
    assert set(got) == set(answered), "the answered chunk did not all land"
    for surface in failed:
        assert surface not in got
        assert await er.resolve(store, surface) is None, (
            f"{surface!r} got no answer yet has a row — an absence became a "
            f"verdict")
