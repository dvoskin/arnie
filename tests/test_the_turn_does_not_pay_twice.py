"""Two costs a food turn was paying for nothing.

From the 18:23 cheeseburger + apple turn (ms=15242, phase executed 17830):

    interpreter                     4.0 s
    _variant_spreads -> plan_turn   3.5 s   awaited before the decision
    enrichment                      5.1 s
    composer                        1.0 s
    deep-observe second interpreter 2.6 s   AFTER the reply already shipped

Legacy was ~6 s for the same turn.
"""
import pytest


# ── the observation does not run the interpreter a second time ───────────────
def _req(text="had 2 eggs and toast", **kw):
    from core.turns.models import TurnRequest
    meta = {"user": kw.pop("user", None), "db": kw.pop("db", None)}
    meta.update(kw)
    return TurnRequest(turn_id="t", user_id=1, platform="ios",
                       source_type="ios", text=text, metadata=meta)


@pytest.mark.asyncio
async def test_a_supplied_interpretation_is_lifted_not_recomputed(monkeypatch):
    """`deep_observing()` bought disposition agreement for a second Sonnet
    call. Handed the plan the turn already computed, it costs nothing — so it
    is no longer gated on the flag either."""
    import core.turns.observe as OB
    import core.turns.stages.food as FS
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.delenv("TURN_COORDINATOR_OBSERVE_DEEP", raising=False)

    async def _boom(*a, **k):
        raise AssertionError("the turn already decided; do not ask again")
    monkeypatch.setattr(FS.FoodPlanStage, "run", _boom)

    pred = await OB.observe_turn(
        _req(), actual_route="structured_food", actual_disposition="execute",
        interpretation={"action": "log", "tool_calls": [
            {"name": "log_food", "input": {"food_name": "Egg"}}]})
    assert pred["disposition"] == "execute"
    assert pred["ops"] == 1


@pytest.mark.asyncio
async def test_a_lane_that_ran_and_produced_nothing_is_a_pass_not_a_re_run(
        monkeypatch):
    """`interpretation=None` is not "no interpretation supplied". The lane ran
    and handed the turn back; re-running it would sample the same model
    twice."""
    import core.turns.observe as OB
    import core.turns.stages.food as FS
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.setenv("TURN_COORDINATOR_OBSERVE_DEEP", "true")

    async def _boom(*a, **k):
        raise AssertionError("the turn already decided; do not ask again")
    monkeypatch.setattr(FS.FoodPlanStage, "run", _boom)

    pred = await OB.observe_turn(_req(), interpretation=None)
    assert pred["disposition"] == "pass"


@pytest.mark.asyncio
async def test_omitting_it_keeps_the_old_opt_in_behaviour(monkeypatch):
    """Callers that have no interpretation to hand over — the coordinator's own
    tests, a turn the lane never took — are unchanged."""
    import core.turns.observe as OB
    import core.turns.stages.food as FS
    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.delenv("TURN_COORDINATOR_OBSERVE_DEEP", raising=False)

    async def _boom(*a, **k):
        raise AssertionError("shallow observation must not plan")
    monkeypatch.setattr(FS.FoodPlanStage, "run", _boom)

    pred = await OB.observe_turn(_req())
    assert pred["disposition"] == ""


def test_the_live_turn_hands_its_interpretation_over():
    """The saving is worth nothing if the call site does not pass it."""
    import inspect
    import core.conversation as C
    source = inspect.getsource(C)
    assert "interpretation=locals().get(\"_sft\")" in source


def test_one_lift_serves_both_callers():
    """If the stage and the observation lifted the plan differently, the
    agreement line would be comparing two liftings rather than the wiring."""
    import inspect
    from core.turns.stages import food as FS
    assert "return plan_from_interpretation(out)" in \
        inspect.getsource(FS.FoodPlanStage.run)


# ── the variant fetch is bounded, and skipped when it cannot matter ──────────
TARGETS = {"calories": 2200, "protein": 160}


@pytest.mark.parametrize("mode", ["quick"])
def test_quick_never_pays_for_a_variant_lookup(mode):
    """`MATERIAL_FRACTIONS["quick"] = 1.01` — quick opts out of the fraction
    rule by construction, so no shelf spread it could fetch would ever produce
    a material ambiguity. It was paying the network round trip anyway."""
    from core.food_turn import _spread_could_matter
    assert not _spread_could_matter({"calories": 210}, mode=mode,
                                    targets=TARGETS)


def test_an_unsizeable_doubt_is_still_fetched():
    """No calories means the doubt cannot be sized either way, and that is the
    case the lookup exists to answer."""
    from core.food_turn import _spread_could_matter
    assert _spread_could_matter({}, mode="moderate", targets=TARGETS)


def test_the_gate_asks_the_real_scorer():
    """A second copy of the thresholds here would drift from the ones the ask
    decision uses, and the fetch would start skipping items the pipeline would
    have asked about."""
    import inspect
    from core.food_turn import _spread_could_matter
    source = inspect.getsource(_spread_could_matter)
    assert "from skills.nutrition.ambiguity import materiality" in source
    # The best case is the WHOLE item in doubt: no per-100g spread can exceed
    # the ceiling it is measured against.
    assert "calorie_span=calories" in source


def test_the_lookup_does_not_get_the_whole_turn_budget():
    """It is decoration for the ask, never for the write — every failure is
    already an absent entry — so it may not spend what is left of the turn."""
    import inspect
    import core.food_turn as FT
    assert FT._VARIANT_SPREAD_SECONDS <= 2.0
    assert "seconds=_VARIANT_SPREAD_SECONDS" in \
        inspect.getsource(FT._variant_spreads)
