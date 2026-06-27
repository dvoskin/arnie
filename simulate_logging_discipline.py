"""
HIGH-FREQUENCY logging-discipline stress simulation — adversarial validator.

Drives the REAL code paths deterministically (no LLM, so thousands of iterations
cost nothing) to try to BREAK the logging-discipline fix across all four domains:

  • food / water / exercise — the shared TURN-INTENT GATE (skills/logging_intent.py,
    wired in handlers/tool_executor._dispatch): an explicit add-cue in the CURRENT
    user turn ("another", "one more", "a second cottage cheese", "2nd Barebells",
    "twice", "ещё один", "2 more", "x2") HONORS a real repeat (2nd row written) even
    when payload+window matches; a phantom re-fire on a topic pivot (no cue) is
    BLOCKED; a retry/re-send ("log the elmhurst again") is BLOCKED.
  • authoritative DB readback — a successful food/water log appends
    "ON THE BOARD NOW (from the DB): ..." counted from the DB; exercise has the
    analogous "ON THE BOARD NOW (authoritative, from the DB): ..." set-count line.
  • exercise roll-up — a re-stated running set list ('12'→'12,12'→'12,12,10')
    UPSERTs ONE row that grows, not N rows.
  • weight source-aware (db/queries.add_body_metric) — manual + apple_health coexist
    as ONE row each per (user, local day); a 2nd apple_health folds; a manual
    correction updates in place; the headline + users.current_weight_kg is MANUAL.
  • leak sweep — no dedup-result string (the 2026-06-27 leak surface) contains
    YOUR REPLY / [# / [TODAY] / dedup guard / force it through / never tell, and the
    entry id is the bare '#id' form, never the bracketed '[#id]'.

The sim calls `_dispatch` (the per-tool executor) and `add_body_metric` directly
with synthetic (tool_call_input, user_message) pairs, and asserts DB ground truth
after each turn (row counts, which rows exist, current_weight_kg, readback string,
no leak tokens).

It also CARRIES ITS OWN PROOF: with --prove-regression it disables one fix at a
time (neuter the gate-override; make add_body_metric source-blind) and confirms the
right assertions FAIL, then restores. A sim that stays green with the fixes off is
worthless.

Run from arnie/ with the py3.11 venv:
    <venv>/bin/python simulate_logging_discipline.py                  # full run
    <venv>/bin/python simulate_logging_discipline.py --iters 4000     # heavier
    <venv>/bin/python simulate_logging_discipline.py --prove-regression
    <venv>/bin/python simulate_logging_discipline.py --quiet          # summary only
"""
from __future__ import annotations

import argparse
import asyncio
import random
import sys
from datetime import date, datetime, timedelta, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

# ── Forbidden tokens the user-visible dedup-result strings must never carry.
#    These are exactly the 2026-06-27 leak: an "Already on the board" dup string
#    that carried model-facing directives ("YOUR REPLY: ...") + the bracketed
#    "[#id]" token, both echoed verbatim to the user.
#
#    SCOPE — this sweep targets the strings a user can SEE: the dedup-block result
#    ("Already on the board: ...") and the roll-up result ("Updated the running
#    set ..."). By contract those are DATA-ONLY (see the format_dedup_result /
#    format_rollup_result docstrings in skills/*/dedup.py). It does NOT target the
#    SUCCESS directive results (the normal log_food/exercise/water tool result),
#    which legitimately embed "YOUR REPLY:" as a MODEL-FACING instruction payload
#    — that string is consumed by the follow-up LLM and never surfaced raw. (The
#    real 06-27 incident was the dedup string leaking, not the success directive.)
FORBIDDEN_TOKENS = ("YOUR REPLY", "[#", "[TODAY]", "dedup guard", "force it through",
                    "never tell")


def _is_user_visible_dedup(s: str) -> bool:
    """True when a tool-result string is one of the user-visible dedup/rollup
    strings (the leak surface), vs a model-facing SUCCESS directive."""
    s = s if isinstance(s, str) else str(s)
    return s.startswith("Already on the board") or s.startswith("Updated the running set")


class Results:
    def __init__(self, quiet=False):
        self.passed = 0
        self.failed = 0
        self.quiet = quiet
        self.failures: list[str] = []
        # Aggregate per-category counters for the summary.
        self.counts: dict[str, int] = {}

    def check(self, label, cond, detail="", category=None):
        if category:
            self.counts[category] = self.counts.get(category, 0) + 1
        if cond:
            self.passed += 1
            if not self.quiet:
                print(f"    {G}✓{X} {label}" + (f" {D}{detail}{X}" if detail else ""))
        else:
            self.failed += 1
            self.failures.append(f"{label} :: {detail}")
            # Always print failures, even in quiet mode.
            print(f"    {R}✗ {label}{X}" + (f" {R}{detail}{X}" if detail else ""))
        return cond


def head(t):
    print(f"\n{B}{C}{'='*70}{X}\n{B}{C} {t}{X}\n{B}{C}{'='*70}{X}")


def assert_no_leak(res, label, s, category="leak"):
    """Leak sweep over a tool-result string.

    • If it's a user-visible dedup/rollup string ("Already on the board" /
      "Updated the running set"), sweep the FULL forbidden-token list — this is
      the 06-27 leak surface and must be byte-clean.
    • Otherwise (a model-facing SUCCESS directive that legitimately embeds
      "YOUR REPLY:"), only assert the bracketed "[#id]" marker is absent — that
      raw internal token must never appear ANYWHERE, success or dup."""
    s = s if isinstance(s, str) else str(s)
    if _is_user_visible_dedup(s):
        hit = [tok for tok in FORBIDDEN_TOKENS if tok in s]
        return res.check(f"{label}: dup string no leak tokens", not hit,
                         f"leaked {hit} in {s[:90]!r}" if hit else "", category=category)
    # success directive — only the bracket id-marker is forbidden here
    return res.check(f"{label}: no bracketed [#id marker", "[#" not in s,
                     f"found [# in {s[:90]!r}" if "[#" in s else "", category=category)


# ─────────────────────────────────────────────────────────────────────────────
# DB fixture — in-memory SQLite + StaticPool + hand-rolled _migrate (same pattern
# as simulate_live_workout.py). A fresh user per scenario keeps every iteration
# independent; the engine is shared so we don't pay create_all repeatedly.
# ─────────────────────────────────────────────────────────────────────────────
class Harness:
    def __init__(self):
        self.engine = None
        self.Maker = None
        self._uid_seq = 0

    async def setup(self):
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
        from sqlalchemy.pool import StaticPool
        from db.database import Base, _migrate
        from db import models  # noqa: register mappers

        self.engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _migrate(conn)
        from sqlalchemy.ext.asyncio import AsyncSession as _AS
        self.Maker = async_sessionmaker(self.engine, class_=_AS, expire_on_commit=False)

    async def new_user(self, tz="America/New_York", cur_weight=86.0, **kw):
        """Create a fresh user + today's DailyLog. Returns user_id."""
        from db.models import User, UserPreferences
        from db.queries import get_or_create_webhook_token, get_or_create_today_log
        self._uid_seq += 1
        async with self.Maker() as db:
            u = User(
                telegram_id=f"LOGDISC_{self._uid_seq:06d}",
                name="Danny", age=37, sex="male",
                height_cm=178.0, current_weight_kg=cur_weight, goal_weight_kg=80.0,
                primary_goal="cut", training_experience="advanced",
                injuries="none", timezone=tz, onboarding_completed=True,
            )
            db.add(u)
            db.add(UserPreferences(user=u, calorie_target=kw.get("cal", 2126),
                                   protein_target=kw.get("pro", 190),
                                   coaching_style="direct", accountability_level="high",
                                   wake_time="07:00", sleep_time="23:30"))
            await db.flush()
            uid = u.id
            await get_or_create_webhook_token(db, u.id)
            await get_or_create_today_log(db, uid, tz)
            await db.commit()
        return uid

    async def session(self):
        return self.Maker()

    async def reloaded(self, db, uid):
        """User + freshly-loaded today_log (food/exercise/water selectinloaded)."""
        from db.queries import reload_user, get_today_log
        user = await reload_user(db, uid)
        today_log = await get_today_log(db, uid, user.timezone)
        return user, today_log


# ─────────────────────────────────────────────────────────────────────────────
# Turn driver — runs ONE log_* tool call through the real execute_tool_calls path
# (which snapshots pre-existing IDs and calls _dispatch). Using execute_tool_calls
# (not bare _dispatch) exercises the production snapshot/telemetry wrapper too.
# Returns the tool-result string.
# ─────────────────────────────────────────────────────────────────────────────
async def run_log_turn(H, uid, tool_name, tool_input, user_message):
    from handlers.tool_executor import execute_tool_calls
    async with await H.session() as db:
        user, today_log = await H.reloaded(db, uid)
        tc = {"name": tool_name, "input": dict(tool_input)}
        results = await execute_tool_calls(
            [tc], user, today_log, db, source_type="text", user_message=user_message,
        )
        await db.commit()
        return results.get(tool_name, "")


async def db_food_rows(H, uid):
    from sqlalchemy import select
    from db.models import FoodEntry, DailyLog
    async with await H.session() as db:
        rows = (await db.execute(
            select(FoodEntry).join(DailyLog, FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == uid).order_by(FoodEntry.id))).scalars().all()
        return rows


async def db_food_rows_named(H, uid, name):
    from skills.nutrition.food_dedup import normalize_food_name as nfn
    key = nfn(name)
    rows = await db_food_rows(H, uid)
    return [r for r in rows if nfn(r.parsed_food_name or "") == key]


async def db_water_rows(H, uid):
    from sqlalchemy import select
    from db.models import WaterEntry
    async with await H.session() as db:
        rows = (await db.execute(
            select(WaterEntry).where(WaterEntry.user_id == uid)
            .order_by(WaterEntry.id))).scalars().all()
        return rows


async def db_exercise_rows(H, uid, name=None):
    from sqlalchemy import select
    from db.models import ExerciseEntry, DailyLog
    from skills.fitness.exercise_dedup import normalize_exercise_name as nx
    async with await H.session() as db:
        rows = (await db.execute(
            select(ExerciseEntry).join(DailyLog, ExerciseEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == uid).order_by(ExerciseEntry.id))).scalars().all()
    if name is None:
        return rows
    key = nx(name)
    return [r for r in rows if nx(r.exercise_name or "") == key]


async def db_weight_rows(H, uid):
    from sqlalchemy import select
    from db.models import BodyMetric
    async with await H.session() as db:
        rows = (await db.execute(
            select(BodyMetric).where(BodyMetric.user_id == uid)
            .order_by(BodyMetric.timestamp))).scalars().all()
        return rows


async def db_current_weight(H, uid):
    from db.queries import reload_user
    async with await H.session() as db:
        u = await reload_user(db, uid)
        return u.current_weight_kg


# ─────────────────────────────────────────────────────────────────────────────
# Randomized payload generators
# ─────────────────────────────────────────────────────────────────────────────
FOODS = [
    ("cottage cheese", "1 cup", 220), ("barebells bar", "1 bar", 200),
    ("greek yogurt", "170g", 100), ("chicken breast", "150g", 230),
    ("elmhurst protein", "1 carton", 130), ("oatmeal", "1 cup", 150),
    ("protein shake", "1 scoop", 120), ("banana", "1 medium", 105),
    ("almonds", "28g", 160), ("rice", "1 cup", 205),
]
# Add/repeat cues that MUST open the gate. Restricted to phrasings the contract
# guarantees: "another", "one more", "a second X", "2nd", "twice", "ещё один",
# "2 more" (numeral), "x2", plus the bilingual/serving-noun forms the gate
# documents (вторую, "a couple more", "double", "second helping of", "extra").
# NOTE: spelled-out "two more"/"three more" are deliberately NOT here — the gate
# only recognizes the NUMERAL "N more", not the word form. That gap is reported
# as a finding, not silently masked by including a phrasing that happens to pass.
ADD_CUES = [
    "another {f}", "one more {f}", "a second {f}", "2nd {f}", "{f} again twice",
    "x2 {f}", "had {f} twice", "ещё один {f}", "вторую {f}",
    "a couple more {f}", "2 more {f}", "double {f}", "second helping of {f}",
    "third serving of {f}", "extra {f}",
]
# CUES that must NOT open the gate (retry / re-send / topic pivot / bare mention).
NON_CUES_RETRY = [
    "log the {f} again", "re-log {f}", "log {f}",  # bare mention / retry
    "{f}", "you forgot the {f}", "did you get the {f}",
    "снова {f}", "опять {f}",  # "again" RU — retry not add
]
PIVOTS = [
    "connect apple health", "link my apple health", "what's my protein today",
    "how am i doing on calories", "show me my week", "wait a second",
    "give me a second", "no more food for now",
]


def cap(s):
    return s[:1].upper() + s[1:] if s else s


# ─────────────────────────────────────────────────────────────────────────────
# FOOD scenarios
# ─────────────────────────────────────────────────────────────────────────────
async def food_scenarios(H, res, rng, iters):
    head(f"FOOD — turn-intent gate ({iters} randomized iterations)")
    for i in range(iters):
        fname, qty, cal = rng.choice(FOODS)
        uid = await H.new_user()
        # 1) initial log — always writes
        r0 = await run_log_turn(H, uid, "log_food",
                                {"food_name": fname, "quantity": qty, "calories": cal},
                                f"had {fname}")
        rows = await db_food_rows_named(H, uid, fname)
        ok0 = res.check(f"[food#{i}] initial {fname!r} → 1 row", len(rows) == 1,
                        f"got {len(rows)}", category="food_initial")
        assert_no_leak(res, f"[food#{i}] initial result", r0, category="food_leak")
        # readback present + DB-accurate
        res.check(f"[food#{i}] initial readback present",
                  "ON THE BOARD NOW (from the DB)" in r0 and "1 × " in r0,
                  f"missing/incorrect in {r0[:80]!r}", category="food_readback")

        branch = rng.random()
        if branch < 0.45:
            # ADD-CUE repeat → MUST land a 2nd row (gate opens)
            cue = rng.choice(ADD_CUES).format(f=fname)
            r1 = await run_log_turn(H, uid, "log_food",
                                    {"food_name": fname, "quantity": qty, "calories": cal},
                                    cue)
            rows = await db_food_rows_named(H, uid, fname)
            res.check(f"[food#{i}] add-cue {cue!r} → 2 rows", len(rows) == 2,
                      f"got {len(rows)} (result={r1[:70]!r})", category="food_addcue")
            # readback should now count 2
            res.check(f"[food#{i}] add-cue readback shows 2",
                      "2 × " in r1, f"result={r1[:90]!r}", category="food_readback2")
            assert_no_leak(res, f"[food#{i}] add-cue result", r1, category="food_leak")
        elif branch < 0.75:
            # PHANTOM re-fire on a topic pivot → MUST stay 1 row (gate closed)
            pivot = rng.choice(PIVOTS)
            r1 = await run_log_turn(H, uid, "log_food",
                                    {"food_name": fname, "quantity": qty, "calories": cal},
                                    pivot)
            rows = await db_food_rows_named(H, uid, fname)
            res.check(f"[food#{i}] phantom-on-pivot {pivot!r} → still 1 row",
                      len(rows) == 1, f"got {len(rows)}", category="food_phantom")
            res.check(f"[food#{i}] phantom blocked → 'Already on the board'",
                      r1.startswith("Already on the board"),
                      f"result={r1[:70]!r}", category="food_phantom_msg")
            assert_no_leak(res, f"[food#{i}] phantom dup string", r1, category="food_leak")
            # the bare #id, never the bracketed [#id]
            res.check(f"[food#{i}] dup string uses bare #id (no [#)",
                      "[#" not in r1, f"result={r1[:70]!r}", category="food_idfmt")
        else:
            # RETRY / re-send / bare mention → MUST stay 1 row (gate closed)
            cue = rng.choice(NON_CUES_RETRY).format(f=fname)
            r1 = await run_log_turn(H, uid, "log_food",
                                    {"food_name": fname, "quantity": qty, "calories": cal},
                                    cue)
            rows = await db_food_rows_named(H, uid, fname)
            res.check(f"[food#{i}] retry {cue!r} → still 1 row", len(rows) == 1,
                      f"got {len(rows)} (result={r1[:70]!r})", category="food_retry")
            assert_no_leak(res, f"[food#{i}] retry dup string", r1, category="food_leak")


async def food_danny_replay(H, res):
    head("FOOD — Danny's exact 2026-06-27 cottage-cheese + Barebells replay")
    # Sequence: log cottage cheese, then "second cottage cheese" → 2 rows.
    # Then log a barebells, then "a second barebells" → 2 rows. These are the
    # exact phrasings the numeral-only draft missed and that ate both servings.
    uid = await H.new_user()
    await run_log_turn(H, uid, "log_food",
                       {"food_name": "cottage cheese", "quantity": "1 cup", "calories": 220},
                       "cottage cheese for breakfast")
    r = await run_log_turn(H, uid, "log_food",
                           {"food_name": "cottage cheese", "quantity": "1 cup", "calories": 220},
                           "second cottage cheese")
    rows = await db_food_rows_named(H, uid, "cottage cheese")
    res.check("[danny] 'second cottage cheese' → 2 rows land", len(rows) == 2,
              f"got {len(rows)} (result={r[:70]!r})", category="danny_food")
    res.check("[danny] cottage cheese readback shows 2", "2 × " in r,
              f"result={r[:90]!r}", category="danny_food")

    await run_log_turn(H, uid, "log_food",
                       {"food_name": "barebells bar", "quantity": "1 bar", "calories": 200},
                       "a barebells")
    r = await run_log_turn(H, uid, "log_food",
                           {"food_name": "barebells bar", "quantity": "1 bar", "calories": 200},
                           "a second barebells")
    rows = await db_food_rows_named(H, uid, "barebells bar")
    res.check("[danny] 'a second barebells' → 2 rows land", len(rows) == 2,
              f"got {len(rows)} (result={r[:70]!r})", category="danny_food")

    # And confirm a retry on the SAME morning still blocks (no over-open).
    r = await run_log_turn(H, uid, "log_food",
                           {"food_name": "barebells bar", "quantity": "1 bar", "calories": 200},
                           "log the barebells again")
    rows = await db_food_rows_named(H, uid, "barebells bar")
    res.check("[danny] 'log the barebells again' (retry) → still 2 rows", len(rows) == 2,
              f"got {len(rows)} (result={r[:70]!r})", category="danny_food")


# ─────────────────────────────────────────────────────────────────────────────
# WATER scenarios
# ─────────────────────────────────────────────────────────────────────────────
async def water_scenarios(H, res, rng, iters):
    head(f"WATER — turn-intent gate ({iters} randomized iterations)")
    for i in range(iters):
        ml = rng.choice([240, 350, 473, 500, 591, 750])
        uid = await H.new_user()
        r0 = await run_log_turn(H, uid, "log_water", {"amount_ml": ml}, "had some water")
        rows = await db_water_rows(H, uid)
        res.check(f"[water#{i}] initial → 1 row", len(rows) == 1, f"got {len(rows)}",
                  category="water_initial")
        res.check(f"[water#{i}] readback present",
                  "ON THE BOARD NOW (from the DB)" in r0, f"result={r0[:80]!r}",
                  category="water_readback")
        assert_no_leak(res, f"[water#{i}] initial result", r0, category="water_leak")

        branch = rng.random()
        if branch < 0.45:
            cue = rng.choice(["another glass", "one more glass of water", "ещё стакан",
                              "2 more glasses", "a second glass", "x2 water"])
            r1 = await run_log_turn(H, uid, "log_water", {"amount_ml": ml}, cue)
            rows = await db_water_rows(H, uid)
            res.check(f"[water#{i}] add-cue {cue!r} → 2 rows", len(rows) == 2,
                      f"got {len(rows)} (result={r1[:70]!r})", category="water_addcue")
            assert_no_leak(res, f"[water#{i}] add-cue result", r1, category="water_leak")
        elif branch < 0.75:
            pivot = rng.choice(PIVOTS)
            r1 = await run_log_turn(H, uid, "log_water", {"amount_ml": ml}, pivot)
            rows = await db_water_rows(H, uid)
            res.check(f"[water#{i}] phantom-on-pivot {pivot!r} → still 1 row",
                      len(rows) == 1, f"got {len(rows)}", category="water_phantom")
            res.check(f"[water#{i}] phantom blocked msg",
                      r1.startswith("Already on the board"), f"result={r1[:70]!r}",
                      category="water_phantom_msg")
            assert_no_leak(res, f"[water#{i}] phantom dup string", r1, category="water_leak")
        else:
            r1 = await run_log_turn(H, uid, "log_water", {"amount_ml": ml},
                                    "log that water again")
            rows = await db_water_rows(H, uid)
            res.check(f"[water#{i}] retry → still 1 row", len(rows) == 1,
                      f"got {len(rows)} (result={r1[:70]!r})", category="water_retry")
            assert_no_leak(res, f"[water#{i}] retry dup string", r1, category="water_leak")


# ─────────────────────────────────────────────────────────────────────────────
# EXERCISE scenarios — roll-up + add-cue + authoritative count
# ─────────────────────────────────────────────────────────────────────────────
# Names that canonicalize to THEMSELVES (so the sim's name-based DB lookups are
# exact). "Cable Row" is deliberately excluded — the catalog aliases it to
# "Seated Cable Row", which is correct behavior but would muddy a row-count
# assertion keyed on the raw name (that aliasing is not part of THIS fix's
# contract; it has its own tests in test_exercise_dedup).
EXERCISES = [
    ("Lat Pulldown", 79.0), ("Upright Row", 45.0), ("Face Pull", 31.0),
    ("Bench Press", 60.0), ("Overhead Press", 50.0),
]


async def exercise_scenarios(H, res, rng, iters):
    head(f"EXERCISE — roll-up + add-cue + authoritative count ({iters} iterations)")
    for i in range(iters):
        ename, wlb = rng.choice(EXERCISES)
        rep = rng.choice([8, 10, 12, 15])
        uid = await H.new_user()

        branch = rng.random()
        if branch < 0.5:
            # ROLL-UP: re-state the running list '12'→'12,12'→'12,12,N' → 1 row grows.
            r1 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 1, "reps": str(rep),
                                     "weight": wlb, "weight_unit": "lbs"},
                                    f"{rep}x{int(wlb)} {ename} first set")
            r2 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 2,
                                     "reps": f"{rep},{rep}", "weight": wlb,
                                     "weight_unit": "lbs"},
                                    "second set same")
            last_rep = rep - rng.choice([0, 2])
            r3 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 3,
                                     "reps": f"{rep},{rep},{last_rep}", "weight": wlb,
                                     "weight_unit": "lbs"},
                                    "third set")
            rows = await db_exercise_rows(H, uid, ename)
            res.check(f"[ex#{i}] roll-up {ename!r} → ONE row (grows)", len(rows) == 1,
                      f"got {len(rows)} rows", category="ex_rollup")
            if rows:
                res.check(f"[ex#{i}] roll-up final row = 3 sets",
                          (rows[0].sets or 0) == 3,
                          f"sets={rows[0].sets} reps={rows[0].reps!r}",
                          category="ex_rollup_sets")
            # roll-up result names ONE entry growing, no new row
            res.check(f"[ex#{i}] roll-up result says 'one entry grew'",
                      "one entry grew, no new row" in r3 or "Updated the running set" in r3,
                      f"result={r3[:80]!r}", category="ex_rollup_msg")
            for rr in (r1, r2, r3):
                assert_no_leak(res, f"[ex#{i}] roll-up step", rr, category="ex_leak")
        elif branch < 0.8:
            # ADD-CUE: identical single set re-logged WITH a cue → honored (2 rows).
            r1 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 1, "reps": str(rep),
                                     "weight": wlb, "weight_unit": "lbs"},
                                    f"{rep}x{int(wlb)} {ename}")
            cue = rng.choice(["another set", "one more set", "second set same weight",
                              "2 more sets", "ещё подход", "did that twice"])
            r2 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 1, "reps": str(rep),
                                     "weight": wlb, "weight_unit": "lbs"},
                                    cue)
            rows = await db_exercise_rows(H, uid, ename)
            # add-cue honors → 2 rows (gate opens; the equality-dup would block).
            res.check(f"[ex#{i}] add-cue {cue!r} → 2 rows (honored)", len(rows) == 2,
                      f"got {len(rows)} (result={r2[:70]!r})", category="ex_addcue")
            # authoritative board count = 2 sets across the two single-set rows
            res.check(f"[ex#{i}] authoritative set count = 2 sets",
                      "2 sets" in r2, f"result={r2[:90]!r}", category="ex_count")
            assert_no_leak(res, f"[ex#{i}] add-cue result", r2, category="ex_leak")
        else:
            # PHANTOM: identical single set re-fired on a topic pivot → blocked (1 row).
            r1 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 1, "reps": str(rep),
                                     "weight": wlb, "weight_unit": "lbs"},
                                    f"{rep}x{int(wlb)} {ename}")
            pivot = rng.choice(PIVOTS)
            r2 = await run_log_turn(H, uid, "log_exercise",
                                    {"exercise_name": ename, "sets": 1, "reps": str(rep),
                                     "weight": wlb, "weight_unit": "lbs"},
                                    pivot)
            rows = await db_exercise_rows(H, uid, ename)
            res.check(f"[ex#{i}] phantom-on-pivot {pivot!r} → still 1 row",
                      len(rows) == 1, f"got {len(rows)}", category="ex_phantom")
            res.check(f"[ex#{i}] phantom blocked msg",
                      r2.startswith("Already on the board"), f"result={r2[:70]!r}",
                      category="ex_phantom_msg")
            assert_no_leak(res, f"[ex#{i}] phantom dup string", r2, category="ex_leak")
            res.check(f"[ex#{i}] dup string uses bare #id (no [#)", "[#" not in r2,
                      f"result={r2[:70]!r}", category="ex_idfmt")


# ─────────────────────────────────────────────────────────────────────────────
# WEIGHT scenarios — source-aware add_body_metric
# ─────────────────────────────────────────────────────────────────────────────
async def weight_scenarios(H, res, rng, iters):
    head(f"WEIGHT — source-aware add_body_metric ({iters} randomized iterations)")
    from db.queries import add_body_metric
    for i in range(iters):
        uid = await H.new_user(cur_weight=86.0)
        manual_kg = round(rng.uniform(80.0, 95.0), 2)
        # apple_health within a normal scale/HealthKit discrepancy (the 0.55 kg gap
        # that escaped the old <0.06 fold), but always > the fold so it's a real test.
        ah_kg = round(manual_kg + rng.choice([-1, 1]) * rng.uniform(0.2, 0.9), 2)
        order = rng.random() < 0.5  # randomize which source lands first

        async with await H.session() as db:
            if order:
                await add_body_metric(db, uid, manual_kg, source="manual",
                                      context="morning_fasted")
                await add_body_metric(db, uid, ah_kg, source="apple_health")
            else:
                await add_body_metric(db, uid, ah_kg, source="apple_health")
                await add_body_metric(db, uid, manual_kg, source="manual",
                                      context="morning_fasted")
            await db.commit()

        rows = await db_weight_rows(H, uid)
        res.check(f"[wt#{i}] manual+apple_health same day → exactly 2 rows",
                  len(rows) == 2, f"got {len(rows)}", category="wt_tworows")
        sources = sorted((r.source or "manual") for r in rows)
        res.check(f"[wt#{i}] one row per source", sources == ["apple_health", "manual"],
                  f"sources={sources}", category="wt_sources")
        cw = await db_current_weight(H, uid)
        res.check(f"[wt#{i}] headline (current_weight_kg) = MANUAL", cw == manual_kg,
                  f"current={cw} manual={manual_kg} ah={ah_kg}", category="wt_headline")

        # A 2nd apple_health folds; a manual correction updates in place.
        ah2 = round(ah_kg + rng.uniform(-0.3, 0.3), 2)
        manual2 = round(manual_kg + rng.uniform(-0.5, 0.5), 2)
        async with await H.session() as db:
            m_ah = await add_body_metric(db, uid, ah2, source="apple_health")
            m_mn = await add_body_metric(db, uid, manual2, source="manual")
            await db.commit()
        rows = await db_weight_rows(H, uid)
        res.check(f"[wt#{i}] 2nd apple_health + manual correction → STILL 2 rows",
                  len(rows) == 2, f"got {len(rows)}", category="wt_fold")
        by_src = {(r.source or "manual"): r.weight_kg for r in rows}
        res.check(f"[wt#{i}] apple_health row folded to latest", by_src.get("apple_health") == ah2,
                  f"ah row={by_src.get('apple_health')} expected={ah2}", category="wt_fold_val")
        res.check(f"[wt#{i}] manual row updated in place", by_src.get("manual") == manual2,
                  f"manual row={by_src.get('manual')} expected={manual2}", category="wt_corr")
        cw = await db_current_weight(H, uid)
        res.check(f"[wt#{i}] headline = corrected MANUAL", cw == manual2,
                  f"current={cw} expected={manual2}", category="wt_headline2")


async def weight_danny_replay(H, res):
    head("WEIGHT — Danny's exact 4-write oscillation replay (the incident)")
    from db.queries import add_body_metric
    from api.native_data import _weight_block
    from db.queries import reload_user
    uid = await H.new_user(cur_weight=86.0)
    async with await H.session() as db:
        await add_body_metric(db, uid, 84.73, source="manual", context="morning_fasted")
        await add_body_metric(db, uid, 85.28, source="apple_health")
        await add_body_metric(db, uid, 85.28, source="manual")        # "188 actually"
        await add_body_metric(db, uid, 85.10, source="apple_health")  # HealthKit re-deliver
        await db.commit()
    rows = await db_weight_rows(H, uid)
    res.check("[danny-wt] 4 writes → exactly 2 rows", len(rows) == 2,
              f"got {len(rows)}", category="danny_wt")
    by_src = {(r.source or "manual"): r.weight_kg for r in rows}
    res.check("[danny-wt] rows = {manual:85.28, apple_health:85.10}",
              by_src == {"manual": 85.28, "apple_health": 85.10},
              f"got {by_src}", category="danny_wt")
    cw = await db_current_weight(H, uid)
    res.check("[danny-wt] headline = corrected manual 85.28", cw == 85.28,
              f"current={cw}", category="danny_wt")
    # Dashboard headline path
    async with await H.session() as db:
        u = await reload_user(db, uid)
        weights = await db_weight_rows(H, uid)
        block = _weight_block(weights, u)
    res.check("[danny-wt] dashboard: ONE point for the shared day",
              block is not None and len(block["recent"]) == 1,
              f"recent={None if not block else block.get('recent')}", category="danny_wt")
    res.check("[danny-wt] dashboard headline kg = manual (85.3)",
              block is not None and block["latest"]["kg"] == 85.3,
              f"latest={None if not block else block.get('latest')}", category="danny_wt")

    # Repeated apple_health folds (idempotent) — fire it 20x, still 1 ah row.
    uid2 = await H.new_user(cur_weight=86.0)
    async with await H.session() as db:
        for k in range(20):
            await add_body_metric(db, uid2, round(85.0 + k * 0.01, 2), source="apple_health")
        await db.commit()
    rows = await db_weight_rows(H, uid2)
    res.check("[danny-wt] 20x apple_health re-deliver → 1 row (idempotent)",
              len(rows) == 1, f"got {len(rows)}", category="danny_wt")


# ─────────────────────────────────────────────────────────────────────────────
# INTERLEAVE / BURST — rapid mixed sequences across all domains for ONE user.
# Shakes out ordering/state bugs (e.g. a food log corrupting the water snapshot).
# ─────────────────────────────────────────────────────────────────────────────
async def interleave_burst(H, res, rng, iters):
    head(f"INTERLEAVE/BURST — rapid mixed cross-domain sequences ({iters} bursts)")
    from db.queries import add_body_metric
    for i in range(iters):
        uid = await H.new_user(cur_weight=86.0)
        # Expected DB ground truth we maintain alongside. Each FRESH log uses a
        # UNIQUE payload so there's never an accidental dedup collision; repeats
        # are issued explicitly with a KNOWN outcome (add-cue → +1, pivot →
        # blocked), so the bookkeeping is exact rather than probabilistic.
        exp_food: dict[str, int] = {}
        exp_water = 0
        exp_ex: dict[str, int] = {}
        last_food: dict[str, tuple] = {}   # fname -> (qty, cal)
        last_water_ml = None
        last_ex: dict[str, tuple] = {}      # ename -> (rep, wlb)
        uniq = 0  # bumps food calories / water ml so distinct logs never collide
        n = rng.randint(12, 20)
        for _ in range(n):
            d = rng.choice(["food", "food", "water", "water", "exercise", "weight"])
            if d == "food":
                fname, qty, _basecal = rng.choice(FOODS)
                # Decide: repeat the SAME payload (with a known outcome) or a fresh
                # distinct one. Only repeat if we've logged this exact (qty,cal).
                if fname in last_food and rng.random() < 0.5:
                    pqty, pcal = last_food[fname]
                    if rng.random() < 0.5:  # add-cue → honored (+1)
                        cue = rng.choice(ADD_CUES).format(f=fname)
                        await run_log_turn(H, uid, "log_food",
                                           {"food_name": fname, "quantity": pqty, "calories": pcal}, cue)
                        exp_food[fname] = exp_food.get(fname, 0) + 1
                    else:  # pivot/retry → blocked (no change)
                        block = rng.choice(PIVOTS + ["log the {f} again".format(f=fname)])
                        await run_log_turn(H, uid, "log_food",
                                           {"food_name": fname, "quantity": pqty, "calories": pcal}, block)
                else:  # fresh, UNIQUE payload → always writes
                    # Distinct QUANTITY string guarantees no dedup collision: the
                    # food dedup requires an EXACT quantity match, so a unique qty
                    # can never false-dedup against a prior fresh log of the same
                    # food (calorie-only uniqueness wasn't enough — two fresh logs
                    # a few cal apart fall inside the ±15% calorie tolerance).
                    uniq += 1
                    uqty = f"{qty} #{uniq}"
                    cal = _basecal + uniq
                    await run_log_turn(H, uid, "log_food",
                                       {"food_name": fname, "quantity": uqty, "calories": cal},
                                       f"had {fname}")
                    exp_food[fname] = exp_food.get(fname, 0) + 1
                    last_food[fname] = (uqty, cal)
            elif d == "water":
                if last_water_ml is not None and rng.random() < 0.5:
                    if rng.random() < 0.5:  # add-cue → +1
                        await run_log_turn(H, uid, "log_water", {"amount_ml": last_water_ml}, "another glass")
                        exp_water += 1
                    else:  # pivot → blocked
                        await run_log_turn(H, uid, "log_water", {"amount_ml": last_water_ml}, rng.choice(PIVOTS))
                else:  # fresh, distinct ml (≥ +60 apart so never within ±30 of prior)
                    uniq += 1
                    ml = 200 + uniq * 70
                    await run_log_turn(H, uid, "log_water", {"amount_ml": ml}, "some water")
                    exp_water += 1
                    last_water_ml = ml
            elif d == "exercise":
                ename, wlb = rng.choice(EXERCISES)
                if ename in last_ex and rng.random() < 0.5:
                    prep, pwlb = last_ex[ename]
                    if rng.random() < 0.5:  # add-cue → +1
                        await run_log_turn(H, uid, "log_exercise",
                                           {"exercise_name": ename, "sets": 1, "reps": str(prep),
                                            "weight": pwlb, "weight_unit": "lbs"}, "another set")
                        exp_ex[ename] = exp_ex.get(ename, 0) + 1
                    else:  # pivot → blocked
                        await run_log_turn(H, uid, "log_exercise",
                                           {"exercise_name": ename, "sets": 1, "reps": str(prep),
                                            "weight": pwlb, "weight_unit": "lbs"}, rng.choice(PIVOTS))
                else:  # fresh, UNIQUE load (distinct weight) → never dedups
                    # Step by 5 lbs per unique, NOT 1: the exercise dedup folds
                    # loads within ±0.5 kg, and 1 lb ≈ 0.45 kg < that tolerance, so
                    # consecutive +1-lb "fresh" logs at the same reps would
                    # (correctly) dedup. 5 lbs ≈ 2.27 kg clears the fold cleanly.
                    uniq += 1
                    wl = wlb + uniq * 5  # distinct load (≥0.5 kg apart) each fresh log
                    rep = rng.choice([8, 10, 12])
                    await run_log_turn(H, uid, "log_exercise",
                                       {"exercise_name": ename, "sets": 1, "reps": str(rep),
                                        "weight": wl, "weight_unit": "lbs"},
                                       f"{rep}x{int(wl)} {ename}")
                    exp_ex[ename] = exp_ex.get(ename, 0) + 1
                    last_ex[ename] = (rep, wl)
            else:  # weight — fire repeatedly, expect ≤2 rows (one day, ≤1 per source)
                async with await H.session() as db:
                    await add_body_metric(db, uid, round(rng.uniform(80, 95), 2),
                                          source=rng.choice(["manual", "apple_health"]))
                    await db.commit()

        # Verify food/water/exercise ground truth matches expectation exactly.
        for fname, exp in exp_food.items():
            got = len(await db_food_rows_named(H, uid, fname))
            res.check(f"[burst#{i}] food {fname!r} rows match", got == exp,
                      f"expected {exp} got {got}", category="burst_food")
        gw = len(await db_water_rows(H, uid))
        res.check(f"[burst#{i}] water rows match", gw == exp_water,
                  f"expected {exp_water} got {gw}", category="burst_water")
        for ename, exp in exp_ex.items():
            got = len(await db_exercise_rows(H, uid, ename))
            res.check(f"[burst#{i}] exercise {ename!r} rows match", got == exp,
                      f"expected {exp} got {got}", category="burst_ex")
        wrows = await db_weight_rows(H, uid)
        res.check(f"[burst#{i}] weight ≤ 2 rows (one day, ≤1 per source)",
                  len(wrows) <= 2, f"got {len(wrows)}", category="burst_wt")


# ─────────────────────────────────────────────────────────────────────────────
# Core run — all green expected on the fixed worktree.
# ─────────────────────────────────────────────────────────────────────────────
async def run_all(iters, seed, quiet):
    rng = random.Random(seed)
    H = Harness()
    await H.setup()
    res = Results(quiet=quiet)

    # Scale per-domain iteration counts off the headline --iters.
    food_n = iters
    water_n = max(1, iters // 2)
    ex_n = max(1, iters // 2)
    wt_n = max(1, iters // 2)
    burst_n = max(1, iters // 8)

    await food_scenarios(H, res, rng, food_n)
    await food_danny_replay(H, res)
    await water_scenarios(H, res, rng, water_n)
    await exercise_scenarios(H, res, rng, ex_n)
    await weight_scenarios(H, res, rng, wt_n)
    await weight_danny_replay(H, res)
    await interleave_burst(H, res, rng, burst_n)

    # ── Summary ──────────────────────────────────────────────────────────────
    head("SUMMARY")
    total = res.passed + res.failed
    print(f"  iterations(headline)={iters}  total assertions={total}")
    print(f"  {B}{G}{res.passed} passed{X}, "
          f"{(R if res.failed else G)}{res.failed} failed{X}")
    if res.failed:
        print(f"\n  {R}{B}FAILURES:{X}")
        for f in res.failures[:40]:
            print(f"    {R}- {f}{X}")
    await H.engine.dispose()
    return res


# ─────────────────────────────────────────────────────────────────────────────
# REGRESSION-TOGGLE PROOF — disable one fix at a time, confirm the sim FAILS the
# right assertions, then restore. Each toggle monkeypatches the module in-process,
# runs a FOCUSED scenario, asserts the expected failures appeared, and reverts.
# ─────────────────────────────────────────────────────────────────────────────
async def prove_regression(iters, seed):
    head("REGRESSION-TOGGLE PROOF — a sim that stays green with fixes off is worthless")
    rng = random.Random(seed + 99)
    H = Harness()
    await H.setup()
    overall_ok = True

    # ── Toggle A: neuter the food/water/exercise gate-override (turn_supports_log
    #    → always False). The "another X ⇒ 2 rows" assertions MUST fail. ──────────
    import skills.logging_intent as li
    _orig_tsl = li.turn_supports_log
    # _dispatch imports turn_supports_log at call time via `from skills.logging_intent
    # import turn_supports_log`, so patching the module attribute is enough.
    li.turn_supports_log = lambda *a, **k: False
    try:
        resA = Results(quiet=True)
        # Run only the add-cue branches of food/water/exercise.
        for i in range(max(20, iters // 4)):
            fname, qty, cal = rng.choice(FOODS)
            uid = await H.new_user()
            await run_log_turn(H, uid, "log_food",
                               {"food_name": fname, "quantity": qty, "calories": cal},
                               f"had {fname}")
            cue = rng.choice(ADD_CUES).format(f=fname)
            await run_log_turn(H, uid, "log_food",
                               {"food_name": fname, "quantity": qty, "calories": cal}, cue)
            rows = await db_food_rows_named(H, uid, fname)
            resA.check(f"[A-food#{i}] add-cue → 2 rows", len(rows) == 2,
                       f"got {len(rows)}", category="A_food")
            # exercise add-cue
            ename, wlb = rng.choice(EXERCISES)
            uid2 = await H.new_user()
            await run_log_turn(H, uid2, "log_exercise",
                               {"exercise_name": ename, "sets": 1, "reps": "10",
                                "weight": wlb, "weight_unit": "lbs"}, f"10x{int(wlb)} {ename}")
            await run_log_turn(H, uid2, "log_exercise",
                               {"exercise_name": ename, "sets": 1, "reps": "10",
                                "weight": wlb, "weight_unit": "lbs"}, "another set")
            exrows = await db_exercise_rows(H, uid2, ename)
            resA.check(f"[A-ex#{i}] add-cue → 2 rows", len(exrows) == 2,
                       f"got {len(exrows)}", category="A_ex")
    finally:
        li.turn_supports_log = _orig_tsl

    a_failed = resA.failed
    a_total = resA.passed + resA.failed
    proofA = a_failed > 0 and a_failed >= (a_total // 2)  # the add-cue checks should flip
    print(f"  {B}Toggle A (gate-override OFF — turn_supports_log→False):{X}")
    print(f"    add-cue assertions: {a_total} total, {R}{a_failed} FAILED{X} as expected")
    print(f"    {'%s✓ PROOF: sim catches the second-serving block%s' % (G, X) if proofA else '%s✗ PROOF FAILED: sim did NOT flag the regression%s' % (R, X)}")
    # Confirm restore worked: a fresh add-cue now writes 2 rows again.
    fname, qty, cal = rng.choice(FOODS)
    uid = await H.new_user()
    await run_log_turn(H, uid, "log_food", {"food_name": fname, "quantity": qty, "calories": cal}, f"had {fname}")
    await run_log_turn(H, uid, "log_food", {"food_name": fname, "quantity": qty, "calories": cal},
                       rng.choice(ADD_CUES).format(f=fname))
    restoredA = len(await db_food_rows_named(H, uid, fname)) == 2
    print(f"    restore check: add-cue → 2 rows again: {'%s✓%s' % (G, X) if restoredA else '%s✗%s' % (R, X)}")
    overall_ok = overall_ok and proofA and restoredA

    # ── Toggle B: make add_body_metric source-blind (ignore source — fold by
    #    NEAR-IDENTICAL only, like the OLD code). The weight "2 rows / manual
    #    headline" assertions MUST fail (4 rows stack, headline = latest passive). ─
    import db.queries as q
    _orig_abm = q.add_body_metric

    async def _source_blind_add_body_metric(db, user_id, weight_kg, source="manual", **kwargs):
        # OLD behavior: fold only readings within <0.06 kg / 30 min REGARDLESS of
        # source; otherwise INSERT a new row. current_weight_kg = latest write
        # (no manual-wins logic). This recreates the stacking incident.
        from sqlalchemy import select, desc
        from datetime import datetime as _dt, timedelta as _td
        from db.models import BodyMetric, User
        ures = await db.execute(select(User).where(User.id == user_id))
        user = ures.scalar_one()
        cutoff = _dt.utcnow() - _td(minutes=30)
        rows = (await db.execute(
            select(BodyMetric).where(BodyMetric.user_id == user_id,
                                     BodyMetric.timestamp >= cutoff)
            .order_by(desc(BodyMetric.timestamp)))).scalars().all()
        near = next((r for r in rows if r.weight_kg is not None
                     and abs(r.weight_kg - weight_kg) < 0.06), None)
        if near is not None:
            near.weight_kg = weight_kg
            near.timestamp = _dt.utcnow()
            user.current_weight_kg = weight_kg
            await db.commit()
            await db.refresh(near)
            return near
        m = BodyMetric(user_id=user_id, weight_kg=weight_kg, source=source, **kwargs)
        db.add(m)
        user.current_weight_kg = weight_kg  # latest-wins (the bug)
        await db.commit()
        await db.refresh(m)
        return m

    q.add_body_metric = _source_blind_add_body_metric
    try:
        resB = Results(quiet=True)
        for i in range(max(20, iters // 4)):
            uid = await H.new_user(cur_weight=86.0)
            manual_kg = round(rng.uniform(80, 95), 2)
            ah_kg = round(manual_kg + 0.55, 2)  # the exact escaping gap
            async with await H.session() as db:
                await q.add_body_metric(db, uid, manual_kg, source="manual", context="morning_fasted")
                await q.add_body_metric(db, uid, ah_kg, source="apple_health")
                await db.commit()
            rows = await db_weight_rows(H, uid)
            resB.check(f"[B-wt#{i}] → exactly 2 rows", len(rows) == 2,
                       f"got {len(rows)}", category="B_rows")
            cw = await db_current_weight(H, uid)
            resB.check(f"[B-wt#{i}] headline = MANUAL", cw == manual_kg,
                       f"current={cw} manual={manual_kg}", category="B_headline")
    finally:
        q.add_body_metric = _orig_abm

    b_failed = resB.failed
    b_total = resB.passed + resB.failed
    proofB = b_failed > 0
    print(f"  {B}Toggle B (add_body_metric source-blind — OLD <0.06kg fold):{X}")
    print(f"    weight assertions: {b_total} total, {R}{b_failed} FAILED{X} as expected")
    print(f"    {'%s✓ PROOF: sim catches the weight stacking / wrong-headline%s' % (G, X) if proofB else '%s✗ PROOF FAILED: sim did NOT flag the regression%s' % (R, X)}")
    # Restore check: the real source-aware fn yields 2 rows + manual headline.
    uid = await H.new_user(cur_weight=86.0)
    async with await H.session() as db:
        await q.add_body_metric(db, uid, 84.73, source="manual", context="morning_fasted")
        await q.add_body_metric(db, uid, 85.28, source="apple_health")
        await db.commit()
    restoredB = (len(await db_weight_rows(H, uid)) == 2
                 and await db_current_weight(H, uid) == 84.73)
    print(f"    restore check: 2 rows + manual headline again: {'%s✓%s' % (G, X) if restoredB else '%s✗%s' % (R, X)}")
    overall_ok = overall_ok and proofB and restoredB

    await H.engine.dispose()
    print()
    print(f"  {B}REGRESSION PROOF: "
          f"{'%sALL TOGGLES CONFIRMED REAL + RESTORED%s' % (G, X) if overall_ok else '%sPROOF INCOMPLETE%s' % (R, X)}")
    return overall_ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--iters", type=int, default=600,
                    help="headline iteration count (food uses this; others scale down)")
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--quiet", action="store_true", help="summary + failures only")
    ap.add_argument("--prove-regression", action="store_true",
                    help="ALSO disable each fix and prove the sim catches it")
    args = ap.parse_args()

    print(f"{B}{C}{'='*70}{X}")
    print(f"{B}{C} LOGGING-DISCIPLINE HIGH-FREQUENCY STRESS SIM (adversarial){X}")
    print(f"{B}{C}{'='*70}{X}")
    print(f"{D}  Deterministic, no LLM. Drives execute_tool_calls/_dispatch +{X}")
    print(f"{D}  add_body_metric directly. seed={args.seed} iters={args.iters}{X}")

    res = asyncio.run(run_all(args.iters, args.seed, args.quiet))
    proof_ok = True
    if args.prove_regression:
        proof_ok = asyncio.run(prove_regression(args.iters, args.seed))

    failed = res.failed > 0 or (args.prove_regression and not proof_ok)
    print()
    if failed:
        print(f"{B}{R}  OVERALL: FAIL{X}\n")
        return 1
    print(f"{B}{G}  OVERALL: ALL GREEN{X}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
