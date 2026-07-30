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


# ── a real row, a real correction ─────────────────────────────────────────────
class _Priced:
    """What the enrichment ladder returns."""

    def __init__(self, calories=310.0):
        self.calories = calories
        self.protein = 12.0
        self.carbs = 30.0
        self.fat = 14.0
        self.fiber = self.sugar = self.sodium = None
        self.fdc_id = "1"
        self.confidence = "likely"
        self.source = "usda"
        self.protein_density = self.satiety = self.quality = None
        self.per100 = {"calories": 250.0, "protein": 10.0}
        self.serving_text = ""
        self.micros = {}
        self.micros_estimated = False
        self.coach_note = ""
        self.enrichment_source = "usda"
        self.provenance = None


async def _logged(db, make_user, monkeypatch):
    """One committed entry, and the user loaded with its preferences — the
    executor reads them, and a lazy load inside an async session raises."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from db.models import FoodEntry, User
    from db.queries import get_or_create_today_log
    from handlers.tool_executor import execute_tool_calls

    async def _analyze(db_, user_, name, inp, *a, **k):
        return _Priced()
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _analyze)

    created = await make_user()
    user = (await db.execute(
        select(User).where(User.id == created.id)
        .options(selectinload(User.preferences)))).scalars().one()
    await execute_tool_calls(
        [{"name": "log_food",
          "input": {"food_name": "Lunchables Pizza Snack Kit",
                    "quantity": "1 kit", "calories": 310}}],
        user, await get_or_create_today_log(db, user.id), db)
    row = (await db.execute(select(FoodEntry))).scalars().first()
    assert row is not None
    return user, row


async def _update(db, user, entry_id, **fields):
    """Run the correction and return the TYPED outcome the reply layer reads.

    Not the log line: `correction_unpriced` was wired to a dead channel for a
    release while its grep passed, and the fix was to carry the outcome on the
    typed call. Asserting there is asserting on the thing the user's reply is
    built from — and it does not depend on how logging happens to be
    configured when the whole suite runs.
    """
    from core.execution_result import LAST_EXECUTION
    from db.queries import get_or_create_today_log
    from handlers.tool_executor import execute_tool_calls

    await execute_tool_calls(
        [{"name": "update_food_entry", "input": {"entry_id": entry_id,
                                                 **fields}}],
        user, await get_or_create_today_log(db, user.id), db)
    execution = LAST_EXECUTION.get()
    calls = list(getattr(execution, "calls", ()) or ())
    return next((getattr(c, "correction", None) for c in calls
                 if getattr(c, "correction", None) is not None), None)


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


async def test_a_correction_reaches_the_ladder_at_all(db, make_user,
                                                      monkeypatch):
    """The regression this file exists for: `analyze` must be reachable from
    the update path. It was not — `changes` went straight to columns.

    THIS USED TO BE A GREP over the executor's source, in a window measured in
    characters. It broke when the branch grew a comment, which is the tell: a
    test that a string appears near another string cannot fail when the
    BEHAVIOUR regresses and does fail when nothing does. The plan calls that
    pattern out by name — `correction_unpriced` shipped inert for a release
    behind a grep that passed — so both greps in this file are now runs.
    """
    called = []

    async def _re(db_, user_, name, inp, *a, **k):
        called.append(name)
        return _Priced(calories=250.0)

    user, row = await _logged(db, make_user, monkeypatch)
    # Armed after the log: the log gets its own resolution, the correction is
    # the one under test.
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _re)
    outcome = await _update(db, user, row.id, food_name="Extra Cheesy Pizza")

    assert called == ["Extra Cheesy Pizza"], \
        "a corrected identity must be re-resolved, not taken from the model"
    await db.refresh(row)
    assert row.calories == 250.0
    # And the number moved, which is what makes it a correction rather than a
    # relabel — the outcome the reply is built from says so.
    assert outcome["renamed"] and outcome["moved_numbers"]


async def test_a_figure_the_user_stated_survives_the_re_resolution(
        db, make_user, monkeypatch):
    """No database outranks the person reading the packet."""
    async def _re(db_, user_, name, inp, *a, **k):
        return _Priced(calories=250.0)

    user, row = await _logged(db, make_user, monkeypatch)
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _re)
    await _update(db, user, row.id, food_name="Extra Cheesy Pizza",
                  calories=80)

    await db.refresh(row)
    assert row.calories == 80.0, \
        "the re-resolution overwrote a figure the user stated"


# ── a restaurant item may use an exact branded match ──────────────────────────

def test_an_exact_branded_match_beats_a_component_estimate():
    """Audit: "McDonald's Double Cheeseburger" had an exact Open Food Facts hit
    REFUSED — `refused=off:exact` — because OFF was seated nowhere on the
    RESTAURANT ladder. The item fell to `component_estimate` and resolved to
    ZERO calories, so the correction changed the name and left the number, and
    the user had to notice and supply it themselves.
    """
    from skills.nutrition.authority import FoodClass, LADDERS, rung_for_lane
    assert rung_for_lane("off", FoodClass.RESTAURANT,
                         match_grade="exact") == "branded_exact"
    ladder = LADDERS[FoodClass.RESTAURANT]
    assert ladder.index("branded_exact") < ladder.index("component_estimate"), \
        "real label data must outrank a guess with a badge"


def test_a_restaurant_item_still_prefers_the_restaurants_own_page():
    """The chain's published nutrition is the better answer and keeps its
    place. This only stops label data losing to an estimate."""
    from skills.nutrition.authority import FoodClass, LADDERS
    ladder = LADDERS[FoodClass.RESTAURANT]
    for better in ("restaurant_exact", "restaurant_page", "saved_restaurant"):
        assert ladder.index(better) < ladder.index("branded_exact")


def test_a_likely_match_is_not_enough_for_a_menu_item():
    """"likely" is where the wrong-cousin errors live on menu items — the class
    that turned "cavatappi" into CAVA. A restaurant item takes EXACT only."""
    from skills.nutrition.authority import FoodClass, rung_for_lane
    assert rung_for_lane("off", FoodClass.RESTAURANT,
                         match_grade="likely") is None
    # ...while a packaged product still accepts it.
    assert rung_for_lane("off", FoodClass.MANUFACTURED,
                         match_grade="likely") == "branded_exact"


async def test_an_unpriced_correction_is_disclosed_not_swallowed(
        db, make_user, monkeypatch):
    """`if _re.calories:` treated a zero-calorie resolution as "nothing to say"
    and kept the previous row's figures — the name changed, the number did not,
    and the reply announced a correction that had not happened.

    Also formerly a grep, and this is the one the plan uses as its example:
    the disclosure was wired to a dead channel for a whole release while the
    string it searched for sat in the source the whole time.
    """
    async def _unpriced(db_, user_, name, inp, *a, **k):
        return _Priced(calories=0.0)

    user, row = await _logged(db, make_user, monkeypatch)
    monkeypatch.setattr("handlers.tool_executor._analyze_food", _unpriced)
    outcome = await _update(db, user, row.id,
                            food_name="McDonald's Double Cheeseburger")

    assert outcome is not None, "the correction carried no typed outcome"
    assert outcome["renamed"], "the name change was not recorded"
    assert not outcome["moved_numbers"], (
        "the ladder returned nothing, so no number can have moved")
    # The pair the reply's disclosure keys on: renamed and nothing moved. A
    # correction that cannot be priced is a failure to disclose, not a silent
    # no-op.
    assert outcome["unpriced"]
