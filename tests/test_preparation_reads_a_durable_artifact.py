"""PREPARATION IS READ, NEVER COMPUTED — the six gates B-1.5 was approved on.

Measured 2026-08-07, which is why this exists at all: computing the space
inline cost 8,992 ms for 8 records and 15,813 ms for 12, and still opened
nothing — bare `chicken` returns 8 USDA rows, qualification correctly keeps
ONE (refusing chicken spread, chicken FAT at 900 kcal, a frankfurter), and
that survivor carries no preparation. The evidence boundary was working. The
defect was recomputing a UNIVERSAL FACT inside an interactive request.

    BUILD TIME   real provider evidence -> same resolver -> same projection
                 -> versioned artifact -> fingerprint -> committed
    TURN  TIME   identity -> lookup -> fingerprints valid?
                     no  -> UNKNOWN, do not ask
                     yes -> same space_is_material() -> open / closed
                 ZERO provider retrieval, ZERO model call, ZERO web lookup
"""
from __future__ import annotations

import ast
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from core.materiality_artifact import Stale, load, parse, verify
from skills.nutrition import preparation_activation as pa
from skills.nutrition import preparation_artifact as art

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _fresh_reader():
    art._reset_for_tests()
    yield
    art._reset_for_tests()


def _document(**overrides) -> dict:
    doc = {
        "resolver_version": art.resolver_version(),
        "vocabulary_fingerprint": art.vocabulary_fingerprint(),
        "retrieval_fingerprint": art.retrieval_fingerprint(),
        "generated_at": datetime.now(timezone.utc).isoformat()
                                .replace("+00:00", "Z"),
        "entries": {"chicken": {"space": {"roasted": 167.0, "fried": 219.0},
                                "material": True}},
    }
    doc.update(overrides)
    return doc


def _write(tmp_path, doc) -> pathlib.Path:
    path = tmp_path / "artifact.json"
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _verify(path, **kw):
    return load(path, resolver_version=art.resolver_version(),
                vocabulary_fingerprint=art.vocabulary_fingerprint(),
                retrieval_fingerprint=art.retrieval_fingerprint(), **kw)


# ── GATE 1: a fingerprint mismatch makes the artifact unreadable ────────────

@pytest.mark.parametrize("field,reason", [
    ("resolver_version", "a different model reaches different relationships"),
    ("vocabulary_fingerprint", "a new preparation was never queried for"),
    ("retrieval_fingerprint", "different queries reach different rows"),
])
def test_a_mismatched_stamp_refuses_the_artifact(tmp_path, field, reason):
    path = _write(tmp_path, _document(**{field: "sha256:tampered"}))
    with pytest.raises(Stale):
        _verify(path)


def test_a_matching_artifact_is_readable(tmp_path):
    assert _verify(_write(tmp_path, _document())).entries["chicken"]


def test_adding_a_preparation_invalidates_every_artifact(tmp_path, monkeypatch):
    """The subtlest staleness: the registry grows a state the artifact was
    never built to look for, so the stored space is silently INCOMPLETE — it
    would answer confidently while missing an option the field can now offer.
    """
    path = _write(tmp_path, _document())
    assert _verify(path)                      # readable before

    from core import semantic_fields as sf
    real = sf.spec_for

    def wider(attribute):
        spec = real(attribute)
        if spec.attribute_value == "preparation":
            import dataclasses
            return dataclasses.replace(
                spec, vocabulary=tuple(spec.vocabulary) + ("poached",))
        return spec

    monkeypatch.setattr(sf, "spec_for", wider)
    with pytest.raises(Stale):
        load(path, resolver_version=art.resolver_version(),
             vocabulary_fingerprint=art.vocabulary_fingerprint(),
             retrieval_fingerprint=art.retrieval_fingerprint())


# ── GATE 2: build BLOCKS, runtime DEGRADES ─────────────────────────────────

def test_the_committed_artifact_passes_the_release_gate():
    """BUILD SIDE. A stale or mismatched artifact must be unshippable, so this
    is the gate that fails CI rather than a runtime shrug."""
    artifact = art.verified()
    assert artifact.entries, "the committed artifact is empty"
    assert artifact.age_days() <= 90


def test_a_stale_artifact_degrades_at_runtime_instead_of_raising(tmp_path,
                                                                 monkeypatch):
    """RUNTIME SIDE, and the asymmetry is the point. CI makes the bad state
    unreachable; production must never turn it into a slow turn or a failed
    one. Stale ⇒ UNKNOWN ⇒ the field does not open."""
    old = (datetime.now(timezone.utc) - timedelta(days=400)).isoformat()
    path = _write(tmp_path, _document(generated_at=old.replace("+00:00", "Z")))
    monkeypatch.setattr(art, "ARTIFACT_PATH", path)
    art._reset_for_tests()

    assert art.space_for("chicken") == {}, "a stale artifact was still read"


@pytest.mark.parametrize("broken", ["{not json", '{"entries": {}}', ""])
def test_an_unreadable_artifact_never_raises_into_the_turn(tmp_path,
                                                           monkeypatch, broken):
    path = tmp_path / "broken.json"
    path.write_text(broken, encoding="utf-8")
    monkeypatch.setattr(art, "ARTIFACT_PATH", path)
    art._reset_for_tests()

    assert art.space_for("chicken") == {}


def test_a_missing_artifact_never_raises_into_the_turn(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "ARTIFACT_PATH", tmp_path / "absent.json")
    art._reset_for_tests()
    assert art.space_for("chicken") == {}


# ── GATE 3: the turn path issues no provider request ───────────────────────

def test_the_activation_path_cannot_reach_a_provider_or_the_resolver():
    """AST over the module the turn actually calls. It may not search, may not
    resolve, and may not import a provider — there is nothing left for it to
    do but read."""
    tree = ast.parse(pathlib.Path(pa.__file__).read_text(encoding="utf-8"))

    offenders = [(n.lineno, getattr(n.func, "id", "") or getattr(n.func, "attr", ""))
                 for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and (getattr(n.func, "id", "") or getattr(n.func, "attr", ""))
                 in ("search", "search_food", "resolve", "_default_complete")]
    assert not offenders, f"the turn path calls a provider/resolver at {offenders}"

    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert not any("usda" in m or ".off" in m or "search" in m
                   for m in imported), imported


def test_nothing_on_the_turn_path_speculates_any_more():
    """The C2.1a speculation machinery is GONE, not merely unused. A dormant
    starter is one call site away from putting a lookup back on the ask."""
    for name in ("start_supplemental", "supplemental_key", "_web_space",
                 "MATERIALITY_BUDGET_S"):
        assert not hasattr(pa, name), f"{name} survived"
    from core import semantic_fields as sf
    assert not hasattr(sf, "start_speculation")
    assert "speculate" not in {f.name for f in
                               __import__("dataclasses").fields(sf.FieldSpec)}


# ── GATE 4: one projection, shared by the generator and the turn ───────────

def test_the_generator_and_the_turn_path_share_one_materiality_rule():
    """Asserted by IMPORT, not by comment. Two definitions of "material" would
    drift silently: entries written for foods the predicate then declines, or
    foods skipped that it would have opened."""
    source = (ROOT / "scripts/build_materiality_artifact.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source)

    calls = {f"{getattr(n.func, 'value', None) and getattr(n.func.value, 'id', '')}"
             f".{getattr(n.func, 'attr', '')}"
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "pa.space_is_material" in calls, (
        "the generator computes materiality its own way")
    assert "food.preparation_evidence" in calls, (
        "the generator projects evidence its own way")

    # And the rule has exactly one definition in the product.
    #
    # AST, MODULE-LEVEL ONLY. The first version of this asserted
    # `"def is_material(" in source`, which matched `FoodAmbiguity.is_material`
    # and three other unrelated METHODS — a substring ratchet producing a false
    # positive inside the gate meant to prove single ownership, which is the
    # fourth time text matching has lied about code in this migration.
    defs = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", ".venv/", "scripts/", "alembic/")) \
                or rel.startswith("simulate"):
            continue
        try:
            module = ast.parse(path.read_text(encoding="utf-8",
                                              errors="ignore"))
        except SyntaxError:                              # pragma: no cover
            continue
        if any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
               and n.name == "space_is_material" for n in module.body):
            defs.append(rel)
    assert defs == ["skills/nutrition/preparation_activation.py"], (
        f"the materiality rule has {len(defs)} definitions: {defs}")


# ── GATE 5: chicken opens THROUGH ITS REAL CONSUMER ────────────────────────

@pytest.mark.asyncio
async def test_chicken_opens_through_the_real_derivation_path(monkeypatch):
    """THE GATE THAT MATTERS, and the amendment that sharpened it.

    Testing the reader in isolation would prove the artifact works while
    bypassing the thing that uses it — which is exactly how the seam defect
    and the preparation fixture both hid. So this drives the REAL
    `derive_unresolved`, against the REAL committed artifact, with the network
    poisoned: any provider or model call fails the test rather than silently
    making it pass.
    """
    import api.usda as usda
    from core.semantics import ClarificationAttribute
    from core.semantic_fields import derive_unresolved
    from skills.nutrition.ambiguity import AmbiguityType, FoodAmbiguity
    from skills.nutrition.staging import (FoodIdentity, PreparationIntent,
                                          QuantityIntent, StagedFoodItem)

    async def _forbidden(*a, **kw):                       # pragma: no cover
        raise AssertionError("the turn path reached a provider")

    monkeypatch.setattr(usda, "_search", _forbidden)
    monkeypatch.setattr(usda, "search_food", _forbidden)
    monkeypatch.setattr("core.semantic_evidence.resolve", _forbidden)

    item = StagedFoodItem(
        staged_item_id="si_1", original_text="some chicken",
        identity=FoodIdentity(canonical_name="chicken"),
        quantity=QuantityIntent(descriptor="some"), vague_measure="some",
        preparation=PreparationIntent(),
        ambiguities=(FoodAmbiguity(
            ambiguity_id="a1", staged_item_id="si_1",
            ambiguity_type=AmbiguityType.CONSUMED_QUANTITY,
            field_name="estimated_mass_g", materiality_score=2.0,
            calorie_span=180.0),))

    opened = await derive_unresolved(item)
    assert ClarificationAttribute.PREPARATION in opened, (
        "chicken did not open preparation from the committed artifact")


@pytest.mark.asyncio
async def test_a_food_absent_from_the_artifact_opens_nothing(monkeypatch):
    """Fail-closed, through the same real path. Branzino has no entry —
    measured live, USDA carries only two branded rows at one density — so the
    field must stay shut rather than guess."""
    from core.semantic_fields import derive_unresolved
    from skills.nutrition.staging import (FoodIdentity, PreparationIntent,
                                          QuantityIntent, StagedFoodItem)

    item = StagedFoodItem(
        staged_item_id="si_2", original_text="some branzino",
        identity=FoodIdentity(canonical_name="branzino"),
        quantity=QuantityIntent(descriptor="some"),
        preparation=PreparationIntent())
    assert await derive_unresolved(item) == ()


@pytest.mark.asyncio
async def test_a_stated_preparation_still_does_not_reopen():
    """Unchanged by the artifact: asking someone to repeat themselves is how a
    clarification becomes an interrogation."""
    from skills.nutrition.staging import (FoodIdentity, PreparationIntent,
                                          QuantityIntent, StagedFoodItem)

    item = StagedFoodItem(
        staged_item_id="si_3", original_text="grilled chicken",
        identity=FoodIdentity(canonical_name="chicken"),
        quantity=QuantityIntent(descriptor="some"),
        preparation=PreparationIntent(method="grilled", stated=True))
    assert not await pa.preparation_is_materially_unresolved(item)


# ── GATE 6: the committed artifact is what it claims to be ─────────────────

def test_every_stored_space_is_registered_and_material():
    """A space the field cannot RENDER is a question we cannot ask, and a
    space that is not material is an interruption. Both are checked against
    the live registry and the live rule, not against the generator's word."""
    from core.semantic_fields import spec_for

    registered = set(spec_for("preparation").vocabulary)
    artifact = art.verified()
    for food_name, entry in artifact.entries.items():
        space = entry["space"]
        assert set(space) <= registered, (
            f"{food_name} stores {set(space) - registered}, which the field "
            f"cannot offer")
        assert pa.space_is_material(space), (
            f"{food_name} was stored as material but the live rule disagrees")
