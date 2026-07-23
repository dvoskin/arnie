"""IRONCLAD live behavioral matrix — the structured food logger, end to end.

Every canonical case from the July 2026 logging saga, consolidated into ONE
matrix and run against the REAL logger pass (core.food_turn.run, live LLM,
production system prompt). The hermetic suite (tests/test_food_turn.py) proves
the plumbing with a mocked model; THIS proves the model itself still honors
each contract. eval_logging_full.py / torture_logging.py cover the legacy
big-model path — they never touch the structured logger, which is why this
harness exists.

Per case we assert the ACTION CLASS (log / update / ask / pass) plus the
structural invariants that were each, at some point, a production incident:

  • keep-as-is closes the thread (truffle fries) — never a write
  • a stated piece count is the anchor ('5-6 fries'), never a menu side
  • corrections resolve against TODAY'S BOARD (birria, '2 of those') and the
    say starts from Updated/Bumped, never 'logged'
  • the say contract: model digits beyond its own written quantities are
    rejected (enforce_say_contract is applied exactly as production does)
  • 'my usual X' is a pointer into THEIR REGULARS: one match logs exact
    numbers, two matches asks which, none asks once — never a generic estimate
  • strict mode: branded product with unstated flavor ALWAYS asks
  • brands are never stripped from names; branded items carry is_packaged
  • a user-stated fraction survives exactly (1/3 KIND bar -> 0.33)
  • a stated mass keeps the mass unit (200g stays g)
  • ask thresholds scale with mode (quick 300 / moderate 200 / strict 100)
  • thread complaints log ONLY the missing item; 'okay log it' logs the
    proposal; chit-chat passes
  • every logged item is macro-coherent (cal ≈ 4P + 4C + 9F) and editable
    (clean 'amount unit' quantity), and no say/question leaks machinery

The gate itself (applies/thread_routes) is regex — deterministic — so the
matrix checks those rows without an API call; they're included so the printed
matrix is the complete behavioral surface in one place.

Run from arnie/ (needs ANTHROPIC_API_KEY, e.g. via .env):
    set -a; source .env; set +a
    .venv/bin/python scripts/ironclad_eval.py               # full matrix, 1 pass
    .venv/bin/python scripts/ironclad_eval.py --runs 3      # stochastic coverage
    .venv/bin/python scripts/ironclad_eval.py --only usual,board
    .venv/bin/python scripts/ironclad_eval.py --list        # show cases, no LLM

Failures are written to audits/ironclad_fails.txt with the full model result.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import food_turn
from core.food_turn import applies, enforce_say_contract, run, thread_routes

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

QTY_RE = re.compile(r"^\d+(\.\d+)?( [A-Za-z][\w /-]*)?$")
LEAK_RE = re.compile(r"#\d+|\[SYSTEM|\[TODAY\]|log_food|update_food_entry|~|—")


def _user(mode: str = "moderate"):
    return SimpleNamespace(preferences=SimpleNamespace(food_logging_mode=mode))


# ── structural checks shared across cases ────────────────────────────────────
def _macro_coherent(inp: dict) -> str | None:
    cal = inp.get("calories")
    p, c, f = inp.get("protein"), inp.get("carbs"), inp.get("fats")
    if cal is None or None in (p, c, f):
        return f"missing macros on {inp.get('food_name')}: {inp}"
    implied = 4 * p + 4 * c + 9 * f
    if abs(cal - implied) > max(60, 0.20 * max(cal, 1)):
        return (f"{inp.get('food_name')}: {cal} cal vs 4P+4C+9F={implied:.0f} "
                f"(P{p}/C{c}/F{f})")
    return None


def _check_logged_items(res: dict) -> list[str]:
    fails = []
    for tc in res.get("tool_calls") or []:
        inp = tc.get("input") or {}
        qty = str(inp.get("quantity") or "")
        if not QTY_RE.match(qty):
            fails.append(f"uneditable quantity {qty!r} on {inp.get('food_name')}")
        m = _macro_coherent(inp)
        if m:
            fails.append(f"macro-incoherent: {m}")
    say = res.get("say") or ""
    if enforce_say_contract(say, res.get("tool_calls") or []) != say:
        fails.append(f"say contract violated (invented digits): {say!r}")
    if LEAK_RE.search(say):
        fails.append(f"machinery leak in say: {say!r}")
    return fails


def _foods(res: dict) -> list[str]:
    return [((tc.get("input") or {}).get("food_name") or "").lower()
            for tc in (res.get("tool_calls") or [])]


def expect_action(kind: str):
    def chk(res):
        got = "pass" if res is None else res.get("action")
        return [] if got == kind else [f"expected action={kind}, got {got}: {res}"]
    return chk


def expect_log(min_items=1, contains=(), excludes=(), item_check=None):
    def chk(res):
        if res is None or res.get("action") != "log":
            return [f"expected log, got {res}"]
        fails = _check_logged_items(res)
        foods = _foods(res)
        if len(foods) < min_items:
            fails.append(f"expected >= {min_items} items, got {foods}")
        for c in contains:
            if not any(c.lower() in f for f in foods):
                fails.append(f"no item named like {c!r} in {foods}")
        for e in excludes:
            if any(e.lower() in f for f in foods):
                fails.append(f"forbidden item {e!r} present in {foods}")
        if item_check:
            fails += item_check(res)
        return fails
    return chk


def expect_update(entry_id=None, say_never_logged=True):
    def chk(res):
        if res is None or res.get("action") != "update":
            return [f"expected update, got {res}"]
        fails = []
        calls = res.get("tool_calls") or []
        if entry_id is not None and not any(
                (tc.get("input") or {}).get("entry_id") == entry_id for tc in calls):
            fails.append(f"expected entry_id {entry_id}, got {calls}")
        say = (res.get("say") or "").lower()
        if say_never_logged and re.search(r"\blogged\b", say):
            fails.append(f"update say claims 'logged': {res.get('say')!r}")
        if enforce_say_contract(res.get("say") or "", calls) != (res.get("say") or ""):
            fails.append(f"say contract violated: {res.get('say')!r}")
        return fails
    return chk


def expect_ask(mentions=(), max_points=3):
    def chk(res):
        if res is None or res.get("action") != "ask":
            return [f"expected ask, got {res}"]
        text = res.get("text") or ""
        fails = []
        if text.count("\n") > max_points:  # header + up to 3 numbered points
            fails.append(f"more than {max_points} points: {text!r}")
        for m in mentions:
            if m.lower() not in text.lower():
                fails.append(f"ask should mention {m!r}: {text!r}")
        if LEAK_RE.search(text):
            fails.append(f"machinery leak in ask: {text!r}")
        return fails
    return chk


# ── the canonical board / regulars fixtures ──────────────────────────────────
BOARD = [
    {"id": 41, "food": "Birria taco", "qty": "1 taco", "cal": 180},
    {"id": 42, "food": "Truffle fries", "qty": "6 fries", "cal": 90},
    {"id": 43, "food": "Diet Coke", "qty": "1 can", "cal": 0},
]
REG_ONE = [{"name": "Americano", "qty": "16 oz", "calories": 15, "protein": 1,
            "carbs": 2, "fats": 0, "count": 34}]
REG_TWO = REG_ONE + [{"name": "Oat milk latte", "qty": "16 oz", "calories": 190,
                      "protein": 4, "carbs": 22, "fats": 9, "count": 21}]


def _piece_count_check(res):
    """'5-6 truffle fries' priced per piece: a handful of individual fries is
    well under a menu side (~350+ cal). Ceiling 200 allows generous per-fry."""
    total = sum((tc.get("input") or {}).get("calories") or 0
                for tc in res.get("tool_calls") or [])
    return ([] if 0 < total <= 200 else
            [f"piece count re-portioned to a menu side: {total} cal for 5-6 fries"])


def _fraction_check(res):
    for tc in res.get("tool_calls") or []:
        qty = str((tc.get("input") or {}).get("quantity") or "")
        if qty.startswith("0.33"):
            return []
    return [f"1/3 not kept as 0.33: {[t.get('input') for t in res.get('tool_calls') or []]}"]


def _mass_check(res):
    for tc in res.get("tool_calls") or []:
        qty = str((tc.get("input") or {}).get("quantity") or "")
        if re.match(r"^200(\.0)? ?g", qty):
            return []
    return [f"stated 200g not kept as mass unit: {[t.get('input') for t in res.get('tool_calls') or []]}"]


def _usual_exact_check(res):
    for tc in res.get("tool_calls") or []:
        inp = tc.get("input") or {}
        if "americano" in (inp.get("food_name") or "").lower():
            if inp.get("calories") == 15:
                return []
            return [f"'my usual' re-estimated instead of using the regular's 15 cal: {inp}"]
    return [f"americano not logged: {_foods(res)}"]


def _branded_flag_check(res):
    missing = [tc["input"].get("food_name") for tc in res.get("tool_calls") or []
               if not (tc.get("input") or {}).get("is_packaged")]
    return [f"branded item(s) missing is_packaged: {missing}"] if missing else []


def _schmear_check(res):
    """Venue-real dense portion: bagel-shop cream cheese is 150-200 cal, so the
    pair lands 400+ total — a label-serving schmear (~50) under-counts."""
    total = sum((tc.get("input") or {}).get("calories") or 0
                for tc in res.get("tool_calls") or [])
    return [] if total >= 380 else [f"bagel + shop schmear priced at only {total} cal"]


# ── the matrix ────────────────────────────────────────────────────────────────
# (name, kind, payload)
#   kind "gate":  payload = (fn, text, expected_bool)          — deterministic
#   kind "live":  payload = (mode, run_kwargs, check)          — real LLM
CASES = [
    # gate rows: deterministic, no API — the full surface in one matrix
    ("gate-plan-passes", "gate", (applies, "gonna grab a burrito later", False)),
    ("gate-destructive-passes", "gate", (applies, "remove the eggs from today", False)),
    ("gate-water-passes", "gate", (applies, "just drank 20 oz of water", False)),
    ("gate-workout-passes", "gate", (applies, "did 3 sets of bench", False)),
    ("gate-question-passes", "gate", (applies, "how much protein in a big mac?", False)),
    ("gate-keepasis-closes", "gate", (thread_routes, "leave it like this", False)),
    ("gate-keepasis-2", "gate", (thread_routes, "keep it as is", False)),
    ("gate-report-routes", "gate", (applies, "had 2 eggs and toast", True)),
    ("gate-thread-complaint-routes", "gate",
     (thread_routes, "you only logged the sour cream ones", True)),
    ("gate-thread-confirm-routes", "gate", (thread_routes, "okay log it", True)),

    # live rows — clean logs
    ("log-plain-clear", "live", ("moderate",
     dict(message="had 6 oz grilled chicken breast"), expect_log(contains=["chicken"]))),
    ("log-banana-never-asks", "live", ("strict",
     dict(message="ate a medium banana"), expect_log(contains=["banana"]))),
    ("log-composite-splits", "live", ("moderate",
     dict(message="had a caesar salad with grilled chicken strips and an iced tea"),
     expect_log(min_items=3))),
    ("log-piece-count-anchor", "live", ("moderate",
     dict(message="grabbed 5-6 truffle fries off my friend's plate"),
     expect_log(item_check=_piece_count_check))),
    ("log-fraction-exact", "live", ("moderate",
     dict(message="had 1/3 of a KIND bar"),
     expect_log(item_check=_fraction_check))),
    ("log-mass-kept", "live", ("moderate",
     dict(message="ate 200g of cooked white rice"),
     expect_log(item_check=_mass_check))),
    ("log-brand-never-stripped", "live", ("quick",
     dict(message="had a Thomas' Everything Bagel Thin with Philadelphia scallion cream cheese"),
     expect_log(min_items=2, contains=["thomas", "philadelphia"],
                item_check=_branded_flag_check))),
    ("log-venue-real-schmear", "live", ("quick",
     dict(message="bagel with cream cheese from the bagel shop"),
     expect_log(item_check=_schmear_check))),
    ("log-stated-variant-strict", "live", ("strict",
     dict(message="had a Quest cookies and cream bar"),
     expect_log(contains=["quest"], item_check=_branded_flag_check))),

    # live rows — asks and thresholds
    ("ask-strict-branded-flavor", "live", ("strict",
     dict(message="had a quest bar after the gym"), expect_ask())),
    ("ask-dense-addon-strict", "live", ("strict",
     dict(message="big salad with some ranch dressing"), expect_ask())),
    ("log-dense-addon-quick", "live", ("quick",
     dict(message="big salad with some ranch dressing"), expect_log())),
    ("ask-large-swing-all-modes", "live", ("quick",
     dict(message="had half a platter of loaded nachos at the bar"), expect_ask())),
    ("ask-usual-two-matches", "live", ("moderate",
     dict(message="my usual coffee", regulars=REG_TWO),
     expect_ask(mentions=["americano", "latte"]))),
    ("ask-usual-no-match", "live", ("moderate",
     dict(message="had my usual smoothie", regulars=REG_ONE), expect_ask())),
    ("log-usual-one-match", "live", ("moderate",
     dict(message="my usual americano this morning", regulars=REG_ONE),
     expect_log(item_check=_usual_exact_check))),

    # live rows — answer turn
    ("answer-logs-never-reasks", "live", ("strict",
     dict(message="grilled, about 6 oz, and yeah a little olive oil",
          prior={"original": "had some chicken and rice",
                 "question": "Quick one so it's clean, chicken: how much, and grilled or fried?"}),
     expect_log(min_items=2))),

    # live rows — board corrections
    ("update-birria-count", "live", ("moderate",
     dict(message="I actually had 2 birria tacos", board=BOARD),
     expect_update(entry_id=41))),
    ("update-those-recent", "live", ("moderate",
     dict(message="make it 2 of those", board=BOARD,
          last_assistant="Diet Coke logged, 0 cal. Hydration's hydration."),
     expect_update(entry_id=43))),
    ("update-not-on-board-passes", "live", ("moderate",
     dict(message="actually the salmon was 8 oz", board=BOARD),
     expect_action("pass"))),
    ("no-relog-same-serving", "live", ("moderate",
     dict(message="had a birria taco", board=BOARD,
          last_assistant="Birria taco logged, 180 cal."),
     lambda res: [] if res is None or res.get("action") == "update"
     else [f"same serving re-logged: {res}"])),
    ("keepasis-model-never-writes", "live", ("moderate",
     dict(message="nah leave it like this man", board=BOARD,
          last_assistant="Those fries look undercounted, want me to bump them to a full side?"),
     expect_action("pass"))),

    # live rows — thread behavior
    ("thread-complaint-missing-only", "live", ("moderate",
     dict(message="you only logged the sour cream ones, I also had a bag of the BBQ",
          board=[{"id": 51, "food": "Quest Chips Sour Cream & Onion", "qty": "1 bag", "cal": 140}],
          last_assistant="Quest sour cream chips logged, 140 cal."),
     expect_log(min_items=1, contains=["bbq"], excludes=["sour cream"]))),
    ("thread-okay-log-it", "live", ("moderate",
     dict(message="okay log it",
          last_assistant="That reads as a chicken shawarma plate, about 6 oz chicken "
                         "with rice and a heavy pour of garlic sauce. Want me to log it?"),
     expect_log(contains=["shawarma"]))),
    ("thread-chitchat-passes", "live", ("moderate",
     dict(message="man the gym was packed today", board=BOARD),
     expect_action("pass"))),
]


async def run_case(name, mode, kwargs, check, runs):
    fails_all = []
    for i in range(runs):
        res = await run(kwargs["message"], _user(mode),
                        prior=kwargs.get("prior"), board=kwargs.get("board"),
                        last_assistant=kwargs.get("last_assistant", ""),
                        regulars=kwargs.get("regulars"))
        fails = check(res)
        if fails:
            fails_all.append((i + 1, fails, res))
    return fails_all


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--only", default="")
    ap.add_argument("--list", action="store_true")
    args = ap.parse_args()

    cases = CASES
    if args.only:
        keys = [k.strip() for k in args.only.split(",") if k.strip()]
        cases = [c for c in CASES if any(k in c[0] for k in keys)]

    if args.list:
        for name, kind, _ in cases:
            print(f"{kind:5} {name}")
        return 0

    live_count = sum(1 for _, k, _ in cases if k == "live")
    if live_count and not os.getenv("ANTHROPIC_API_KEY"):
        print(f"{R}ANTHROPIC_API_KEY not set — the live rows need the real key. "
              f"Run gate rows only with --only gate, or source .env first.{X}")
        return 2

    print(f"{B}IRONCLAD live behavioral matrix{X} — model "
          f"{food_turn._logger_model()}, {len(cases)} cases, runs={args.runs}\n")
    passed = failed = 0
    fail_log = []
    for name, kind, payload in cases:
        if kind == "gate":
            fn, text, want = payload
            ok = fn(text) is want
            status = f"{G}PASS{X}" if ok else f"{R}FAIL{X}"
            print(f"  {status}  {D}gate{X}  {name}")
            passed += ok; failed += (not ok)
            if not ok:
                fail_log.append(f"{name}: {fn.__name__}({text!r}) != {want}")
            continue
        mode, kwargs, check = payload
        fails = await run_case(name, mode, kwargs, check, args.runs)
        ok = not fails
        status = f"{G}PASS{X}" if ok else f"{R}FAIL{X}"
        print(f"  {status}  {D}{mode:8}{X} {name}")
        passed += ok; failed += (not ok)
        for run_i, fl, res in fails:
            fail_log.append(f"{name} (run {run_i}): {fl}\n    result: {res}")
            for f in fl:
                print(f"          {Y}{f}{X}")

    print(f"\n{B}{passed}/{passed + failed} cases green{X}"
          + (f"  {R}({failed} failing){X}" if failed else f"  {G}IRONCLAD{X}"))
    if fail_log:
        out = Path(__file__).resolve().parent.parent / "audits" / "ironclad_fails.txt"
        out.write_text("\n\n".join(fail_log))
        print(f"{D}failures written to {out}{X}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
