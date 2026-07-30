"""The answer-apply shadow, measured end to end through the real answer turn.

`FOOD_ANSWER_APPLY` is a WRITE path and ships shadowed, like `FOOD_FAST_PATH`:
off, it computes what it would have committed, logs the comparison and changes
nothing. The rule for throwing it is agreement measured on production traffic.

Before the §8.1 join that measurement was meaningless. Every stored resolution
carried `candidate_products: null`, so `commit_from_answer` returned None every
time and the shadow line was never emitted at all — the flag could not have
fired even switched on, and its "agreement rate" was the agreement rate of a
path that never ran.

These tests say what the shadow must now be: with a resolution the REAL ask
produced, an answering turn computes a real price, logs it, and — with the flag
off — still writes nothing. The payload is not hand-built; it comes out of
`plan_turn` exactly as the ask stores it on the pending row.

They do not decide whether the flag may be thrown. That is a production number.
"""
import pytest

from skills.nutrition import off

_TURN = "test:answer:1"

_VARIANTS = [
    {"code": "7340001111111",
     "product_name": "Barebells Salty Peanut Protein Bar",
     "brands": "Barebells", "serving_size": "55 g", "quantity": "55 g",
     "nutriments": {"energy-kcal_100g": 364, "proteins_100g": 36,
                    "carbohydrates_100g": 27, "fat_100g": 15}},
    {"code": "7340002222222",
     "product_name": "Barebells Cookies and Cream Protein Bar",
     "brands": "Barebells", "serving_size": "55 g", "quantity": "55 g",
     "nutriments": {"energy-kcal_100g": 395, "proteins_100g": 29,
                    "carbohydrates_100g": 35, "fat_100g": 16}},
]


class _User:
    id = 999
    first_name = "Test"
    weight_kg = 84.0
    height_cm = 180.0
    age = 34
    sex = "male"

    class preferences:
        food_logging_mode = "moderate"
        calorie_target = 2165
        protein_target = 180


@pytest.fixture
async def staged_prior(monkeypatch):
    """The pending row an ask would actually have stored.

    Produced by running the ask half for real — variant fetch, candidate
    collection, `plan_turn` — with the fakes at the HTTP boundary, then encoded
    with the same codec the ask return uses.
    """
    import core.food_turn as FT
    import handlers.tool_executor as TE
    from core.food_pipeline import plan_turn
    from core.turn_identity import CURRENT_TURN_ID
    from skills.nutrition.staged_codec import encode_items

    class _Resp:
        status_code = 200

        def json(self):
            return {"products": _VARIANTS}

    class _Client:
        async def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(off, "_client", lambda: _Client())
    monkeypatch.setenv("OFF_ENABLED", "true")
    FT._SPREAD_CACHE.clear()
    TE._INFLIGHT_FETCHES.clear()

    data = {"action": "log", "items": [
        {"food": "Barebells salty peanut protein bar", "brand": "Barebells",
         "branded": True, "calories": 200, "protein": 20, "carbs": 15,
         "fat": 8}]}

    token = CURRENT_TURN_ID.set(_TURN)
    try:
        spreads = await FT._variant_spreads(data, mode="moderate",
                                            targets=None)
        decision = plan_turn(data, turn_id=_TURN, message="had a barebells bar",
                             mode="moderate", variant_spreads=spreads,
                             item_candidates=FT._ask_candidates(data))
    finally:
        CURRENT_TURN_ID.reset(token)
        FT._SPREAD_CACHE.clear()
        TE._INFLIGHT_FETCHES.clear()

    item = decision.staged_items[0]
    assert item.candidate_products, "the ask stored no products to shadow"
    yield {
        "original": "had a barebells bar",
        "question": "How much of the bar did you have?",
        "kind": "clarify", "ask_count": 1,
        "response_schema": "quantity",
        "staged_item_id": item.staged_item_id,
        "staged_items": encode_items([item]),
        "items": [dict(data["items"][0])],
    }


def _shadow_lines(caplog):
    return [r.message for r in caplog.records
            if "event=answer_apply" in r.message]


async def test_the_shadow_now_has_a_price_to_report(staged_prior, caplog,
                                                    monkeypatch):
    """The measurement the flag's promotion depends on. It reported nothing at
    all before the join, because there was nothing stored to price from."""
    import core.food_turn as FT

    monkeypatch.delenv("FOOD_ANSWER_APPLY", raising=False)
    caplog.set_level("INFO")
    await FT.run("about 55 grams", _User(), prior=staged_prior)

    lines = _shadow_lines(caplog)
    assert lines, "the answer turn computed no shadow at all"
    line = lines[0]
    assert "outcome=shadow" in line
    assert "buildable=True" in line
    # A REAL number, from the shelf. `cal=None` is what the whole 18h
    # production window reported, and it is what an inert join looks like.
    assert "cal=None" not in line
    assert "cal=200" in line          # 364 cal/100 g over 55 g


async def test_the_shadow_does_not_write(staged_prior, caplog, monkeypatch):
    """Shadow means shadow. With the flag off the answering turn may compute
    the commit and may log it, and may not return it as a write."""
    import core.food_turn as FT

    monkeypatch.delenv("FOOD_ANSWER_APPLY", raising=False)
    caplog.set_level("INFO")
    result = await FT.run("about 55 grams", _User(), prior=staged_prior)

    assert _shadow_lines(caplog), "nothing was shadowed"
    # No model is configured in tests, so the interpreter pass this falls
    # through to produces nothing — which is the point: the ONLY way a write
    # could appear here is the shadowed path having committed.
    assert result is None or not result.get("tool_calls")


async def test_the_flag_commits_exactly_what_the_shadow_measured(
        staged_prior, caplog, monkeypatch):
    """The two must be the same computation, or the agreement rate is measuring
    something other than what would ship."""
    import core.food_turn as FT

    caplog.set_level("INFO")
    monkeypatch.delenv("FOOD_ANSWER_APPLY", raising=False)
    await FT.run("about 55 grams", _User(), prior=staged_prior)
    shadowed = _shadow_lines(caplog)[0]

    caplog.clear()
    monkeypatch.setenv("FOOD_ANSWER_APPLY", "true")
    result = await FT.run("about 55 grams", _User(), prior=staged_prior)

    assert result is not None and result["action"] == "log"
    call = result["tool_calls"][0]
    assert call["name"] == "log_food"
    committed = call["input"]
    assert f"cal={committed['calories']}" in shadowed
    assert "outcome=committed" in _shadow_lines(caplog)[0]
    # The narration is left to the composer and its deterministic floor — a
    # third renderer here would be an English-only one (cause E).
    assert result["say"] == ""


async def test_an_answer_that_changes_the_food_is_not_shadowed(
        staged_prior, caplog, monkeypatch):
    """An answer replacing the product means the stored basis describes
    something else. Declining is correct, and a decline is not a shadow with a
    missing price — it emits nothing."""
    import core.food_turn as FT

    monkeypatch.delenv("FOOD_ANSWER_APPLY", raising=False)
    caplog.set_level("INFO")
    prior = dict(staged_prior, response_schema="product_selection",
                 options=["Salty Peanut", "Cookies and Cream"])
    await FT.run("the cookies and cream one", _User(), prior=prior)
    assert not _shadow_lines(caplog)
