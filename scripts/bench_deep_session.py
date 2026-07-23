"""Deep-session logging reliability benchmark (A/B).

WHAT IT MEASURES
  Tool-calling reliability *deep in a session*, where the model drifts and drops
  logs — the failure a single-turn test can't reproduce. It plays a realistic ~15
  turn day (meals, chat, questions, a workout) through the REAL run_turn pipeline
  with the live model + real prompt + real build_context (the running daily log +
  session state the model sees in prod). DB and the tool executor are mocked, but
  the executor ACCUMULATES logged entries into today_log so the context stays
  faithful. Scoring is CUMULATIVE: for each expected item, did it end up on the
  board by session end? (An item logged a turn late via batching is NOT a drop.)

WHY IT EXISTS
  The 2026-07-23 tool-calling foundation (manifest, rescues, orchestrator) needed a
  before/after that reflected real deep-session behavior. First result: the
  orchestrator (ORCHESTRATOR=on) cut the deep-session drop rate 47%->36% over 5 runs
  vs off. Re-run this against any future change (e.g. deterministic set-append) to
  see if it moves the deep-drop number.

USAGE
  ANTHROPIC_API_KEY=sk-...  RUNS=5  python scripts/bench_deep_session.py
  RUNS=1 TURNS=3 python scripts/bench_deep_session.py     # quick smoke
  Compares CONFIGS below (baseline = tonight's features off, new = on). Edit CONFIGS
  to A/B any switch. Costs real model calls (RUNS x 2 x ~15 growing-context turns).
"""
import os, asyncio
from datetime import datetime

if not os.getenv("ANTHROPIC_API_KEY"):
    raise SystemExit("Set ANTHROPIC_API_KEY (this benchmark makes live model calls).")
os.environ.setdefault("DEFAULT_MODEL", "claude-sonnet-5")
os.environ["LOG_MARKER"] = "true"
RUNS = int(os.getenv("RUNS", "5"))
SMOKE = os.getenv("TURNS") == "3"

from types import SimpleNamespace
import core.conversation as C
import db.queries as Q
import reminders.lifecycle as RL
import core.context_builder as CB
from core.conversation import run_turn
from core.prompts.arnie import build_arnie_system

SYSTEM = build_arnie_system(platform="imessage")


class Entry:  # returns None for any attribute we didn't set → build_context can't crash on one
    def __init__(self, **kw): self.__dict__.update(kw)
    def __getattr__(self, name): return None


def _user():
    return Entry(id=1, telegram_id=None, onboarding_completed=True, timezone="UTC",
        name="Danny", created_at=datetime(2025, 1, 1), primary_goal="recomp",
        nudges_sent="", log_unlocked_at="seeded", brain_dump="", program=None,
        preferences=Entry(calorie_target=2165, protein_target=180, food_logging_mode="moderate"))


class _DB:
    async def refresh(self, *a, **k): pass
    async def commit(self, *a, **k): pass
    async def rollback(self, *a, **k): pass
    async def execute(self, *a, **k):
        class _R:
            def scalar_one_or_none(self): return None
            def scalars(self): return self
            def all(self): return []
            def first(self): return None
            def scalar(self): return None
            def fetchall(self): return []
        return _R()


async def _noop(*a, **k): return None
async def _reload(db, uid): return _user()
async def _empty(*a, **k): return []
async def _prof(*a, **k): return {}
RL.sync_pending_questions = _noop
Q.reload_user = _reload
Q.get_recent_logs = _empty
Q.get_recent_weights = _empty
Q.get_recent_health_snapshots = _empty
CB.read_profile = _prof          # so build_context runs the REAL path, not the fallback
try:
    import memory.memory_manager as MM
    MM.read_memory = lambda *a, **k: ""
except Exception:
    pass

# (message, substrings that must be on the board by session end — [] = not a log turn)
SESSION = [
    ("morning, weighed in at 193.5",                                    []),
    ("had 3 eggs and 2 slices of sourdough toast for breakfast",        ["egg", "toast"]),
    ("coffee with a splash of oat milk",                                ["coffee"]),
    ("how much protein should I be getting again?",                     []),
    ("did 30 min of incline walking on the treadmill",                  ["walk", "tread", "cardio"]),
    ("lunch was a chicken caesar wrap and a side of fruit",             ["wrap", "fruit"]),
    ("actually add a diet coke to that",                                ["coke"]),
    ("feeling good today, energy is way up",                            []),
    ("afternoon snack, greek yogurt with blueberries and a bit of honey",["yogurt"]),
    ("alright starting my workout now, chest day",                      []),
    ("bench press 135 for 12",                                          ["bench"]),
    ("incline dumbbell press 50s for 10",                              ["incline"]),
    ("cable flyes 30 for 15",                                          ["fly"]),
    ("2 scoops of protein in water post workout",                      ["protein", "shake", "whey"]),
    ("dinner, 8oz grilled salmon, a cup of white rice, and roasted broccoli", ["salmon", "rice", "broccoli"]),
]
DEEP_START = 10   # turns 10+ are the deep measured zone (deepest context)
if SMOKE:
    SESSION = SESSION[:3]; DEEP_START = 0

CONFIGS = {
    "baseline": dict(LOOKUP_RESCUE="false", ORCHESTRATOR="false", LOG_FASTPATH="false", ASK_FIRST_HOLD="false"),
    "new":      dict(LOOKUP_RESCUE="true",  ORCHESTRATOR="true",  LOG_FASTPATH="false", ASK_FIRST_HOLD="false"),
}


def _mk_food(inp):
    return Entry(parsed_food_name=inp.get("food_name") or "food", raw_input=inp.get("food_name"),
                 calories=int(inp.get("calories") or 0), protein=int(inp.get("protein") or 0),
                 carbs=0, fats=0, timestamp=datetime.utcnow(), occurred_at=datetime.utcnow(),
                 meal_type=inp.get("meal_type") or "meal")


def _mk_ex(inp):
    return Entry(exercise_name=inp.get("exercise_name") or "exercise", sets=inp.get("sets") or 1,
                 reps=str(inp.get("reps") or ""), weight=inp.get("weight"),
                 duration_minutes=inp.get("duration_minutes"), cardio_type=inp.get("cardio_type"),
                 timestamp=datetime.utcnow(), occurred_at=datetime.utcnow(), id=1)


async def run_session(cfg_env):
    for k, v in cfg_env.items():
        os.environ[k] = v
    today = SimpleNamespace(id=1, total_calories=0, total_protein=0, total_carbs=0,
        total_fats=0, total_water_ml=0, workout_completed=False, cardio_completed=False,
        food_entries=[], exercise_entries=[], date=datetime.utcnow().date())

    async def fake_exec(tcs, *a, **k):
        out = {}
        for tc in tcs:
            nm = tc.get("name"); inp = tc.get("input") or {}
            label = (inp.get("food_name") or inp.get("exercise_name") or nm)
            if nm == "log_food":
                today.food_entries.append(_mk_food(inp))
                today.total_calories += int(inp.get("calories") or 0)
                today.total_protein += int(inp.get("protein") or 0)
            elif nm == "log_exercise":
                today.exercise_entries.append(_mk_ex(inp))
            out[nm] = f"Logged: {label}. Day: {today.total_calories} cal, {today.total_protein}g protein."
        return out
    C.execute_tool_calls = fake_exec

    history = []
    for msg, _expected in SESSION:
        try:
            ctx = await CB.build_context(_user(), today, _DB())
        except Exception as ex:
            ctx = (f"[SESSION STATE]\nLogged today: "
                   f"{[en.exercise_name for en in today.exercise_entries]}, "
                   f"{today.total_calories} cal (ctx fallback: {type(ex).__name__})")
        system = f"{SYSTEM}\n\n{ctx}"
        history.append({"role": "user", "content": msg})
        turn = await run_turn(_user(), _DB(), list(history), system, "imessage",
                              in_onboarding=False, was_onboarding=False, today_log=today)
        reply = " ".join(turn.response.bubbles if turn.response else [])
        history.append({"role": "assistant", "content": reply[:400]})
    return " ".join([(e.parsed_food_name or "").lower() for e in today.food_entries]
                    + [(e.exercise_name or "").lower() for e in today.exercise_entries])


async def main():
    print(f"RUNS={RUNS} SMOKE={SMOKE}  (cumulative deep-drop scoring)", flush=True)
    agg = {"baseline": [0, 0], "new": [0, 0]}       # deep_expected, deep_logged
    drops = {"baseline": [], "new": []}
    for cfg in ("baseline", "new"):
        for run in range(RUNS):
            final = await run_session(CONFIGS[cfg])
            for i, (msg, expected) in enumerate(SESSION):
                if i >= DEEP_START and expected:
                    got = [e for e in expected if e in final]
                    agg[cfg][0] += len(expected); agg[cfg][1] += len(got)
                    miss = [e for e in expected if e not in final]
                    if miss:
                        drops[cfg].append((run, msg[:34], miss))
            de, dl = agg[cfg]
            print(f"  [{cfg}] run {run + 1}/{RUNS} cumulative deep: {dl}/{de}", flush=True)
    print("\n=== AGGREGATE (deep turns, CUMULATIVE — an item logged any turn counts) ===", flush=True)
    for cfg in ("baseline", "new"):
        de, dl = agg[cfg]
        rate = 100.0 * dl / de if de else 0
        print(f"  {cfg:9}: {dl}/{de} deep items logged ({rate:.0f}%)  [{RUNS} runs]", flush=True)
        for run, m, miss in drops[cfg][:12]:
            print(f"      DROPPED r{run}: {m:36} {miss}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
