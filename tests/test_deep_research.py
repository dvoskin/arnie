"""Deep research turns — the agentic loop, its gating, and its guardrails.

Everything here is offline: the Anthropic client and the search function are
injected fakes (the module's test seams). What's pinned:

  • the loop: search rounds run, results feed back, synthesis text returns
  • parallelism cap: >4 queries in one round → extras declined, not dropped
  • wall-clock budget: exhausted budget forces a tool-less synthesis call
  • resilience: a raising search degrades to a failed-result block, a raising
    client degrades to ok=False (never an exception to the caller)
  • gating: deep_research rides the SEARCH_ENABLED gate with web_search
  • the daily cap helper burns/blocks/rolls over correctly
  • the prompt ships the DEEP RESEARCH ladder when search is enabled
  • the heads-up fallback set covers deep_research (slow-tool contract)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.deep_research import run_deep_research, DeepResult
from core.search import SearchResult


# ── Fakes ─────────────────────────────────────────────────────────────────────

def _text_block(text):
    return SimpleNamespace(type="text", text=text)


def _tool_block(tu_id, query):
    return SimpleNamespace(type="tool_use", id=tu_id, name="web_search",
                           input={"query": query})


def _resp(*blocks):
    return SimpleNamespace(content=list(blocks), stop_reason="end_turn")


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []          # kwargs of every create() call, in order

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._responses:
            raise AssertionError("fake client ran out of scripted responses")
        r = self._responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _search_ok(query):
    return SearchResult(
        answer=f"answer for {query}",
        results=[{"title": f"t:{query}", "url": f"https://x.test/{query}",
                  "content": f"content for {query}"}],
        query=query,
    )


async def _fake_search(query):
    return _search_ok(query)


PLAN = ("Here's the week.|||**Fair runs Thu-Sun**, hours 11-7.|||"
        "Protein stays at 180g.|||My move: book Thursday.")


# ── The loop ──────────────────────────────────────────────────────────────────

async def test_one_round_then_synthesis():
    client = _FakeClient([
        _resp(_text_block("checking."), _tool_block("tu1", "fair hours"),
              _tool_block("tu2", "menu options")),
        _resp(_text_block(PLAN)),
    ])
    dr = await run_deep_research(
        "plan the fair weekend", "goal: cut, 2100 cal",
        _chat_client=client, _search_fn=_fake_search,
    )
    assert dr.ok and dr.plan == PLAN
    assert dr.rounds == 1 and dr.searches == 2
    assert ("t:fair hours", "https://x.test/fair hours") in dr.sources
    # Round 2's call carried the tool results back to the model.
    second_call = client.messages.calls[1]
    tool_results = second_call["messages"][-1]["content"]
    assert any(b.get("type") == "tool_result" for b in tool_results)
    assert any("answer for fair hours" in str(b.get("content")) for b in tool_results)


async def test_parallel_cap_declines_extras_but_answers_all_tool_uses():
    """6 queries in one round: 4 execute, 2 get an explicit decline block —
    the API requires a tool_result per tool_use, dropping one would 400."""
    six = [_tool_block(f"tu{i}", f"q{i}") for i in range(6)]
    client = _FakeClient([_resp(*six), _resp(_text_block(PLAN))])
    dr = await run_deep_research(
        "obj", "ctx", _chat_client=client, _search_fn=_fake_search,
    )
    assert dr.ok and dr.searches == 4
    results = client.messages.calls[1]["messages"][-1]["content"]
    assert len([b for b in results if b["type"] == "tool_result"]) == 6
    declined = [b for b in results if "Skipped" in str(b["content"])]
    assert len(declined) == 2


async def test_exhausted_budget_forces_toolless_synthesis():
    """With a zero budget, the very first call must go out WITHOUT tools —
    the model can only answer, so a simple prompt path can never spiral."""
    client = _FakeClient([_resp(_text_block(PLAN))])
    dr = await run_deep_research(
        "obj", "ctx", time_budget_s=0.0,
        _chat_client=client, _search_fn=_fake_search,
    )
    assert dr.ok and dr.rounds == 0
    assert "tools" not in client.messages.calls[0]


async def test_deep_loop_disables_thinking_by_default():
    """The deep loop runs on Sonnet 5; adaptive thinking (the omitted default)
    would silently eat the synthesis max_tokens cap and truncate the plan.
    Every loop call must pass thinking={'type':'disabled'}."""
    client = _FakeClient([
        _resp(_tool_block("tu1", "q1")),
        _resp(_text_block(PLAN)),
    ])
    await run_deep_research("obj", "ctx", _chat_client=client, _search_fn=_fake_search)
    assert all(c.get("thinking") == {"type": "disabled"} for c in client.messages.calls)


async def test_max_rounds_forces_synthesis(monkeypatch):
    monkeypatch.setenv("DEEP_RESEARCH_MAX_ROUNDS", "1")
    client = _FakeClient([
        _resp(_tool_block("tu1", "q1")),
        _resp(_text_block(PLAN)),
    ])
    dr = await run_deep_research(
        "obj", "ctx", _chat_client=client, _search_fn=_fake_search,
    )
    assert dr.ok and dr.rounds == 1
    # The second (synthesis) call is tool-less and carries the time's-up nudge.
    final_call = client.messages.calls[1]
    assert "tools" not in final_call
    trailing = final_call["messages"][-1]["content"]
    assert any("Research time is up" in str(b.get("text", "")) for b in trailing
               if isinstance(b, dict))


async def test_search_exception_degrades_to_failed_block():
    async def _boom(query):
        raise RuntimeError("tavily down")
    client = _FakeClient([
        _resp(_tool_block("tu1", "q1")),
        _resp(_text_block(PLAN)),
    ])
    dr = await run_deep_research(
        "obj", "ctx", _chat_client=client, _search_fn=_boom,
    )
    assert dr.ok  # the loop survives; the model saw the failure and answered
    results = client.messages.calls[1]["messages"][-1]["content"]
    assert any("SEARCH FAILED" in str(b["content"]) for b in results
               if b.get("type") == "tool_result")


async def test_client_exception_returns_not_ok():
    client = _FakeClient([RuntimeError("api down")])
    dr = await run_deep_research(
        "obj", "ctx", _chat_client=client, _search_fn=_fake_search,
    )
    assert not dr.ok and "api down" in dr.error


async def test_empty_objective_rejected():
    dr = await run_deep_research("", "ctx", _chat_client=_FakeClient([]),
                                 _search_fn=_fake_search)
    assert not dr.ok and dr.error == "empty objective"


async def test_empty_synthesis_is_not_ok():
    client = _FakeClient([_resp(_text_block(""))])
    dr = await run_deep_research("obj", "ctx", _chat_client=client,
                                 _search_fn=_fake_search)
    assert not dr.ok and "empty synthesis" in dr.error


async def test_context_and_injuries_reach_the_researcher():
    client = _FakeClient([_resp(_text_block(PLAN))])
    await run_deep_research(
        "obj", "cut at 2100 cal, trains 4x/wk",
        injuries="left shoulder impingement",
        _chat_client=client, _search_fn=_fake_search,
    )
    first_user = client.messages.calls[0]["messages"][0]["content"]
    assert "cut at 2100 cal" in first_user
    assert "left shoulder impingement" in first_user


# ── Gating + guardrails ───────────────────────────────────────────────────────

def test_deep_research_gated_with_search(monkeypatch):
    from core.tools import build_tools
    monkeypatch.setenv("SEARCH_ENABLED", "true")
    names = {t["name"] for t in build_tools()}
    assert "deep_research" in names and "web_search" in names
    monkeypatch.setenv("SEARCH_ENABLED", "false")
    names = {t["name"] for t in build_tools()}
    assert "deep_research" not in names and "web_search" not in names


def test_daily_cap_burns_blocks_and_rolls_over(monkeypatch):
    import handlers.tool_executor as te
    monkeypatch.setenv("DEEP_RESEARCH_DAILY_CAP", "2")
    monkeypatch.setattr(te, "_DEEP_RESEARCH_USED", {}, raising=True)
    assert te._deep_research_allow(999) is True
    assert te._deep_research_allow(999) is True
    assert te._deep_research_allow(999) is False          # cap hit
    assert te._deep_research_allow(1000) is True          # per-user, not global
    # A stale (yesterday) entry resets on the next allow check.
    te._DEEP_RESEARCH_USED[999] = ("2000-01-01", 2)
    assert te._deep_research_allow(999) is True


def test_prompt_ships_deep_research_ladder(monkeypatch):
    monkeypatch.setenv("SEARCH_ENABLED", "true")
    from core.prompts import build_arnie_system
    s = " ".join(build_arnie_system(platform="ios").split())
    assert "DEEP RESEARCH" in s
    assert "deep_research for a real PLAN" in s
    assert "a simple prompt must stay instant" in s
    # Off the gate, the section (and the tool) disappear together.
    monkeypatch.setenv("SEARCH_ENABLED", "false")
    s_off = " ".join(build_arnie_system(platform="ios").split())
    assert "deep_research for a real PLAN" not in s_off


def test_heads_up_fallback_covers_deep_research():
    from handlers.tool_executor import NEEDS_HEADS_UP_TOOLS, tool_heads_up
    assert "deep_research" in NEEDS_HEADS_UP_TOOLS
    line = tool_heads_up("deep_research", seed="plan my trip")
    assert line and len(line) <= 30


# ── run_turn integration: direct delivery ─────────────────────────────────────

from types import SimpleNamespace as _NS


def _turn_user():
    return _NS(
        id=1, onboarding_completed=True, timezone="UTC", name="Danny",
        nudges_sent="", injuries="",
        preferences=_NS(calorie_target=2100, protein_target=180),
    )


def _stub_log():
    """Stands in for today's DailyLog so run_turn doesn't hit the (absent) db.
    id=None also skips the post-tools db.refresh(today_log)."""
    return _NS(
        id=None, total_calories=0, total_protein=0, total_carbs=0,
        total_fats=0, total_water_ml=0, workout_completed=False,
        cardio_completed=False, food_entries=[], exercise_entries=[],
    )


@pytest.fixture(autouse=True)
def _no_db_reload(monkeypatch):
    """run_turn reloads the user post-tools; there's no db in these tests."""
    import db.queries as Q
    async def _same(db, user_id):
        return _turn_user()
    monkeypatch.setattr(Q, "reload_user", _same)


@pytest.fixture(autouse=True)
def _noop_pending_questions(monkeypatch):
    import reminders.lifecycle as RL
    async def _noop(db, user, llm_reply_text="", **kwargs):
        return None
    monkeypatch.setattr(RL, "sync_pending_questions", _noop)


PLAN_FULL = ("Wednesday's covered.|||**Fair opens 11**, VIP Thursday.|||"
             "Protein first at dinner.|||My move: book Thursday, order the bowl.")


@pytest.mark.asyncio
async def test_run_turn_delivers_deep_plan_directly(monkeypatch):
    """A successful deep_research run: the stashed plan IS the reply — no
    follow-up LLM pass runs (latency: the iOS 30s timeout can't absorb a
    second ~1.4k-token generation), nothing compresses the plan."""
    import core.conversation as C
    from core.conversation import run_turn

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None):
        return {
            "text": "give me ~20 seconds, building this properly.",
            "tool_calls": [{"name": "deep_research", "id": "tu1", "input": {
                "objective": "plan the trip eating",
                "key_context": "cut at 2100",
            }}],
            "raw_content": [{"type": "text", "text": "hu"}],
            "stop_reason": "end_turn",
        }

    followups = {"n": 0}
    async def fake_follow_up(*a, **kw):
        followups["n"] += 1
        return "SHOULD NOT RUN"

    async def fake_execute(tool_calls, user, today_log, db, source_type, **kw):
        # Mirror the real handler: stash the plan on the tool input.
        tool_calls[0]["input"]["_deep_plan"] = PLAN_FULL
        return {"deep_research": "RESEARCHED PLAN delivered to the user as-is:…"}

    monkeypatch.setattr(C, "chat", fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", fake_execute)

    turn = await run_turn(
        _turn_user(), None,
        [{"role": "user", "content": "flying out tomorrow, plan my food"}],
        "SYS", "ios", in_onboarding=False, was_onboarding=False, today_log=_stub_log(),
    )
    joined = "|||".join(turn.response.bubbles)
    assert "My move: book Thursday" in joined
    assert "Fair opens 11" in joined
    assert followups["n"] == 0, "deep plan must ship WITHOUT a follow-up pass"
    assert "SHOULD NOT RUN" not in joined


@pytest.mark.asyncio
async def test_run_turn_deep_failure_falls_back_to_followup(monkeypatch):
    """A failed run stashes no plan → the normal voice-by-default follow-up
    coaches from the failure instruction."""
    import core.conversation as C
    from core.conversation import run_turn

    async def fake_chat(messages, system, tools=True, max_tokens=1024, model=None):
        return {
            "text": "building this properly.",
            "tool_calls": [{"name": "deep_research", "id": "tu1", "input": {
                "objective": "plan", "key_context": "ctx",
            }}],
            "raw_content": [{"type": "text", "text": "hu"}],
            "stop_reason": "end_turn",
        }

    async def fake_follow_up(*a, **kw):
        return "couldn't verify the specifics, here's my honest read.|||protein first."

    async def fake_execute(tool_calls, user, today_log, db, source_type, **kw):
        return {"deep_research": "DEEP RESEARCH failed (timeout). …"}

    monkeypatch.setattr(C, "chat", fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", fake_execute)

    turn = await run_turn(
        _turn_user(), None,
        [{"role": "user", "content": "flying out tomorrow, plan my food"}],
        "SYS", "ios", in_onboarding=False, was_onboarding=False, today_log=_stub_log(),
    )
    joined = "|||".join(turn.response.bubbles)
    assert "honest read" in joined
