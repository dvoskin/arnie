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

    await upsert_attribute(db, u.id, attribute_key="custom_cold_shower", value="10 min",
                           display_name="Cold shower", category="custom", confidence="inferred")

    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, prefs, attrs)

    # Basics: short scalars, in order. Goal/targets intentionally NOT in basics
    # — they live in the dedicated "Goals & targets" card on the profile tab.
    assert [b["label"] for b in m["basics"]] == \
        ["Name", "Age", "Sex", "Height", "Current weight"]
    cur = next(b for b in m["basics"] if b["label"] == "Current weight")
    assert cur["edit_field"] == "current_weight_lbs" and cur["value"] == "188.7 lbs"

    std = m["standard"]

    # Goals category now holds LEARNED goal facts only (why, timeline). The
    # structured fields (primary_goal, calorie_target, etc.) moved to the
    # dedicated "Goals & targets" card. Both learned slots are hide_empty
    # and unpopulated here, so std["goals"] is an empty list for this user.
    assert std["goals"] == []

    # Health: injuries column slot (editable) + supplements aggregate (zinc as a chip)
    health = {s["label"]: s for s in std["health"]}
    assert health["Injuries / limitations"]["origin"] == "column"
    assert health["Injuries / limitations"]["edit_field"] == "injuries"
    supps = health["Supplements"]
    assert supps["filled"] and any("Zinc" in c for c in supps["chips"])

    # Fitness: training split filled via ALIAS key; experience via column; cardio empty
    fit = {s["label"]: s for s in std["fitness"]}
    assert fit["Training split"]["filled"] and fit["Training split"]["origin"] == "attribute"
    assert fit["Experience"]["origin"] == "column" and fit["Experience"]["value"] == "Advanced"
    assert fit["Favorite cardio"]["filled"] is False  # always-present "learning" slot

    # Behavior: coaching style column-backed + editable
    beh = {s["label"]: s for s in std["behavior"]}
    assert beh["Coaching style"]["value"] == "Direct"
    assert beh["Coaching style"]["edit_field"] == "coaching_style"

    # Non-standard learned attribute falls through to Custom
    assert any(c["label"] == "Cold shower" for c in m["custom"])


async def test_discontinued_attributes_excluded(db, make_user):
    from memory.attribute_store import upsert_attribute, get_all_attributes

    u = await make_user(telegram_id="UP2", name="Test")
    await upsert_attribute(db, u.id, attribute_key="health_supplement_x", value="1",
                           display_name="Supplement X", category="health",
                           confidence="confirmed", attribute_status="discontinued")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    # discontinued supplement: not in the supplements aggregate, not in custom
    supps = next(s for s in m["standard"]["health"] if s["label"] == "Supplements")
    assert supps["filled"] is False
    assert all(c["label"] != "Supplement X" for c in m["custom"])


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


async def test_staple_foods_derived_when_no_attribute(db, make_user):
    """The Staple foods slot fills from a passed-in derived value (mined from
    logs) when no explicit learned attribute exists."""
    u = await make_user(telegram_id="UP4", name="Test")
    m = build_unified_profile(u, None, [], derived={"nutrition_staple_foods": ["chicken", "rice"]})
    fav = next(s for s in m["standard"]["nutrition"] if s["label"] == "Staple foods")
    assert fav["filled"] and fav["origin"] == "derived"
    assert fav["chips"] == ["chicken", "rice"]


async def test_empty_user_still_has_name_basic(db, make_user):
    """A sparse user (just a name) still produces a Basics entry — the profile
    never renders fully empty for an onboarded user."""
    u = await make_user(telegram_id="UP3", name="Jo")
    m = build_unified_profile(u, None, [])
    assert any(b["label"] == "Name" and b["value"] == "Jo" for b in m["basics"])


async def test_staple_foods_union_does_not_shrink(db, make_user):
    """A single learned staple food must NOT replace the richer derived list —
    they're unioned, with the behavioral (derived) signal leading. Regression
    for the 'favorite foods 5 → 1' report."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP5", name="Test")
    await upsert_attribute(db, u.id, attribute_key="nutrition_staple_foods",
                           value="protein bar", category="nutrition", confidence="inferred")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs,
                              derived={"nutrition_staple_foods":
                                       ["chicken", "rice", "oats", "yogurt", "eggs"]})
    fav = next(s for s in m["standard"]["nutrition"] if s["label"] == "Staple foods")
    assert fav["filled"]
    assert "chicken" in fav["chips"] and "protein bar" in fav["chips"]
    assert len(fav["chips"]) >= 5
    # the learned attribute is consumed by the slot, not duplicated into Custom
    assert all(c["label"].lower() != "staple foods" for c in m["custom"])


async def test_concept_variants_fold_into_standard_slots(db, make_user):
    """Differently-worded variants fold into the matching standard slot instead
    of fragmenting into Custom (cardio_*, vitamins, motivated_by)."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP6", name="Test")
    # Both cardio variants canonicalize to fitness_cardio_habits — they collapse
    # to ONE row of truth (latest write wins) instead of fragmenting into 3 rows.
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_preference",
                           value="Spin bike", display_name="Cardio Preference",
                           category="fitness", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_type",
                           value="Spin bike · incline walk", display_name="Cardio Type",
                           category="fitness", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="motivated_by",
                           value="Rep PRs", display_name="Motivated By",
                           category="custom", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="health_vitamins_minerals",
                           value="ferritin", display_name="Vitamins / minerals",
                           category="health", confidence="confirmed")
    attrs = await get_all_attributes(db, u.id)
    # the two cardio variants collapsed into a single canonical row
    assert len([a for a in attrs if a.attribute_key == "fitness_cardio_habits"]) == 1
    assert not [a for a in attrs if a.attribute_key in
                ("fitness_cardio_preference", "fitness_cardio_type")]
    m = build_unified_profile(u, None, attrs)

    fit = {s["label"]: s for s in m["standard"]["fitness"]}
    assert fit["Favorite cardio"]["filled"]
    assert "incline walk" in " ".join(fit["Favorite cardio"]["chips"])

    beh = {s["label"]: s for s in m["standard"]["behavior"]}
    assert beh["Motivation"]["filled"] and "Rep PRs" in beh["Motivation"]["value"]

    health = {s["label"]: s for s in m["standard"]["health"]}
    assert health["Supplements"]["filled"]

    # none of the folded variants remain in Custom
    custom_labels = {c["label"] for c in m["custom"]}
    assert not ({"Cardio Preference", "Cardio Type", "Motivated By",
                 "Vitamins / minerals"} & custom_labels)


async def test_distinct_facts_stay_in_custom(db, make_user):
    """Facts that only *relate* to a slot but carry distinct info are NOT folded
    away — e.g. an actual-intake 'Calorie Range' stays separate from the target."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP9", name="Test")
    await upsert_attribute(db, u.id, attribute_key="nutrition_calorie_range",
                           value="1700-1900", display_name="Calorie Range",
                           category="nutrition", confidence="confirmed")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    assert any(c["label"] == "Calorie Range" for c in m["custom"])


async def test_custom_items_are_removable_with_key(db, make_user):
    """Custom items expose attribute_key + removable for the soft-hide control."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP7", name="Test")
    await upsert_attribute(db, u.id, attribute_key="custom_cold_shower", value="10 min",
                           display_name="Cold shower", category="custom", confidence="inferred")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    cs = next(c for c in m["custom"] if c["label"] == "Cold shower")
    assert cs["key"] == "custom_cold_shower" and cs["removable"] is True


async def test_set_attribute_status_soft_hides(db, make_user):
    """set_attribute_status('discontinued') drops an attribute from active reads."""
    from memory.attribute_store import (upsert_attribute, get_all_attributes,
                                         set_attribute_status)
    u = await make_user(telegram_id="UP8", name="Test")
    await upsert_attribute(db, u.id, attribute_key="custom_foo", value="bar",
                           display_name="Foo", category="custom", confidence="inferred")
    assert any(a.attribute_key == "custom_foo" for a in await get_all_attributes(db, u.id))
    assert await set_attribute_status(db, u.id, "custom_foo", "discontinued") is True
    assert all(a.attribute_key != "custom_foo" for a in await get_all_attributes(db, u.id))
    assert await set_attribute_status(db, u.id, "nonexistent_key", "discontinued") is False


async def test_supplements_prefer_per_item_over_aggregate(db, make_user):
    """Structured per-item supplement keys are the display; an aggregate
    'supplements: a, b, c' restatement is folded away, not shown as a dup chip.
    The verbose 'Health Supplement ' prefix is stripped."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP10", name="Test")
    await upsert_attribute(db, u.id, attribute_key="health_supplement_fish_oil",
                           value="daily", display_name="Health Supplement Fish Oil",
                           category="health", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="health_aggregate_note",
                           value="Fish oil, vitamin D, magnesium daily",
                           display_name="Supplements", category="health", confidence="confirmed")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    supps = next(s for s in m["standard"]["health"] if s["label"] == "Supplements")
    assert any("Fish Oil" in c for c in supps["chips"])
    assert not any("vitamin D, magnesium" in c for c in supps["chips"])
    assert not any(c.startswith("Health Supplement") for c in supps["chips"])
    assert all(c["label"] != "Supplements" for c in m["custom"])


async def test_cardio_canonical_only_when_present(db, make_user):
    """When a canonical cardio attribute exists, variant rephrasings are folded
    away (covered), NOT unioned into wordy extra chips."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP11", name="Test")
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_habits",
                           value="Spin, incline walk", category="fitness", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_pref_note",
                           value="Spin bike 14-30 min, tends to add when frustrated",
                           display_name="Cardio Preference", category="fitness", confidence="inferred")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    cardio = next(s for s in m["standard"]["fitness"] if s["label"] == "Favorite cardio")
    assert cardio["chips"] == ["Spin", "incline walk"]
    assert all(c["label"] != "Cardio Preference" for c in m["custom"])


def test_split_list_preserves_thousands_separator():
    """A thousands comma in a number must NOT fracture a list value."""
    from memory.profile_view import _split_list
    assert _split_list("9,200 steps/day") == ["9,200 steps/day"]
    assert _split_list("running, walking, cycling") == ["running", "walking", "cycling"]
    assert _split_list("averages 9,200 steps/day") == ["averages 9,200 steps/day"]
    assert _split_list("Spin, 1,500 cal burn") == ["Spin", "1,500 cal burn"]


async def test_steps_separated_from_favorite_cardio(db, make_user):
    """Regression (Ryan): a step count mis-filed under the cardio key must surface
    as 'Daily steps', NOT as comma-split chips under 'Favorite cardio'."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP12", name="Ryan")
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_habits",
                           value="averages 9,200 steps/day", category="fitness",
                           confidence="inferred")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    fit = m["standard"]["fitness"]

    steps = next(s for s in fit if s["label"] == "Daily steps")
    assert steps["filled"] is True
    assert "9,200 steps/day" in steps["value"]      # number intact, no fracture
    assert "averages" not in steps["value"].lower()  # leading qualifier stripped

    cardio = next(s for s in fit if s["label"] == "Favorite cardio")
    assert cardio["filled"] is False                 # no step fragments leak in
    assert cardio["chips"] == []


async def test_real_cardio_activities_still_show(db, make_user):
    """A genuine cardio-activities value still populates Favorite cardio, and no
    empty Daily steps slot appears (hide_empty)."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="UP13", name="Test")
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_habits",
                           value="walking, cycling", category="fitness", confidence="confirmed")
    attrs = await get_all_attributes(db, u.id)
    m = build_unified_profile(u, None, attrs)
    fit = m["standard"]["fitness"]
    cardio = next(s for s in fit if s["label"] == "Favorite cardio")
    assert cardio["chips"] == ["walking", "cycling"]
    assert all(s["label"] != "Daily steps" for s in fit)  # hidden when no steps
