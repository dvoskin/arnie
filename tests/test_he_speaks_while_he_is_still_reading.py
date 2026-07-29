"""The heads-up covers the wait instead of following it.

The reassurance existed and fired in the wrong place. `_turn_t0` starts at
`conversation.py:680`, the interpreter is awaited at :1075, and the heads-up
check sat at :1578 — around 450 lines and four seconds later. So its 2.5s
threshold was always already satisfied, the promise in its comment ("if the
interpreter gets faster, this stops firing on its own") could never trigger,
and the user sat in complete silence for the longest block of the turn and
was then told something was happening after it was over.

The signal to fire on already existed. `_SpeculativeEnrichment` watches the
stream for a food NAME so it can start enrichment early, and the interpreter's
JSON opens with `{"action":"log","items":[{"food":` — so the first name lands
within the first handful of tokens. That name is also the earliest moment
anything in the turn KNOWS this is food: not a regex guess, the model having
already parsed one. Which is exactly what makes it safe to speak before the
parse finishes.

Three properties this has to keep, because a heads-up that is wrong is worse
than none:

  * ONCE. Two "checking the macros" in a turn reads as the lane stuttering.
  * NEVER FATAL. It runs inside a stream handler; a delta that raises costs
    the caller its bubbles, and the turn is worth more than the reassurance
    about it.
  * NOT ON THE ANSWER TURN. A clarification answer is short and already in a
    thread the user is watching; "checking the macros" there reads as the
    question being asked again.
"""
import asyncio

import pytest

import core.food_turn as FT

CHUNKS = ['{"action":"log","items":[{"food":"Chicken schnitzel"',
          ',"amount":1,"unit":"cutlet","calories":420},',
          '{"food":"Kartoffelsalat","amount":1,"unit":"cup"}],',
          '"ambiguities":[],"points":[]}']


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """The handler's other job is starting lookups. Silence them so these
    tests are about the announcement only."""
    monkeypatch.setattr(FT._SpeculativeEnrichment, "_start",
                        staticmethod(lambda food: None))


async def _stream(handler, gap=0.02):
    for chunk in CHUNKS:
        await handler(chunk)
        await asyncio.sleep(gap)


async def test_it_fires_before_the_generation_finishes():
    """The whole point. Firing after is what the old placement did."""
    loop = asyncio.get_running_loop()
    fired = []
    start = loop.time()

    async def on_first(name):
        fired.append((name, loop.time() - start))

    await _stream(FT._SpeculativeEnrichment(on_first))
    total = loop.time() - start
    assert fired, "nothing announced"
    _, at = fired[0]
    assert at < total / 2, (
        f"announced at {at:.3f}s of {total:.3f}s — that is not early")


async def test_it_fires_on_the_first_food_the_model_writes():
    fired = []

    async def on_first(name):
        fired.append(name)

    await _stream(FT._SpeculativeEnrichment(on_first))
    assert fired[0] == "Chicken schnitzel"


async def test_it_fires_exactly_once_however_many_foods_arrive():
    fired = []

    async def on_first(name):
        fired.append(name)

    await _stream(FT._SpeculativeEnrichment(on_first))
    assert len(fired) == 1, f"announced {len(fired)} times: {fired}"


async def test_a_repeated_name_does_not_announce_again():
    fired = []
    h = FT._SpeculativeEnrichment(lambda n: fired.append(n) or asyncio.sleep(0))
    await h('{"items":[{"food":"Toast"}')
    await h(',{"food":"Toast"}]}')
    assert len(fired) == 1


async def test_a_callback_that_raises_does_not_break_the_stream():
    """It runs inside the stream handler. A raising delta costs the caller
    its bubbles, and the turn is worth more than the reassurance."""
    async def boom(_name):
        raise RuntimeError("client disconnected")

    await _stream(FT._SpeculativeEnrichment(boom))    # must not raise


async def test_the_lookups_still_start_regardless(monkeypatch):
    """The announcement is a passenger on the enrichment signal, not a
    replacement for it."""
    started = []
    monkeypatch.setattr(FT._SpeculativeEnrichment, "_start",
                        staticmethod(started.append))

    async def boom(_name):
        raise RuntimeError("nope")

    await _stream(FT._SpeculativeEnrichment(boom))
    assert started == ["Chicken schnitzel", "Kartoffelsalat"]


async def test_no_callback_is_the_old_behaviour():
    await _stream(FT._SpeculativeEnrichment())
    await _stream(FT._SpeculativeEnrichment(None))


async def test_a_stream_with_no_food_announces_nothing():
    """`{"action":"pass"}` is not a food turn, and saying "checking the
    macros" on one would be the gate speaking instead of the model."""
    fired = []

    async def on_first(name):
        fired.append(name)

    h = FT._SpeculativeEnrichment(on_first)
    await h('{"action":"pass"}')
    assert not fired


# ── the wiring ───────────────────────────────────────────────────────────────
def test_the_interpreter_entry_points_accept_the_callback():
    import inspect
    for fn in (FT.run, FT._run_untraced):
        assert "on_first_food" in inspect.signature(fn).parameters


def test_the_late_heads_up_stands_down_when_the_early_one_spoke():
    """Two in one turn reads as stuttering. The suppression is a flag rather
    than a timing guess, because the early one may fire arbitrarily long
    before the late check runs."""
    import pathlib
    src = pathlib.Path("core/conversation.py").read_text()
    assert "not _early_heads_up_sent" in src


def test_the_answer_turn_is_excluded():
    """A clarification answer is short and already in a thread the user is
    watching; a lookup line there reads as the question being re-asked."""
    import pathlib
    src = pathlib.Path("core/conversation.py").read_text()
    assert "_early_heads_up_sent or _sft_prior is not None" in src
