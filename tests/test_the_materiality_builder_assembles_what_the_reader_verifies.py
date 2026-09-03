"""The builder's document assembly, as a pure function with its own proof — it had
silently gone missing (NameError at the write on every run since a refactor)."""
from __future__ import annotations

from datetime import datetime, timezone

from core import materiality_artifact as ma
from scripts.build_materiality_artifact import assemble_document, FAILED, IMMATERIAL, MATERIAL
from skills.nutrition import preparation_artifact as pa

RESULTS = [
    {"food": "chicken", "status": MATERIAL, "material": True, "space": {"fried": 219.0, "grilled": 151.0}, "evidence_ids": ["usda:2", "usda:1"]},
    {"food": "potato", "status": IMMATERIAL, "material": False, "space": {"fried": 148.0, "roasted": 119.0}, "evidence_ids": ["usda:3"]},
    {"food": "rice", "status": FAILED, "material": False, "space": {}, "evidence_ids": []},
]
NOW = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)


def test_only_material_foods_get_an_entry():
    doc = assemble_document(RESULTS, now=NOW)
    assert set(doc["entries"]) == {"chicken"}, "no entry IS the immaterial claim; a second encoding would double it"
    assert doc["entries"]["chicken"] == {"space": {"fried": 219.0, "grilled": 151.0}, "evidence_ids": ["usda:2", "usda:1"], "material": True}


def test_the_assembly_is_deterministic_and_parses():
    a, b = assemble_document(RESULTS, now=NOW), assemble_document(RESULTS, now=NOW)
    assert a == b
    parsed = ma.parse(a)
    assert parsed.resolver_version == pa.live_resolver_version()
    assert parsed.vocabulary_fingerprint == pa.vocabulary_fingerprint()
    assert parsed.retrieval_fingerprint == pa.retrieval_fingerprint()
    assert parsed.generated_at == NOW
