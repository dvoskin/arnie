"""Enrichment starts while the interpreter is still writing.

The interpreter and the enrichment were strictly sequential: generate ~700
tokens of JSON, parse it, then go to the network. That ordering is an accident
of how the code was written, not a real dependency — what enrichment needs is a
food NAME, and names are the first thing the model writes. Production traces
put the interpreter around 4 s and enrichment 2-5 s behind it, back to back,
for a total nobody had to pay.

Two pieces make the overlap safe rather than clever:

  * `_fetch_usda_off` is single-flighted per turn, so the speculative lookup
    and the real one are the same request — whoever asks second awaits what
    the first started. Turn-keyed, because a stale hit would be a wrong number
    rather than a slow one.
  * A speculative miss costs one unused read against a public database. It
    never touches the session, the ledger or the decision, so it cannot make a
    turn incorrect — only earlier.
"""
import asyncio

import pytest

import core.food_turn as FT
import handlers.tool_executor as TE

CHUNKS = ['{"action":"log","items":[{"food":"Chicken schnitzel"',
          ',"amount":1,"unit":"palm size","calories":420},',
          '{"food":"Kartoffelsalat","amount":1,"unit":"cup"}],',
          '"say":"..."}']


@pytest.fixture(autouse=True)
def _clean_registry():
    TE._INFLIGHT_FETCHES.clear()
    yield
    TE._INFLIGHT_FETCHES.clear()


@pytest.fixture
def fake_fetch(monkeypatch):
    calls = []

    async def _fetch(name, packaged):
        calls.append(name)
        await asyncio.sleep(0.05)
        return ({"desc": name}, None)

    monkeypatch.setattr(TE, "_fetch_usda_off_uncached", _fetch)
    return calls


async def _stream(handler, gap=0.04):
    for chunk in CHUNKS:
        await handler(chunk)
        await asyncio.sleep(gap)


async def test_the_lookup_is_already_done_when_the_parse_finishes(fake_fetch):
    loop = asyncio.get_running_loop()
    start = loop.time()
    await _stream(FT._SpeculativeEnrichment())
    generated = loop.time() - start
    await asyncio.gather(TE._fetch_usda_off("Chicken schnitzel", True),
                         TE._fetch_usda_off("Kartoffelsalat", False))
    total = loop.time() - start
    assert total - generated < 0.03, (
        f"enrichment added {total - generated:.3f}s after generation; "
        "the point is that it costs nothing")


async def test_one_request_per_food_not_one_per_caller(fake_fetch):
    await _stream(FT._SpeculativeEnrichment())
    await TE._fetch_usda_off("Chicken schnitzel", True)
    await TE._fetch_usda_off("Chicken schnitzel", True)
    assert fake_fetch.count("Chicken schnitzel") == 1


async def test_the_speculative_result_is_the_real_one(fake_fetch):
    await _stream(FT._SpeculativeEnrichment())
    usda, _ = await TE._fetch_usda_off("Kartoffelsalat", False)
    assert usda == {"desc": "Kartoffelsalat"}


async def test_a_name_is_only_ever_started_once_from_the_stream(fake_fetch):
    handler = FT._SpeculativeEnrichment()
    # The same name arriving twice — a rewrite mid-generation — is one lookup.
    await handler('{"items":[{"food":"Toast"}')
    await handler(',{"food":"Toast"}]}')
    await asyncio.sleep(0.08)
    assert fake_fetch.count("Toast") == 1


async def test_a_failed_speculative_lookup_does_not_poison_the_real_one(
        monkeypatch):
    attempts = []

    async def _flaky(name, packaged):
        attempts.append(name)
        if len(attempts) == 1:
            raise RuntimeError("OFF timed out")
        return ({"desc": name}, None)

    monkeypatch.setattr(TE, "_fetch_usda_off_uncached", _flaky)
    await FT._SpeculativeEnrichment()('{"items":[{"food":"Bagel"}]}')
    await asyncio.sleep(0.02)
    usda, _ = await TE._fetch_usda_off("Bagel", False)
    assert usda == {"desc": "Bagel"}, "a dead speculative fetch must re-run"


async def test_another_turns_result_is_never_reused(fake_fetch, monkeypatch):
    """Turn-keyed on purpose: a stale hit would be a wrong number, which is a
    worse failure than the slow one this exists to fix."""
    from core.turn_identity import CURRENT_TURN_ID
    CURRENT_TURN_ID.set("turn-a")
    await TE._fetch_usda_off("Toast", False)
    CURRENT_TURN_ID.set("turn-b")
    await TE._fetch_usda_off("Toast", False)
    assert fake_fetch.count("Toast") == 2
