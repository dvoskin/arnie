"""⛔⛔⛔ ONE ASK-TYPE VOCABULARY, DECIDED AT THE DECISION POINT.

Before this tranche TWO vocabularies existed and disagreed:

    core/food_turn._KIND_PHRASING   portion|identity|preparation|extras|detail
    note_food_clarification.kind    portion|brand|cook_method|ingredient|other

They agreed on `portion` and diverged everywhere else — the four-tables
condition `skills/nutrition/materiality.py` was written to end, one layer up.
Worse, `portion` conflated THREE types with different defaults (menu_size,
continuous_portion, portion_multiplier), and `consumption_complete` was
inexpressible in both: **the one ask type with no defensible default was the
one the system could not name.**
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from skills.nutrition import ask_type as AT


def _ask_return_sites(path="core/food_turn.py"):
    tree = ast.parse(pathlib.Path(path).read_text())
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Return) and isinstance(node.value, ast.Dict)):
            continue
        keys = [k.value for k in node.value.keys if isinstance(k, ast.Constant)]
        for k, v in zip(node.value.keys, node.value.values):
            if (isinstance(k, ast.Constant) and k.value == "action"
                    and isinstance(v, ast.Constant) and v.value == "ask"):
                out.append((node.lineno, keys))
    return out


def test_every_ask_producing_site_types_before_returning():
    """⭐ AST, NOT GREP. An `ask_types` mentioned in a COMMENT above a return
    would satisfy a text search — that exact grep trap has bitten this repo
    before (M5, P8)."""
    sites = _ask_return_sites()
    assert sites, "no ask-shaped return sites found — the scanner is broken"
    untyped = [ln for ln, keys in sites if "ask_types" not in keys]
    assert not untyped, (
        f"ask-shaped returns at lines {untyped} do not emit a canonical ask "
        "type. An untyped ask is invisible in the production denominator that "
        "a per-type policy is sized against.")


def test_there_is_exactly_ONE_ask_type_vocabulary():
    """No second declaration of the canonical values anywhere.

    ⚠ `core/food_turn._RENDER_PHRASING` is deliberately NOT a violation: its
    keys are PRESENTATION facets derived from question text, they never reach a
    durable field, and promoting them would reintroduce prose inference — a
    text-derived key cannot tell menu_size from continuous_portion. It is
    checked separately by the persistence test below.
    """
    canon = {AT.MENU_SIZE, AT.CONTINUOUS_PORTION, AT.CONSUMPTION_COMPLETE,
             AT.PREPARATION_FAT, AT.UNSTATED_EXTRAS, AT.PORTION_MULTIPLIER,
             AT.IDENTITY_VARIANT}
    offenders = []
    for path in sorted(pathlib.Path(".").glob("[cshd]*/**/*.py")):
        if "test" in str(path) or path.as_posix() == "skills/nutrition/ask_type.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                vals = {e.value for e in node.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)}
                if len(vals & canon) >= 3:
                    offenders.append(f"{path}:{node.lineno}")
    assert not offenders, (
        f"a second ask-type vocabulary is declared at {offenders}. There must "
        "be exactly one; import it from skills.nutrition.ask_type.")


def test_the_tool_enum_is_SOURCED_from_the_one_vocabulary():
    """It reaches a durable field (`pq.payload_json`, and `pq.tier`), so a
    hand-written enum here is a second CANONICAL vocabulary, not a rendering
    one."""
    import core.tools as T
    tool = next(t for t in T.ALL_TOOLS if t.get("name") == "note_food_clarification")
    enum = set(tool["input_schema"]["properties"]["kind"]["enum"])
    assert enum == set(AT.ALL) - {AT.UNCLASSIFIED}, (
        f"the tool enum has drifted from the one vocabulary: {sorted(enum)}")
    assert AT.UNCLASSIFIED not in enum, (
        "the model must not be offered 'unclassified' as a choice — an "
        "unmappable ask becomes unclassified downstream, not by election")


# ── THE ACCEPTANCE GATE ───────────────────────────────────────────────────────
def test_REWORDING_THE_QUESTION_DOES_NOT_CHANGE_THE_TYPE():
    """⭐⭐⭐ THE BOUNDARY, STATED AS A TEST (Danny, 2026-08-27): *if the
    renderer can change wording without changing ask_type, you've got the
    boundary right.*

    The mechanism this replaced, `_render_facet`, matched prose needles against
    the text the system had just generated — so a copy edit silently changed
    the recorded type.

    ⛔⛔ THE FIRST VERSION OF THIS TEST WAS VACUOUS AND PASSED ANYWAY. It used
    "Small, medium, or large?" on a BRANDED item, so the text answer and the
    structural answer BOTH said menu_size — a text-dependent implementation was
    unobservable because the two agreed. Mutation M2 (return MENU_SIZE whenever
    the text contains "large") stayed GREEN through it.

    ⭐ THE FIXTURE MUST MAKE TEXT AND STRUCTURE DISAGREE. Here the item is
    UNBRANDED, so the structural answer is continuous_portion while the prose
    screams menu size. Any implementation that reads the text now returns the
    wrong value and this test fails.
    """
    import core.food_turn as FT
    # UNBRANDED -> structurally continuous_portion, whatever the words say.
    ambiguities = [{"item": "Rice", "field": "quantity", "impact_cal": 200}]
    items = [{"food": "Rice", "branded": False}]
    worded = [
        "Small, medium, or large?",          # prose of a MENU SIZE question
        "Which size did you grab, roughly?",
        "How much rice was that?",
        "¡Hola! ¿Qué tamaño?",
        "",
    ]
    got = [FT._ask_types_from({"ambiguities": ambiguities, "items": items,
                               "text": t}) for t in worded]
    assert all(g == (AT.CONTINUOUS_PORTION,) for g in got), (
        f"the type moved with the wording: {list(zip(worded, got))}")

    # And the converse: menu-size prose must not be required to GET menu_size.
    branded = FT._ask_types_from(
        {"ambiguities": [{"item": "Fries", "field": "quantity"}],
         "items": [{"food": "Fries", "branded": True}],
         "text": "no question mark here at all"})
    assert branded == (AT.MENU_SIZE,), branded


def test_the_type_is_NOT_recoverable_from_text_alone():
    """The same words, two different structured facts, two different types.
    A prose classifier CANNOT produce this distinction — which is why the type
    must be decided upstream of rendering."""
    import core.food_turn as FT
    same_words = {"text": "How much of that did you have?"}
    branded = FT._ask_types_from(dict(same_words,
        ambiguities=[{"item": "Fries", "field": "quantity"}],
        items=[{"food": "Fries", "branded": True}]))
    unbranded = FT._ask_types_from(dict(same_words,
        ambiguities=[{"item": "Rice", "field": "quantity"}],
        items=[{"food": "Rice", "branded": False}]))
    assert branded == (AT.MENU_SIZE,)
    assert unbranded == (AT.CONTINUOUS_PORTION,)
    assert branded != unbranded


# ── THE NEGATIVE INVARIANT ────────────────────────────────────────────────────
def test_consumption_complete_is_distinguishable_from_every_defaultable_class():
    """⛔ "Did you finish it?" is USER STATE. No amount of nutrition data yields
    it, so it must never be reachable as, or collapsed into, a type a defaulting
    policy may act on."""
    assert AT.CONSUMPTION_COMPLETE not in AT.DEFAULTABLE_CANDIDATES
    assert AT.CONSUMPTION_COMPLETE in AT.ALL
    for d in AT.DEFAULTABLE_CANDIDATES:
        assert d != AT.CONSUMPTION_COMPLETE
    # It has its own field and cannot be produced by any quantity-shaped one.
    assert AT.classify("consumed") == AT.CONSUMPTION_COMPLETE
    for f in ("quantity", "amount", "portion", "size", "prep", "extras",
              "brand", "identity"):
        for branded in (True, False):
            assert AT.classify(f, branded=branded) != AT.CONSUMPTION_COMPLETE, f
    # And no legacy value silently becomes it.
    for legacy in AT.LEGACY_MAP:
        assert AT.from_legacy(legacy) != AT.CONSUMPTION_COMPLETE, legacy


def test_an_unmappable_field_is_recorded_AS_unmapped():
    """Absence is not a negative. A field the vocabulary cannot map must not be
    folded into a real type — a silently mis-bucketed ask corrupts the
    denominator a policy is sized against."""
    assert AT.classify("something_new") == AT.UNCLASSIFIED
    assert AT.classify(None) == AT.UNCLASSIFIED
    assert AT.classify("") == AT.UNCLASSIFIED


def test_every_ask_emits_at_least_one_canonical_value():
    """An ask with no determinable type records `unclassified`, never an empty
    tuple: a missing type and a typed-as-nothing ask must not be the same row."""
    import core.food_turn as FT
    for data in ({}, {"ambiguities": []}, {"ambiguities": None},
                 {"ambiguities": [{"item": "x", "field": "??"}]}):
        got = FT._ask_types_from(data)
        assert got and all(t in AT.ALL for t in got), (data, got)


def test_legacy_values_are_READ_ONLY_and_never_written():
    """Legacy names get a forward map for reading historical rows. They must not
    become second-class canonical enums."""
    assert AT.from_legacy("cook_method") == AT.PREPARATION_FAT
    assert AT.from_legacy("brand") == AT.IDENTITY_VARIANT
    # every legacy value maps INTO the canonical vocabulary, never beside it
    for v in AT.LEGACY_MAP.values():
        assert v in AT.ALL, v
    # and no legacy KEY is itself a canonical value being round-tripped
    assert not (set(AT.LEGACY_MAP) & (set(AT.ALL) - {AT.UNCLASSIFIED})) - {"portion"}


def test_the_rendering_vocabulary_never_reaches_a_durable_field():
    """`_RENDER_PHRASING` keys are presentation. If one is ever persisted, the
    two vocabularies have silently merged again."""
    import core.food_turn as FT
    render_keys = set(FT._RENDER_PHRASING)
    conv = pathlib.Path("core/conversation.py").read_text()
    i = conv.index('"ask_types": list(_sft.get("ask_types")')
    line = conv[i:conv.index("\n", i)]
    assert "_render_facet" not in line and "_RENDER_PHRASING" not in line
    # the durable value comes from _sft, which food_turn typed structurally
    assert '_sft.get("ask_types")' in line
    # sanity: the two vocabularies genuinely differ, so this test is not vacuous
    assert render_keys - set(AT.ALL), (
        "the rendering keys are now a subset of the canonical vocabulary — "
        "either they merged, or this test no longer checks anything")
