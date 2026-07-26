"""Replay REAL interpreter plans, not invented ones.

The generated harness fixes coverage breadth; it cannot fix fidelity. Every
payload in both harnesses is still a guess at what the model emits, and a shape
nobody predicted is exercised by neither.

`_capture_interpreter_output` logs the interpreter's raw plan once per turn, so
the corpus grows with USE. This replays whatever has been collected into
`tests/fixtures/interpreter_plans.jsonl` through the same invariants the
generated cases use — one JSON object per line, `{"msg": ..., "plan": {...}}`.

It skips cleanly when the corpus is absent, because a green suite on a machine
with no captures must not read as "the real shapes pass". Harvest with:

    grep -o 'event=interpreter_output .*' app.log \\
      | sed -E "s/event=interpreter_output msg=(.*) plan=(.*)/{\\"msg\\":\\1,\\"plan\\":\\2}/" \\
      > tests/fixtures/interpreter_plans.jsonl
"""
import json
import pathlib
import re
from types import SimpleNamespace

import pytest

import core.food_turn as FT

CORPUS = pathlib.Path(__file__).parent / "fixtures" / "interpreter_plans.jsonl"


def _load():
    if not CORPUS.exists():
        return []
    out = []
    for line in CORPUS.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue                       # a truncated capture is not a failure
        if isinstance(row, dict) and isinstance(row.get("plan"), dict):
            out.append((str(row.get("msg") or ""), row["plan"]))
    return out


CAPTURED = _load()
_SKIP = pytest.mark.skipif(not CAPTURED,
                           reason="no captured plans — see the module docstring")


def _interp(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


async def _run(monkeypatch, message, plan, mode):
    monkeypatch.setattr(FT, "chat", _interp(plan))
    out = await FT.run(message, SimpleNamespace(
        preferences=SimpleNamespace(food_logging_mode=mode)))
    return out, ((out or {}).get("text", "")
                 if (out or {}).get("action") == "ask" else "")


_IDS = [f"{i}:{m[:28]}" for i, (m, _) in enumerate(CAPTURED)]


@_SKIP
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("message,plan", CAPTURED, ids=_IDS or None)
async def test_a_real_plan_asks_at_most_one_question(monkeypatch, mode,
                                                     message, plan):
    _, text = await _run(monkeypatch, message, plan, mode)
    assert text.count("?") <= 1, text


@_SKIP
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("message,plan", CAPTURED, ids=_IDS or None)
async def test_a_real_plan_never_treats_a_hedge_as_a_noun(monkeypatch, mode,
                                                          message, plan):
    _, text = await _run(monkeypatch, message, plan, mode)
    assert not re.search(r"\bthe some\b|\bone some\b|\ba some\b", text, re.I), \
        text


@_SKIP
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("message,plan", CAPTURED, ids=_IDS or None)
async def test_a_real_plan_never_dead_ends(monkeypatch, mode, message, plan):
    """An ask with no text or a commit with no calls is silence to the user."""
    out, text = await _run(monkeypatch, message, plan, mode)
    if out is None:
        return
    if out["action"] == "ask":
        assert text.strip(), out
    else:
        assert out.get("tool_calls"), out


@_SKIP
@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["moderate", "strict"])
@pytest.mark.parametrize("message,plan", CAPTURED, ids=_IDS or None)
async def test_a_real_plan_never_asks_to_approve_the_whole_parse(monkeypatch,
                                                                 mode, message,
                                                                 plan):
    _, text = await _run(monkeypatch, message, plan, mode)
    assert "Does that all look right?" not in text, text


# ── the capture itself ────────────────────────────────────────────────────────
def test_the_interpreter_output_is_captured():
    """Without this line there is no corpus, and the replay above is theatre."""
    import inspect
    src = inspect.getsource(FT)
    assert "event=interpreter_output" in src
    assert "_capture_interpreter_output(message, data)" in src


def test_a_capture_never_raises():
    """It runs on every food turn. A logging failure must not cost a log."""
    FT._capture_interpreter_output("x", None)
    FT._capture_interpreter_output("x", {})
    FT._capture_interpreter_output(None, {"action": "log"})

    class _Unserialisable:
        def __repr__(self):
            raise RuntimeError("boom")
    FT._capture_interpreter_output("x", {"k": _Unserialisable()})


def test_a_capture_is_bounded():
    """A log line is not a data store."""
    assert FT._CAPTURE_MAX_CHARS <= 4000
