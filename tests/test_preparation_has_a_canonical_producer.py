"""B-1.5 producer defect: preparation was askable and unreachable.

MEASURED IN PRODUCTION 2026-08-07, on the deployed build. "I had some chicken"
opened ONE field. The B-1.5 machinery ran — `answered` was populated, which
only the new build writes — so holding, readiness, `ResolvedFields` and
settlement all executed correctly. The field simply was never opened, because
it was opened only when the INTERPRETER volunteered a `preparation` ambiguity,
and for a food it identifies confidently it reports no uncertainty at all.

Generic "Chicken" committed at 1.88 cal/g. Grilled breast is ~1.65 and fried
thigh ~2.4, so the number landed mid-range on a food where the unasked question
is worth about 40%.

THE TWO EASY FIXES WERE BOTH FORBIDDEN AND BOTH WRONG — the interpreter prompt
(enhancements go in code) and a list of foods that need preparation (a
food-name branch by another name). The field decides its own necessity from
USDA's own rows, through a generic `unresolved_when` hook every future field
declares the same way.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from core import semantic_fields as sf
from core.semantics import ClarificationAttribute
from skills.nutrition import preparation_materiality as pm
from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
from skills.nutrition.staging import (FoodIdentity, PreparationIntent,
                                      QuantityIntent, StagedFoodItem)


def _item(name="chicken", *, preparation=None, ambiguities=()):
    return StagedFoodItem(
        staged_item_id="si_1", original_text=f"some {name}",
        identity=FoodIdentity(canonical_name=name),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        preparation=preparation or PreparationIntent(),
        ambiguities=tuple(ambiguities))


def _row(description, calories):
    return {"description": description, "per100g": {"calories": calories}}


#: USDA's real shape for a generic bird: several preparations, real spread.
CHICKEN_ROWS = [
    _row("Chicken, broilers or fryers, breast, meat only, cooked, grilled", 165),
    _row("Chicken, broilers or fryers, breast, meat only, cooked, roasted", 165),
    _row("Chicken, broilers or fryers, thigh, meat and skin, fried", 253),
]

#: A food whose preparations price the same. The question would change nothing.
#:
#: BOTH PREPARATIONS MUST BE REGISTERED, or this tests the wrong branch. The
#: first version used raw / boiled / grilled — only `grilled` is registered, so
#: the predicate exited at "fewer than two preparations" and never reached the
#: materiality comparison at all. It passed, and went on passing when the
#: threshold was mutated away. Caught by exactly that mutation.
FLAT_ROWS = [
    _row("Zucchini, grilled", 21),
    _row("Zucchini, roasted", 22),
]


@pytest.fixture
def usda(monkeypatch):
    """Serve rows without the network, and record what was asked for."""
    asked = []

    def serve(rows):
        async def _search(query, page_size=8):
            asked.append(query)
            return list(rows)
        monkeypatch.setattr("api.usda.search_food", _search)
        return asked

    return serve


# ── gate 1: the production-shaped turn opens both ───────────────────────────

@pytest.mark.asyncio
async def test_i_had_some_chicken_opens_preparation(usda):
    """THE PRODUCTION CASE. No interpreter ambiguity, no stated method — and
    USDA's own rows disagree by 165 vs 253."""
    usda(CHICKEN_ROWS)
    assert await pm.preparation_is_materially_unresolved(_item("chicken"))

    opened = await sf.derive_unresolved(_item("chicken"))
    assert ClarificationAttribute.PREPARATION in opened


@pytest.mark.asyncio
async def test_the_derivation_needs_no_interpreter_ambiguity(usda):
    """Gate 7, stated directly: the item carries a QUANTITY ambiguity only —
    exactly what production sent — and preparation still opens."""
    usda(CHICKEN_ROWS)
    item = _item("chicken", ambiguities=(FoodAmbiguity(
        ambiguity_id="a1", staged_item_id="si_1",
        ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="estimated_mass_g", materiality_score=2.0,
        calorie_span=180.0),))
    assert not any(a.ambiguity_type is AmbiguityType.PREPARATION
                   for a in item.material_ambiguities())
    assert await pm.preparation_is_materially_unresolved(item)


# ── gate 3: no question where the answer changes nothing ────────────────────

@pytest.mark.asyncio
async def test_a_food_whose_preparations_price_the_same_is_not_asked(usda):
    """Preparation VOCABULARY existing is not a reason to interrupt someone."""
    usda(FLAT_ROWS)
    assert not await pm.preparation_is_materially_unresolved(_item("zucchini"))


@pytest.mark.asyncio
async def test_one_preparation_in_the_evidence_is_nothing_to_choose_between(
        usda):
    usda([_row("Rice, white, long-grain, cooked", 130)])
    assert not await pm.preparation_is_materially_unresolved(_item("rice"))


# ── gates 4 and 5: do not re-ask, do not invent ─────────────────────────────

@pytest.mark.asyncio
async def test_a_stated_preparation_does_not_reopen(usda):
    asked = usda(CHICKEN_ROWS)
    item = _item("chicken",
                 preparation=PreparationIntent(method="grilled", stated=True))
    assert not await pm.preparation_is_materially_unresolved(item)
    assert not asked, "a stated preparation should not even cost a lookup"


@pytest.mark.asyncio
async def test_a_name_that_already_carries_a_preparation_is_not_asked(usda):
    """"Grilled chicken" answers itself. Re-asking would price a food the user
    already described."""
    usda(CHICKEN_ROWS)
    assert not await pm.preparation_is_materially_unresolved(
        _item("grilled chicken"))


@pytest.mark.asyncio
async def test_a_failed_lookup_does_not_invent_a_question(monkeypatch):
    """Evidence we could not gather is not evidence of ambiguity."""
    async def _boom(query, page_size=8):
        raise RuntimeError("usda down")

    monkeypatch.setattr("api.usda.search_food", _boom)
    assert not await pm.preparation_is_materially_unresolved(_item("chicken"))


@pytest.mark.asyncio
async def test_a_predicate_that_raises_opens_nothing(monkeypatch):
    """Core must survive a domain predicate that throws — and open no field."""
    async def _boom(item, ctx=None):
        raise RuntimeError("domain broke")

    # Patched at the module the registered wrapper imports lazily — `FieldSpec`
    # is frozen, which is the point of it.
    monkeypatch.setattr(
        "skills.nutrition.preparation_materiality"
        ".preparation_is_materially_unresolved", _boom)
    assert await sf.derive_unresolved(_item("chicken")) == ()


@pytest.mark.asyncio
async def test_only_resolver_supported_preparations_count(usda):
    """Gate 5. USDA says "breaded" and "poached"; neither is registered, so
    neither may create a question this system could not act on."""
    usda([_row("Chicken, breaded, fried", 290),
          _row("Chicken, poached", 150)])
    assert not await pm.preparation_is_materially_unresolved(_item("chicken"))


def test_word_boundaries_keep_accidental_matches_out():
    vocabulary = tuple(sf.spec_for("preparation").vocabulary)
    assert pm._preparations_in("stir-fried rice", vocabulary) == {"fried"}
    assert pm._preparations_in("strawberry jam", vocabulary) == set()


# ── gate 6: no food-name branch anywhere in the derivation ──────────────────

def test_no_food_name_branch_and_no_curated_list():
    """The forbidden shape, checked as source.

    A list of foods that need preparation is a food-name branch wearing a
    different hat: wrong for the first food not on it, and exactly what the
    Semantic Extension Contract refuses.
    """
    source = pathlib.Path(pm.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    # No string literal in a comparison — that is how a food name gets in.
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                assert not (isinstance(side, ast.Constant)
                            and isinstance(side.value, str) and side.value), (
                    f"line {node.lineno} compares against a string literal — "
                    f"if that is a food name, this is the branch we refuse")

    # Module-level collections may hold tuning constants, not foods.
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for value in ast.walk(node):
                if isinstance(value, (ast.List, ast.Set)):
                    strings = [e for e in value.elts
                               if isinstance(e, ast.Constant)
                               and isinstance(e.value, str)]
                    assert not strings, (
                        f"line {node.lineno} holds a literal string "
                        f"collection — a curated food or preparation list "
                        f"belongs in the registry, not here")


def test_the_coordinator_names_no_field_in_the_derivation():
    """`try_take_ownership` asks the registry and reads one answer out of it.
    It must not decide WHICH fields exist."""
    from core import b1_quantity_operation as b1

    # AST, NOT SUBSTRING — the first version flagged the comment explaining
    # what this replaced. A ratchet that punishes writing down WHY pressures
    # the next author to delete the explanation.
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(b1.try_take_ownership)))
    called = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "derive_unresolved" in called, "the generic stage is gone"
    assert "preparation_is_open" not in called, (
        "the coordinator went back to a preparation-specific trigger")


# ── gate 9: the shared staged state is untouched ────────────────────────────

@pytest.mark.asyncio
async def test_the_derivation_does_not_mutate_the_staged_item(usda):
    """Legacy observes the same object. A derivation that wrote to it would be
    new food behaviour inside a frozen path."""
    usda(CHICKEN_ROWS)
    item = _item("chicken")
    before = (item.identity.canonical_name, item.preparation,
              tuple(item.ambiguities), item.vague_measure)

    await sf.derive_unresolved(item)

    assert (item.identity.canonical_name, item.preparation,
            tuple(item.ambiguities), item.vague_measure) == before


def test_legacy_eligibility_is_unchanged_by_the_derivation():
    """Gate 2, at the seam that matters: the legacy lane's own predicate never
    consults the canonical derivation."""
    from skills.nutrition import quantity_clarification as qc

    source = inspect.getsource(qc.is_eligible)
    assert "derive_unresolved" not in source
    assert "preparation_materiality" not in source
