"""
Lane C — search plumbing tests.

Everything search-related is GATED by db.queries.search_enabled() (default OFF)
and INERT until SEARCH_ENABLED=true. These tests toggle the flag in-process (or
monkeypatch search_enabled) and inject a fake httpx client (the test seam) so no
network is ever hit. The default suite stays byte-green because the flag is off.
"""
import os

import pytest

import core.tools as T
import core.search as S
import core.prompts.arnie as P


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture
def search_on(monkeypatch):
    """Force the gate ON for one test (restored automatically)."""
    monkeypatch.setattr("db.queries.search_enabled", lambda: True)
    return True


@pytest.fixture
def search_off(monkeypatch):
    monkeypatch.setattr("db.queries.search_enabled", lambda: False)
    return False


class _FakeResp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = "fake error body"

    def json(self):
        return self._payload


class _FakeClient:
    """Injectable httpx-like client. Records calls; returns a canned response or
    raises, per construction."""
    def __init__(self, resp=None, raises=None):
        self._resp = resp
        self._raises = raises
        self.calls = []

    async def post(self, url, json=None):
        self.calls.append((url, json))
        if self._raises is not None:
            raise self._raises
        return self._resp


# ── C3: gate decides tool lists, OpenAI mirrors via delegation ──────────────────

def _names(tools):
    return {t["name"] for t in tools}


def _oai_names(tools):
    return {t["function"]["name"] for t in tools}


def test_active_tools_excludes_web_search_when_off(search_off):
    assert "web_search" not in _names(T._active_tools())
    assert "web_search" not in _names(T.build_tools())


def test_active_tools_includes_web_search_when_on(search_on):
    assert "web_search" in _names(T._active_tools())
    assert "web_search" in _names(T.build_tools())


def test_openai_mirrors_anthropic_when_on(search_on):
    # build_tools_openai MUST delegate to build_tools — same gate, two formats.
    assert _oai_names(T.build_tools_openai()) == _names(T.build_tools())
    assert "web_search" in _oai_names(T.build_tools_openai())


def test_openai_mirrors_anthropic_when_off(search_off):
    assert _oai_names(T.build_tools_openai()) == _names(T.build_tools())
    assert "web_search" not in _oai_names(T.build_tools_openai())


def test_web_search_tool_shape(search_on):
    tool = next(t for t in T.build_tools() if t["name"] == "web_search")
    props = tool["input_schema"]["properties"]
    assert set(props) == {"query", "context"}          # exactly two fields
    assert tool["input_schema"]["required"] == ["query"]  # context optional


def test_arnie_tools_alias_is_callable_and_flag_aware(search_on):
    from core.llm import ARNIE_TOOLS
    # Converted from a stale import-time snapshot to a flag-aware callable.
    assert callable(ARNIE_TOOLS)
    assert "web_search" in _names(ARNIE_TOOLS())


# ── INT-2: web_search name + gate contract (one flag, BOTH prompt + tool) ───────
#
# The single search_enabled() flag must light BOTH the SEARCH_RULES prompt section
# (so Arnie KNOWS when to reach for search) AND the web_search tool (so the call can
# actually be made). Neither dark-advertise (prompt without tool) nor advertise-
# without-tool (tool without prompt) is allowed. The literal name the prompt teaches
# and the literal name the tool registers must be byte-identical — the dispatch elif,
# the re-voice set, and the gate all key off this one string.

_SEARCH_TOOL_NAME = "web_search"


def test_search_tool_name_is_exactly_web_search(search_on):
    # The registered tool is named exactly "web_search".
    names = _names(T.build_tools())
    assert _SEARCH_TOOL_NAME in names
    # And the conversation re-voice set keys off the SAME literal.
    import core.conversation as C
    assert _SEARCH_TOOL_NAME in C._VOICED_RESULT_TOOLS


def test_search_rules_section_names_exactly_web_search():
    # The prompt's SEARCH_RULES constant teaches the tool by the same literal name.
    assert _SEARCH_TOOL_NAME in P.SEARCH_RULES


def test_gate_on_lights_both_prompt_and_tool(monkeypatch):
    """search_enabled()=true → SEARCH_RULES IS in the assembled system prompt AND
    web_search IS in the active tool list. No advertise-without-tool, no dark tool."""
    monkeypatch.setattr("db.queries.search_enabled", lambda: True)

    system = P.build_arnie_system("imessage")
    assert P.SEARCH_RULES.strip() in system, "prompt section missing when gate ON"
    assert _SEARCH_TOOL_NAME in _names(T.build_tools()), "tool missing when gate ON"


def test_gate_off_darkens_both_prompt_and_tool(monkeypatch):
    """search_enabled()=false → neither the SEARCH_RULES section NOR the web_search
    tool appears. No dark-advertise (prompt teaching a tool that isn't registered)."""
    monkeypatch.setattr("db.queries.search_enabled", lambda: False)

    system = P.build_arnie_system("imessage")
    assert P.SEARCH_RULES.strip() not in system, "prompt section leaked when gate OFF"
    assert _SEARCH_TOOL_NAME not in _names(T.build_tools()), "tool leaked when gate OFF"


def test_prompt_and_tool_gate_move_together(monkeypatch):
    """The two surfaces are driven by the SAME flag — they can never diverge."""
    for flag in (True, False):
        monkeypatch.setattr("db.queries.search_enabled", lambda f=flag: f)
        in_prompt = P.SEARCH_RULES.strip() in P.build_arnie_system("imessage")
        in_tools = _SEARCH_TOOL_NAME in _names(T.build_tools())
        assert in_prompt == in_tools == flag, (
            f"prompt/tool gate diverged at flag={flag}: "
            f"in_prompt={in_prompt}, in_tools={in_tools}"
        )


# ── C1/C2: search() never raises; graceful empty on missing key / non-200 / exc ─

@pytest.fixture(autouse=True)
def _clean_cache():
    S.reset_cache()
    yield
    S.reset_cache()


async def test_search_missing_key_returns_empty(monkeypatch):
    monkeypatch.setattr(S, "_key", lambda: "")
    sr = await S.search("macros for a chipotle bowl")
    assert sr.results == []
    assert sr.error is not None
    assert sr.query == "macros for a chipotle bowl"
    assert sr.cache_hit is False


async def test_search_non_200_returns_empty(monkeypatch):
    monkeypatch.setattr(S, "_key", lambda: "k")
    client = _FakeClient(resp=_FakeResp(status_code=503))
    sr = await S.search("creatine timing", _client=client)
    assert sr.results == []
    assert sr.error is not None and "503" in sr.error
    assert client.calls, "the injected client should have been used"


async def test_search_exception_returns_empty(monkeypatch):
    monkeypatch.setattr(S, "_key", lambda: "k")
    client = _FakeClient(raises=RuntimeError("boom"))
    sr = await S.search("anything", _client=client)
    assert sr.results == []
    assert sr.error is not None
    # NEVER raises to the caller.


async def test_search_success_populates_query_and_results(monkeypatch):
    monkeypatch.setattr(S, "_key", lambda: "k")
    payload = {
        "answer": "A Chipotle chicken bowl is ~700 cal.",
        "results": [
            {"title": "Chipotle Nutrition", "url": "http://x", "content": "chicken bowl ~700 cal"},
        ],
    }
    client = _FakeClient(resp=_FakeResp(payload=payload))
    sr = await S.search("chipotle chicken bowl macros", _client=client)
    assert sr.error is None
    assert "700" in sr.answer
    assert sr.results and sr.results[0]["title"] == "Chipotle Nutrition"
    assert sr.query == "chipotle chicken bowl macros"


# ── C2: TTL cache — a second identical query is a cache hit ──────────────────────

async def test_second_identical_query_is_cache_hit(monkeypatch):
    monkeypatch.setattr(S, "_key", lambda: "k")
    payload = {"answer": "ans", "results": [{"title": "t", "url": "u", "content": "c"}]}
    client = _FakeClient(resp=_FakeResp(payload=payload))

    first = await S.search("Gym near me", _client=client)
    assert first.cache_hit is False
    assert len(client.calls) == 1

    # Same query, different casing/whitespace → normalized → cache hit, no 2nd call.
    second = await S.search("  gym   near me  ", _client=client)
    assert second.cache_hit is True
    assert second.answer == first.answer
    assert len(client.calls) == 1, "cache hit must not re-call the provider"


async def test_reset_cache_forces_a_fresh_call(monkeypatch):
    monkeypatch.setattr(S, "_key", lambda: "k")
    client = _FakeClient(resp=_FakeResp(payload={"answer": "a", "results": []}))
    await S.search("same q", _client=client)
    S.reset_cache()
    await S.search("same q", _client=client)
    assert len(client.calls) == 2, "after reset_cache the provider is called again"


# ── C4: _dispatch(web_search) returns the instruction-wrapped re-voice string ────

async def test_dispatch_web_search_returns_revoice_string(monkeypatch, make_user, db):
    user = await make_user(telegram_id="900")
    from handlers import tool_executor as TE

    async def _fake_search(query, context="", **kw):
        return S.SearchResult(
            answer="A Chipotle chicken bowl is ~700 cal, 40g protein.",
            results=[{"title": "Chipotle", "url": "http://x", "content": "700 cal"}],
            query=query, cache_hit=False, provider="tavily", error=None,
        )

    monkeypatch.setattr("core.search.search", _fake_search)

    out = await TE._dispatch(
        "web_search",
        {"query": "chipotle chicken bowl macros"},
        user, today_log=None, db=db, source_type="text",
    )
    assert isinstance(out, str)
    assert "700 cal" in out                       # raw fact carried (G4 seam)
    assert "re-voice" in out.lower()              # explicit re-voice instruction
    assert "chipotle chicken bowl macros" in out  # the query is in the string


async def test_dispatch_web_search_folds_in_injuries(monkeypatch, make_user, db):
    user = await make_user(telegram_id="901", injuries="ACL reconstruction")
    from handlers import tool_executor as TE

    async def _fake_search(query, context="", **kw):
        return S.SearchResult(answer="some leg exercises", results=[],
                              query=query, error=None)

    monkeypatch.setattr("core.search.search", _fake_search)
    out = await TE._dispatch("web_search", {"query": "leg exercises"},
                             user, today_log=None, db=db, source_type="text")
    assert "ACL reconstruction" in out
    assert "caution" in out.lower()


async def test_dispatch_web_search_empty_result_tells_model_to_be_honest(
        monkeypatch, make_user, db):
    user = await make_user(telegram_id="902")
    from handlers import tool_executor as TE

    async def _fake_search(query, context="", **kw):
        return S.SearchResult(query=query, results=[], error="http 503")

    monkeypatch.setattr("core.search.search", _fake_search)
    out = await TE._dispatch("web_search", {"query": "x"},
                             user, today_log=None, db=db, source_type="text")
    assert "fabricate" in out.lower()  # don't invent a number/source on a miss


# ── C5 REGRESSION (load-bearing): a web_search call FORCES a follow-up even when
#    the first pass already wrote text — proving the search facts are re-voiced. ──

async def test_web_search_forces_followup_over_first_pass_text(
        monkeypatch, make_user, db, search_on):
    """The model writes first-pass text AND calls web_search. Without C5, that text
    (response_text truthy, not onboarding) would short-circuit the follow-up and the
    re-voiced search facts would never reach the user. With _VOICED_RESULT_TOOLS the
    follow-up is forced and its voiced text REPLACES the pre-search placeholder."""
    import core.conversation as C

    user = await make_user(telegram_id="950", current_weight_kg=86.0,
                           primary_goal="cut")

    calls = {"chat": 0, "follow_up": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None):
        calls["chat"] += 1
        # First-pass text present alongside the web_search tool call.
        return {
            "text": "let me check that for you.",
            "tool_calls": [{"name": "web_search", "id": "t1",
                            "input": {"query": "chipotle chicken bowl macros"}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
        calls["follow_up"] += 1
        return "a chipotle chicken bowl runs ~700 cal.|||40g protein, solid for the cut."

    # The search tool result string — what the follow-up re-voices.
    async def _fake_execute(tool_calls, user, log, db, source_type):
        return {"web_search": "WEB SEARCH RESULTS ... COACH INSTRUCTION: re-voice this ..."}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "macros for a chipotle chicken bowl?"}],
        system="SYS",
        platform="imessage",
        in_onboarding=False,
        was_onboarding=False,
    )

    # The follow-up WAS invoked despite non-empty first-pass text...
    assert calls["follow_up"] == 1, "web_search must force the re-voice follow-up"
    # ...and its voiced text REPLACED the pre-search placeholder.
    joined = " ".join(result.response.bubbles).lower()
    assert "700 cal" in joined, f"search facts not re-voiced: {result.response.bubbles}"
    assert "let me check that for you" not in joined, "pre-search text leaked to user"


async def test_non_voiced_non_logging_tool_keeps_first_pass_text_no_followup(
        monkeypatch, make_user, db, search_on):
    """Control: a NON-voiced, NON-logging tool (update_profile) with first-pass text
    present must NOT force a follow-up — only voiced-result tools do. The first-pass
    text is kept. Proves C5 added a term, not a blanket force."""
    import core.conversation as C

    user = await make_user(telegram_id="951")
    calls = {"follow_up": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None):
        return {
            "text": "locked in your new target.",
            "tool_calls": [{"name": "update_profile", "id": "p1",
                            "input": {"fields": {"calorie_target": 2200}}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
        calls["follow_up"] += 1
        return "SHOULD NOT BE USED"

    async def _fake_execute(tool_calls, user, log, db, source_type):
        return {"update_profile": "Profile updated: ['calorie_target']"}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "set my target to 2200"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
    )
    # No follow-up forced (not a voiced-result tool); first-pass text is kept.
    assert calls["follow_up"] == 0, "non-voiced tool must not force a follow-up"
    joined = " ".join(result.response.bubbles).lower()
    assert "locked in your new target" in joined
    assert "should not be used" not in joined


# ── INTERIM HEADS-UP — mid-turn "looking that up" bubble (masks search latency) ──
#
# A keyword-only on_interim callback fires inside run_turn's tool block BEFORE the
# slow execute_tool_calls + re-voice run, ONLY for web_search turns. HYBRID wording:
# the model's first-pass text when present, else the deterministic search_heads_up()
# fallback. NOT a double-send: the final answer is the re-voiced follow-up (C5).

def test_search_heads_up_is_short_nonempty_and_deterministic():
    """The deterministic fallback returns a short non-empty in-voice line, and the
    same input always maps to the same line (stable index, no randomness)."""
    from handlers.tool_executor import search_heads_up

    line = search_heads_up("chipotle chicken bowl macros")
    assert isinstance(line, str) and line.strip()
    assert len(line) <= 80, "heads-up must be ONE short line, not a paragraph"
    assert "|||" not in line, "a single bubble — no multi-bubble split"
    # Deterministic for a given input.
    assert search_heads_up("chipotle chicken bowl macros") == line
    # No-arg / None is also valid and stable.
    assert search_heads_up() == search_heads_up(None)
    assert search_heads_up().strip()


async def _run_interim_turn(monkeypatch, make_user, db, *, first_pass_text,
                            tool_name="web_search", tool_input=None,
                            on_interim=None):
    """Drive run_turn with a single tool call and a captured re-voice follow-up.
    Returns (result, follow_up_calls). Shared by the interim tests below."""
    import core.conversation as C

    user = await make_user(telegram_id="960")
    calls = {"follow_up": 0}

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None):
        return {
            "text": first_pass_text,
            "tool_calls": [{"name": tool_name, "id": "t1",
                            "input": tool_input or {}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
        calls["follow_up"] += 1
        # The FINAL voiced answer — deliberately distinct from any interim text.
        return "a chipotle chicken bowl runs ~700 cal.|||40g protein, solid for the cut."

    async def _fake_execute(tool_calls, user, log, db, source_type):
        return {tool_name: "WEB SEARCH RESULTS ... COACH INSTRUCTION: re-voice this ..."}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    result = await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "macros for a chipotle chicken bowl?"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
        on_interim=on_interim,
    )
    return result, calls


async def test_interim_fires_with_first_pass_text_before_final_and_no_double_send(
        monkeypatch, make_user, db, search_on):
    """web_search turn WITH first-pass text → on_interim called ONCE with that text,
    and the FINAL voiced answer differs from the interim (no double-send)."""
    seen: list[str] = []

    async def _capture(text):
        seen.append(text)

    result, calls = await _run_interim_turn(
        monkeypatch, make_user, db,
        first_pass_text="good q, let me check that real quick.",
        tool_input={"query": "chipotle chicken bowl macros"},
        on_interim=_capture,
    )

    # Interim fired exactly once, with the model's own first-pass line.
    assert seen == ["good q, let me check that real quick."]
    # The re-voice follow-up still ran (its text is the FINAL answer).
    assert calls["follow_up"] == 1
    final = " ".join(result.response.bubbles).lower()
    assert "700 cal" in final, "final answer must be the re-voiced search result"
    # NO double-send: the interim text is NOT also in the final answer.
    assert "let me check that real quick" not in final, "interim text leaked into final"


async def test_interim_fires_before_execute_tool_calls(
        monkeypatch, make_user, db, search_on):
    """Latency masking is the whole point: the heads-up MUST be sent before the
    slow search runs. Pin the ordering with a shared sentinel list so a refactor
    can't silently move the interim after execute_tool_calls and stay green."""
    import core.conversation as C

    user = await make_user(telegram_id="961")
    order: list[str] = []

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None):
        return {
            "text": "let me check that.",
            "tool_calls": [{"name": "web_search", "id": "t1", "input": {"query": "x"}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
        return "the answer.|||done."

    async def _fake_execute(tool_calls, user, log, db, source_type):
        order.append("execute")
        return {"web_search": "RESULTS ... re-voice this ..."}

    async def _on_interim(text):
        order.append("interim")

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "q?"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
        on_interim=_on_interim,
    )

    assert order == ["interim", "execute"], (
        "the heads-up must be sent BEFORE execute_tool_calls (latency masking)"
    )


async def test_interim_uses_fallback_when_no_first_pass_text(
        monkeypatch, make_user, db, search_on):
    """web_search turn with NO first-pass text → on_interim gets the deterministic
    search_heads_up() fallback line (keyed off the query)."""
    from handlers.tool_executor import search_heads_up
    seen: list[str] = []

    async def _capture(text):
        seen.append(text)

    result, calls = await _run_interim_turn(
        monkeypatch, make_user, db,
        first_pass_text="",   # model wrote no pre-search line
        tool_input={"query": "creatine timing latest research"},
        on_interim=_capture,
    )

    assert seen == [search_heads_up("creatine timing latest research")]
    assert calls["follow_up"] == 1
    final = " ".join(result.response.bubbles).lower()
    assert "700 cal" in final  # final is still the re-voiced result


async def test_interim_never_fires_on_non_search_turn(
        monkeypatch, make_user, db, search_on):
    """A NON-search turn (log_food only) must NEVER trigger on_interim — it's gated
    strictly by _VOICED_RESULT_TOOLS."""
    import core.conversation as C

    user = await make_user(telegram_id="961")
    seen: list[str] = []

    async def _capture(text):
        seen.append(text)

    async def _fake_chat(messages, system, tools=True, max_tokens=4096, model=None):
        return {
            "text": "logged that for you.",
            "tool_calls": [{"name": "log_food", "id": "f1",
                            "input": {"food_name": "banana"}}],
            "raw_content": [{"x": 1}],
            "stop_reason": "tool_use",
        }

    async def _fake_follow_up(messages, raw, tcs, results, system, max_tokens=512):
        return "banana, ~100 cal.|||you're at 1,100 for the day."

    async def _fake_execute(tool_calls, user, log, db, source_type):
        return {"log_food": "Logged banana: 100 cal, 1g protein. DAY TOTAL: 1100 cal."}

    monkeypatch.setattr(C, "chat", _fake_chat)
    monkeypatch.setattr(C, "chat_follow_up", _fake_follow_up)
    monkeypatch.setattr(C, "execute_tool_calls", _fake_execute)

    await C.run_turn(
        user, db,
        messages=[{"role": "user", "content": "had a banana"}],
        system="SYS", platform="imessage",
        in_onboarding=False, was_onboarding=False,
        on_interim=_capture,
    )
    assert seen == [], "on_interim must NOT fire on a non-search (log_food) turn"


async def test_interim_none_on_search_turn_does_not_crash(
        monkeypatch, make_user, db, search_on):
    """run_turn with on_interim=None (default) on a web_search turn must not crash —
    the heads-up is simply skipped and the turn completes normally."""
    result, calls = await _run_interim_turn(
        monkeypatch, make_user, db,
        first_pass_text="let me check.",
        tool_input={"query": "anything"},
        on_interim=None,
    )
    assert calls["follow_up"] == 1
    final = " ".join(result.response.bubbles).lower()
    assert "700 cal" in final
