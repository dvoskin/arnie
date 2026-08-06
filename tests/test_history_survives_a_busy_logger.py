"""A FOOD YOU EAT OFTEN MUST STILL BE FOUND UNDER EVERYTHING YOU ATE SINCE.

MEASURED IN PRODUCTION, 2026-08-06. A quantity question about "White rice,
steamed" offered only ontology portions, while the user had FIFTEEN prior
non-estimated rows of that exact name inside the 90-day window.

`_history_grams` fetched the 50 most recent non-estimated rows across ALL
foods and compared names in Python afterwards. At roughly ten logged items a
day, fifty rows reaches back about a week — so the 90-day cutoff in the same
query was dead code, and any food not eaten in the last few days was invisible
regardless of how often it had been logged. At the moment of that ask the
fifty rows reached back only to 2026-07-29.

WHY EVERY EXISTING TEST PASSED. They seed a handful of rows. With five foods
in the table the cap never engages, so the truncation cannot occur — the
fixture's small world made the bug unreachable. The variable that matters is
not whether history works; it is how much OTHER food sits between now and the
last time you ate this one.

This file is that variable.
"""
import pytest

# The session and user fixtures already exist for this slice; a fourth copy
# would be a fourth thing to keep in step with the schema.
from tests.test_b1_answer_ownership import sessions, user  # noqa: F401


@pytest.mark.asyncio
async def test_history_is_found_behind_a_hundred_unrelated_meals(sessions, user):
    """The exact production shape: one old match, buried under noise.

    Fails on the pre-fix code with `None`, because the rice row sits outside
    the fifty most recent rows.
    """
    from datetime import date, timedelta

    from db.models import DailyLog, FoodEntry
    from skills.nutrition.quantity_clarification import _history_grams

    async with sessions() as s:
        # The meal we want found — logged a while ago, exactly named, trusted.
        old = DailyLog(user_id=user.id, date=date.today() - timedelta(days=40))
        s.add(old)
        await s.flush()
        s.add(FoodEntry(daily_log_id=old.id, parsed_food_name="White rice, steamed",
                        quantity="180 g", calories=290.0, estimated_flag=False))
        # Then everything else eaten since, which is what buried it.
        for day in range(30):
            log = DailyLog(user_id=user.id, date=date.today() - timedelta(days=day))
            s.add(log)
            await s.flush()
            for n in range(6):
                s.add(FoodEntry(daily_log_id=log.id,
                                parsed_food_name=f"Unrelated food {day}-{n}",
                                quantity="100 g", calories=100.0,
                                estimated_flag=False))
        await s.commit()

    async with sessions() as s:
        grams = await _history_grams(s, user.id, "White rice, steamed")

    assert grams == 180.0, (
        f"history returned {grams!r} for a food with an exact, trusted, "
        f"in-window prior — 180 unrelated meals were logged since, and the "
        f"scan gave up before reaching it")


@pytest.mark.asyncio
async def test_history_still_refuses_a_different_food(sessions, user):
    """The fix must widen recall, not loosen matching.

    Token-set equality is what stops "grilled chicken breast" answering for
    "chicken breast" — reading a portion off a food the user did not eat is
    worse than offering no history at all, because it looks authoritative.
    """
    from datetime import date

    from db.models import DailyLog, FoodEntry
    from skills.nutrition.quantity_clarification import _history_grams

    async with sessions() as s:
        log = DailyLog(user_id=user.id, date=date.today())
        s.add(log)
        await s.flush()
        s.add(FoodEntry(daily_log_id=log.id,
                        parsed_food_name="Grilled chicken breast",
                        quantity="200 g", calories=330.0, estimated_flag=False))
        await s.commit()

    async with sessions() as s:
        assert await _history_grams(s, user.id, "Chicken breast") is None


@pytest.mark.asyncio
async def test_an_estimated_row_never_becomes_a_suggestion(sessions, user):
    """A row is not ground truth just because we wrote it.

    One bad auto-estimate would otherwise launder itself into a permanent
    suggestion the user keeps being offered.
    """
    from datetime import date

    from db.models import DailyLog, FoodEntry
    from skills.nutrition.quantity_clarification import _history_grams

    async with sessions() as s:
        log = DailyLog(user_id=user.id, date=date.today())
        s.add(log)
        await s.flush()
        s.add(FoodEntry(daily_log_id=log.id, parsed_food_name="White rice, steamed",
                        quantity="180 g", calories=290.0, estimated_flag=True))
        await s.commit()

    async with sessions() as s:
        assert await _history_grams(s, user.id, "White rice, steamed") is None
