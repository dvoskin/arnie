"""Fast paths, caching and the turn budget (PR #30).

The three optimizations share one property, and every test here is ultimately
about it: **none of them may change an answer.** A fast path that logs a
different meal, a cache that serves a stale one, or a deadline that turns a slow
lookup into a lost log are all worse than the latency they were added to remove.

So the tests are weighted heavily toward refusal and equivalence rather than
toward speed. Speed is easy to verify and easy to notice when it regresses; a
silently wrong log is neither.
"""
import time

import pytest

from core import deadline
from core.food_fast_path import parse, refusal_reason
from core.food_fast_path import refusal_reason
from skills.nutrition import cache


@pytest.fixture(autouse=True)
def _clean():
    cache.CACHE.clear()
    deadline.CURRENT_DEADLINE.set(None)
    yield
    cache.CACHE.clear()
    deadline.CURRENT_DEADLINE.set(None)


# ── the fast path accepts only what has one reading ───────────────────────────
@pytest.mark.parametrize("message,expected", [
    ("150g chicken breast", [("chicken breast", 150.0, "g")]),
    ("2 eggs", [("eggs", 2.0, "piece")]),
    ("three eggs", [("eggs", 3.0, "piece")]),
    ("500ml milk", [("milk", 500.0, "ml")]),
    ("6 oz salmon", [("salmon", 6.0, "oz")]),
    ("1 cup oats", [("oats", 1.0, "cup")]),
    ("200g chicken and 150g rice",
     [("chicken", 200.0, "g"), ("rice", 150.0, "g")]),
    ("2 slices bread, 30g peanut butter",
     [("bread", 2.0, "slice"), ("peanut butter", 30.0, "g")]),
    # The word after the number is not a unit, so it belongs to the food.
    # Dropping it would log "2 thighs" as "2 chicken".
    ("2 chicken thighs", [("chicken thighs", 2.0, "piece")]),
])
def test_the_fast_path_parses_unambiguous_logs(message, expected):
    data = parse(message)
    assert data is not None, message
    assert data["action"] == "log"
    assert [(i["food"], i["amount"], i["unit"]) for i in data["items"]] == expected
    # Every item must be marked stated, or the clarification ladder will offer
    # to confirm a portion the user typed in grams.
    assert all(i["basis"] == "stated" for i in data["items"])


@pytest.mark.parametrize("message,why", [
    ("some chicken", "vague_quantity"),
    ("a bit of rice", "vague_quantity"),
    ("half a bagel", "vague_quantity"),
    ("about 150g of rice", "hedge"),
    ("I had that again", "reference"),
    ("the same as yesterday", "reference"),
    ("what did I log?", "question"),
    ("how many calories is that", "interrogative"),
    ("actually make it 200g", "reference"),
    ("delete the last one", "reference"),
    ("#3 was wrong", "board_id"),
    ("yesterday I had eggs", "time_reference"),
    ("chicken breast 200 cal", "stated_macros"),
    ("2 eggs but no toast", "conditional"),
    ("", "empty"),
])
def test_the_fast_path_refuses_everything_else(message, why):
    """A miss costs one model call — what the turn costs today. A wrong accept
    costs a user a wrong log, silently. The asymmetry is why the bar is
    "provably one reading" rather than "probably fine"."""
    assert refusal_reason(message) == why
    assert parse(message) is None


def test_a_partially_parseable_message_is_refused_entirely():
    """Logging the half we understood and dropping the rest is the worst
    available outcome: the user sees a log, so they do not re-send."""
    assert parse("200g chicken and whatever was left of the pasta") is None


def test_a_food_name_that_is_really_a_sentence_is_refused():
    assert parse("2 of the things my brother made last weekend") is None


def test_absurd_amounts_are_refused():
    assert parse("99999 g chicken") is None
    assert parse("0 g chicken") is None


def test_the_fast_path_is_off_by_default(monkeypatch):
    """A new parser in front of the write path ships off. A misparse here does
    not fall back — it commits."""
    from core.food_fast_path import fast_path_enabled, shadow_enabled
    monkeypatch.delenv("FOOD_FAST_PATH", raising=False)
    monkeypatch.delenv("FOOD_FAST_PATH_SHADOW", raising=False)
    assert fast_path_enabled() is False
    assert shadow_enabled() is False


def test_the_switch_gates_use_not_parsing(monkeypatch):
    """`parse` is a pure parser and does not read the switch: shadow mode has to
    be able to measure the parse without the flag that gates writes also gating
    measurement. Whether the answer is USED is decided in core/food_turn.py."""
    from core.food_fast_path import fast_path_enabled
    monkeypatch.setenv("FOOD_FAST_PATH", "off")
    assert fast_path_enabled() is False
    assert parse("150g chicken breast") is not None


def test_the_fast_path_can_be_switched_on(monkeypatch):
    from core.food_fast_path import fast_path_enabled
    monkeypatch.setenv("FOOD_FAST_PATH", "on")
    assert fast_path_enabled() is True


def test_the_output_is_the_shape_the_existing_executor_accepts():
    """The fast path adds no downstream branch — it produces the same input the
    model does, and everything after it is unchanged."""
    from core.food_turn import _log_call, _normalize_ops

    data = parse("150g chicken breast and 2 eggs")
    ops = _normalize_ops(data)
    assert [k for k, _ in ops] == ["log", "log"]
    calls = [_log_call(o) for _, o in ops]
    assert all(c is not None and c["name"] == "log_food" for c in calls)
    assert calls[0]["input"]["quantity"] == "150 g"
    assert calls[0]["input"]["basis"] == "stated"


def test_the_fast_path_writes_no_prose():
    """Response text comes from the deterministic composer downstream, the same
    way it does on a model turn with the composer off. A parser inventing
    sentences would be a second voice in the product."""
    assert parse("150g chicken breast")["say"] == ""


# ── the cache may never change an answer ──────────────────────────────────────
def _request(**kwargs):
    from skills.nutrition.models import FoodResolutionRequest
    return FoodResolutionRequest(**{"food_name": "Banana, raw",
                                    "raw_quantity": "118g", **kwargs})


def _candidate(calories=89, name="Banana, raw"):
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import profile_from_values
    from skills.nutrition.provenance import MatchGrade, SourceTier
    from skills.nutrition.scaling import Per100g
    return Candidate(
        source="usda", tier=SourceTier.GENERIC_EXACT, name=name,
        profile=profile_from_values("usda", basis="per_100g", confidence=0.8,
                                    calories=calories, protein=1.1),
        basis=Per100g(), reported_grade=MatchGrade.EXACT)


def test_a_cached_resolution_equals_a_recomputed_one(monkeypatch):
    """The property the whole cache rests on: `resolve` is a pure function of
    (request, candidates), so a cached answer and a fresh one are the same
    answer. If this fails, the cache is unsafe and not merely slow."""
    from skills.nutrition.resolver import _resolve, resolve

    monkeypatch.setenv("NUTRITION_RESOLUTION_CACHE", "on")
    request, candidates = _request(), [_candidate()]
    cached = resolve(request, candidates)
    assert resolve(request, candidates) is cached          # actually a hit
    fresh = _resolve(request, candidates)

    assert cached.nutrients.as_dict() == fresh.nutrients.as_dict()
    assert cached.source == fresh.source
    assert cached.assumptions == fresh.assumptions
    assert cached.warnings == fresh.warnings


def test_different_candidates_are_a_different_key():
    """The candidates are part of the key, not the value. A cache that
    remembered what USDA said would keep serving a stale product after a
    correction — and the label winning is the entire point of the resolver."""
    from skills.nutrition.resolver import resolve

    request = _request()
    first = resolve(request, [_candidate(calories=89)])
    second = resolve(request, [_candidate(calories=200)])
    assert first.nutrients.amount("calories") != second.nutrients.amount("calories")


def test_every_request_field_participates_in_the_key():
    """A field that changes the answer and is missing from the key is a
    correctness bug. The builder reads the dataclass fields rather than a
    hand-listed subset that would silently fall behind."""
    base = cache.key_for(_request(), [_candidate()])
    for field, value in (("mode", "strict"), ("brand", "Dole"),
                         ("variant", "green"), ("raw_quantity", "200g"),
                         ("is_packaged", True), ("food_name", "Apple")):
        assert cache.key_for(_request(**{field: value}),
                             [_candidate()]) != base, field


def test_user_label_values_change_the_key():
    """A user's own label values arrive on the request and absolutely change
    the answer. Nothing here knows about users, which is the strongest form of
    "it cannot leak between them"."""
    from skills.nutrition.models import profile_from_values
    labelled = _request(user_label_values=profile_from_values(
        "user_label", basis="per_100g", confidence=1.0, calories=50))
    assert cache.key_for(labelled, [_candidate()]) != cache.key_for(
        _request(), [_candidate()])


def test_the_cache_is_off_by_default(monkeypatch):
    """A cache whose key was wrong once earns its way back on."""
    from skills.nutrition.resolver import resolve
    monkeypatch.delenv("NUTRITION_RESOLUTION_CACHE", raising=False)
    assert cache.caching_enabled() is False
    request, candidates = _request(), [_candidate()]
    assert resolve(request, candidates) is not resolve(request, candidates)


def test_the_cache_can_be_switched_off_explicitly(monkeypatch):
    from skills.nutrition.resolver import resolve
    monkeypatch.setenv("NUTRITION_RESOLUTION_CACHE", "off")
    request, candidates = _request(), [_candidate()]
    assert resolve(request, candidates) is not resolve(request, candidates)


def test_entries_expire():
    memo = cache.ResolutionCache(ttl_s=10.0)
    memo.put("k", "v", now=100.0)
    assert memo.get("k", now=105.0) == "v"
    assert memo.get("k", now=120.0) is None
    assert memo.stats.expirations == 1


def test_the_cache_is_bounded():
    """An unbounded memo in a long-lived process is a leak with a delay."""
    memo = cache.ResolutionCache(max_entries=3)
    for i in range(10):
        memo.put(f"k{i}", i)
    assert len(memo) == 3
    assert memo.stats.evictions == 7
    assert memo.get("k0") is None and memo.get("k9") == 9


def test_least_recently_used_is_what_gets_evicted():
    memo = cache.ResolutionCache(max_entries=2)
    memo.put("a", 1)
    memo.put("b", 2)
    memo.get("a")                       # a is now the recent one
    memo.put("c", 3)
    assert memo.get("a") == 1 and memo.get("b") is None


def test_an_empty_hit_rate_is_none_not_zero():
    """A hit rate of zero and no traffic are different facts, and conflating
    them reports a cold process as a broken cache."""
    assert cache.ResolutionCache().stats.hit_rate is None


def test_an_unkeyable_request_skips_the_cache_rather_than_failing():
    """The cache is an optimization, and an optimization that can fail a turn
    is not one."""
    class Weird:
        __dataclass_fields__ = property(lambda self: 1 / 0)

    assert cache.key_for(Weird(), []) is None
    assert cache.memoize(Weird(), [], lambda: "computed") == "computed"


# ── the turn budget ───────────────────────────────────────────────────────────
def test_no_deadline_means_unbounded():
    """Background jobs and tests have nobody waiting on them and must not
    inherit an interactive budget."""
    assert deadline.remaining() == float("inf")
    assert not deadline.expired()
    assert deadline.cap(6.0) == 6.0


def test_a_budget_caps_a_per_call_timeout():
    """The point of the module in one assertion: a six-second per-call timeout
    is fine until it is the fourth one in a twenty-second turn."""
    with deadline.budget(2.0):
        assert deadline.cap(6.0) <= 2.0
        assert deadline.cap(0.5) == 0.5


def test_a_nested_budget_can_only_tighten():
    """An inner block asking for more time than the turn has left does not get
    it — that is what makes the outer budget a guarantee."""
    with deadline.budget(1.0):
        with deadline.budget(60.0):
            assert deadline.remaining() <= 1.0


def test_the_budget_is_released_on_the_way_out():
    """A deadline left set would starve the next turn on the same task of time
    it never used."""
    with deadline.budget(1.0):
        assert deadline.remaining() != float("inf")
    assert deadline.remaining() == float("inf")


def test_a_useless_sliver_is_reported_as_no_time_at_all():
    """A 50ms budget handed to an HTTP call guarantees a timeout after paying
    connection setup — worse than not calling, because it costs the time AND
    produces nothing."""
    with deadline.budget(deadline.MIN_USEFUL_S / 2):
        assert deadline.remaining() == 0.0
        assert deadline.expired()
        assert deadline.cap(6.0) == 0.0


@pytest.mark.asyncio
async def test_wait_for_raises_a_distinct_type_on_expiry():
    """Distinct from asyncio.TimeoutError so a caller can tell "this call was
    slow" from "the turn is over", and stop rather than retry into a budget
    that is gone."""
    import asyncio

    with deadline.budget(0.3):
        with pytest.raises(deadline.DeadlineExceeded):
            await deadline.wait_for(asyncio.sleep(5))


@pytest.mark.asyncio
async def test_wait_for_refuses_before_starting_when_the_budget_is_gone():
    async def _never_runs():           # pragma: no cover - must not be awaited
        raise AssertionError("the call should not have been started")

    coro = _never_runs()
    try:
        with deadline.budget(deadline.MIN_USEFUL_S / 2):
            with pytest.raises(deadline.DeadlineExceeded):
                await deadline.wait_for(coro)
    finally:
        coro.close()


@pytest.mark.asyncio
async def test_wait_for_is_a_plain_await_when_unbounded():
    async def _value():
        return 7
    assert await deadline.wait_for(_value()) == 7


@pytest.mark.asyncio
async def test_a_lookup_past_the_deadline_returns_a_miss_not_an_error():
    """Expiry degrades. A food turn whose enrichment ran out of time should log
    an estimate and say so; one that raises has turned a slow lookup into a
    lost meal."""
    from skills.nutrition import off

    with deadline.budget(deadline.MIN_USEFUL_S / 2):
        assert await off._get_json("http://example.invalid", {}) is None


@pytest.mark.asyncio
async def test_the_executor_opens_a_budget_and_closes_it(monkeypatch):
    """The batch is where the number of calls is known, so it is where they can
    be bounded together."""
    import handlers.tool_executor as TE

    seen = {}

    async def _inner(*args, **kwargs):
        seen["remaining"] = deadline.remaining()
        return {}

    monkeypatch.setattr(TE, "_execute_tool_calls", _inner)
    await TE.execute_tool_calls([], None, None, None)

    assert seen["remaining"] != float("inf")
    assert deadline.remaining() == float("inf")


# ── the headline claim: a deterministic log costs no model call ──────────────
class _User:
    id = 1
    preferences = None


@pytest.mark.asyncio
async def test_a_deterministic_log_makes_no_model_call(monkeypatch):
    """The whole point of PR #30. `chat` is replaced with something that fails
    the test if called at all — a mock returning a plausible answer would let a
    regression pass by quietly restoring the round trip."""
    import core.food_turn as FT

    async def _must_not_be_called(*a, **k):     # pragma: no cover
        raise AssertionError("the fast path should have avoided the model")

    monkeypatch.setattr(FT, "chat", _must_not_be_called)
    monkeypatch.setenv("FOOD_FAST_PATH", "true")

    out = await FT.run("150g chicken breast and 2 eggs", _User())

    assert out is not None
    assert out["action"] == "log"
    assert [c["input"]["food_name"] for c in out["tool_calls"]] == [
        "chicken breast", "eggs"]
    assert out["tool_calls"][0]["input"]["quantity"] == "150 g"


@pytest.mark.asyncio
async def test_a_message_the_fast_path_refuses_still_reaches_the_model(
        monkeypatch):
    """The other half: a miss must fall through cleanly, not fail the turn."""
    import core.food_turn as FT

    called = {"n": 0}

    async def _chat(*a, **k):
        called["n"] += 1
        return {"text": '{"action":"log","items":[{"food":"rice",'
                        '"amount":1,"unit":"bowl"}],"say":"Logged."}'}

    monkeypatch.setattr(FT, "chat", _chat)
    monkeypatch.setenv("FOOD_FAST_PATH", "true")

    await FT.run("some rice", _User())
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_an_answer_turn_never_takes_the_fast_path(monkeypatch):
    """A `prior` means this message answers a question we asked, and the
    question's context is exactly what the parser does not have."""
    import core.food_turn as FT

    called = {"n": 0}

    async def _chat(*a, **k):
        called["n"] += 1
        return {"text": '{"action":"log","items":[]}'}

    monkeypatch.setattr(FT, "chat", _chat)
    monkeypatch.setenv("FOOD_FAST_PATH", "true")

    await FT.run("150g chicken breast", _User(),
                 prior={"original": "chicken", "question": "how much?"})
    assert called["n"] == 1


@pytest.mark.asyncio
async def test_a_message_with_a_board_never_takes_the_fast_path(monkeypatch):
    """With today's entries in play, "2 eggs" may be a correction to one of
    them, and only the model sees the board."""
    import core.food_turn as FT

    called = {"n": 0}

    async def _chat(*a, **k):
        called["n"] += 1
        return {"text": '{"action":"log","items":[]}'}

    monkeypatch.setattr(FT, "chat", _chat)
    monkeypatch.setenv("FOOD_FAST_PATH", "true")

    await FT.run("2 eggs", _User(),
                 board=[{"id": 1, "food": "eggs", "qty": "2", "cal": 140}])
    assert called["n"] == 1


# ── an unknown unit is refused, never folded into the food name ───────────────
# The parser's promise is that it only accepts messages with one provable
# reading. The unknown-word branch broke that promise: any token it did not
# recognise as a unit became part of the food name, so "2 tablespoons peanut
# butter" logged 2 pieces of "tablespoons peanut butter" — a confident write
# under a name no source will ever match, with basis="stated" telling the rest of
# the system not to ask.
@pytest.mark.parametrize("message", [
    # Measures we can convert exactly — these must PARSE, not refuse. Their
    # absence from the unit table is what sent them down the unknown-word branch.
    "2 tablespoons peanut butter",
    "1 tablespoon olive oil",
    "2 teaspoons sugar",
    "1 teaspoon honey",
])
def test_a_spelled_out_spoon_is_a_unit_not_a_food_word(message):
    parsed = parse(message)
    assert parsed is not None, f"{message!r} was refused"
    item = parsed["items"][0]
    assert item["unit"] in ("tbsp", "tsp"), item
    assert "spoon" not in item["food"], (
        f"the measure was folded into the food name: {item['food']!r}")


@pytest.mark.parametrize("message", [
    # Containers: the contents depend on the product, and there is no lookup.
    "1 bottle Fairlife",
    "2 bottles sparkling water",
    "1 can Diet Coke",
    "1 bar Barebells",
    "2 bars granola",
    "1 packet oatmeal",
    "1 package ramen",
    "1 container yogurt",
    "1 carton egg whites",
    "1 box cereal",
    # Vague helpings: not stated portions, and this path marks what it emits
    # `stated`, which tells the pipeline not to ask.
    "2 bowls rice",
    "1 bowl oatmeal",
    "1 plate pasta",
    "2 servings pasta",
    "1 serving rice",
    "1 scoop whey",
    "2 scoops protein powder",
    "1 handful almonds",
    "2 glasses milk",
    "1 mug coffee",
    "1 shot espresso",
    "1 spoonful peanut butter",
    "1 bite cake",
])
def test_a_container_or_vague_helping_is_refused(message):
    assert parse(message) is None, f"{message!r} was accepted"
    assert refusal_reason(message) is not None, (
        f"{message!r} refused without an attributable reason")


@pytest.mark.parametrize("message", [
    "1 bottle Fairlife", "2 bowls rice", "1 scoop whey", "1 bar Barebells",
])
def test_the_refusal_is_attributable(message):
    """"we fall back 80% of the time" is not actionable; "we fall back 80% of
    the time on container_or_vague_unit" is."""
    assert refusal_reason(message) == "container_or_vague_unit"


@pytest.mark.parametrize("message,food", [
    # The case the unknown-word branch exists for, and which must keep working:
    # a food whose own name follows the count.
    ("2 chicken thighs", "chicken thighs"),
    ("3 chicken wings", "chicken wings"),
    ("2 corn tortillas", "corn tortillas"),
])
def test_a_food_word_after_the_count_still_belongs_to_the_food(message, food):
    parsed = parse(message)
    assert parsed is not None, f"{message!r} was refused"
    assert parsed["items"][0]["food"] == food
    assert parsed["items"][0]["unit"] == "piece"


# ── the cache key covers everything that changes the answer ───────────────────
# The candidate side was a hand-listed subset that named the basis's TYPE
# ("per_serving") and none of its numbers, so two candidates with the same panel
# and different serving masses shared a key. The second one got the first one's
# answer — wrong by exactly the ratio of the serving masses.
def _with_basis(basis, **kw):
    from skills.nutrition.candidates import Candidate
    from skills.nutrition.models import profile_from_values
    from skills.nutrition.provenance import MatchGrade, SourceTier
    return Candidate(
        source=kw.get("source", "off"),
        tier=kw.get("tier", SourceTier.BRANDED_EXACT),
        name=kw.get("name", "Protein bar"),
        profile=profile_from_values("off", basis="per_serving", confidence=0.8,
                                    calories=200, protein=20),
        basis=basis, brand=kw.get("brand"), variant=kw.get("variant"),
        reported_grade=MatchGrade.EXACT)


@pytest.mark.parametrize("a,b,why", [
    ("PerServing(serving_mass_g=30)", "PerServing(serving_mass_g=60)",
     "serving mass"),
    ("PerServing(serving_ml=240)", "PerServing(serving_ml=480)",
     "serving volume"),
    ("PerServing(servings_per_package=1)", "PerServing(servings_per_package=2)",
     "servings per package"),
    ("PerUnit(unit_mass_g=30)", "PerUnit(unit_mass_g=60)", "unit mass"),
    ("PerServing()", "PerUnit()", "basis type with no fields set"),
    ("PerServing()", "Per100g()", "basis type"),
])
def test_the_key_separates_candidates_that_scale_differently(a, b, why):
    from skills.nutrition.scaling import Per100g, PerServing, PerUnit  # noqa
    request = _request()
    key_a = cache.key_for(request, [_with_basis(eval(a))])
    key_b = cache.key_for(request, [_with_basis(eval(b))])
    assert key_a and key_b
    assert key_a != key_b, f"cache key ignores {why}"


@pytest.mark.parametrize("field,one,two", [
    ("name", "Protein bar", "Protein bar, chocolate"),
    ("brand", "Barebells", "Quest"),
    ("variant", "caramel", "cookies and cream"),
])
def test_the_key_separates_candidates_with_different_identities(field, one, two):
    from skills.nutrition.scaling import PerServing
    request = _request()
    key_a = cache.key_for(request, [_with_basis(PerServing(), **{field: one})])
    key_b = cache.key_for(request, [_with_basis(PerServing(), **{field: two})])
    assert key_a != key_b, f"cache key ignores candidate {field}"


def test_the_key_is_stable_for_identical_inputs():
    from skills.nutrition.scaling import PerServing
    request = _request()
    first = cache.key_for(request, [_with_basis(PerServing(serving_mass_g=30))])
    again = cache.key_for(request, [_with_basis(PerServing(serving_mass_g=30))])
    assert first == again


def test_a_new_basis_field_cannot_be_forgotten():
    """The structural walk is the point: adding a field to a basis changes the
    key without anyone remembering to list it. This asserts the mechanism rather
    than the field list, because the field list is what went stale."""
    from dataclasses import fields
    from skills.nutrition.scaling import PerServing
    for f in fields(PerServing):
        base = PerServing()
        bumped = PerServing(**{f.name: (
            2.0 if f.type != "bool" and not isinstance(
                getattr(base, f.name), bool) else True)})
        if bumped == base:
            continue
        assert cache.key_for(_request(), [_with_basis(base)]) != \
            cache.key_for(_request(), [_with_basis(bumped)]), (
                f"cache key ignores PerServing.{f.name}")
