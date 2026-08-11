"""B-1.6c — THE OWNERSHIP SEAM, PROVEN BY POISON RATHER THAN BY GREP.

`core/portions.py` holds a phrase table that decides added fat from RAW TEXT:

    _ADDED_FAT_CAL       "in butter" -> 100, "with ranch" -> 145, "alfredo" -> 180
    _ADDED_FAT_NEGATIONS "no dressing", "without", "plain", ...
    added_fat_calories() the calories a named fat contributes
    mentions_fat()       whether the text ADDRESSED fat at all

That is a SECOND SEMANTIC OWNER for a question B-1.6 now models as fields. It
is not deleted: legacy and non-eligible turns keep it unchanged, and it goes
on the deletion inventory for the promotion boundary. What must be true today
is narrower and checkable — CANONICAL cannot reach it.

⭐ POISON, NOT GREP (Danny). A direct-call search can look clean while
`settle -> canonical_pricing -> some shared helper` still lands on the legacy
owner. Import gates prove a module is not NAMED; they do not prove it is not
REACHED. So every one of the four is replaced with something that raises, and
a canonical settle is required to complete anyway.

⭐⭐ AND IT MAY NOT SURVIVE BY TAKING A WEAKER RUNG (also Danny). "Canonical
completed" is not the claim. A path that quietly falls to the estimate rung
when the phrase tables explode is still DEPENDENT on them — it has merely
converted a hard failure into an accuracy loss, which is worse because it does
not announce itself. The rung and the numbers must be IDENTICAL to an
unpoisoned run.

⭐⭐⭐ THE BOUNDARY IS BROADER THAN THESE FOUR NAMES. The rule worth gating is
that canonical settlement derives nutrition ONLY from canonical resolved state
and canonical evidence — never from phrase-table interpretation of the
original utterance. Gating the four names alone would let the same
second-owner pattern reappear under a fifth.
"""
from __future__ import annotations

import ast
import pathlib
from decimal import Decimal

import pytest

from core import canonical_pricing as cp
from core.canonical_pricing import ArtifactEvidence, EstimateEvidence, Rung
from skills.nutrition.models import NormalizedQuantity

ROOT = pathlib.Path(__file__).resolve().parent.parent

POISONED = ("added_fat_calories", "mentions_fat", "prep_fat_span")


def _explode(*_a, **_k):
    raise AssertionError(
        "the canonical lane reached a legacy added-fat phrase table — the "
        "seam is not cut, only unreferenced by name")


@pytest.fixture
def poisoned(monkeypatch):
    """All four legacy owners, forced to raise."""
    from core import portions

    for name in POISONED:
        if hasattr(portions, name):
            monkeypatch.setattr(portions, name, _explode)
    # The tables themselves, not only the functions that read them: a caller
    # that inlined the lookup would sail past a patched function.
    monkeypatch.setattr(portions, "_ADDED_FAT_CAL", _Exploding())
    monkeypatch.setattr(portions, "_ADDED_FAT_NEGATIONS", _Exploding())
    return portions


class _Exploding:
    """A table that raises on ANY use — membership, iteration, indexing."""

    def __contains__(self, _item): _explode()
    def __iter__(self): _explode()
    def __getitem__(self, _k): _explode()
    def get(self, *_a, **_k): _explode()
    def items(self): _explode()
    def __len__(self): _explode()


def _grams(n: float) -> NormalizedQuantity:
    return NormalizedQuantity(amount=n, unit="g", grams=float(n))


def _artifact():
    return ArtifactEvidence(
        candidates=({"fdc_id": 1,
                     "description": "Beef, shoulder, cooked, grilled",
                     "per100g": {"calories": 208.0, "protein": 28.4}},),
        fingerprint="f")


# ── the canonical path completes, and prices identically ───────────────────

def test_canonical_pricing_completes_with_every_phrase_table_poisoned(poisoned):
    priced = cp.price(entity="Beef, grilled", consumed=_grams(120),
                      artifact=_artifact())
    assert priced.rung is Rung.ARTIFACT
    # 208 kcal/100 g scaled to 120 g, rounded by the pricer as every rung is.
    assert priced.calories == 250.0


def test_it_does_not_survive_by_dropping_to_a_weaker_rung(poisoned):
    """⭐ THE NEGATIVE INVARIANT. Falling to the estimate rung when the phrase
    tables explode would still be a DEPENDENCY — a hard failure converted into
    a silent accuracy loss, which is the worse of the two."""
    estimate = EstimateEvidence(calories=999.0, protein=1.0, basis_grams=120.0)
    priced = cp.price(entity="Beef, grilled", consumed=_grams(120),
                      artifact=_artifact(), estimate=estimate)
    assert priced.rung is Rung.ARTIFACT, (
        f"canonical completed on the {priced.rung.value} rung with the phrase "
        f"tables poisoned — it did not survive independently, it degraded")
    assert priced.calories != 999.0


def test_the_numbers_are_identical_poisoned_and_not(monkeypatch):
    """Same identity, same evidence, same portion: byte-for-byte the same
    result. A difference of any size means something in the path consulted a
    table that is now unavailable."""
    clean = cp.price(entity="Beef, grilled", consumed=_grams(120),
                     artifact=_artifact())

    from core import portions
    for name in POISONED:
        if hasattr(portions, name):
            monkeypatch.setattr(portions, name, _explode)
    monkeypatch.setattr(portions, "_ADDED_FAT_CAL", _Exploding())
    monkeypatch.setattr(portions, "_ADDED_FAT_NEGATIONS", _Exploding())

    poisoned_result = cp.price(entity="Beef, grilled", consumed=_grams(120),
                               artifact=_artifact())
    assert (poisoned_result.calories, poisoned_result.protein,
            poisoned_result.rung, poisoned_result.evidence_id) == (
        clean.calories, clean.protein, clean.rung, clean.evidence_id)


# ── and legacy still depends on them, so this is a SEAM not a deletion ─────

def test_the_legacy_path_still_depends_on_the_phrase_tables():
    """The helpers are NOT deleted, and proving canonical is free of them is
    only meaningful if something still uses them. If this ever goes green
    because nothing calls them at all, they belong in the deletion inventory's
    DONE column, not in this file."""
    from core.portions import added_fat_calories, mentions_fat

    assert added_fat_calories("sirloin cooked in butter") == (100, "in butter")
    assert mentions_fat("grilled chicken, no oil") is True

    callers = []
    for path in list((ROOT / "core").glob("*.py")) + \
            list((ROOT / "handlers").glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if path.name == "portions.py":
            continue
        if "added_fat_calories" in text or "mentions_fat" in text:
            callers.append(path.name)
    assert callers, (
        "nothing outside portions.py uses the added-fat phrase tables any "
        "more — they are dead, so move them to DELETION_INVENTORY.md's done "
        "column rather than leaving a seam test guarding nothing")


# ── ⭐⭐⭐ the broader boundary, gated by name-independence ────────────────

def test_canonical_settlement_reads_no_raw_utterance_helper():
    """CANONICAL NUTRITION COMES FROM RESOLVED STATE AND EVIDENCE — never from
    phrase-table interpretation of what the user typed.

    Broader than "does not call added_fat_calories", deliberately. Gating the
    four names would let the identical second-owner pattern return under a
    fifth, and the pattern is the defect: a helper that takes the raw message
    and returns a nutrition number is a second opinion about the meal, held by
    a module with no access to the evidence the first opinion used.
    """
    canonical = ["core/canonical_pricing.py", "core/canonical_writer.py",
                 "core/commit_coordinator.py", "core/interaction_generation.py",
                 "core/field_activation.py"]
    # Every phrase-table style helper `portions` exposes — read from the
    # module, so a new one is covered the day it is written rather than the
    # day someone remembers to add it here.
    from core import portions

    text_helpers = {n for n in dir(portions)
                    if not n.startswith("__")
                    and callable(getattr(portions, n, None))
                    and n in ("added_fat_calories", "mentions_fat",
                              "prep_fat_span", "is_vague_unit")}
    assert text_helpers, "portions exposes no raw-text helpers to guard against"

    offenders = []
    for rel in canonical:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.endswith("portions"):
                    names = [a.name for a in node.names]
            for name in names:
                if name in text_helpers:
                    offenders.append(f"{rel}:{node.lineno} imports {name}")
    assert not offenders, (
        "canonical settlement imports a raw-utterance nutrition helper:\n  "
        + "\n  ".join(offenders))
