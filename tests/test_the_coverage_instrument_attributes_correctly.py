"""P11/P12 — the coverage instrument's own correctness gates.

⛔⛔ THE SCRIPT MAKES NO MODEL CALLS AND WRITES NOTHING, but the parts that
DECIDE are pure, and every one of them has already been wrong once:

    the meal key      keyed on the turn id alone, so two users sharing a client
                      key merged into ONE synthetic meal — the SAME identity
                      mistake P10g fixed in settlement, made again one file over
    classification    `canonical:*` read as structured-chat, so a canonical
                      QUICK-LOG entered the ordinary-chat numerator
    unknown ownership reported as `legacy_executor`, which is how the canary
                      would go invisible in the one branch it depends on
"""
from __future__ import annotations

import json

import pytest

from scripts.measure_settlement_coverage import (classify_meal, meal_key,
                                                 operations_by_entry)


# ══ the meal key ════════════════════════════════════════════════════════════

def test_two_users_sharing_a_client_turn_id_are_two_meals():
    """⛔⛔ THE P10g LESSON, IN THE INSTRUMENT. `make_turn_id` returns
    `f"{channel}:{cid}"` with no user in it, so `ios:X` is not unique. Merged,
    the synthetic meal takes whichever `user_id` lands last, evaluates BOTH
    users' foods against ONE user's memory, and inherits BOTH users'
    operations — so one general-settled row would paint the whole thing as
    general settlement and the canary would over-report itself."""
    assert meal_key(26, "ios:X") != meal_key(99, "ios:X")


def test_one_user_keeps_one_meal_per_turn():
    """The twin: scoping must not shatter a genuine multi-item meal."""
    assert meal_key(26, "ios:X") == meal_key(26, "ios:X")


# ══ classification — the operation decides a canonical row ══════════════════

@pytest.mark.parametrize("sources,operations,expected", [
    # The canary's own branch. `general:*` is `operation_id_for("general", ...)`.
    ({"canonical:create"}, {"general"}, "structured"),
    # B-1's answer path — canonical, and still an ordinary food-chat turn.
    ({"canonical:create"}, {"chat_quantity"}, "structured"),
    # ⛔ A CANONICAL QUICK-LOG IS NOT A CHAT TURN. Classified by SOURCE alone
    # this entered the ordinary-chat numerator and blamed the lane for traffic
    # that never went near it.
    ({"canonical:create"}, {"quick_log"}, "not_a_chat_turn"),
    # The legacy executor on the structured route.
    ({"structured_food:food_interpreter_v2"}, set(), "structured"),
    ({"legacy:ios"}, set(), "legacy"),
    ({"quick_log:ios"}, set(), "not_a_chat_turn"),
    ({"something_new:1"}, set(), "unknown_writer"),
])
def test_classification(sources, operations, expected):
    assert classify_meal(sources, operations) == expected


def test_an_unattributable_canonical_meal_is_unknown_not_legacy():
    """⛔⛔ "I COULD NOT TELL" IS ITS OWN ANSWER. A canonical row whose commit
    payload could not be mapped is UNKNOWN ownership — never evidence that
    legacy settled it. Reporting it as legacy is precisely how the canary goes
    invisible in the branch this measurement exists to watch, and the run
    withholds its verdict while any exist."""
    assert classify_meal({"canonical:create"}, set()) == "unclassified_canonical"


# ══ the operation mapping — the canary's only eye ═══════════════════════════

def test_a_synthetic_general_commit_is_attributed_to_the_general_owner():
    """⭐ THE BRANCH PRODUCTION HAS NOT EXERCISED. `general_settlement_owner` is
    zero in every measurement so far, correctly, because the cohort is unset —
    so the one path the canary depends on has never run against real data. This
    drives it synthetically, end to end: a MealCommit shaped as the writer
    shapes it, through the mapping, into the classification."""
    commits = [("general:26:ios:ABC", json.dumps({"result": {
        "committed_items": [{"entry_id": 4242, "name": "Asparagus",
                             "calories": 20.0}]}}))]

    mapping = operations_by_entry(commits)

    assert mapping == {4242: "general:26:ios:ABC"}
    family = mapping[4242].split(":")[0]
    assert classify_meal({"canonical:create"}, {family}) == "structured"


def test_the_b1_answer_path_is_still_told_apart_from_the_general_owner():
    """Both emit `canonical:create`; only the operation separates them."""
    commits = [("chat_quantity:26:abc", json.dumps({"result": {
                    "committed_items": [{"entry_id": 1}]}})),
               ("general:26:ios:X", json.dumps({"result": {
                    "committed_items": [{"entry_id": 2}]}}))]

    mapping = operations_by_entry(commits)

    assert mapping[1].split(":")[0] == "chat_quantity"
    assert mapping[2].split(":")[0] == "general"


def test_the_mapping_reads_the_payload_shape_the_writer_actually_writes():
    """⚠ THE PAYLOAD NESTS UNDER `result`, and a reader that looked at the top
    level once printed "legacy wrote it" over a row canonical had just written
    with rung=artifact. Both shapes are accepted; neither silently yields {}."""
    nested = operations_by_entry([("general:1:t", json.dumps(
        {"result": {"committed_items": [{"entry_id": 7}]}}))])
    flat = operations_by_entry([("general:1:t", json.dumps(
        {"committed_items": [{"entry_id": 8}]}))])
    assert nested == {7: "general:1:t"} and flat == {8: "general:1:t"}


def test_an_unparseable_payload_yields_no_attribution_rather_than_a_wrong_one():
    assert operations_by_entry([("general:1:t", "{not json")]) == {}
    assert operations_by_entry([("general:1:t", None)]) == {}
