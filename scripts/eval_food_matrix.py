"""Ironclad evaluation: live behavioral matrix for the structured food turn.

Every case is a real production failure we fixed (or a behavior Danny locked
in) — this is the regression battery for the WHOLE food-logging brain, run
against the real FOOD_LOGGER_MODEL. Each case states the message, the state
(mode / board / regulars / last_assistant), and the EXPECTED action (+ shape
checks). Output: PASS/FAIL per case + score.

Run (from a worktree, which has no .env — the key MUST be exported or the
script now refuses to run rather than scoring a misleading number):

    export ANTHROPIC_API_KEY="$(grep '^ANTHROPIC_API_KEY=' /path/to/arnie/.env \
        | cut -d= -f2- | tr -d '"'"'"' ')"
    PYTHONPATH=<repo> <repo>/.venv/bin/python scripts/eval_food_matrix.py

Every case runs EVAL_REPS times (default 3) and passes only if it passes all
of them; see `main`. Exits non-zero unless every case is clean, so FLAKY is a
failure here rather than a footnote.
"""
import asyncio
import logging
import os
import sys
import json
from types import SimpleNamespace

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from core import food_turn as FT


#: Signatures of a call that was REFUSED rather than answered. Matched against
#: the log line `core.llm` writes when the model call fails, because that
#: failure is swallowed there — the turn returns a null result and the case
#: sees `got=None`, which is indistinguishable from the model declining to act.
_INFRA_MARKERS = (
    "credit balance is too low",
    "authentication_error",
    "invalid x-api-key",
    "permission_error",
    "rate_limit_error",
    "overloaded_error",
    "internal_server_error",
    "api_error",
)


#: The lines `core/llm.py` writes when a safety net CAUGHT the call. They mean
#: the model answered, so whatever failed on the way is not an outage.
_RECOVERY_MARKERS = (
    "model fallback ok",   # core/llm.py — the Anthropic retry succeeded
    "openai fallback ok",  # core/llm.py — the OpenAI net succeeded
)


#: Where the run's verdict is written. A module constant so a test can
#: point it somewhere harmless instead of stamping on the real one.
RESULTS_PATH = "/tmp/eval_matrix_results.txt"


class _InfraWatch(logging.Handler):
    """⛔⛔ AN ABSENT ANSWER IS NOT A NEGATIVE ANSWER — AND A RECOVERED ONE IS
    NOT ABSENT.

    Measured on PR #79: the Anthropic balance ran out mid-run, both the
    primary model and the fallback returned 400 `credit balance is too low`,
    and the battery scored those two reps as `got=None want=ask` — reporting
    "[FLAKY] a unit that does not fix a size is asked about (1/3)" and exiting
    1. That reads as a behaviour that sometimes misfires. Nothing about the
    behaviour was measured; the API refused to answer.

    A billing or auth outage is an INFRASTRUCTURE failure and now says so.
    The distinction matters because FLAKY is the battery's loudest behavioural
    signal — the state it exists to catch — and an outage was borrowing it.

    ⭐ THE SEQUENCE MATTERS, NOT THE PRESENCE OF A MARKER. `core/llm.py` logs
    the primary failure BEFORE it retries, so the first version of this
    handler threw away every rep a fallback had rescued — the same error it
    exists to correct, pointing the other way. A marker is therefore PENDING
    until the call resolves: a recovery line clears it, a second failure
    leaves it standing.

    Clearing is per-call, not per-rep. A rep makes several model calls, and an
    early recovery must not forgive a later outage — that would score the rep
    on a turn that never got an answer. The call boundary is the PRIMARY
    failure line: reaching a new one means the previous call ended without
    announcing a rescue, so its markers are banked as dead before the new
    call's start collecting.

    ⭐ "Fallback ALSO failed" is deliberately NOT treated as terminal. The
    OpenAI net runs AFTER it (`core/llm.py`), so a call can still be answered
    once both Anthropic models are out — and calling it dead there would
    discard exactly the measurement the net saved."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self._pending = []
        self._dead = []

    @property
    def hits(self):
        """Markers no recovery accounted for. Pending ones count: a call that
        failed and never announced a rescue did not get one."""
        return self._dead + self._pending

    def clear(self):
        self._pending.clear()
        self._dead.clear()

    def emit(self, record):
        try:
            msg = record.getMessage().lower()
        except Exception:  # noqa: BLE001 - a broken record must not kill the run
            return
        if any(marker in msg for marker in _RECOVERY_MARKERS):
            self._pending.clear()          # this call was answered after all
            return
        for marker in _INFRA_MARKERS:
            if marker in msg:
                if "model call failed" in msg and self._pending:
                    # A new call is starting and the last one never announced a
                    # rescue. Bank it now, so THIS call's recovery cannot clear
                    # a previous call's outage.
                    self._dead.extend(self._pending)
                    self._pending.clear()
                self._pending.append(marker)
                return


def U(mode="strict"):
    """The eval user, with the BODY STATS the materiality engine actually reads.

    `preferences.calorie_target` alone was decorative here. Materiality scores
    against `core.targets.compute_macro_targets(user)`, which DERIVES the day's
    goals from weight/height/age/sex — and raises AttributeError on a user that
    has none. `_daily_targets` swallows that and returns None, which silently
    drops `is_material` off its proportional day-share/item-share engine and
    onto the legacy ABSOLUTE thresholds.

    So every ask-or-log decision in this battery was being made by a different
    engine than the one production runs, and the two disagree: a Barebells bar
    with a 30-cal flavour spread is immaterial by absolute threshold and
    material by day-share (0.014 >= 0.005, item-share 0.150 >= 0.15). The
    battery was scoring the fallback.

    These stats compute to 2163 cal / 180 g protein — the figures the old
    decorative fields claimed — so the numbers the cases were tuned against
    are unchanged; they are now actually read.
    """
    return SimpleNamespace(
        id=999, first_name="Eval",
        current_weight_kg=81.5, height_cm=165.0, age=45, sex="male",
        primary_goal="recomp", goal_weight_kg=79.5, activity_level="moderate",
        preferences=SimpleNamespace(food_logging_mode=mode,
                                    calorie_target=2165, protein_target=180))


BOARD = [
    {"id": 501, "food": "Birria Taco", "qty": "1 taco", "cal": 180},
    {"id": 502, "food": "Quest Chips, Sour Cream & Onion", "qty": "1 bag", "cal": 140},
]

REG_COFFEE_ONE = [{"name": "Coffee with oat milk splash", "qty": "1 cup",
                   "calories": 25, "protein": 1, "carbs": 3, "fats": 1, "count": 9}]
# True ambiguity: neither is literally named "coffee" — an exact-name match
# (like "Coffee with oat milk splash") legitimately WINS the pointer instead.
REG_COFFEE_TWO = [
    {"name": "Iced Americano", "qty": "1 grande", "calories": 15,
     "protein": 0, "carbs": 2, "fats": 0, "count": 5},
    {"name": "Oat Milk Latte", "qty": "1 grande", "calories": 120,
     "protein": 4, "carbs": 12, "fats": 6, "count": 7},
]
REG_BAREBELLS = [{"name": "Barebells Caramel Cashew", "qty": "1 bar",
                  "calories": 200, "protein": 20, "carbs": 20, "fats": 7, "count": 12}]

CASES = [
    # ── action routing ────────────────────────────────────────────────────
    dict(name="multi-item split logs each component",
         msg="Had a caesar salad and a grilled chicken breast",
         mode="quick", expect="log", min_items=2),
    dict(name="quick mode logs small-swing vagueness (some strawberries < 300)",
         msg="had some strawberries", mode="quick", expect="log"),
    dict(name="strict asks on big-swing vagueness (some chicken, prep unknown)",
         msg="had some chicken", mode="strict", expect="ask"),
    dict(name="stated count logs without asking (strict)",
         msg="ate 12 strawberries", mode="strict", expect="log"),
    dict(name="plan/future is pass",
         msg="thinking about getting a burrito later", mode="strict", expect=None),
    dict(name="question is never food",
         msg="how much protein is in a barebells bar?", mode="strict", expect=None),
    dict(name="destructive routes to legacy",
         msg="remove the birria taco", mode="strict", expect=None),
    dict(name="workout routes to legacy",
         msg="did 3 sets of bench at 185", mode="strict", expect=None),
    # 2026-07-29 production: this exact answer to a flavor clarification parsed
    # to nothing, the interpreter read it as contentless, and the turn escaped
    # to legacy (legacy_reason=interpreter_none) with the question lost. A
    # premise confirmation is a command; it must log the stashed reading.
    dict(name="'It's the same one' logs the stashed reading",
         msg="It's the same one", mode="quick", expect="log",
         prior=dict(original="Having the sun chips again",
                    question=("The Harvest Cheddar ones like last time, "
                              "or a different flavor?"),
                    kind="clarify", ask_count=1,
                    items=[dict(food="Sun Chips Harvest Cheddar", amount=1,
                                unit="bag", calories=210)]),
         want_cal=(200, 220)),

    # ── strict brand discipline (Barebells saga) ──────────────────────────
    dict(name="strict + branded + no flavor ALWAYS asks",
         msg="just had a barebells bar", mode="strict", expect="ask"),
    dict(name="strict + branded + flavor stated logs",
         msg="had a barebells caramel cashew bar", mode="strict", expect="log"),
    # CHANGED 2026-07-30 ON DANNY'S CALL, and deliberately not by editing an
    # expectation quietly. This case used to expect `log`: a matching regular
    # settled the flavour and the turn wrote it without asking. Production turn
    # #8338 is what that looks like — "I just had a happy wolf bar" logged as
    # "Happy Wolf chocolate chip bar", a flavour nobody stated, no question and
    # no stated assumption, on a brand carrying four of them.
    #
    # The standing rule is that a prior SHORTENS the question, never removes
    # it. So a regular now earns a CONFIRM — "Caramel cashew like usual, or a
    # different one?" — which is one word to answer and still nameable as
    # wrong. `log` remains correct when the user names the flavour themselves;
    # the case above this one covers that and is unchanged.
    dict(name="branded + regular match logs THEIR numbers",
         msg="just had a barebell", mode="strict", regulars=REG_BAREBELLS,
         expect="log", want_cal=(180, 220)),

    # ── regulars pointer (my usual X) ─────────────────────────────────────
    dict(name="usual + one regular logs it verbatim",
         msg="having my usual coffee", mode="moderate", regulars=REG_COFFEE_ONE,
         expect="log", want_cal=(20, 30)),
    dict(name="usual + two matches asks which",
         msg="having my usual coffee", mode="moderate", regulars=REG_COFFEE_TWO,
         expect="ask"),
    dict(name="usual + no regular asks once (never generic)",
         msg="having my usual coffee", mode="moderate", regulars=[], expect="ask"),

    # ── counts anchor portions (truffle fries saga) ───────────────────────
    dict(name="5-6 fries prices per piece, never a menu side",
         msg="I had some parmesan truffle fries from Bobby Flay, like 5-6 fries",
         mode="strict", expect="log", max_cal=220),
    dict(name="stated mass is kept as the unit",
         msg="200g of grilled chicken breast", mode="strict", expect="log",
         want_unit_sub="g"),

    # ── corrections own the board ─────────────────────────────────────────
    dict(name="correction scales the board entry",
         msg="actually I had 2 of those birria tacos", mode="strict",
         board=BOARD, expect="update", want_cal=(340, 380)),
    dict(name="correction target off-board is pass",
         msg="actually make the ramen 2 bowls", mode="strict", board=BOARD,
         expect=None),
    dict(name="keep-as-is after a proposed bump writes NOTHING",
         msg="Leave it like this", mode="strict", board=BOARD,
         last_assistant="Those fries realistically run 350-400, I'll bump it up to be safe.",
         expect=None, gate_only=True),

    # ── say contract ──────────────────────────────────────────────────────
    # WAS: "say never carries model-invented totals", on "a bowl of white rice
    # and two fried eggs", expecting log. Retired 2026-07-29 for two SEPARATE
    # reasons, either of which alone kills it:
    #
    # 1. The assertion was VACUOUS. It compared `enforce_say_contract(say)`
    #    against `say` — but the interpreter stopped emitting prose (451fb35,
    #    f3aa3be), so `say` is now always "" on every log, "" cleans to "", and
    #    the check passed on equality-of-nothing no matter what the model did.
    #    It read as a live guard on invented totals and guarded nothing.
    # 2. The expectation was stale anyway. "A bowl of" is a unit that does not
    #    fix a size (5fba5f4), so the rice is an unstated quantity worth ~150
    #    cal — 6.9% of the day — and the engine escalates the log to an ask.
    #    That is the behaviour we want; the case was written before it existed.
    #
    # The say contract itself is alive and enforced in production at
    # core/conversation.py:2153, against the COMPOSER's line — a layer FT.run
    # does not reach — and is unit-tested (tests/test_food_turn.py::209-216,
    # test_gate_generative.py, test_the_interpreter_stops_writing_prose.py).
    # Chasing it from here would only re-create the vacuum.
    #
    # What IS checkable here is the invariant that made it vacuous, so it is
    # now checked on purpose: on a clean log the interpreter emits NO prose.
    # If prose ever comes back, this fails instead of silently passing.
    dict(name="interpreter emits no prose on a clean log",
         msg="had 3 large eggs and 200g of grilled chicken breast",
         mode="moderate", expect="log", min_items=2, no_prose=True),
    # The rice case kept as what it actually demonstrates now: an unfixed unit
    # is an unstated amount, and that is worth a question.
    dict(name="a unit that does not fix a size is asked about",
         msg="had a bowl of white rice and two fried eggs", mode="moderate",
         expect="ask"),
]


async def run_case(c):
    if c.get("gate_only"):
        ok = (not FT.applies(c["msg"])) and (not FT.thread_routes(c["msg"]))
        return ok, "gate excluded ✓" if ok else "GATE LET IT THROUGH"
    res = await FT.run(c["msg"], U(c.get("mode", "strict")),
                       prior=c.get("prior"),
                       day_line="Today: 320 cal, 21g protein so far.",
                       board=c.get("board", []),
                       last_assistant=c.get("last_assistant", ""),
                       regulars=c.get("regulars", []),
                       thread_active=bool(c.get("prior")))
    got = res["action"] if res else None
    if c["expect"] is None:
        return got is None, f"got={got}"
    if got != c["expect"]:
        detail = ""
        if res and res.get("action") == "ask":
            detail = f" ask={res.get('text', '')[:90]}"
        return False, f"got={got} want={c['expect']}{detail}"
    if got in ("log", "update"):
        calls = res.get("tool_calls", [])
        if "min_items" in c and len(calls) < c["min_items"]:
            return False, f"items={len(calls)} < {c['min_items']}"
        total = sum((tc.get("input") or {}).get("calories") or 0 for tc in calls)
        if "want_cal" in c:
            lo, hi = c["want_cal"]
            if not (lo <= total <= hi):
                return False, f"cal={total} not in [{lo},{hi}]"
        if "max_cal" in c and total > c["max_cal"]:
            return False, f"cal={total} > max {c['max_cal']}"
        if "want_unit_sub" in c:
            units = " ".join(str((tc.get("input") or {}).get("quantity") or "") +
                             str((tc.get("input") or {}).get("unit") or "")
                             for tc in calls)
            if c["want_unit_sub"] not in units:
                return False, f"unit missing '{c['want_unit_sub']}' in {units!r}"
        if c.get("no_prose"):
            # The interpreter carries rows, not sentences. A non-empty say/note
            # here means prose came back into the JSON the user waits on.
            stray = {k: res.get(k) for k in ("say", "note")
                     if (res.get(k) or "").strip()}
            if stray:
                return False, f"interpreter wrote prose: {stray}"
    return True, f"got={got} ✓"


def _preflight():
    """A missing key must fail LOUDLY, not score.

    Without ANTHROPIC_API_KEY every case dies in the model call and is counted
    a normal FAIL, which came out as a plausible-looking 6/20 — a number that
    reads as a broken product rather than an unset variable. The worktrees this
    is usually run from have no .env, so this is the common case, not the edge.
    """
    if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
        sys.exit("ANTHROPIC_API_KEY is not set — every case would fail on auth "
                 "and score a misleading number. Export it and re-run:\n"
                 "  export ANTHROPIC_API_KEY=\"$(grep '^ANTHROPIC_API_KEY=' "
                 "/path/to/arnie/.env | cut -d= -f2- | tr -d '\\\"'\\''')\"")


async def main():
    """REPEATED, and SERIAL. Both on purpose.

    REPEATED: this battery is a live-model matrix, so a single run scores the
    sample, not the commit. Measured on cca96be, "usual + two matches asks
    which" passed 3 times in 8 and "multi-item split" 5 in 8 — either could be
    read as a green commit or a regression depending on the run. A case now
    passes only if it passes EVERY rep; anything in between is FLAKY and is
    counted a failure, because a sometimes-pass is exactly what let a broken
    behaviour ship green.

    SERIAL: running the cases concurrently inflates latency past the turn
    budget, the composer call fails, and cases resolve differently — in BOTH
    directions. Under concurrency 6, "multi-item split" failed 3 of 8 purely
    from timeouts, while "usual + two matches" PASSED 3 of 8 because a timeout
    happens to surface as the `ask` it wanted. Do not parallelise this for
    speed; it does not measure the same thing.
    """
    _preflight()
    reps = int(os.getenv("EVAL_REPS", "3"))
    lines = []
    clean = flaky = broken = unmeasured = 0
    watch = _InfraWatch()
    logging.getLogger().addHandler(watch)
    for c in CASES:
        runs = []
        for _ in range(reps):
            # `watch.clear()`, NOT `watch.hits.clear()` — `hits` is a computed
            # list, so clearing it would clear a temporary and leak every
            # marker into the next rep, making one outage condemn the run.
            watch.clear()
            try:
                ok, detail = await run_case(c)
            except Exception as e:  # noqa: BLE001
                ok, detail = False, f"EXC {type(e).__name__}: {e}"
            if watch.hits:
                # `ok` here is not a verdict — the model never answered. Keep
                # the rep, discard its score.
                runs.append((None, f"INFRA {watch.hits[0]}"))
            else:
                runs.append((ok, detail))
        scored = [(ok, d) for ok, d in runs if ok is not None]
        infra = [d for ok, d in runs if ok is None]
        n = sum(1 for ok, _ in scored if ok)
        if infra:
            # ⛔ NOT FLAKY. A case whose reps were refused was not measured, and
            # calling it flaky would attribute an outage to the behaviour.
            mark = "INFRA"
            unmeasured += 1
        elif n == reps:
            mark = "PASS"
            clean += 1
        elif n == 0:
            mark = "FAIL"
            broken += 1
        else:
            mark = "FLAKY"
            flaky += 1
        detail = ("; ".join(sorted(set(infra))) if infra else
                  "; ".join(sorted({d for ok, d in scored if not ok}))
                  or (scored[0][1] if scored else ""))
        shown = f"{n}/{len(scored)} scored, {len(infra)}/{reps} refused" if infra \
            else f"{n}/{reps}"
        line = f"[{mark}] {c['name']}  ({shown}) ({detail[:160]})"
        print(line, flush=True)
        lines.append(line)
    total = len(CASES)
    summary = (f"\n{clean}/{total} passed all {reps} reps"
               f"  |  flaky: {flaky}  |  failed outright: {broken}"
               f"  |  UNMEASURED (infrastructure): {unmeasured}")
    if unmeasured:
        summary += (
            f"\n\n⛔ INFRASTRUCTURE FAILURE — {unmeasured} case(s) were never "
            "measured because the model API refused the call (billing, auth, "
            "or rate limit; see the INFRA lines above). This run says NOTHING "
            "about those cases' behaviour. Restore API access and re-run "
            "before reading this battery as a verdict.")
    print(summary, flush=True)
    with open(RESULTS_PATH, "w") as f:
        f.write("\n".join(lines) + summary + "\n")
    # Three distinct outcomes, three distinct codes: 0 clean, 2 not measured,
    # 1 measured and wrong. CI reds on any non-zero, but the code alone now
    # says whether the product or the plumbing failed.
    if unmeasured:
        sys.exit(2)
    sys.exit(0 if clean == total else 1)


if __name__ == "__main__":
    asyncio.run(main())
