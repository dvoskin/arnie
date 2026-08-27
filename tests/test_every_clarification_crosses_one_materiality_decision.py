"""⛔⛔⛔ EVERY CLARIFICATION PROPOSAL MUST CROSS EXACTLY ONE MATERIALITY
DECISION BEFORE IT CAN BECOME AN ASK.

Measured 2026-08-26 over the frozen 25-meal corpus: **2 of 25** clarifications
reached `_proposed_ask_is_material`. The other twenty-three arrived through the
`note_food_clarification` TOOL, whose handler recorded whatever the model
proposed and replied *"just ask the question naturally"* — no span, no mode, no
day-share, no decision at all.

⭐⭐⭐ TWO CLARIFICATION PATHS WITH DIFFERENT RIGOUR IS THE SAME DEFECT
`skills/nutrition/materiality` WAS WRITTEN TO END — four tables deciding one
question and disagreeing. Fixing the RULE while most asks route around it would
have tuned a policy that 92% of clarifications never consult.

So the gate here is REACHABILITY, not policy: both paths call the SAME
function, and deleting either call must go RED.
"""
from __future__ import annotations

import ast
import inspect
import pathlib


def _calls_in(func) -> set:
    """Every function NAME called in `func`'s source."""
    tree = ast.parse(inspect.cleandoc(inspect.getsource(func)))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def test_the_structured_lane_crosses_the_decision():
    """The path that always did. Pinned so it cannot quietly stop."""
    from core.turns.stages import execute_native  # noqa: F401
    import core.food_turn as FT

    src = inspect.getsource(FT)
    assert "_proposed_ask_is_material" in src, (
        "the structured lane no longer consults the shared materiality "
        "decision")


def test_the_tool_path_crosses_the_SAME_decision():
    """⛔ THE PATH THAT DID NOT. `note_food_clarification` handled 23 of 25
    clarifications in the corpus and weighed none of them."""
    src = pathlib.Path("handlers/tool_executor.py").read_text()
    start = src.index('elif name == "note_food_clarification":')
    end = src.index('elif name == "schedule_check_in":', start)
    handler = src[start:end]

    assert "_proposed_ask_is_material" in handler, (
        "the note_food_clarification handler records an ask without crossing "
        "the shared materiality decision — this is the ungated path that "
        "carried 23 of 25 clarifications")
    assert "record_pending_question" in handler, (
        "precondition: this handler is still the one that records the ask")
    # ⭐ THE ORDER MATTERS. A decision consulted AFTER the write is not a gate.
    assert handler.index("_proposed_ask_is_material") < handler.index(
        "record_pending_question"), (
        "the materiality decision runs AFTER the question is recorded — a "
        "gate that fires after the write is not a gate")


def test_there_is_exactly_ONE_materiality_POLICY():
    """⛔⛔ NOT A SECOND POLICY. Two rules that agree today are two rules that
    disagree later — the four-table condition `materiality.py` was written to
    end.

    ⚠ AND IT ASSERTS ON THE POLICY, NOT THE NAME. A first version matched any
    `is_material` and failed on three innocent METHODS: a reply-priority
    property (`"important"/"urgent"`), a normalized-score property, and a
    "carries any macro" check. Same word, unrelated meanings. Matching a name
    and calling it a policy is how a grep gate becomes a grep trap — so this
    counts only MODULE-LEVEL functions, which is what a shared policy is.
    """
    definers = []
    for root in ("core", "handlers", "skills"):
        for path in sorted(pathlib.Path(root).rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in tree.body:          # module level ONLY, never methods
                if (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and node.name == "is_material"):
                    definers.append(str(path))
    assert definers == ["skills/nutrition/materiality.py"], (
        f"a second materiality POLICY exists: {definers}")


def test_the_demotion_tells_the_model_to_log():
    """⭐ THE NEGATIVE INVARIANT. Refusing the question must not leave the turn
    doing nothing — that trades over-clarification for silence, which case 24
    already shows is its own defect. The handler's demotion reply must send it
    to log."""
    src = pathlib.Path("handlers/tool_executor.py").read_text()
    start = src.index('elif name == "note_food_clarification":')
    end = src.index('elif name == "schedule_check_in":', start)
    handler = src[start:end]
    demotion = handler[handler.index("_proposed_ask_is_material"):]
    assert "Log '" in demotion or "Log " in demotion, (
        "the demotion path does not instruct a log — an immaterial question "
        "must become a logged meal, never a dropped turn")
    assert "Do NOT ask" in demotion
