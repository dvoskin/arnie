"""⭐ STEP 6 — the resolved identity becomes the key to durable food memory.

This is where the interpretation boundary stops being an annotation and starts
being worth something. The measured payoff was never the artifact rung — only 1
of 31 resolved entities reaches it — it is MEMORY, which carries 44.6% of real
production and which the §1a containment currently makes unreachable for every
non-English food.

    Помидор                       + tomato            -> 'tomato'
    Творог 2%                     + tvorog 2 percent  -> 'tvorog 2 percent'
    Кукуруза варёная (2 початка)  + corn              -> 'corn'

Those three shared the key `'2'` before, and one of them priced a real meal from
another. They cannot now, because the key is what the food MEANS.

⭐⭐ ONE KEY FUNCTION FOR READ AND WRITE, IN BOTH LANES. A reader on the
canonical key and a writer on the legacy one would cache every food where nobody
looks for it — a quieter version of the same defect, and one that would look
like a cache-miss problem rather than an identity problem.

⭐⭐⭐ AND WITHOUT AN IDENTITY IT IS BYTE-IDENTICAL TO TODAY. `memory_key` falls
straight through to `normalize_name`, so with `ENTITY_RESOLUTION_MODE=off` — the
default — nothing in this file changes any behaviour at all. That is the whole
monotonicity guarantee, expressed at the last layer that could have broken it.
"""
from __future__ import annotations

import inspect

import pytest

from core.food_intelligence import memory_key, normalize_name

CORN = "Кукуруза варёная (2 початка)"
TVOROG = "Творог 2%"
EGGS = "Омлет из 2 яиц"


# ── the key ───────────────────────────────────────────────────────────────────

def test_without_an_identity_the_key_is_exactly_todays():
    """The default path, and the one that must not move. Asserted against
    `normalize_name` itself rather than against literals, so the two cannot
    drift apart in a later edit."""
    for name in (CORN, TVOROG, "Chicken breast", "White rice", "", "  "):
        assert memory_key(name, "") == normalize_name(name)
        assert memory_key(name) == normalize_name(name)


def test_a_resolved_identity_makes_a_non_english_food_addressable():
    """⭐ THE 300 FOODS THE CONTAINMENT COULD ONLY MAKE SAFE. `Помидор`
    normalizes to nothing, so it has never been able to hold a memory row; with
    an identity it addresses one."""
    from core.food_intelligence import memory_key_is_addressable

    assert normalize_name("Помидор") == ""
    assert not memory_key_is_addressable(memory_key("Помидор", ""))
    assert memory_key("Помидор", "tomato") == "tomato"
    assert memory_key_is_addressable(memory_key("Помидор", "tomato"))


def test_the_colliding_foods_can_no_longer_collide():
    """⛔ THE PRODUCTION DEFECT, CLOSED AT THE KEY RATHER THAN GUARDED AT THE
    DOOR. All three normalized to `'2'`; with identities they are three keys."""
    assert normalize_name(CORN) == normalize_name(TVOROG) == normalize_name(EGGS)

    keyed = {memory_key(CORN, "corn"), memory_key(TVOROG, "tvorog 2 percent"),
             memory_key(EGGS, "omelette")}
    assert len(keyed) == 3


def test_one_food_named_in_two_languages_is_one_memory():
    """⭐⭐ THE UNIFICATION, WHICH IS THE POINT AND NOT A SIDE EFFECT. A user
    who logs `Помидор` on Monday and `Tomato` on Friday has logged one food, and
    before this they had two rows or none."""
    assert memory_key("Помидор", "tomato") == memory_key("Tomato", "tomato")


def test_a_letterless_identity_falls_through_rather_than_addressing_anything():
    """The containment is not bypassed by arriving through the new door. An
    entity that somehow carries no letters is no more addressable than a legacy
    key that carries none."""
    assert memory_key(TVOROG, "2") == normalize_name(TVOROG)
    assert memory_key(TVOROG, "") == normalize_name(TVOROG)
    assert memory_key("Chicken breast", "%%%") == "chicken breast"


def test_the_identity_is_normalized_before_it_is_used_as_a_key():
    """Two spellings of one entity must not become two rows — the same failure
    the DISTINCT reuse step exists to prevent, one layer down."""
    assert memory_key("Творог", "Tvorog") == memory_key("Творог", "tvorog")


# ── both lanes, both directions ───────────────────────────────────────────────

def test_the_legacy_lane_reads_and_writes_through_the_shared_key():
    """⚠ THE READ AND THE WRITE SHARE ONE `name_norm` IN THAT FUNCTION, so
    binding it once is what keeps them symmetric. Asserted on the source
    because the alternative is exercising a 6,000-line executor to observe a
    variable assignment."""
    from handlers import tool_executor

    source = inspect.getsource(tool_executor.fetch_candidates)
    assert "_memory_key(food_name" in source, (
        "the legacy lane stopped using the shared key — a reader on the "
        "canonical key beside a writer on the legacy one caches every food "
        "where nobody looks for it")
    assert "normalize_name(food_name)" not in source


def test_the_canonical_lane_passes_the_identity_into_the_memory_rung():
    from core import canonical_pricing_inputs as cpi

    assert "canonical_entity_id" in inspect.getsource(cpi.assemble)
    assert "memory_key" in inspect.getsource(cpi._memory)


def test_the_interpreter_carries_the_identity_onto_the_call():
    """Without this the stamp dies at the plan boundary and every consumer
    below falls through forever — a feature that is wired at both ends and
    connected nowhere."""
    from core import food_turn

    source = inspect.getsource(food_turn._log_call)
    assert 'inp["canonical_entity_id"] = _entity' in source


def test_an_unstamped_item_adds_no_key_to_the_call():
    """With the flag off nothing is stamped, so `log_food` must look exactly as
    it does today — no empty field, no `None`, no new key at all."""
    from core.food_turn import _log_call

    call = _log_call({"food": "Chicken breast", "amount": 1, "unit": "breast"})
    assert "canonical_entity_id" not in call["input"]


def test_a_stamped_item_carries_its_identity():
    from core.food_turn import _log_call

    call = _log_call({"food": "Помидор", "amount": 2, "unit": "шт",
                      "canonical_entity_id": "tomato"})
    assert call["input"]["canonical_entity_id"] == "tomato"
