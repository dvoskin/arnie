"""A corrected food updates the card it is already on — it does not ride the
next meal's card.

PROD, 2026-08-03 19:16:17 (Danny). One turn did both things: `le#921` UPDATED
the tuna sashimi from 4 pieces to 1, and `le#922` CREATED the Quest chips. Two
faults came out of that single turn.

  • THE CARD. Both writes emitted a `macro_card`, so both landed in the turn's
    `cards` list. The client buckets that list by card type — N food cards from
    one turn collapse into a single grouped meal card — so the corrected tuna
    became a row on the chips' card, while still living on the earlier card it
    was actually logged on. The same food, twice on screen, from one meal.

  • THE VERB. The reply was "Logged Tuna Sashimi and Quest Chips Chili Lime",
    announcing an hour-old row as a fresh log. `_subject_line` read the verb off
    `plan.intent`, and a mixed turn is COMMIT — its label is "commit" precisely
    because no single verb fits it — so the correction was given the log verb
    along with the genuinely new food.

Both repairs say the same thing in two places: what happened to a ROW is a
property of that row, not of the turn that touched it.
"""
from core.conversation import _logged_entry_card
from core.food_response import (FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, _subject_line, build_prompt)


# The turn as it actually ran: one update, one create, in that order.
TUNA = {"name": "update_food_entry",
        "input": {"entry_id": 921, "food_name": "Tuna Sashimi",
                  "quantity": "1 piece", "calories": 130, "protein": 28}}
CHIPS = {"name": "log_food",
         "input": {"_entry_id": 922, "food_name": "Quest Chips Chili Lime",
                   "quantity": "1 bag", "calories": 140, "protein": 19}}


def _turn_cards(calls):
    """The cards a turn emits, built the one way `_run_turn` builds them: the
    card builder per executed call, in order (core/conversation.py, "Typed
    inline cards for native clients")."""
    return [c for c in (_logged_entry_card(t["name"], t["input"])
                        for t in calls) if c is not None]


# ── the card ────────────────────────────────────────────────────────────────

def test_a_meal_card_lists_only_what_this_turn_created():
    """The chips' card carries the chips. The tuna is not on it."""
    cards = _turn_cards([TUNA, CHIPS])
    meal_rows = [c["payload"] for c in cards if c["type"] == "macro_card"]
    assert [r["name"] for r in meal_rows] == ["Quest Chips Chili Lime"]
    assert all(r["entry_id"] != 921 for r in meal_rows)


def test_the_correction_travels_as_a_patch_keyed_by_entry_id():
    """Addressed to the row, so the client can find the card it is already on."""
    cards = _turn_cards([TUNA, CHIPS])
    patches = [c for c in cards if c["type"] == "macro_card_patch"]
    assert len(patches) == 1
    payload = patches[0]["payload"]
    assert payload["entry_id"] == 921
    assert payload["corrected"] is True
    # The revision itself, or the patch has nothing to apply.
    assert payload["quantity"] == "1 piece"
    assert payload["calories"] == 130


def test_the_turn_emits_one_of_each_and_nothing_more():
    """Two writes, two artifacts — no duplicate row anywhere in the payload."""
    cards = _turn_cards([TUNA, CHIPS])
    assert [c["type"] for c in cards] == ["macro_card_patch", "macro_card"]


def test_a_correction_alone_still_confirms_itself():
    """A solo correction is the case the patch must not regress: it emitted a
    card so the change would not land invisibly, and it still emits its full
    payload — under the type that says which card to put it on."""
    (patch,) = _turn_cards([TUNA])
    assert patch["type"] == "macro_card_patch"
    assert patch["payload"]["name"] == "Tuna Sashimi"
    assert patch["payload"]["calories"] == 130


def test_no_row_no_patch():
    """THE INVARIANT, unchanged. A card — and now a patch — appears only where a
    real DB row was created or updated. This is what stopped a stale card
    leaking onto a reply that logged nothing (Danny 2026-06-26: "what is 84.9kg
    in lbs" surfaced an earlier coffee's macro_card with entry_id=null), and a
    patch addressed to no row is the same defect wearing a new type."""
    assert _logged_entry_card("update_food_entry",
                              {"food_name": "Tuna Sashimi"}) is None
    assert _logged_entry_card("update_food_entry",
                              {"entry_id": None, "calories": 130}) is None
    assert _turn_cards([{"name": "update_food_entry",
                         "input": {"food_name": "Tuna Sashimi"}}]) == []


# ── the verb ────────────────────────────────────────────────────────────────

def _mixed_plan():
    """The same turn, as the response layer sees it."""
    return FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="Tuna Sashimi", corrected=True),
                         FoodItemSummary(name="Quest Chips Chili Lime")))


def test_a_correction_is_not_announced_as_a_fresh_log():
    """The shipped sentence, and the one that replaces it."""
    line = _subject_line(_mixed_plan())
    assert line != "Logged Tuna Sashimi and Quest Chips Chili Lime."
    assert line == ("Updated Tuna Sashimi. Logged Quest Chips Chili Lime.")


def test_the_new_food_is_still_named_as_logged():
    """Fixing the verb on the correction must not take the other one with it —
    the chips genuinely were logged, and a turn that wrote a row may not go
    unnamed."""
    assert "Logged Quest Chips Chili Lime." in _subject_line(_mixed_plan())


def test_a_turn_with_one_verb_of_its_own_keeps_it():
    """Only a MIXED turn needs per-item verbs. An UNDO undid everything it
    names, and reaching for the item flag there would invent a distinction the
    turn does not have."""
    undo = FoodResponsePlan(
        intent=FoodResponseIntent.UNDO,
        committed_items=(FoodItemSummary(name="Tuna Sashimi", corrected=True),
                         FoodItemSummary(name="Rice")))
    assert _subject_line(undo) == "Undid Tuna Sashimi and Rice."
    plain = FoodResponsePlan(
        intent=FoodResponseIntent.COMMIT,
        committed_items=(FoodItemSummary(name="Rice"),
                         FoodItemSummary(name="Chicken")))
    assert _subject_line(plain) == "Logged Rice and Chicken."
    correct_only = FoodResponsePlan(
        intent=FoodResponseIntent.CORRECT,
        committed_items=(FoodItemSummary(name="Tuna Sashimi", corrected=True),))
    assert _subject_line(correct_only) == "Updated Tuna Sashimi."


def test_the_composer_is_told_which_rows_were_already_there():
    """The same fault reached by the other path: listing a corrected row under
    LOGGED tells the writer a fresh entry landed, and it writes one."""
    brief = build_prompt(_mixed_plan()).lower()
    assert "updated" in brief, "the correction is not distinguished at all"
    logged, updated = brief[brief.index("logged ("):].split("updated", 1)
    assert "quest chips chili lime" in logged
    assert "tuna sashimi" not in logged      # the fault: a repair listed as a log
    assert "tuna sashimi" in updated
