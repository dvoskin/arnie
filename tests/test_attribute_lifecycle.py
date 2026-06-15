"""Self-healing lifecycle (B) — decay stale facts to archive; prune as backstop."""
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_

from db.models import UserAttribute
from memory.attribute_store import (
    upsert_attribute, decay_stale_attributes, prune_attributes, get_all_attributes,
)


async def _age_row(db, user_id, key, days):
    row = (await db.execute(select(UserAttribute).where(and_(
        UserAttribute.user_id == user_id, UserAttribute.attribute_key == key,
    )))).scalar_one()
    row.updated_at = datetime.now(timezone.utc) - timedelta(days=days)
    await db.commit()


async def test_decay_archives_stale_contextual_only(db, make_user):
    u = await make_user(telegram_id="DEC1", name="Test")
    # stale contextual (conversation) → should decay
    await upsert_attribute(db, u.id, attribute_key="health_old_note",
                           value="mentioned a tweak once", category="health",
                           relevance_tier="contextual", source="conversation")
    # stale contextual but USER-STATED → protected
    await upsert_attribute(db, u.id, attribute_key="health_user_note",
                           value="explicitly told us this", category="health",
                           relevance_tier="contextual", source="user_stated")
    # stale CORE → protected (identity)
    await upsert_attribute(db, u.id, attribute_key="fitness_training_split",
                           value="PPL", category="fitness", relevance_tier="core",
                           source="conversation")
    # fresh contextual → not stale
    await upsert_attribute(db, u.id, attribute_key="health_fresh_note",
                           value="said this today", category="health",
                           relevance_tier="contextual", source="conversation")
    for k in ("health_old_note", "health_user_note", "fitness_training_split"):
        await _age_row(db, u.id, k, 60)

    n = await decay_stale_attributes(db, u.id, days=45)
    assert n == 1

    tiers = {a.attribute_key: a.relevance_tier for a in await get_all_attributes(db, u.id)}
    assert tiers["health_old_note"] == "archive"          # decayed
    assert tiers["health_user_note"] == "contextual"      # user_stated protected
    assert tiers["fitness_training_split"] == "core"      # core protected
    assert tiers["health_fresh_note"] == "contextual"     # fresh, untouched


async def test_prune_ignores_archive_and_protects_identity(db, make_user):
    u = await make_user(telegram_id="PRN1", name="Test")
    # two protected: a core fact and a user-stated fact
    await upsert_attribute(db, u.id, attribute_key="fitness_training_split",
                           value="PPL", category="fitness", relevance_tier="core",
                           source="conversation")
    await upsert_attribute(db, u.id, attribute_key="nutrition_diet_style",
                           value="keto", category="nutrition", source="user_stated")
    # three evictable contextual conversation facts
    for i in range(3):
        await upsert_attribute(db, u.id, attribute_key=f"custom_filler_{i}",
                               value=f"filler {i}", category="custom",
                               relevance_tier="contextual", source="conversation",
                               confidence="inferred")
    # one archived fact — must not count toward the cap
    await upsert_attribute(db, u.id, attribute_key="custom_archived",
                           value="old", category="custom", relevance_tier="archive",
                           source="conversation")

    # cap=4: non-archive=5 (2 protected + 3 filler) → evict 1 (the weakest/oldest filler)
    n = await prune_attributes(db, u.id, cap=4)
    assert n == 1

    active = {a.attribute_key for a in await get_all_attributes(db, u.id)}
    assert "fitness_training_split" in active and "nutrition_diet_style" in active
    assert "custom_archived" in active  # archive never evicted, never counted
    remaining_filler = [k for k in active if k.startswith("custom_filler_")]
    assert len(remaining_filler) == 2
