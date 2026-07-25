"""Every card in one meal reports the same day (shipped screenshots, 2:12–2:15).

The executor runs tool calls SERIALLY, and each receipt is computed right after
its own write. In a one-item turn that is the whole day. In a multi-item meal it
is a partial one: item 1's card describes a day containing only item 1, and by
the time the user reads it, items 2..N have landed.

The shipped sequence, with the numbers from the screenshots:

    2:12   card says "240 cal left"
    2:14   dinner logged, card says "2,320 cal over"
    2:15   eggs card says "10 cal left"   ← 240 − 230, the pre-dinner day

Each of those was accurate about the instant it was taken. None of them
described the day the user was looking at, and two of them contradicted each
other on screen — which is what "the day total looks stale" actually was.

A meal is one event. The cards in it report one day state, and the verdict is
read once from the meal's combined macros rather than N times from slices of
it, because a sixth of a meal did not do what the meal did.
"""
import pytest

from handlers.tool_executor import _resync_batch_receipts


class _Prefs:
    calorie_target = 2200
    protein_target = 150
    fat_target = 70


class _User:
    preferences = _Prefs()


class _Log:
    """The day as it FINALLY stands — what every card in the batch must show."""
    id = 1
    total_calories = 4520.0
    total_protein = 190.0
    total_fats = 150.0
    workout_completed = False


class _OtherDay:
    id = 2
    total_calories = 1800.0
    total_protein = 120.0
    total_fats = 60.0
    workout_completed = False


class _DB:
    """Just enough session to return the finished day.

    `logs` is served in the order the resync asks for them, which is the order
    the batch first touched each day — deterministic, because the grouping
    preserves insertion order.
    """
    def __init__(self, logs=None):
        self._logs = list(logs) if logs else None

    async def execute(self, _stmt):
        log = _Log() if self._logs is None else self._logs.pop(0)

        class _R:
            def scalar_one(_self):
                return log
        return _R()


def _ctx(receipt, calories, protein, log_id=1, carbs=None):
    return {"receipt": dict(receipt),
            "receipt_basis": {"daily_log_id": log_id, "calories": calories,
                              "protein": protein, "carbs": carbs,
                              "confidence": None, "estimated": False,
                              "updated": False, "local_hour": 14}}


@pytest.mark.asyncio
async def test_the_eggs_card_no_longer_shows_a_day_without_the_dinner():
    """The exact shipped pair. 2,330 cal of dinner and 230 of eggs, logged
    together; the eggs card reported the day before the dinner existed."""
    eggs = _ctx({"remaining_cal": 10, "remaining_protein": 5,
                 "verdict": "You're on pace, so there's nothing to correct."},
                calories=230, protein=20)
    dinner = _ctx({"remaining_cal": -2320, "remaining_protein": -40,
                   "verdict": "Protein landed, but that's about 2320 calories "
                              "over for the day."},
                  calories=2330, protein=95)

    await _resync_batch_receipts([eggs, dinner], _User(), _DB())

    # 2200 target against a 4520 day.
    assert eggs["receipt"]["remaining_cal"] == -2320
    assert dinner["receipt"]["remaining_cal"] == -2320
    assert eggs["receipt"]["remaining_cal"] == dinner["receipt"]["remaining_cal"]


@pytest.mark.asyncio
async def test_no_card_in_the_batch_claims_to_be_on_pace():
    """The contradiction the user actually saw: one card saying the day is
    fine, printed beside another saying it is 2,320 over."""
    eggs = _ctx({"remaining_cal": 10,
                 "verdict": "You're on pace, so there's nothing to correct."},
                calories=230, protein=20)
    dinner = _ctx({"remaining_cal": -2320, "verdict": "over"},
                  calories=2330, protein=95)

    await _resync_batch_receipts([eggs, dinner], _User(), _DB())

    for ctx in (eggs, dinner):
        assert "on pace" not in ctx["receipt"]["verdict"].lower()
    assert eggs["receipt"]["verdict"] == dinner["receipt"]["verdict"]


@pytest.mark.asyncio
async def test_per_item_honesty_survives_the_resync():
    """The range on a vague estimate is a fact about THAT item, not about the
    day. Sharing the day state must not flatten it."""
    vague = _ctx({"remaining_cal": 10, "verdict": "x",
                  "cal_low": 200, "cal_high": 260, "confidence": 0.4},
                 calories=230, protein=20)
    other = _ctx({"remaining_cal": -2320, "verdict": "y"},
                 calories=2330, protein=95)

    await _resync_batch_receipts([vague, other], _User(), _DB())

    assert vague["receipt"]["cal_low"] == 200
    assert vague["receipt"]["cal_high"] == 260
    assert vague["receipt"]["confidence"] == 0.4
    assert "cal_low" not in other["receipt"]


@pytest.mark.asyncio
async def test_a_single_item_turn_is_left_exactly_as_it_was():
    """Its receipt already describes the whole day. Recomputing it could only
    change a card that was right."""
    only = _ctx({"remaining_cal": 870, "verdict": "Efficient protein."},
                calories=230, protein=20)
    before = dict(only["receipt"])

    await _resync_batch_receipts([only], _User(), _DB())

    assert only["receipt"] == before


@pytest.mark.asyncio
async def test_items_written_to_different_days_are_not_pooled():
    """A backfilled item ("and a bagel yesterday") lands on another day. Today's
    cards must report today; the backfilled pair must report THAT day, and
    neither total may leak into the other."""
    eggs = _ctx({"remaining_cal": 10, "verdict": "x"}, calories=230,
                protein=20, log_id=1)
    dinner = _ctx({"remaining_cal": -2320, "verdict": "y"}, calories=2330,
                  protein=95, log_id=1)
    bagel = _ctx({"remaining_cal": 900, "verdict": "z"}, calories=280,
                 protein=11, log_id=2)
    toast = _ctx({"remaining_cal": 800, "verdict": "w"}, calories=120,
                 protein=4, log_id=2)

    await _resync_batch_receipts([eggs, dinner, bagel, toast], _User(),
                                 _DB([_Log(), _OtherDay()]))

    assert eggs["receipt"]["remaining_cal"] == -2320      # 2200 − 4520
    assert dinner["receipt"]["remaining_cal"] == -2320
    assert bagel["receipt"]["remaining_cal"] == 400       # 2200 − 1800
    assert toast["receipt"]["remaining_cal"] == 400


@pytest.mark.asyncio
async def test_a_broken_receipt_never_breaks_the_batch():
    """A receipt is garnish; the logs already stand."""
    good = _ctx({"remaining_cal": 10, "verdict": "x"}, calories=230, protein=20)
    junk = {"receipt": "not a dict"}
    await _resync_batch_receipts([good, junk, None], _User(), _DB())
