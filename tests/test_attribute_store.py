"""Tests for attribute-store write-path hardening.

F4 — canonical map collapses synonym keys.
F5 — dedup-on-write skips a long identical value under a different key.
F7 — prune_attributes caps active growth, protecting confirmed facts.
"""
from memory.attribute_store import canonicalize_key


def test_canonicalize_collapses_known_variants():
    # F4: differently-worded keys map to one canonical key
    assert canonicalize_key("cardio_preference") == "fitness_cardio_habits"
    assert canonicalize_key("Cardio Type") == "fitness_cardio_habits"
    assert canonicalize_key("motivated_by") == "behavior_motivation_driver"
    assert canonicalize_key("supplements") == "health_supplements"
    assert canonicalize_key("vitamins_minerals") == "health_supplements"
    assert canonicalize_key("wake_sleep_schedule") == "lifestyle_sleep_schedule"
    assert canonicalize_key("preferred_training_time") == "fitness_training_time"
    # unknown keys pass through unchanged (still allows novel custom fields)
    assert canonicalize_key("nutrition_calorie_range") == "nutrition_calorie_range"


async def test_dedup_on_write_skips_long_identical_value(db, make_user):
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="AS1", name="Test")
    long_val = "Fish oil, vitamin D, magnesium 120mg four times a week"
    await upsert_attribute(db, u.id, attribute_key="health_stack_a", value=long_val,
                           category="health", confidence="confirmed")
    # same long value, different key, same category → treated as a reworded dup, skipped
    await upsert_attribute(db, u.id, attribute_key="health_stack_b", value=long_val,
                           category="health", confidence="confirmed")
    keys = [a.attribute_key for a in await get_all_attributes(db, u.id)]
    assert "health_stack_a" in keys
    assert "health_stack_b" not in keys


async def test_dedup_on_write_allows_short_shared_values(db, make_user):
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="AS2", name="Test")
    # short identical values ('daily') are legitimately distinct facts → both kept
    await upsert_attribute(db, u.id, attribute_key="health_supplement_fish_oil", value="daily",
                           category="health", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="health_supplement_vitamin_d", value="daily",
                           category="health", confidence="confirmed")
    keys = [a.attribute_key for a in await get_all_attributes(db, u.id)]
    assert "health_supplement_fish_oil" in keys
    assert "health_supplement_vitamin_d" in keys


async def test_category_enforced_by_key_prefix_not_llm_category(db, make_user):
    """The key prefix is the source of truth for the lane — an LLM-supplied
    category that contradicts the prefix must NOT mislabel the fact."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="AS-tax", name="Test")
    # LLM mislabels a health_* supplement as 'nutrition' → prefix wins (health).
    await upsert_attribute(db, u.id, attribute_key="health_supplement_creatine",
                           value="5g every morning", category="nutrition", confidence="confirmed")
    row = next(a for a in await get_all_attributes(db, u.id)
               if a.attribute_key == "health_supplement_creatine")
    assert row.category == "health"
    # a key with NO recognized lane prefix still honors the caller's category.
    await upsert_attribute(db, u.id, attribute_key="freeform_note",
                           value="likes training fasted", category="lifestyle", confidence="confirmed")
    row2 = next(a for a in await get_all_attributes(db, u.id)
                if a.attribute_key == "freeform_note")
    assert row2.category == "lifestyle"


async def test_dedup_revives_retired_twin_instead_of_duplicating(db, make_user):
    """A fact re-asserted by synthesis whose only copy was retired (discontinued/
    decayed) revives that row rather than spawning a duplicate — kills the
    insert → consolidator-retires → insert oscillation."""
    from memory.attribute_store import upsert_attribute, get_all_attributes
    u = await make_user(telegram_id="AS-rev", name="Test")
    val = "Creatine, fish oil, and vitamin D every single morning"
    await upsert_attribute(db, u.id, attribute_key="health_stack_x", value=val,
                           category="health", confidence="confirmed")
    twin = next(a for a in await get_all_attributes(db, u.id)
                if a.attribute_key == "health_stack_x")
    twin.attribute_status = "discontinued"   # the nightly consolidator retires it
    await db.commit()
    # synthesis re-asserts the SAME value under a fresh key
    await upsert_attribute(db, u.id, attribute_key="health_stack_y", value=val,
                           category="health", confidence="confirmed")
    rows = await get_all_attributes(db, u.id)
    keys = [a.attribute_key for a in rows]
    assert "health_stack_y" not in keys                    # no duplicate inserted
    assert "health_stack_x" in keys                        # retired twin revived
    assert next(a for a in rows if a.attribute_key == "health_stack_x").attribute_status == "active"


async def test_prune_evicts_weakest_protects_confirmed(db, make_user):
    from memory.attribute_store import (upsert_attribute, get_all_attributes,
                                        prune_attributes)
    u = await make_user(telegram_id="AS3", name="Test")
    for i in range(3):
        await upsert_attribute(db, u.id, attribute_key=f"custom_conf_{i}", value=f"value c{i}",
                               category="custom", confidence="confirmed")
    for i in range(5):
        await upsert_attribute(db, u.id, attribute_key=f"custom_inf_{i}", value=f"value i{i}",
                               category="custom", confidence="inferred")
    for i in range(2):
        await upsert_attribute(db, u.id, attribute_key=f"custom_nv_{i}", value=f"value n{i}",
                               category="custom", confidence="needs_verification")

    pruned = await prune_attributes(db, u.id, cap=6)
    assert pruned == 4  # 10 active − cap 6
    remaining = await get_all_attributes(db, u.id)
    assert len(remaining) == 6
    # all confirmed survive; weakest (needs_verification) evicted first
    assert sum(1 for a in remaining if a.confidence == "confirmed") == 3
    assert all(a.confidence != "needs_verification" for a in remaining)


async def test_prune_noop_under_cap(db, make_user):
    from memory.attribute_store import upsert_attribute, prune_attributes
    u = await make_user(telegram_id="AS4", name="Test")
    await upsert_attribute(db, u.id, attribute_key="custom_a", value="value a",
                           category="custom", confidence="inferred")
    assert await prune_attributes(db, u.id, cap=40) == 0
