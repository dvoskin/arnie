"""⛔⛔⛔ THE PRODUCER THAT RAISES A CLARIFICATION MUST BE THE SOURCE OF ITS
DURABLE ASK TYPE.

**Reproducibility cannot validate authority selection** (Danny, 2026-08-27).
A measurement can be perfectly pinned, stable, controlled and mutation-tested
while still reading the wrong canonical object. None of the five existing
guards could catch this, because every one of them verifies that a measurement
is REPRODUCIBLE — not that it reads the object that OWNS the outcome.

The incident: `core/food_turn.py` has TWO ask authorities.

    interpreter         data["ambiguities"]                    2 field values
    staged pipeline     ClarificationDecision.questions        9 AmbiguityTypes

The staged site returned an ask built from `_decision.asks` and typed it from
`data`. Every pipeline-raised ask therefore landed `unclassified` while
carrying full structure of its own. Confirmed by durable-row provenance:
**3/3** omitting asks carried `question_id` + `staged_item_id`; **0/10**
interpreter-typed asks did.

~150 turns went into characterising, discriminating and base-rating a "defect"
that was an instrument looking in the wrong store.
"""
from __future__ import annotations

import ast
import pathlib

from skills.nutrition import ask_type as AT

SRC = pathlib.Path("core/food_turn.py")


def _staged_ask_return():
    """The ask-return site that carries staged provenance — the one whose
    authority is `_decision`, identified structurally rather than by line."""
    tree = ast.parse(SRC.read_text())
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
            continue
        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        if "action" in keys and "question_id" in keys and "staged_item_id" in keys:
            return node, keys
    return None, []


def test_the_staged_site_types_from_the_DECISION_not_the_interpreter():
    """⭐ THE INVARIANT. `question_id`/`staged_item_id` mark the staged
    authority; that site must not type from `data`."""
    node, keys = _staged_ask_return()
    assert node is not None, "no staged ask-return site found — scanner broken"
    assert "ask_types" in keys
    src = ast.get_source_segment(SRC.read_text(), node) or ""
    assert "_ask_types_staged" in src, (
        "the staged ask site types from the interpreter's store. It returns an "
        "ask raised from `_decision.asks`, so `data` is not its authority — "
        "this is the bug that cost ~150 turns.")
    assert "\"ask_types\": _ask_types_from(data)" not in src


def test_the_staged_vocabulary_reaches_subjects_the_interpreter_cannot():
    """⭐ WHY AUTHORITY MATTERS, not just tidiness. The staged store natively
    distinguishes subjects the interpreter never emitted — both were recorded
    as having ZERO producers while only one store was read."""
    assert AT.classify_staged("consumed_quantity") == AT.CONSUMPTION_COMPLETE
    assert AT.classify_staged("component_breakdown") == AT.UNSTATED_EXTRAS
    assert AT.classify_staged("package_size") == AT.MENU_SIZE
    # the interpreter's store cannot produce these from its two field values
    assert AT.classify("quantity") != AT.CONSUMPTION_COMPLETE
    assert AT.classify("prep") != AT.UNSTATED_EXTRAS


def test_an_unmapped_staged_field_stays_unclassified():
    """`serving_basis` has no canonical subject and must NOT be folded into a
    portion type — that is the CF28 question, and mis-bucketing corrupts the
    denominator a policy would be sized against."""
    assert AT.classify_staged("serving_basis") == AT.UNCLASSIFIED
    assert AT.classify_staged("nonsense") == AT.UNCLASSIFIED


def test_classify_all_staged_reads_requested_fields():
    class Q:
        def __init__(self, f): self.requested_fields = f
    got = AT.classify_all_staged([Q(("consumed_quantity",)), Q(("package_size",))])
    assert got == (AT.MENU_SIZE, AT.CONSUMPTION_COMPLETE), got
    assert AT.classify_all_staged([]) == ()
    assert AT.classify_all_staged(None) == ()


def test_where_the_two_STORES_share_a_field_name_they_AGREE():
    """Two authorities, two mappings, one canonical vocabulary.

    ⚠ AN EARLIER VERSION OF THIS TEST ASSERTED THE MAPS MUST BE DISJOINT. That
    was wrong: `preparation` legitimately appears in both stores meaning the
    same thing, and attribution comes from WHICH FUNCTION is called
    (`classify` vs `classify_staged`), not from key disjointness. What must
    hold is that a shared name cannot mean two different subjects — otherwise
    the same word would resolve differently by producer and the vocabulary
    would no longer be one vocabulary.
    """
    shared = set(AT._STAGED_MAP) & set(AT._FIELD_MAP)
    assert shared, "expected at least `preparation` in common; check the maps"
    for k in shared:
        assert AT._STAGED_MAP[k] == AT._FIELD_MAP[k], (
            f"field {k!r} means {AT._FIELD_MAP[k]} to the interpreter but "
            f"{AT._STAGED_MAP[k]} to the staged pipeline — one word, two "
            "subjects, which is the four-tables condition again")


# ── the test that would have caught the INERT read ───────────────────────────
class _Q:
    def __init__(self, fields): self.requested_fields = fields
class _Clar:
    def __init__(self, qs): self.questions = tuple(qs)
class _Plan:
    """Shaped like `core.food_pipeline.FoodTurnDecision`: the questions live on
    `.clarification`, and `.asks` is the PLAN's property."""
    def __init__(self, qs): self.clarification = _Clar(qs)
    @property
    def asks(self): return bool(self.clarification.questions)


def test_the_staged_typing_ACTUALLY_returns_staged_types_not_the_fallback():
    """⛔⛔ THE INERT-READ TEST. The first version of `_ask_types_staged` read
    `decision.questions` — but `_decision` is the PLAN, which holds the
    ClarificationDecision at `.clarification`. It always got nothing and fell
    through to the interpreter store, so the "authority fix" was INERT while
    looking correct, and a 50-turn census reported staged types that had
    actually come from the fallback.

    The structural test above did NOT catch it: it only asserted the site
    CALLS `_ask_types_staged`. Same shape as the CF23 guard that was true of
    rows nobody could create — correct, and inert.
    """
    from core.food_turn import _ask_types_staged
    plan = _Plan([_Q(("consumed_quantity",))])
    assert plan.asks
    # interpreter data deliberately says something DIFFERENT, so a fallback is
    # visible rather than coincidentally equal
    data = {"ambiguities": [{"item": "x", "field": "prep"}], "items": []}
    got = _ask_types_staged(plan, data)
    assert got == (AT.CONSUMPTION_COMPLETE,), (
        f"staged typing returned {got} — it fell back to the interpreter store "
        "instead of reading the producer that raised the ask")
    assert AT.PREPARATION_FAT not in got


def test_the_fallback_is_still_reachable_when_the_decision_is_empty():
    """The fallback is legitimate when there is genuinely nothing staged — but
    it must not be how staged asks get typed."""
    from core.food_turn import _ask_types_staged
    data = {"ambiguities": [{"item": "x", "field": "prep"}], "items": []}
    assert _ask_types_staged(_Plan([]), data) == (AT.PREPARATION_FAT,)
    assert _ask_types_staged(None, data) == (AT.PREPARATION_FAT,)
    assert _ask_types_staged(None, {}) == (AT.UNCLASSIFIED,)
