"""The promotion gate reports what actually happened, in both directions.

From a production log, 2026-07-28:

    predicted_lane=structured_food actual_lane=general agree=NO

Both routers had agreed. The food lane took the turn, ran the interpreter, and
the interpreter handed it back — and `_turn_route` is "legacy" for that just as
it is for a turn the gate never admitted. So every food-shaped question the
lane is DESIGNED to decline was scored as a routing disagreement, and the rate
gating the rollout was inflated by exactly the class of turn that proves the
design works.

The other half was worse because it was silent: `actual_disposition` was
reported only for an ask, and `observe_turn` short-circuits `agree_disp` to
True on an empty string. Every commit turn reported `actual_disposition=-`, so
disposition agreement had never once been compared — while
TURN_COORDINATOR_OBSERVE_DEEP=true pays for a second Sonnet call per food turn
to produce it.
"""
import pytest

from core.turns.observe import legacy_disposition, legacy_lane


# ── the lane ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("reason", ["interpreter_none", "interpreter_timeout",
                                    "pipeline_exception", "ask_stash_failed"])
def test_a_turn_the_lane_declined_is_still_the_lane(reason):
    """It looked at the turn and handed it back. That is the food lane doing
    its job, not the coordinator being wrong about routing."""
    assert legacy_lane("legacy", reason) == "structured_food"
    assert legacy_disposition("legacy", reason) == "pass"


@pytest.mark.parametrize("reason", ["kill_switch", "not_food_shaped",
                                    "mixed_domain", "non_english"])
def test_a_turn_the_gate_never_admitted_is_general(reason):
    """The control. These never reached the interpreter, so GENERAL is the
    honest answer and counting them as food would hide real disagreement."""
    assert legacy_lane("legacy", reason) == "general"
    assert legacy_disposition("legacy", reason) == ""


def test_an_unknown_reason_does_not_get_promoted():
    assert legacy_lane("legacy", "something_new") == "general"


# ── the disposition ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("route,expected", [
    ("structured_log", "execute"),
    ("structured_update", "execute"),
    ("structured_delete", "execute"),
    ("structured_commit", "execute"),
    ("confirm_replay", "execute"),
    ("structured_ask", "ask"),
])
def test_a_committing_turn_reports_execute(route, expected):
    """Previously every one of these reported "" and agreement short-circuited
    to True — so the disposition metric could not fail, which is the same as
    not having one."""
    assert legacy_disposition(route) == expected


def test_the_ask_is_not_swallowed_by_the_structured_prefix():
    """`structured_ask` also starts with `structured_`; ordering matters and a
    refactor that reorders the branches would silently call every ask an
    execute."""
    assert legacy_disposition("structured_ask") == "ask"


# ── end to end through observe_turn ───────────────────────────────────────────

async def test_a_declined_turn_now_agrees(monkeypatch):
    """§3's stated acceptance case: interpreter declines, both sides report
    structured_food/pass, and the turn stops counting against the gate."""
    import core.turns.observe as OB
    from core.turns.models import TurnRequest

    monkeypatch.setenv("TURN_COORDINATOR_MODE", "new_observe")
    monkeypatch.setenv("TURN_COORDINATOR_OBSERVE_DEEP", "true")

    async def _declines(*a, **k):
        return None

    import core.food_turn as FT
    monkeypatch.setattr(FT, "run", _declines)

    async def _is_food(*a, **k):
        return True
    monkeypatch.setattr(FT, "food_relevance", _is_food)

    request = TurnRequest(turn_id="t1", user_id=1, platform="ios",
                          source_type="text", text="had a bar",
                          metadata={"user": object(), "food_pending": True})
    prediction = await OB.observe_turn(
        request,
        actual_route=legacy_lane("legacy", "interpreter_none"),
        actual_disposition=legacy_disposition("legacy", "interpreter_none"))

    assert prediction is not None
    assert prediction["lane"] == "structured_food"
    assert prediction["disposition"] == "pass"
