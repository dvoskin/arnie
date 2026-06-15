"""Salience layer — relevance scoring + spotlight/recall in the AI profile block."""
import pytest

from memory.salience import score_attribute, select_relevant
from memory.attribute_store import upsert_attribute, get_attributes_for_context


class _Attr:
    """Lightweight stand-in for a UserAttribute row (scorer only reads fields)."""
    def __init__(self, key, value, display=None, tier="contextual"):
        self.attribute_key = key
        self.value = value
        self.display_name = display
        self.relevance_tier = tier
        self.updated_at = None
        self.created_at = None


def test_score_matches_topic_via_synonyms():
    injury = _Attr("health_injuries", "ACL and meniscus reconstruction 2023")
    # "knee" never appears in the attribute, but both map to concept "injury"
    assert score_attribute("my knee feels off today", injury) > 0
    assert score_attribute("what should I eat for lunch", injury) == 0


def test_cardio_message_matches_cardio_attr():
    cardio = _Attr("fitness_cardio_habits", "Spin Zone 1-2 preferred, incline walk")
    diet = _Attr("nutrition_diet_style", "flexible dieting, tracks protein")
    rows = [cardio, diet]
    picked = select_relevant("how much cardio should I do today", rows)
    assert cardio in picked and diet not in picked


def test_select_relevant_empty_message_returns_nothing():
    rows = [_Attr("fitness_cardio_habits", "spin bike")]
    assert select_relevant("", rows) == []


async def test_spotlight_appears_for_matching_message(db, make_user):
    u = await make_user(telegram_id="SAL1", name="Test")
    await upsert_attribute(db, u.id, attribute_key="fitness_cardio_habits",
                           value="Spin Zone 1-2 preferred, incline walk secondary",
                           category="fitness", confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="nutrition_diet_style",
                           value="flexible dieting, tracks calories and protein",
                           category="nutrition", confidence="confirmed")
    block = await get_attributes_for_context(db, u.id, "what cardio should I do")
    assert "[RELEVANT TO THIS MESSAGE" in block
    # the spotlight names the cardio fact, not the diet one
    spot = block.split("[RELEVANT TO THIS MESSAGE")[1].split("[FITNESS]")[0]
    assert "Spin" in spot

    # empty message → no spotlight, full picture preserved (backward compatible)
    plain = await get_attributes_for_context(db, u.id, "")
    assert "[RELEVANT TO THIS MESSAGE" not in plain
    assert "Spin" in plain and "flexible dieting" in plain


async def test_archived_fact_recalled_on_topic_match(db, make_user):
    u = await make_user(telegram_id="SAL2", name="Test")
    # an archived fact is held out of the default block...
    await upsert_attribute(db, u.id, attribute_key="nutrition_alcohol_habits",
                           value="occasional Duvel Belgian strong ale",
                           category="nutrition", relevance_tier="archive",
                           confidence="confirmed")
    await upsert_attribute(db, u.id, attribute_key="nutrition_diet_style",
                           value="flexible dieting", category="nutrition",
                           confidence="confirmed")
    # ...until the topic matches, then it's recalled
    on_topic = await get_attributes_for_context(db, u.id, "can I have a beer tonight")
    assert "[RECALLED" in on_topic and "Duvel" in on_topic

    off_topic = await get_attributes_for_context(db, u.id, "what should I train today")
    assert "Duvel" not in off_topic
