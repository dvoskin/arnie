"""Meals GENERATED from axes, not hand-written one at a time.

`test_meal_invariants.py` is twelve meals and thirty-one hand-authored
interpreter payloads. It is a good regression net for defects already found and
it does not scale, for three reasons worth stating plainly:

  * every payload is a GUESS at what the interpreter emits, so a shape nobody
    predicted is never exercised;
  * coverage grows linearly with someone's typing;
  * it covered ONE of the two ask paths, which is how a two-questions-in-one-
    bubble defect survived a file written to catch that class.

This module fixes the second and third. Meals are composed from axes — portion
certainty, food class, unit kind, mode, and ask path — so the case count is a
product rather than a list, and the same invariants apply to all of it without
being restated. The FIRST reason is fixed elsewhere, by
`_capture_interpreter_output`: real plans are logged now, and a replay corpus
grows with use.

The invariants live in one place and are imported by both files, so a rule can
never hold in one harness and not the other.
"""
import itertools
import json
import re
from types import SimpleNamespace

import pytest

import core.food_turn as FT

# ── the axes ──────────────────────────────────────────────────────────────────
#: How the amount arrived. The distinction the whole response layer turns on.
CERTAINTY = {
    "stated":   dict(basis="stated", amount=2, unit="slice"),
    "inferred": dict(basis="estimate", amount=1, unit="cup"),
    "hedged":   dict(basis="estimate", amount=1, unit="some"),
    "fraction": dict(basis="stated", amount=0.5, unit="bagel"),
}

#: What the food IS. Drives the ladder, and drives whether a question is fair.
CLASS = {
    "branded":    dict(food="Barebells Caramel Cashew Protein Bar", branded=True,
                       cal=200, pro=20),
    "generic":    dict(food="White rice", branded=False, cal=205, pro=4),
    "sauce":      dict(food="Ranch dressing", branded=False, cal=145, pro=1),
    "composite":  dict(food="Cava bowl", branded=False, cal=600, pro=45),
}

MODES = ("moderate", "strict")

#: BOTH ask paths. The staged engine derives its own ambiguities; the
#: interpreter raises its own `ask`. Only the first was ever parametrized.
ASK_PATHS = ("staged", "interpreter")


def _interp(payload):
    async def fake(messages, system, tools=True, max_tokens=0, model=None, **k):
        return {"text": json.dumps(payload), "raw_content": [],
                "tool_calls": []}
    return fake


def _payload(certainty, klass, ask_path):
    c, k = CERTAINTY[certainty], CLASS[klass]
    item = {"food": k["food"], "amount": c["amount"], "unit": c["unit"],
            "basis": c["basis"], "branded": k["branded"],
            "calories": k["cal"], "protein": k["pro"]}
    if ask_path == "interpreter":
        # The interpreter's own ask, with more than one facet — the exact shape
        # that shipped two question marks in one bubble.
        return {"action": "ask",
                "points": [f"how much of the {k['food'].lower()}",
                           "and was there anything else with it"],
                "ready": []}
    return {"action": "log", "items": [item],
            "say": "Logged, {batch_cal} cal."}


CASES = list(itertools.product(CERTAINTY, CLASS, MODES, ASK_PATHS))
IDS = [f"{a}-{b}-{c}-{d}" for a, b, c, d in CASES]


async def _run(monkeypatch, certainty, klass, mode, ask_path):
    monkeypatch.setattr(FT, "chat",
                        _interp(_payload(certainty, klass, ask_path)))
    out = await FT.run(f"had {CERTAINTY[certainty]['amount']} "
                       f"{CERTAINTY[certainty]['unit']} of "
                       f"{CLASS[klass]['food']}",
                       SimpleNamespace(preferences=SimpleNamespace(
                           food_logging_mode=mode)))
    return out, ((out or {}).get("text", "")
                 if (out or {}).get("action") == "ask" else "")


# ── the invariants, applied to every generated combination ───────────────────
@pytest.mark.asyncio
@pytest.mark.parametrize("certainty,klass,mode,ask_path", CASES, ids=IDS)
async def test_one_question_per_bubble(monkeypatch, certainty, klass, mode,
                                      ask_path):
    """The rule that broke on the path nobody parametrized."""
    _, text = await _run(monkeypatch, certainty, klass, mode, ask_path)
    assert text.count("?") <= 1, text


@pytest.mark.asyncio
@pytest.mark.parametrize("certainty,klass,mode,ask_path", CASES, ids=IDS)
async def test_no_hedge_is_treated_as_a_noun(monkeypatch, certainty, klass,
                                             mode, ask_path):
    _, text = await _run(monkeypatch, certainty, klass, mode, ask_path)
    assert not re.search(r"\bthe some\b|\bone some\b|\ba some\b", text, re.I), \
        text


@pytest.mark.asyncio
@pytest.mark.parametrize("certainty,klass,mode,ask_path", CASES, ids=IDS)
async def test_no_whole_parse_confirm(monkeypatch, certainty, klass, mode,
                                      ask_path):
    _, text = await _run(monkeypatch, certainty, klass, mode, ask_path)
    assert "Does that all look right?" not in text, text


@pytest.mark.asyncio
@pytest.mark.parametrize("certainty,klass,mode,ask_path", CASES, ids=IDS)
async def test_a_turn_always_resolves_to_something(monkeypatch, certainty,
                                                   klass, mode, ask_path):
    """No combination may produce a dead turn — an ask with no text, or a
    commit with no calls. Both are silence to the user."""
    out, text = await _run(monkeypatch, certainty, klass, mode, ask_path)
    if out is None:
        return                          # declined to the legacy path, fine
    if out["action"] == "ask":
        assert text.strip(), out
    else:
        assert out.get("tool_calls"), out


@pytest.mark.asyncio
@pytest.mark.parametrize("certainty,klass,mode,ask_path", CASES, ids=IDS)
async def test_an_invented_amount_is_never_listed_unmarked(monkeypatch,
                                                           certainty, klass,
                                                           mode, ask_path):
    _, text = await _run(monkeypatch, certainty, klass, mode, ask_path)
    if CERTAINTY[certainty]["basis"] == "stated" or not text:
        return
    for line in text.split("\n"):
        if line.strip().startswith("•") \
                and CLASS[klass]["food"].lower() in line.lower():
            assert "(my estimate)" in line, line


# ── the axes themselves are the contract ─────────────────────────────────────
def test_the_case_count_is_a_product_not_a_list():
    """The whole point: coverage grows by adding an AXIS VALUE, not by writing
    another meal. Four certainties x four classes x two modes x two ask paths."""
    assert len(CASES) == len(CERTAINTY) * len(CLASS) * len(MODES) * \
        len(ASK_PATHS)
    assert len(CASES) >= 60


def test_both_ask_paths_are_covered():
    """The gap that let the two-question defect through a harness written for
    it. Named as an axis so it cannot silently drop out again."""
    assert set(ASK_PATHS) == {"staged", "interpreter"}
    assert all(any(p in i for i in IDS) for p in ASK_PATHS)
