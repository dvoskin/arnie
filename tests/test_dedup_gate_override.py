"""Integration tests for the turn-intent dedup gate at the tool_executor layer.

The gate (skills/logging_intent.py, threaded through execute_tool_calls →
_dispatch as user_message=) is what distinguishes a LEGIT second serving from a
phantom re-fire / retry. With an explicit add cue in the turn, a payload+window
duplicate logs THROUGH; without one, it's still blocked exactly as before.

Covers all three log types (food / water / exercise) and the authoritative
DB-readback lines the gate-override relies on. Mirrors the stub style of
test_log_exercise_dedup_integration.py — SimpleNamespace rows, monkeypatched
writers, no real DB.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from handlers import tool_executor as TE


# ── helpers ──────────────────────────────────────────────────────────────────

def _food_row(id_, name="Cottage cheese", qty="150g", calories=162.0, ago_s=120):
    return SimpleNamespace(
        id=id_, parsed_food_name=name, quantity=qty, calories=calories,
        timestamp=datetime.utcnow() - timedelta(seconds=ago_s),
    )


def _analysis(name="Cottage cheese", cal=162.0, pro=18.0):
    """Stand-in for FoodAnalysis with the fields the food path reads."""
    return SimpleNamespace(
        calories=cal, protein=pro, carbs=6.0, fat=4.0,
        fiber=0.0, sugar=4.0, sodium=350.0,
        confidence="high", coach_note="solid protein hit",
        enrichment_source="usda",
    )


def _patch_food_writers(monkeypatch, today_log, write_count):
    """Patch _analyze_food + add_food_entry so the food path runs writer-free.
    add_food_entry appends a stub row to today_log.food_entries (mirroring the
    db.refresh the executor does) so the DB-readback can count it."""
    async def _fake_analyze(db, user, food_name, inp):
        return _analysis(name=food_name)

    async def _fake_add(db, daily_log_id, **kw):
        write_count["n"] += 1
        new_id = 2000 + write_count["n"]
        row = SimpleNamespace(
            id=new_id,
            parsed_food_name=kw.get("parsed_food_name"),
            quantity=kw.get("quantity"),
            calories=kw.get("calories"),
            timestamp=datetime.utcnow(),
        )
        today_log.food_entries.append(row)
        # keep the running total coherent for the result string
        today_log.total_calories = (today_log.total_calories or 0) + (kw.get("calories") or 0)
        today_log.total_protein = (today_log.total_protein or 0) + (kw.get("protein") or 0)
        return row

    async def _resolve_noop(*a, **kw):
        return None

    monkeypatch.setattr(TE, "_analyze_food", _fake_analyze)
    monkeypatch.setattr(TE, "add_food_entry", _fake_add)
    # resolve_pending_questions_for_logged_items is imported lazily from
    # db.queries inside the food path and wrapped in try/except; patch it at the
    # source so the stub db doesn't make it raise (harmless, but noisy).
    import db.queries as Q
    monkeypatch.setattr(Q, "resolve_pending_questions_for_logged_items", _resolve_noop)


def _food_log(prior_rows, cal=162.0, pro=18.0):
    return SimpleNamespace(
        id=1, date=None, food_entries=list(prior_rows),
        preferences=SimpleNamespace(calorie_target=2200, protein_target=200),
        total_calories=cal, total_protein=pro,
    )


def _user():
    return SimpleNamespace(
        id=26, timezone="UTC",
        preferences=SimpleNamespace(calorie_target=2200, protein_target=200),
    )


async def _refresh(*a, **kw):
    pass


# ── FOOD ─────────────────────────────────────────────────────────────────────

def test_merge_quantity_helper():
    m = TE._merge_quantity
    assert m("150g", "150g") == "300 g"
    assert m("1 bag", "1 bag") == "2 bag"
    assert m("2 bag", "1 bag") == "3 bag"        # keeps accumulating
    assert m("2 bags", "1 bag") == "3 bags"      # plural/singular fold, keeps unit spelling
    assert m("1 cup", "200g").startswith("2×")   # different units → readable fallback


@pytest.mark.asyncio
async def test_food_second_serving_with_add_intent_merges(monkeypatch):
    """RECONCILE-BEFORE-LOG (Danny 2026-07-02, the quest-chip): a 2nd cottage cheese
    inside the window WITH an add cue must BUMP the existing row's quantity + macros,
    not spawn a second entry (and not block). One row that reads '300 g', 324 cal."""
    user = _user()
    prior = _food_row(1322, "Cottage cheese", "150g", 162.0, ago_s=120)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    merged = {"calls": 0, "entry_id": None, "changes": None}

    async def _fake_update(db, entry_id, user_id, **changes):
        merged["calls"] += 1
        merged["entry_id"] = entry_id
        merged["changes"] = changes
        delta_cal = (changes.get("calories") or 0) - (prior.calories or 0)
        prior.quantity = changes.get("quantity")
        prior.calories = changes.get("calories")
        today_log.total_calories = (today_log.total_calories or 0) + delta_cal
        return prior

    monkeypatch.setattr(TE, "q_update_food_entry", _fake_update)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Cottage cheese", "quantity": "150g", "calories": 162},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="another cottage cheese",
    )
    assert wc["n"] == 0, "merge must NOT create a new row"
    assert merged["calls"] == 1, "add-intent 2nd serving must UPDATE the existing row"
    assert merged["entry_id"] == 1322
    assert merged["changes"]["quantity"] == "300 g"
    assert merged["changes"]["calories"] == 324.0
    assert result.startswith("Updated "), result
    assert "300 g" in result


@pytest.mark.asyncio
async def test_food_second_serving_without_add_intent_blocked(monkeypatch):
    """Same 2nd cottage cheese but the turn is a topic pivot (no add cue) — the
    payload+window dedup still blocks it (phantom-re-fire defense intact)."""
    user = _user()
    prior = _food_row(1322, "Cottage cheese", "150g", 162.0, ago_s=120)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Cottage cheese", "quantity": "150g", "calories": 162},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="connect apple health",
    )
    assert wc["n"] == 0, "no add-intent → dup must be blocked"
    assert result.startswith("Already on the board:"), result


@pytest.mark.asyncio
async def test_food_default_empty_message_still_blocks(monkeypatch):
    """Gate defaults closed: empty user_message keeps the legacy block."""
    user = _user()
    prior = _food_row(1322, "Cottage cheese", "150g", 162.0, ago_s=120)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Cottage cheese", "quantity": "150g", "calories": 162},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        # user_message omitted → ""
    )
    assert wc["n"] == 0
    assert result.startswith("Already on the board:"), result


@pytest.mark.asyncio
async def test_food_readback_after_normal_log(monkeypatch):
    """The DB readback appears on a NORMAL (non-dup) food log too, so the model
    always reconciles the count against truth."""
    user = _user()
    today_log = _food_log([])  # empty — first log of this item
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Greek yogurt", "quantity": "200g", "calories": 130},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="had some greek yogurt",
    )
    assert wc["n"] == 1
    assert "ON THE BOARD NOW (from the DB)" in result
    assert "1 × Greek yogurt" in result


# ── WATER ────────────────────────────────────────────────────────────────────

def _water_db(commit_count):
    async def _commit():
        commit_count["n"] += 1
    async def _refresh_(*a, **kw):
        pass
    return SimpleNamespace(commit=_commit, refresh=_refresh_)


@pytest.mark.asyncio
async def test_water_second_drink_with_add_intent_logs(monkeypatch):
    """'another glass' of the same amount within the window logs through."""
    user = _user()
    prior = SimpleNamespace(id=70, amount_ml=500, context="random",
                            timestamp=datetime.utcnow() - timedelta(seconds=120))
    today_log = SimpleNamespace(id=1, date=None, total_water_ml=500,
                                water_entries=[prior])
    writes = {"n": 0}

    async def _fake_add_water(db, user_id, daily_log_id, **kw):
        writes["n"] += 1
        today_log.water_entries.append(SimpleNamespace(
            id=900 + writes["n"], amount_ml=kw.get("amount_ml"),
            context=kw.get("context"), timestamp=datetime.utcnow()))

    monkeypatch.setattr(TE, "add_water_entry", _fake_add_water)

    # The dispatch now derives total_water_ml authoritatively by re-summing the
    # rows (recompute_water_total) instead of an in-place += — stub it to sum the
    # fake rows so the asserted total reflects both entries.
    async def _fake_recompute(db, daily_log_id):
        today_log.total_water_ml = sum(e.amount_ml for e in today_log.water_entries)
        return today_log.total_water_ml
    monkeypatch.setattr("db.queries.recompute_water_total", _fake_recompute)
    commits = {"n": 0}

    result = await TE._dispatch(
        "log_water", {"amount_ml": 500},
        user, today_log, db=_water_db(commits), source_type="ios",
        user_message="another glass",
    )
    assert writes["n"] == 1, "add-intent 2nd drink must write through"
    assert result.startswith("Logged "), result
    assert "ON THE BOARD NOW (from the DB)" in result
    # total grew to 1000ml across 2 entries
    assert "1000ml" in result


@pytest.mark.asyncio
async def test_water_second_drink_without_add_intent_blocked(monkeypatch):
    """Same 2nd drink, topic-pivot turn → blocked (no inflation of total)."""
    user = _user()
    prior = SimpleNamespace(id=70, amount_ml=500, context="random",
                            timestamp=datetime.utcnow() - timedelta(seconds=120))
    today_log = SimpleNamespace(id=1, date=None, total_water_ml=500,
                                water_entries=[prior])
    writes = {"n": 0}

    async def _fake_add_water(db, user_id, daily_log_id, **kw):
        writes["n"] += 1

    monkeypatch.setattr(TE, "add_water_entry", _fake_add_water)

    result = await TE._dispatch(
        "log_water", {"amount_ml": 500},
        user, today_log, db=_water_db({"n": 0}), source_type="ios",
        user_message="what's my protein at",
    )
    assert writes["n"] == 0, "no add-intent → water dup must be blocked"
    assert result.startswith("Already on the board:"), result
    assert today_log.total_water_ml == 500, "total must NOT be inflated"


# ── EXERCISE ─────────────────────────────────────────────────────────────────

def _ex_row(id_, name="Barbell Curl", sets=1, reps="10", weight=27.0, ago_s=20):
    return SimpleNamespace(
        id=id_, exercise_name=name, sets=sets, reps=reps, weight=weight,
        timestamp=datetime.utcnow() - timedelta(seconds=ago_s),
    )


@pytest.mark.asyncio
async def test_exercise_another_set_with_add_intent_appends(monkeypatch):
    """An identical set inside the 120s window WITH 'another set' is honored —
    since 2026-07-02 by APPENDING to the movement's session row (one entry that
    reads 2×'10,10'), not by inserting a parallel one-set row."""
    user = _user()
    prior = _ex_row(151, "Barbell Curl", 1, "10", 27.0, ago_s=20)
    prior.weights = None
    prior.cardio_type = None
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])
    wc = {"n": 0}
    upd = {"n": 0, "changes": None}

    async def _capture(db, daily_log_id, **kw):
        wc["n"] += 1

    async def _capture_update(db, entry_id, user_id, **changes):
        upd["n"] += 1
        upd["changes"] = changes
        return SimpleNamespace(id=entry_id, exercise_name="Barbell Curl",
                               sets=changes.get("sets"), reps=changes.get("reps"),
                               weight=27.0, weights=changes.get("weights"))

    monkeypatch.setattr(TE, "add_exercise_entry", _capture)
    monkeypatch.setattr(TE, "q_update_exercise_entry", _capture_update)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Barbell Curl", "sets": 1, "reps": "10",
         "weight": 60, "weight_unit": "lbs"},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="another set",
    )
    assert wc["n"] == 0, "add-intent identical set must grow the row, not insert"
    assert upd["n"] == 1
    assert upd["changes"]["reps"] == "10,10"
    assert upd["changes"]["sets"] == 2
    assert result.startswith("Appended the set"), result


@pytest.mark.asyncio
async def test_exercise_rapid_refire_without_add_intent_blocked(monkeypatch):
    """Same identical set inside the window with NO add cue (topic pivot) — the
    rapid-re-fire block still applies."""
    user = _user()
    prior = _ex_row(151, "Barbell Curl", 1, "10", 27.0, ago_s=20)
    today_log = SimpleNamespace(id=1, exercise_entries=[prior])
    wc = {"n": 0}

    async def _no_write(*a, **kw):
        wc["n"] += 1

    monkeypatch.setattr(TE, "add_exercise_entry", _no_write)

    result = await TE._dispatch(
        "log_exercise",
        {"exercise_name": "Barbell Curl", "sets": 1, "reps": "10",
         "weight": 60, "weight_unit": "lbs"},
        user, today_log, db=None, source_type="ios",
        user_message="what's next",
    )
    assert wc["n"] == 0, "no add-intent → rapid re-fire must be blocked"
    assert result.startswith("Already on the board:"), result


@pytest.mark.asyncio
async def test_food_carryover_item_not_named_blocked(monkeypatch):
    """CARRYOVER GUARD (the third-Barebells incident, Danny 2026-07-19): the
    user says "Also 150g ground turkey and 100g white rice"; the model drags
    the PRIOR turn's bar into the batch. The payload dedup whiffs (existing
    row reconciled to 2 bars / 400 cal vs the phantom 1 bar / 200 cal), but
    the item is absent from the message and on the board 57 min ago → block."""
    user = _user()
    prior = _food_row(1400, "Barebells Salty Peanut Protein Bar", "2 bars",
                      400.0, ago_s=57 * 60)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Barebells Salty Peanut Protein Bar",
         "quantity": "1 bar", "calories": 200},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="Also 150g ground turkey and 100g white rice",
    )
    assert wc["n"] == 0, "carried-over item must NOT write"
    assert result.startswith("Already on the board:"), result


@pytest.mark.asyncio
async def test_food_carryover_named_item_still_writes(monkeypatch):
    """Control: the same portion-mismatched shape but the user NAMED the item
    ("one more barebells bar...") — the add cue + name keeps the write path
    open (reconcile/merge, never a silent block)."""
    user = _user()
    prior = _food_row(1400, "Barebells Salty Peanut Protein Bar", "2 bars",
                      400.0, ago_s=57 * 60)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    merged = {"calls": 0}

    async def _fake_update(db, entry_id, user_id, **changes):
        merged["calls"] += 1
        prior.quantity = changes.get("quantity")
        prior.calories = changes.get("calories")
        return prior

    monkeypatch.setattr(TE, "q_update_food_entry", _fake_update)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Barebells Salty Peanut Protein Bar",
         "quantity": "1 bar", "calories": 200},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="one more barebells salty peanut bar",
    )
    assert not result.startswith("Already on the board:"), result
    assert wc["n"] == 1 or merged["calls"] == 1, "named repeat must land"


def test_effective_intent_message_combines_affirmation():
    """The cookies-and-caramel incident (2026-07-19): the log fires on the
    "Yes" turn answering a clarifying question — the gate must judge the
    prior message's item + add cue too."""
    from skills.logging_intent import effective_intent_message, turn_supports_log
    prior = "Also just had a cookies and caramel barbell"
    combined = effective_intent_message("Yes", prior)
    assert "cookies and caramel" in combined and "Yes" in combined
    # Longer real messages stand alone — no combining.
    assert effective_intent_message("connect apple health", prior) == "connect apple health"
    assert effective_intent_message("Yes", None) == "Yes"
    # RU affirmation combines too.
    assert "барбелл" in effective_intent_message("да", "ещё один барбелл")


@pytest.mark.asyncio
async def test_food_salmon_clarify_answer_and_venue_tokens(monkeypatch):
    """The salmon incident (2026-07-20 01:07Z): the clarify-ANSWER said '6 oz
    fish…' (never 'salmon'), and the venue parenthetical '(Cafe Luxembourg)'
    cross-matched the Niçoise from 19 min earlier — the carryover guard ate
    the plate's centerpiece. With the answer combined against the question's
    exchange and venue tokens stripped, the salmon writes."""
    from skills.logging_intent import effective_intent_message
    user = _user()
    prior = _food_row(1939, "Niçoise salad with shrimp (Cafe Luxembourg)",
                      "1 salad", 380.0, ago_s=19 * 60)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    gate_msg = effective_intent_message(
        "6 oz fish and yes everything else didn't leave some of the corn salad",
        "I had the full salmon plate 2 pieces French bread and like 5 French fries",
        prior_assistant="The salmon, was it a full standard entrée portion?")
    result = await TE._dispatch(
        "log_food",
        {"food_name": "Grilled salmon (Cafe Luxembourg)",
         "quantity": "6 oz", "calories": 350},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message=gate_msg,
    )
    assert not result.startswith("Already on the board:"), result
    assert wc["n"] == 1, "the salmon must write"


@pytest.mark.asyncio
async def test_food_venue_token_alone_never_matches_carryover(monkeypatch):
    """Even WITHOUT the combiner (gate judges the bare answer), the venue
    parenthetical must not manufacture an on-board match — unnamed + no
    same-item on board falls through to the normal write path."""
    user = _user()
    prior = _food_row(1939, "Niçoise salad with shrimp (Cafe Luxembourg)",
                      "1 salad", 380.0, ago_s=19 * 60)
    today_log = _food_log([prior])
    wc = {"n": 0}
    _patch_food_writers(monkeypatch, today_log, wc)

    result = await TE._dispatch(
        "log_food",
        {"food_name": "Grilled salmon (Cafe Luxembourg)",
         "quantity": "6 oz", "calories": 350},
        user, today_log, db=SimpleNamespace(refresh=_refresh), source_type="ios",
        user_message="6 oz fish and yes everything else",
    )
    assert not result.startswith("Already on the board:"), result
    assert wc["n"] == 1
