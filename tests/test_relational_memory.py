"""Memory graph Stage 3 — the "knowing you" relational layer.

Relational facts (the people in their life, their deeper why, their boundaries/
sensitivities) ride the existing user_attributes store but are pinned to CORE
tier so they're in front of Arnie every turn — that's what makes coaching feel
personal, and for boundaries, keeps it safe.
"""
from __future__ import annotations

import pytest

from memory.attribute_store import tier_for_key


# ── Relational keys are always core (always surfaced) ─────────────────────────

@pytest.mark.parametrize("key", [
    "lifestyle_person_wife",
    "lifestyle_person_daughter",
    "family_context",
    "lifestyle_child_age",
    "behavior_deeper_why",
    "behavior_why_underneath",
    "behavior_motivation_driver",
    "mental_boundary_calorie_talk",
    "health_sensitivity_disordered_eating",
    "lifestyle_spouse_diet",
])
def test_relational_keys_are_core(key):
    assert tier_for_key(key) == "core", f"{key} should be core-tier (always surfaced)"


@pytest.mark.parametrize("key", [
    "nutrition_favorite_snack",       # daily, not core
    "health_biomarker_a1c",           # contextual
    "lifestyle_occupation",           # contextual (no relational marker)
])
def test_non_relational_keys_keep_default_tier(key):
    assert tier_for_key(key) != "core"


# ── Stored relational fact lands at core tier end-to-end ──────────────────────

async def test_store_relational_attribute_is_core(db, make_user):
    from memory.attribute_store import upsert_attribute
    from sqlalchemy import select
    from db.models import UserAttribute
    u = await make_user()
    await upsert_attribute(
        db, u.id,
        attribute_key="lifestyle_person_daughter",
        value="Mia, 3yo",
        category="lifestyle",
        source="conversation",
        confidence="confirmed",
    )
    row = (await db.execute(
        select(UserAttribute).where(
            UserAttribute.user_id == u.id,
            UserAttribute.attribute_key == "lifestyle_person_daughter",
        )
    )).scalar_one()
    assert row.relevance_tier == "core"


# ── Prompt ships the capture + weave + boundary-safety discipline ─────────────

def test_prompt_ships_relationship_memory():
    from core.prompts import build_arnie_system
    s = " ".join(build_arnie_system(platform="ios").split())
    assert "KNOWING THEM" in s
    assert "THEIR WHY" in s
    assert "BOUNDARIES ARE SACRED" in s
    assert "NEVER like a database" in s


def test_store_attribute_desc_mentions_relational_capture():
    from core.tools import ALL_TOOLS
    desc = next(t["description"] for t in ALL_TOOLS if t["name"] == "store_attribute")
    d = desc.lower()
    assert "people in their life" in d
    assert "deeper why" in d
    assert "boundaries" in d and "sensitiv" in d
