"""Which renderer spoke, on which model, and how many calls it took.

`compose_async` is generate → validate → retry → fall back. From outside it,
all four outcomes are one `await` returning a string: a turn that spoke on the
first call and a turn that paid for two and then used the template are
indistinguishable in the log. That is the shape stacked retries hide in — a
bounded turn becomes an unbounded one and nothing in the log changes.

Three facts only the voice layer holds, so it records them itself:

  * `retry_count` — a validation retry is a second model call wearing the same
    await. Counted as CALLS MINUS ONE rather than counting retries directly:
    the loop exits from three places, "how many did we pay for" is the same
    arithmetic at all three, and "was that last one a retry" is a different
    answer at each.
  * `fallback_path` — decided by which return branch is taken, and the
    branches are not equivalent. `model_unavailable` is an outage,
    `validation:…` is the model saying something it was not allowed to say,
    `composer_off` is a flag, `renderer_exception` is a bug. One `fallback=1`
    would merge four different problems.
  * `voice_profile` — the COMPILED brief, not the raw intent. Ten intents map
    onto four profiles, and the question the report answers is "how does each
    brief behave": a `commit` and a `correct` sharing the micro brief share
    its latency and its failure modes, and splitting them by intent would put
    four samples in ten buckets. The field did not have to move when the
    compiler landed, because "which voice spoke on this turn" is the same
    question either way.

Every path out of the renderer is covered here, including the two that never
reach `compose_async` at all. A report that only counts the model path cannot
see the turns where nothing spoke but the template.
"""
import pytest

import core.food_response as FR
import core.food_trace as TRACE
import core.llm
from core.food_ledger import TransactionSnapshot
from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, render_plan,
                                voice_profile_for)


def _trace(tid="v"):
    return TRACE.begin(turn_id=tid, user_id=1, mode="moderate", channel="ios")


def _plan(intent=FoodResponseIntent.COMMIT) -> FoodResponsePlan:
    """A committing turn, so `validate` has a snapshot to check figures
    against — without one there is nothing for a bad number to contradict."""
    return FoodResponsePlan(
        intent=intent,
        committed_items=(FoodItemSummary(name="Rice cake", calories=35,
                                         protein=0),),
        committed_snapshot=TransactionSnapshot(
            batch_cal=35, batch_protein=0, day_cal=1450, day_protein=95,
            cal_target=2200, protein_target=160, logged=("Rice cake",)))


def _model(text=None, boom=False):
    async def _fake(*a, **k):
        if boom:
            raise RuntimeError("529 overloaded")
        return {"text": text, "tool_calls": [], "raw_content": []}
    return _fake


# ── the happy path costs one call ────────────────────────────────────────────
async def test_a_clean_first_attempt_records_no_retries(monkeypatch):
    monkeypatch.setattr(core.llm, "chat",
                        _model("Rice cake logged. You're at 1450."))
    t = _trace()
    await FR.compose_async(_plan())
    d = t.as_dict()
    assert d["retry_count"] == 0
    assert d["fallback_path"] == ""
    # The COMPILED profile, not the raw intent: ten intents map onto four
    # briefs, and the report has to answer "how does each brief behave".
    assert d["voice_profile"] == "micro_acknowledgement"


async def test_the_model_that_spoke_is_named(monkeypatch):
    monkeypatch.setattr(core.llm, "chat", _model("Rice cake logged."))
    t = _trace()
    await FR.compose_async(_plan(), model="claude-haiku-4-5-20251001")
    assert t.as_dict()["voice_model"] == "claude-haiku-4-5-20251001"


# ── the expensive paths are visible ──────────────────────────────────────────
async def test_an_outage_is_one_call_and_no_retry(monkeypatch):
    """`chat()` has already tried its own model fallback by then. Retrying a
    call that never happened would be paying twice for an outage."""
    monkeypatch.setattr(core.llm, "chat", _model(boom=True))
    t = _trace()
    _, why = await FR.compose_async(_plan())
    assert why == "model_unavailable"
    assert t.as_dict()["retry_count"] == 0
    assert t.as_dict()["fallback_path"] == "model_unavailable"


async def test_a_turn_that_never_validates_records_the_second_call(monkeypatch):
    """The number that makes stacked retries visible. Two calls, one retry —
    and a `fallback_path` naming what the model kept doing wrong."""
    calls = []

    async def _bad(*a, **k):
        calls.append(1)
        # A figure the snapshot cannot support: the whole point of validate().
        return {"text": "Rice cake logged, 900 cal and 40g protein.",
                "tool_calls": [], "raw_content": []}

    monkeypatch.setattr(core.llm, "chat", _bad)
    t = _trace()
    await FR.compose_async(_plan())
    d = t.as_dict()
    assert len(calls) == 2, "the retry did not happen — fixture no longer fails"
    assert d["retry_count"] == 1
    assert d["fallback_path"].startswith("validation:")


async def test_the_four_fallback_paths_are_not_merged(monkeypatch):
    """`fallback=1` would report an outage, a bad flag, a validator rejection
    and a bug as the same event."""
    seen = set()

    monkeypatch.setattr(core.llm, "chat", _model(boom=True))
    t = _trace()
    await FR.compose_async(_plan())
    seen.add(t.as_dict()["fallback_path"])

    monkeypatch.setenv("FOOD_COMPOSER", "false")
    t = _trace()
    await render_plan(_plan())
    seen.add(t.as_dict()["fallback_path"])

    assert seen == {"model_unavailable", "composer_off"}


# ── the paths that never reach compose_async ─────────────────────────────────
async def test_the_composer_being_off_is_still_a_voice(monkeypatch):
    monkeypatch.setenv("FOOD_COMPOSER", "false")
    t = _trace()
    text = await render_plan(_plan())
    assert text.strip(), "the floor must still say something"
    d = t.as_dict()
    # The COMPILED profile, not the raw intent: ten intents map onto four
    # briefs, and the report has to answer "how does each brief behave".
    assert d["voice_profile"] == "micro_acknowledgement"
    assert d["fallback_path"] == "composer_off"


async def test_a_renderer_bug_is_recorded_as_one(monkeypatch):
    monkeypatch.setenv("FOOD_COMPOSER", "true")

    async def _explode(*a, **k):
        raise ValueError("bug in build_prompt")

    monkeypatch.setattr(FR, "compose_async", _explode)
    t = _trace()
    text = await render_plan(_plan())
    assert text.strip()
    assert t.as_dict()["fallback_path"] == "renderer_exception"


@pytest.mark.parametrize("intent", [FoodResponseIntent.CLARIFY,
                                    FoodResponseIntent.CORRECT,
                                    FoodResponseIntent.COMMIT])
async def test_every_intent_declares_its_profile(monkeypatch, intent):
    """Voice-profile coverage is a success metric, so an unlabelled turn is a
    hole in the measurement rather than a cosmetic gap."""
    monkeypatch.setenv("FOOD_COMPOSER", "false")
    t = _trace()
    await render_plan(_plan(intent))
    assert t.as_dict()["voice_profile"] == voice_profile_for(intent)


def test_noting_the_voice_with_no_trace_is_silent():
    FR._note_voice(_plan(), voice_model="m")


# ── the worst case is bounded ────────────────────────────────────────────────
async def test_a_hanging_composer_costs_the_sentence_not_the_write(monkeypatch):
    """This was the one model call in the lane not under the turn budget, and
    the arithmetic is why that mattered: the Anthropic client carries
    max_retries=3 at a 45s timeout, so one `await chat(...)` is up to four
    round trips and ~180s — and the loop makes up to two of them. Nothing
    bounded it, so a composer that hung outlived the turn it was writing for.
    """
    import asyncio

    monkeypatch.setenv("FOOD_VOICE_DEADLINE_S", "0.2")

    async def _hang(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(core.llm, "chat", _hang)
    loop = asyncio.get_running_loop()
    started = loop.time()
    text, why = await FR.compose_async(_plan())
    assert loop.time() - started < 2.0, "the deadline did not bind"
    assert text.strip(), "the floor must still speak"
    assert "Rice cake" in text, "and it must still name what was written"
    assert why == "voice_timeout"


async def test_slow_and_down_are_not_the_same_finding(monkeypatch):
    """Both end in the deterministic floor, so the user cannot tell — but one
    is fixed by a provider and the other by a budget, and a report that merges
    them sends you to the wrong one."""
    import asyncio

    monkeypatch.setenv("FOOD_VOICE_DEADLINE_S", "0.2")

    async def _hang(*a, **k):
        await asyncio.sleep(30)

    monkeypatch.setattr(core.llm, "chat", _hang)
    t = _trace()
    await FR.compose_async(_plan())
    slow = t.as_dict()["fallback_path"]

    monkeypatch.setattr(core.llm, "chat", _model(boom=True))
    t = _trace()
    await FR.compose_async(_plan())
    down = t.as_dict()["fallback_path"]

    assert {slow, down} == {"voice_timeout", "model_unavailable"}


async def test_a_timeout_stops_rather_than_retrying_into_a_dead_budget(
        monkeypatch):
    """`DeadlineExceeded` means the turn is over, not that this call was
    unlucky. Retrying would spend a budget that is already gone."""
    import asyncio

    calls = []
    monkeypatch.setenv("FOOD_VOICE_DEADLINE_S", "0.2")

    async def _hang(*a, **k):
        calls.append(1)
        await asyncio.sleep(30)

    monkeypatch.setattr(core.llm, "chat", _hang)
    await FR.compose_async(_plan())
    assert len(calls) == 1, f"retried a timed-out call {len(calls)} times"
