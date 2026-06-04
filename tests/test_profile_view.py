"""Tests for the unified profile read model (memory/profile_view.py).

Confirms the merge of typed columns + learned attributes into one categorized
model: the Basics grid, declared-before-learned ordering, editability mirroring
the PATCH whitelist, and exclusion of discontinued attributes.
"""
from memory.profile_view import build_unified_profile, _height_str, _lbs


def test_height_and_lbs_helpers():
    assert _height_str(183.0) == "6'0\""
    assert _lbs(85.6) == 188.7
    assert _height_str(None) is None
    assert _lbs(None) is None


async def test_basics_and_category_merge(db, make_user):
    from db.models import UserPreferences
    from sqlalchemy import select
    from memory.attribute_store import upsert_attribute, get_all_attributes

    u = await make_user(
        telegram_id="UP1", name="Danny", age=31, sex="male", height_cm=183.0,
        current_weight_kg=85.6, goal_weight_kg=81.6, primary_goal="cut",
        training_experience="advanced", dietary_preferences="high-protein",
        injuries="ACL reconstruction",
    )
    prefs = (await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == u.id)
    )).scalar_one()
    prefs.calorie_target = 2000
    prefs.protein_target = 200
    prefs.coaching_style = "direct"
    prefs.accountability_level = "high"
    await db.commit()

    await upsert_attribute(db, u.id, attribute_key="health_supplement_zinc_mg",
                           value="50", unit="mg", display_name="Zinc",
                           category="health", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="fitness_workout_split",
                           value="PPL", display_name="Workout split",
                           category="fitness", confidence="confirmed")

    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, prefs, attrs)

    # Basics: short scalars, in order
    assert [b["label"] for b in m["basics"]] == \
        ["Name", "Age", "Sex", "Height", "Current", "Goal"]
    sex = next(b for b in m["basics"] if b["label"] == "Sex")
    assert sex["edit_field"] is None  # display-only (not in PATCH whitelist)
    cur = next(b for b in m["basics"] if b["label"] == "Current")
    assert cur["edit_field"] == "current_weight_lbs"
    assert cur["value"] == "188.7 lbs"

    # Categories: goals first; declared merged before learned
    assert list(m["categories"].keys())[0] == "goals"
    health = [f["label"] for f in m["categories"]["health"]]
    assert health[0] == "Injuries / limitations"
    assert "Zinc" in health
    fit = [f["label"] for f in m["categories"]["fitness"]]
    assert fit.index("Experience") < fit.index("Workout split")

    # Declared facts editable + column-origin; learned not editable + attribute-origin
    inj = next(f for f in m["categories"]["health"] if f["label"].startswith("Injuries"))
    assert inj["edit_field"] == "injuries" and inj["origin"] == "column"
    zinc = next(f for f in m["categories"]["health"] if f["label"] == "Zinc")
    assert zinc["edit_field"] is None and zinc["origin"] == "attribute"


async def test_discontinued_attributes_excluded(db, make_user):
    from memory.attribute_store import upsert_attribute, get_all_attributes

    u = await make_user(telegram_id="UP2", name="Test")
    await upsert_attribute(db, u.id, attribute_key="health_supplement_x", value="1",
                           display_name="Supplement X", category="health",
                           confidence="confirmed", attribute_status="discontinued")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    health = m["categories"].get("health", [])
    assert all(f["label"] != "Supplement X" for f in health)


def test_dedupe_labels_strips_redundant_prefixes():
    from memory.profile_view import _dedupe_labels

    def mk(lbl):
        return {"label": lbl, "origin": "attribute"}

    # leading word == category → stripped
    fitness = [mk("Fitness Cardio Preference"), mk("Fitness Dislikes")]
    _dedupe_labels(fitness, "fitness")
    assert [f["label"] for f in fitness] == ["Cardio Preference", "Dislikes"]

    # shared sub-prefix across 2+ learned facts → stripped (even if != category)
    custom = [mk("Psychology Frustrated By"), mk("Psychology Motivated By"), mk("Recovery Limiter")]
    _dedupe_labels(custom, "custom")
    assert [f["label"] for f in custom] == ["Frustrated By", "Motivated By", "Recovery Limiter"]

    # declared (column) facts and single non-matching learned facts are untouched
    mixed = [{"label": "Injuries / limitations", "origin": "column"}, mk("Zinc")]
    _dedupe_labels(mixed, "health")
    assert [f["label"] for f in mixed] == ["Injuries / limitations", "Zinc"]


async def test_empty_user_still_has_name_basic(db, make_user):
    """A sparse user (just a name) still produces a Basics entry — the profile
    never renders fully empty for an onboarded user."""
    u = await make_user(telegram_id="UP3", name="Jo")
    m = build_unified_profile(u, None, [])
    assert any(b["label"] == "Name" and b["value"] == "Jo" for b in m["basics"])
