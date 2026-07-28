"""An answer option names the pack and what it costs, or it isn't answerable.

`_variant_options`' docstring has always promised "the flavours Open Food Facts
holds, WITH THEIR OWN NUMBERS". The loop kept `name` and dropped the calories;
`search_variants` kept the calories and dropped the pack size it had already
fetched — `_FIELDS` asks for `serving_size` and `quantity`, and `search()` maps
both. So the question could name flavours and never sizes, and the user got
"was that a single small…".

What this file does NOT pin is which packs are worth offering. A 24 oz share
bag is a real product and usually a silly thing to log in one sitting, and
which of those facts matters depends on the food and the occasion. That is
judgement about the world, not a rule this layer can hold — it supplies the
shelf; the sentence weighs it.
"""
import asyncio

from core.food_turn import _option_line, _variant_options


def _variant(name, pack="", cal=500):
    return {"name": name, "package_text": pack, "per100g": {"calories": cal}}


def test_a_pack_size_becomes_a_size_and_a_number():
    line = _option_line("Takis Fuego", _variant("Takis Fuego", "3 oz", 500))
    assert "3 oz" in line
    assert "425" in line, f"pack calories should be per-100g x mass: {line}"


def test_two_pack_sizes_are_distinguishable_by_their_cost():
    small = _option_line("Takis", _variant("Takis", "3 oz", 500))
    share = _option_line("Takis", _variant("Takis", "9.9 oz", 500))
    assert small != share
    assert "425" in small and "1403" in share


def test_an_unparseable_pack_keeps_the_name_and_claims_no_size():
    """Degrading to the name is honest. Inventing a serving is the failure the
    whole shelf lookup exists to avoid."""
    line = _option_line("Takis Blue Heat", _variant("Takis Blue Heat",
                                                    "family size", 500))
    assert line.startswith("Takis Blue Heat")
    assert "cal" not in line


def test_no_pack_text_at_all_is_just_the_name():
    assert _option_line("Takis Nitro", _variant("Takis Nitro")) == "Takis Nitro"


def test_the_shelf_too_wide_rule_still_withholds(monkeypatch):
    """Six or more variants means we are looking at a SAMPLE, and naming three
    of a dozen reads as the whole choice. Sizes do not change that."""
    import skills.nutrition.off as OFF

    async def _wide(name, limit=5):
        return [_variant(f"Flavour {i}", "3 oz", 500) for i in range(6)]

    monkeypatch.setattr(OFF, "search_variants", _wide)
    assert asyncio.run(_variant_options("Takis", True)) == ()


def test_search_variants_carries_the_size_it_already_fetched():
    """The field was requested, mapped by `search()`, and dropped by this
    builder. Pinned so the round trip is not paid for twice."""
    import inspect
    import skills.nutrition.off as OFF
    body = inspect.getsource(OFF.search_variants)
    assert "package_text" in body and "serving_text" in body
    assert "serving_size" in OFF._FIELDS and "quantity" in OFF._FIELDS
