"""Time-to-first-byte and the token split, off the call that actually paid them.

The interpreter is the largest block in a food turn, and "it takes about four
seconds" was the whole of what anyone knew about it. Four seconds of what, was
unanswerable: time-to-first-byte, input tokens, output tokens and whether the
prefix cache hit are all facts only the model call has, and it threw every one
of them away.

That matters for the obvious reason — you cannot shorten what you have not
split — and for a less obvious one. A warm prefix and a cold one are different
latencies wearing the same stage name. Averaged into a single `interpret:3900`
they hide each other, and the report says the interpreter is uniformly slow
when the truth might be that one turn in ten pays for a cache miss.

Two rules here are easy to get backwards:

  * TTFB is stamped BEFORE the caller's stream handler runs. On the food lane
    that handler starts network fetches, and charging its work to the model's
    response time would make the interpreter look slower every time the
    speculative lookup got faster.
  * The buffered path reports NO `ttfb_ms` rather than zero. "The whole
    response arrived at once" and "it arrived instantly" are different facts,
    and a latency report must not average them together.
"""
import asyncio
import importlib
from types import SimpleNamespace as NS

import pytest

import core.food_trace as TRACE
import core.food_turn as FT


@pytest.fixture
def llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    import core.llm as m
    importlib.reload(m)
    return m


# ── a fake streaming client ──────────────────────────────────────────────────
class _Stream:
    def __init__(self, deltas, first_delay):
        self._deltas, self._first_delay = deltas, first_delay

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    @property
    def text_stream(self):
        async def _gen():
            await asyncio.sleep(self._first_delay)
            for d in self._deltas:
                yield d
        return _gen()

    async def get_final_message(self):
        return NS(content=[NS(type="text", text="".join(self._deltas))],
                  stop_reason="end_turn",
                  usage=NS(input_tokens=6183, output_tokens=118,
                           cache_read_input_tokens=5940,
                           cache_creation_input_tokens=0))


def _client(deltas=("{", '"action"', ':"log"}'), first_delay=0.05):
    return NS(messages=NS(stream=lambda **kw: _Stream(list(deltas), first_delay)))


async def test_ttfb_is_reported_from_the_streaming_path(llm, monkeypatch):
    monkeypatch.setattr(llm, "_get_anthropic", lambda: _client())

    async def handler(_delta):
        return None

    out = await llm._anthropic_chat([{"role": "user", "content": "hi"}], "SYS",
                                    use_tools=False, max_tokens=100,
                                    stream_handler=handler)
    assert out["ttfb_ms"] >= 40


async def test_the_handlers_own_work_is_not_charged_to_the_model(llm,
                                                                monkeypatch):
    """The rule that is easy to get backwards. A handler that takes 300ms must
    not make the model's first byte look 300ms later than it was."""
    monkeypatch.setattr(llm, "_get_anthropic",
                        lambda: _client(deltas=("a", "b", "c"),
                                        first_delay=0.02))

    async def slow_handler(_delta):
        await asyncio.sleep(0.1)

    out = await llm._anthropic_chat([{"role": "user", "content": "hi"}], "SYS",
                                    use_tools=False, max_tokens=100,
                                    stream_handler=slow_handler)
    assert out["ttfb_ms"] < 80, (
        f"ttfb {out['ttfb_ms']}ms includes the handler's 300ms of work")


async def test_the_buffered_path_reports_no_ttfb_rather_than_zero(llm,
                                                                 monkeypatch):
    class _Messages:
        async def create(self, **kw):
            return NS(content=[NS(type="text", text="ok")],
                      stop_reason="end_turn", usage=None)

    monkeypatch.setattr(llm, "_get_anthropic", lambda: NS(messages=_Messages()))
    out = await llm._anthropic_chat([{"role": "user", "content": "hi"}], "SYS",
                                    use_tools=False, max_tokens=100)
    assert "ttfb_ms" not in out, "zero would read as 'instant' in the report"


async def test_usage_still_rides_along(llm, monkeypatch):
    monkeypatch.setattr(llm, "_get_anthropic", lambda: _client())

    async def handler(_d):
        return None

    out = await llm._anthropic_chat([{"role": "user", "content": "hi"}], "SYS",
                                    use_tools=False, max_tokens=100,
                                    stream_handler=handler)
    assert out["usage"]["output_tokens"] == 118
    assert out["usage"]["cache_read_input_tokens"] == 5940


# ── onto the trace ───────────────────────────────────────────────────────────
RESPONSE = {"text": "{}", "ttfb_ms": 612.4,
            "usage": {"input_tokens": 6183, "output_tokens": 118,
                      "cache_read_input_tokens": 5940}}


def test_the_cost_lands_on_the_ambient_trace():
    t = TRACE.begin(turn_id="t", user_id=1, mode="moderate", channel="ios")
    FT._note_interpreter_cost(RESPONSE, "claude-sonnet-5")
    d = t.as_dict()
    assert d["interpreter_model"] == "claude-sonnet-5"
    assert d["interpreter_ttfb_ms"] == 612.4
    assert d["interpreter_input_tokens"] == 6183
    assert d["interpreter_output_tokens"] == 118
    assert d["interpreter_cached_tokens"] == 5940


def test_a_warm_prefix_is_distinguishable_from_a_cold_one():
    """The reason cached tokens are recorded separately at all."""
    warm = TRACE.begin(turn_id="w", user_id=1, mode="moderate", channel="ios")
    FT._note_interpreter_cost(RESPONSE, "m")
    warm_ratio = (warm.interpreter_cached_tokens
                  / warm.interpreter_input_tokens)
    cold = TRACE.begin(turn_id="c", user_id=1, mode="moderate", channel="ios")
    FT._note_interpreter_cost(
        {"usage": {"input_tokens": 6183, "output_tokens": 118}}, "m")
    assert warm_ratio > 0.9 and cold.interpreter_cached_tokens == 0


@pytest.mark.parametrize("res", [None, {}, {"usage": None},
                                 {"usage": {"input_tokens": "junk"}}])
def test_measuring_a_turn_never_costs_the_turn(res):
    """This runs between the model call and the parse. A tracer that can raise
    there turns a measured turn into a lost meal."""
    TRACE.begin(turn_id="t", user_id=1, mode="moderate", channel="ios")
    FT._note_interpreter_cost(res, "m")


def test_noting_the_cost_with_no_trace_is_silent():
    FT._note_interpreter_cost(RESPONSE, "m")


def test_marking_a_moment_with_no_trace_is_silent():
    TRACE.mark("first_visible")
