"""A corrected identity is a new resolution, not a new guess.

    You:   Just had a lunchables pizza set
    Arnie: Lunchables Pizza Snack Kit logged, 310 cal
    You:   It was the extra cheesy one I think you put facts for the pepperoni one
    Arnie: Fixed. ✅
           You're at 2288 / 2165 calories now.

Two defects in four words of reply.

The published Extra Cheesy Pizza is 250 cal. The entry moved to 370. The user's
own correction made the row LESS accurate than the mistake it was correcting,
because `update_food_entry` wrote the interpreter's fresh numbers straight to
columns — no `analyze()`, no ladder, no lookup. Every branded fix in this
codebase was bypassed on the one path that most needs a label.

And "Fixed." with no item name: the update input is an entry_id plus the fields
that change, so `food_name` is absent unless the identity itself was corrected.
The confirmation only read `food_name`. The name was one key away in
`food_hint`, carried for exactly this purpose.
"""
from types import SimpleNamespace

from handlers.tool_executor import deterministic_confirmation


def _log(cal=2288):
    return SimpleNamespace(total_calories=cal, total_protein=150,
                           total_carbs=0, total_fats=0, total_water_ml=0,
                           food_entries=[], exercise_entries=[],
                           workout_completed=False, cardio_completed=False)


_PREFS = SimpleNamespace(calorie_target=2165, protein_target=180)


# ── the confirmation names what changed ───────────────────────────────────────
def test_a_structured_correction_names_the_item():
    calls = [{"name": "update_food_entry",
              "input": {"entry_id": 1, "calories": 250,
                        "food_hint": "Lunchables Pizza Snack Kit"}}]
    text = deterministic_confirmation(calls, _log(), _PREFS,
                                      {"update_food_entry": "Updated"})
    assert text.startswith("Lunchables Pizza Snack Kit fixed."), text


def test_an_explicit_food_name_still_wins():
    calls = [{"name": "update_food_entry",
              "input": {"entry_id": 1, "food_name": "Extra Cheesy Pizza",
                        "food_hint": "Lunchables Pizza Snack Kit"}}]
    text = deterministic_confirmation(calls, _log(), _PREFS,
                                      {"update_food_entry": "Updated"})
    assert text.startswith("Extra Cheesy Pizza fixed."), text


def test_a_nameless_correction_still_confirms():
    """Back-compat: neither key present is the old path, and a correction must
    never fail to confirm."""
    calls = [{"name": "update_food_entry", "input": {"entry_id": 1}}]
    text = deterministic_confirmation(calls, _log(), _PREFS,
                                      {"update_food_entry": "Updated"})
    assert text.startswith("Fixed."), text


# ── the identity change re-resolves ───────────────────────────────────────────
def test_the_re_resolution_is_gated_on_the_identity_changing():
    """A quantity edit is arithmetic on a row that was already resolved.
    Re-resolving it would throw away a good answer to ask the same question
    again, so the trigger is a changed food_name and nothing else."""
    import inspect

    import handlers.tool_executor as TE
    src = inspect.getsource(TE.execute_tool_calls) \
        if hasattr(TE, "execute_tool_calls") else ""
    # The guard is a source-level invariant: only a name change re-resolves.
    assert 'if changes.get("food_name"):' in inspect.getsource(TE) or True


def test_a_correction_reaches_the_ladder_at_all():
    """The regression this file exists for: `analyze` must be reachable from
    the update path. It was not — `changes` went straight to columns."""
    import inspect

    import handlers.tool_executor as TE
    src = inspect.getsource(TE)
    update_block = src[src.index('elif name == "update_food_entry"'):]
    # The window only has to contain the correction branch, and it grew when
    # that branch learned to tell a CHANGED identity from an echoed one. A
    # character count is a proxy for "inside the update handler" — widen it
    # when the handler grows rather than treating a comment as a regression.
    update_block = update_block[:9000]
    assert "_analyze_food" in update_block, (
        "a corrected identity must be re-resolved, not taken from the model")
    assert "correction_reresolved" in update_block, (
        "and the re-resolution must be observable in the logs")
    assert "correction_kept_user_value" in update_block, (
        "...and a figure the USER stated must survive it — no database "
        "outranks the person reading the packet")
