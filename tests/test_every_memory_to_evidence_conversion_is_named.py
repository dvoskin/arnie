"""⛔⛔⛔ CF24 — EVERY `UserFoodMatch` -> PRICING OBJECT CONVERSION, ENUMERATED.

2026-08-25: entry 3050 committed 525 kcal, the exact 1.2x image of memory row
936's per-100g. Row 936 is refused by the trust predicate. Both known readers
apply the guard. The same row and the same item do NOT reproduce locally. The
tier-0 history override is ruled out by production data.

⭐⭐⭐ SO THE QUESTION IS NOT "WHO QUERIES `user_food_matches`" — it is WHERE
CAN A STORED ROW BECOME A PRICING OBJECT, including from state that was
already hydrated before any guard ran. A grep for `get_user_food_match` finds
readers; it does not find conversions.

This gate enumerates the conversions by AST: every function that reads the
per-100g attributes off something. The list is FROZEN. A new conversion site
fails this test until it is added deliberately — which is the moment to ask
whether it goes through `memory_nutrition_evidence`.

⛔ THE LIST IS NOT AN APPROVAL. Sites here are recorded, not blessed; the
consumer of row 936 may well be sitting in it. What the gate buys is that the
set cannot grow silently while the hole is open.
"""
from __future__ import annotations

import ast
import pathlib

#: Attribute names that only exist on a stored memory row.
_PER100_ATTRS = frozenset({"cal_100", "protein_100", "carbs_100", "fat_100",
                           "fiber_100", "sugar_100", "sodium_100"})

#: Directories that ship. Scripts and tests are excluded deliberately: they
#: cannot price a user's meal.
_SHIPPED = ("core", "handlers", "skills", "db", "api")

#: (module, function) -> why it may touch stored per-100g values.
#: FROZEN 2026-08-25. Add a line only with a reason.
KNOWN_CONVERSIONS = {
    ("db/queries.py", "memory_nutrition_evidence"):
        "THE ONE DOOR. Asks the predicate and emits the typed event.",
    ("db/queries.py", "address_has_one_authority"):
        "reads per-100g to compare BINDINGS; returns a bool, never values",
    ("core/canonical_pricing_inputs.py", "_memory"):
        "canonical memory rung — goes through the door",
    ("handlers/tool_executor.py", "fetch_candidates"):
        "legacy memory rung — goes through the door",
    ("core/food_intelligence.py", "analyze"):
        "⚠⚠⚠ PRIME SUSPECT FOR THE 3050 CONSUMER. It reads `cal_100` off a "
        "candidate dict it did NOT fetch — `src.get(\"per100g\") or "
        "{\"calories\": src.get(\"cal_100\"), ...}` — so a candidate carrying "
        "raw memory column names is converted to a priced profile with no "
        "guard of its own. This is the prehydrated-state shape: the trust "
        "check runs at the reader, and a copy made elsewhere never meets it. "
        "NOT patched on suspicion; the production replay decides.",
}


def _conversions() -> dict:
    found = {}
    root = pathlib.Path(__file__).resolve().parent.parent
    for folder in _SHIPPED:
        for path in sorted((root / folder).rglob("*.py")):
            rel = str(path.relative_to(root))
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for sub in ast.walk(node):
                    name = None
                    if isinstance(sub, ast.Attribute):
                        name = sub.attr
                    elif isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                        name = sub.value
                    if name in _PER100_ATTRS:
                        found.setdefault((rel, node.name), set()).add(name)
    return found


def test_no_unnamed_memory_to_evidence_conversion_exists():
    """⛔ A NEW CONVERSION MUST NOT APPEAR SILENTLY WHILE THE HOLE IS OPEN."""
    found = _conversions()
    unknown = {k: sorted(v) for k, v in found.items() if k not in KNOWN_CONVERSIONS}
    assert not unknown, (
        "a function reads stored per-100g values and is not in "
        "KNOWN_CONVERSIONS. Decide whether it must go through "
        "`memory_nutrition_evidence`, then record it:\n  "
        + "\n  ".join(f"{m}::{f} -> {a}" for (m, f), a in sorted(unknown.items())))


def test_the_named_list_has_not_gone_stale():
    """⭐ THE NEGATIVE INVARIANT. A frozen list that names functions which no
    longer exist stops being a gate and becomes decoration — and would hide
    the very growth it was written to catch."""
    found = _conversions()
    gone = sorted(k for k in KNOWN_CONVERSIONS if k not in found)
    assert not gone, (
        "KNOWN_CONVERSIONS names sites that no longer read per-100g values; "
        f"remove them so the gate keeps meaning something: {gone}")


def test_the_door_is_the_only_thing_that_asks_the_predicate():
    """⛔⛔ ONE PREDICATE CALLER, SO 'WHO USED THIS ROW' IS ONE LOG LINE.

    Before CF24's instrumentation both rungs called
    `memory_nutrition_is_trusted` directly and neither said so. With two
    callers and no event, the answer to "which consumer priced row 936" was a
    week of reading code — which is exactly what this session spent."""
    root = pathlib.Path(__file__).resolve().parent.parent
    callers = []
    for folder in _SHIPPED:
        for path in sorted((root / folder).rglob("*.py")):
            src = path.read_text(encoding="utf-8")
            rel = str(path.relative_to(root))
            if "memory_nutrition_is_trusted" not in src:
                continue
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call)
                        and isinstance(node.func, ast.Name)
                        and node.func.id == "memory_nutrition_is_trusted"):
                    callers.append(rel)
    assert callers == ["db/queries.py"], (
        "the trust predicate is called outside the shared door, so a "
        f"conversion can pass the guard without emitting the event: {callers}")
