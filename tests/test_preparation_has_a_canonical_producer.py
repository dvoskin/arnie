"""Preparation opens from QUALIFIED SEMANTIC EVIDENCE, not from string tokens.

History, because it is the whole reason this file changed shape twice:

* B-1.5 shipped preparation askable and UNREACHABLE — the field opened only
  when the interpreter volunteered a `preparation` ambiguity, which it does
  not do for a food it identifies confidently. Measured in production: "I had
  some chicken" opened one field, and generic Chicken committed at 1.88 cal/g
  where grilled breast is ~1.65 and fried thigh ~2.4.
* The first fix matched registered preparation tokens against raw USDA
  descriptions. It passed FOURTEEN gates against a fixture I wrote to look
  like USDA and never checked — and a live probe then showed a bare `chicken`
  query returns chicken spread, meatless chicken, chicken FAT at 900 kcal and
  a frankfurter. Token matching over that is identity-by-string-overlap: the
  exact defect the evidence boundary exists to delete.
* B-1.5E C2 DELETED that predicate rather than refining it. Preparation now
  consumes qualified semantic assessments, and the invariants below survive
  the change unaltered — which is the point of testing rules rather than
  implementations.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from core import semantic_fields as sf
from core.semantics import ClarificationAttribute
from skills.nutrition import evidence_semantics as food
from skills.nutrition import preparation_activation as pa
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


@pytest.fixture
def space(monkeypatch):
    """Control the evidence-derived preparation space directly. What the
    resolver does with real records is layer C (the eval script); this file
    tests the DECISION over a given space."""
    def serve(mapping):
        async def _space(food_name):
            return dict(mapping)
        monkeypatch.setattr(pa, "preparation_space", _space)
    return serve


# ── the production case ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_material_preparations_open_the_field(space):
    """The turn that must work: no interpreter ambiguity, no stated method,
    and evidence establishing grilled ~165 vs fried ~250."""
    space({"grilled": 165.0, "fried": 250.0})
    assert await pa.preparation_is_materially_unresolved(_item("chicken"))

    opened = await sf.derive_unresolved(_item("chicken"))
    assert ClarificationAttribute.PREPARATION in opened


@pytest.mark.asyncio
async def test_no_interpreter_ambiguity_is_required(space):
    """The B-1.5 defect, gated: the item carries a QUANTITY ambiguity only —
    exactly what production sent — and preparation still opens."""
    space({"grilled": 165.0, "fried": 250.0})
    item = _item("chicken", ambiguities=(FoodAmbiguity(
        ambiguity_id="a1", staged_item_id="si_1",
        ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
        field_name="estimated_mass_g", materiality_score=2.0,
        calorie_span=180.0),))
    assert not any(a.ambiguity_type is AmbiguityType.PREPARATION
                   for a in item.material_ambiguities())
    assert await pa.preparation_is_materially_unresolved(item)


# ── every reason NOT to ask ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_preparations_that_price_the_same_do_not_interrupt(space):
    """Vocabulary existing is not a reason to interrupt someone."""
    space({"grilled": 21.0, "roasted": 22.0})
    assert not await pa.preparation_is_materially_unresolved(_item("zucchini"))


@pytest.mark.asyncio
async def test_one_preparation_is_nothing_to_choose_between(space):
    space({"roasted": 165.0})
    assert not await pa.preparation_is_materially_unresolved(_item("chicken"))


@pytest.mark.asyncio
async def test_preparations_without_densities_cannot_prove_materiality(space):
    """Two preparations exist and the difference cannot be priced, so the
    question cannot be shown to be worth asking. Silence beats a guess."""
    space({"grilled": None, "fried": None})
    assert not await pa.preparation_is_materially_unresolved(_item("chicken"))


@pytest.mark.asyncio
async def test_a_stated_preparation_does_not_reopen(monkeypatch):
    """Asking someone to repeat themselves is how a clarification becomes an
    interrogation — and it must not even cost a lookup."""
    called = []

    async def _space(food_name):
        called.append(food_name)
        return {"grilled": 165.0, "fried": 250.0}

    monkeypatch.setattr(pa, "preparation_space", _space)
    item = _item("chicken",
                 preparation=PreparationIntent(method="grilled", stated=True))
    assert not await pa.preparation_is_materially_unresolved(item)
    assert not called, "a stated preparation should not cost an evidence pass"


@pytest.mark.asyncio
async def test_an_interpreter_raised_ambiguity_short_circuits(monkeypatch):
    """Believe the interpreter when it volunteers preparation, and spend
    nothing proving what it already said."""
    called = []

    async def _space(food_name):
        called.append(food_name)
        return {}

    monkeypatch.setattr(pa, "preparation_space", _space)
    item = _item("chicken", ambiguities=(FoodAmbiguity(
        ambiguity_id="a2", staged_item_id="si_1",
        ambiguity_type=AmbiguityType.PREPARATION, field_name="preparation",
        materiality_score=1.5, calorie_span=90.0),))
    assert await pa.preparation_is_materially_unresolved(item)
    assert not called


@pytest.mark.asyncio
async def test_a_failed_evidence_pass_opens_nothing(monkeypatch):
    """Evidence we could not gather is not evidence of ambiguity."""
    async def _boom(food_name):
        raise RuntimeError("resolver down")

    monkeypatch.setattr(pa, "preparation_space", _boom)
    assert await sf.derive_unresolved(_item("chicken")) == ()


@pytest.mark.asyncio
async def test_a_nameless_item_opens_nothing(space):
    space({"grilled": 165.0, "fried": 250.0})
    item = StagedFoodItem(staged_item_id="si_1", original_text="some food",
                          identity=FoodIdentity(canonical_name=""),
                          quantity=QuantityIntent(descriptor="some"))
    assert not await pa.preparation_is_materially_unresolved(item)


# ── the prohibitions ────────────────────────────────────────────────────────

def test_no_food_name_branch_and_no_curated_list():
    """A list of foods that need preparation is a food-name branch wearing a
    different hat — wrong for the first food not on it."""
    source = pathlib.Path(pa.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for side in [node.left, *node.comparators]:
                assert not (isinstance(side, ast.Constant)
                            and isinstance(side.value, str) and side.value), (
                    f"line {node.lineno} compares against a string literal")

    for node in tree.body:
        if isinstance(node, ast.Assign):
            for value in ast.walk(node):
                if isinstance(value, (ast.List, ast.Set)):
                    strings = [e for e in value.elts
                               if isinstance(e, ast.Constant)
                               and isinstance(e.value, str)]
                    assert not strings, (
                        f"line {node.lineno} holds a literal string "
                        f"collection — vocabulary belongs in the registry")


def test_the_superseded_token_matcher_is_gone():
    """DELETED, not refined. Its `_preparations_in` matched registered tokens
    against raw provider descriptions — regex identity, prohibited."""
    root = pathlib.Path(__file__).resolve().parent.parent
    assert not (root / "skills/nutrition/preparation_materiality.py").exists()

    # AST, NOT SUBSTRING. The first version asserted `"import re" not in
    # source` — which matches `from core.semantic_evidence import resolve`
    # ("import re" + "solve"). A substring false positive inside the test
    # written to ban substring identity matching; the third time today that
    # text-matching lied about code.
    tree = ast.parse(pathlib.Path(pa.__file__).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            assert not any(a.name == "re" for a in node.names), (
                f"line {node.lineno} imports `re` — the activation path "
                f"reintroduced regex matching over provider text")
        if isinstance(node, ast.ImportFrom):
            assert node.module != "re", f"line {node.lineno} imports from re"


def test_the_coordinator_still_names_no_field():
    from core import b1_quantity_operation as b1

    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(b1.try_take_ownership)))
    called = {getattr(n.func, "id", "") or getattr(n.func, "attr", "")
              for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "derive_unresolved" in called
    assert not {c for c in called if "preparation" in c.lower()}, (
        "the coordinator named a specific field again")


def test_activation_cannot_reach_a_provider_client_directly():
    """It consumes QUALIFIED evidence and the search lane; it never talks to
    USDA or OFF itself."""
    tree = ast.parse(pathlib.Path(pa.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("usda" in m or ".off" in m for m in imported), imported


def test_the_registered_vocabulary_still_drives_the_web_query():
    """The query names the registry's preparations, so extending the
    vocabulary extends the evidence sought — no second list."""
    source = inspect.getsource(pa._web_space)
    assert "_registered_preparations()" in source
    assert "site:" in source, (
        "source quality is a function of query construction — ask for "
        "authority rather than grading whatever returns")
