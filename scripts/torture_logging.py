"""Food-logging TORTURE harness — the multi-turn, real-execution stress test.

Where eval_multi_item.py measures *planning* (does the model emit N log_food
calls for an N-item message, tools=True, NO execution), THIS drives the FULL
production turn — real model → run_chat_turn → tool execution → phantom-rescue →
persistence — against a scratch in-memory DB, then asserts the DATABASE actually
gained the right rows. The DB is the oracle. That is the only way to catch the
class of bug that burned Danny: a reply that SAYS "logged" (even "checked the
board, it's there") while nothing was written.

Per turn we classify against ground truth (DB row delta):
  PASS     — enough new rows, required items present, no false claim
  PHANTOM  — the reply CLAIMS a save (or a running total) but the DB didn't
             gain what it should  ← the worst failure, the one we hunt
  DROP     — some but not all named items landed (the salmon incident)
  MISS     — a turn that MUST log logged nothing and didn't even claim it
             (over-timid: asked to clarify when the message was unambiguous)
  DOUBLE   — more rows than expected (over-logging / relog dup)

  python scripts/torture_logging.py                     # 1 pass over the battery
  python scripts/torture_logging.py --runs 5            # 5× for stochastic coverage
  python scripts/torture_logging.py --model claude-opus-4-8   # pin the tier (prod)
  python scripts/torture_logging.py --only veggie,break       # subset by name

Set DEFAULT_MODEL via --model (prod runs opus-4-8). Failing transcripts are
written to audits/torture_fails_<model>.txt for inspection.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── Scenario battery ─────────────────────────────────────────────────────────
# Each scenario is a list of turns. A turn:
#   say         — the user message (supports "[EDIT]" prefix → replaces prior turn)
#   min         — minimum NEW food rows this turn must create (default 0)
#   max_total   — optional cap on TOTAL rows after this turn (catch double-log)
#   need        — item-name fragments that must be present among ALL rows after
#                 this turn (cumulative; catches the centerpiece-drop)
#   must_log    — if True, logging nothing here is a MISS even if no false claim
#                 (used when the message is unambiguous and clarifying is wrong)
SCENARIOS = {
    # ---- completeness (planning that must survive execution) ----
    "multi3": [
        dict(say="chicken breast, white rice, and broccoli",
             min=3, need=["chicken", "rice", "broccoli"], must_log=True),
    ],
    "multi_bowl5": [
        dict(say="burrito bowl — rice, black beans, steak, guac, and cheese",
             min=5, need=["rice", "bean", "steak", "guac", "cheese"], must_log=True),
    ],
    "dinner_centerpiece": [  # the salmon-drop shape: centerpiece + sides in one msg
        dict(say="6 oz salmon, quinoa, roasted brussels sprouts, and a slice of bread",
             min=4, need=["salmon", "quinoa", "brussel", "bread"], must_log=True),
    ],
    "big_meal_vague_portions": [  # Danny 19:59 — the REAL failure: a 5-item meal where
        # MULTIPLE portions are vague (medium fries, unsized latte, "four bites"). Model
        # must log ALL 5 now with estimates, NOT hold + ask "fries size? latte oz?" first.
        dict(say="Just had a big meal :( I had a turkey club on toasted sourdough with "
                 "about 5 oz turkey, 3 slices of bacon, 2 slices cheddar, lettuce, tomato "
                 "and mayo. I also had a medium order of fries, some coleslaw, an iced "
                 "whole-milk latte, and about four bites of cheesecake",
             min=5, need=["turkey", "fries", "coleslaw", "latte", "cheesecake"],
             must_log=True),
    ],
    "big_meal_vague_portions:strict": [  # Danny's EXACT prod condition: strict mode +
        # the vague-portion big meal. Must log all 5 FIRST (strict asks to refine AFTER).
        dict(say="Just had a big meal :( I had a turkey club on toasted sourdough with "
                 "about 5 oz turkey, 3 slices of bacon, 2 slices cheddar, lettuce, tomato "
                 "and mayo. I also had a medium order of fries, some coleslaw, an iced "
                 "whole-milk latte, and about four bites of cheesecake",
             min=5, need=["turkey", "fries", "coleslaw", "latte", "cheesecake"],
             must_log=True),
    ],
    "list_with_ambiguity": [  # Danny 19:42 — a 7-item list where one item's prep is
        # unstated (broccoli "cooked with olive oil", chicken prep). Must log ALL now
        # with estimates, NEVER hold the list for a "grilled or oil?" clarify.
        dict(say="For lunch I had 6 oz grilled chicken breast, 1¼ cups jasmine rice, "
                 "half an avocado, a cup of roasted broccoli, 2 tbsp spicy mayo, a Diet "
                 "Coke, and one small chocolate chip cookie",
             min=6, need=["chicken", "rice", "avocado", "broccoli", "mayo", "cookie"],
             must_log=True),
    ],
    # ---- imperative commands (the phantom class) ----
    "imperative_bar": [
        dict(say="add a barebells salty peanut bar", min=1, need=["barebell"], must_log=True),
    ],
    "veggie_20cal": [  # Danny's exact 2:38 phantom — small item under tolerance
        dict(say="Add lettuce, tomato, onion and mustard, 20 cal, to my lunch",
             min=1, need=["lettuce"], must_log=True),
    ],
    "put_on_log": [
        dict(say="I just ate 6 oz grilled chicken and a cup of white rice", min=1),
        dict(say="put it on my log", need=["chicken", "rice"], must_log=True),
    ],
    # ---- clarify → answer (must not phantom on the answer) ----
    "clarify_wrap": [
        dict(say="I had a grilled chicken wrap", min=0),
        dict(say="regular 10 inch wrap, chicken was about 5 oz, minimal oil",
             need=["chicken"], must_log=True),
    ],
    # ---- break-into-components / delete+relog (THE failing case) ----
    "break_components": [
        dict(say="log a grilled chicken wrap, about 480 cal", min=1),
        dict(say="actually break that wrap into its components instead — chicken, tortilla, and the veggies",
             need=["chicken", "tortilla"], must_log=True, max_total=6),
    ],
    "relog_corrected": [
        dict(say="log a protein shake, 300 cal", min=1),
        dict(say="actually that was 220 cal, fix it", max_total=1, need=["shake"]),
    ],
    # ---- repeats (completeness vs dedup) ----
    "another_one": [
        dict(say="a barebells salty peanut bar", min=1),
        dict(say="had another one", min=1, max_total=2, need=["barebell"], must_log=True),
    ],
    # ---- edit flow ----
    "edit_add_item": [
        dict(say="chicken and rice", min=2),
        dict(say="[EDIT] chicken, rice, and broccoli",
             need=["chicken", "rice", "broccoli"], max_total=3),
    ],
    # ---- small-item total-claim (medjool dates) ----
    "dates_small": [
        dict(say="I had 2 medjool dates", min=1, need=["date"], must_log=True),
    ],
    # ---- carryover guard (must NOT over-log next turn) ----
    "carryover_guard": [
        dict(say="grilled chicken and white rice", min=2),
        dict(say="thanks, that hit the spot", min=0, max_total=2),
    ],
    # ---- rapid fire (high-frequency within one session) ----
    "rapid_fire": [
        dict(say="add a banana", min=1),
        dict(say="add a cup of black coffee", min=1),
        dict(say="add 3 scrambled eggs", min=1),
        dict(say="add 2 slices of whole wheat toast", min=1),
        dict(say="add a scoop of whey protein", min=1, max_total=5),
    ],
    # ---- mixed food + water ----
    "food_plus_water": [
        dict(say="a greek yogurt with honey and a big glass of water",
             min=1, need=["yogurt"], must_log=True),
    ],
    # ---- restaurant two-item then portions ----
    "restaurant": [
        dict(say="at dinner I got the salmon and a side caesar salad", min=0),
        dict(say="salmon was about 7 oz, caesar was a full portion",
             need=["salmon", "caesar"], must_log=True),
    ],

    # ══ DIFFICULT FOOD COMBINATIONS ══════════════════════════════════════════
    # Composed bowl — 6 named components, must decompose fully (burrito-shape).
    "poke_bowl": [
        dict(say="a poke bowl with about 5 oz ahi tuna, a cup of rice, edamame, "
                 "half an avocado, seaweed salad, and a drizzle of spicy mayo",
             min=5, need=["tuna", "rice", "edamame", "avocado", "mayo"], must_log=True),
    ],
    # Grazing board — many small distinct items in one message.
    "charcuterie": [
        dict(say="a charcuterie board: prosciutto, salami, some brie, a bit of "
                 "cheddar, a handful of crackers, grapes, a few olives and a little honey",
             min=6, need=["prosciutto", "salami", "brie", "cracker", "olive"],
             must_log=True),
    ],
    # DEDUP TRAP — same protein, DIFFERENT cuts must stay TWO rows (not merged).
    "two_chicken_cuts": [
        dict(say="6 oz grilled chicken breast and 4 oz braised chicken thigh",
             min=2, need=["breast", "thigh"], max_total=2, must_log=True),
    ],
    # OVER-DECOMPOSITION GUARD — a PB&J is ONE item, not three (bread+PB+jelly).
    "pbj_is_one": [
        dict(say="a peanut butter and jelly sandwich", min=1, max_total=1,
             need=["peanut butter", "jelly"]),
    ],
    # Branded + homemade in one message.
    "branded_plus_generic": [
        dict(say="a Chipotle chicken burrito bowl and a homemade side salad",
             min=2, need=["chipotle", "salad"], must_log=True),
    ],
    # Alcohol — three drinks, each a distinct log.
    "mixed_drinks": [
        dict(say="a margarita, a light beer, and a glass of red wine",
             min=3, need=["margarita", "beer", "wine"], must_log=True),
    ],
    # Fried/hidden-fat restaurant meal — must estimate UP, log all three.
    "restaurant_fried": [
        dict(say="chicken parm at an Italian spot, probably fried, with a side of "
                 "spaghetti and a piece of garlic bread",
             min=3, need=["parm", "spaghetti", "garlic bread"], must_log=True),
    ],
    # Russian multi-item lunch — RU units/separators must decompose like EN.
    "ru_lunch": [
        dict(say="на обед рис 200г, куриная отбивная 150г и салат из огурцов",
             min=3, need=["рис", "отбивн", "салат"], must_log=True),
    ],
    # Combined dish that IS multiple items — burger + fries + shake = three.
    "burger_combo": [
        dict(say="a double cheeseburger with fries and a chocolate milkshake",
             min=3, need=["burger", "fries", "shake"], must_log=True),
    ],
}

_CLAIM_WORDS = (
    "logged", "on the board", "on your log", "in your log", "that's in",
    "recorded", "noted", "in now", "in the books", "locked in", "added that",
    "all three", "all four", "all five", "it's there", "actually there",
    "got it down", "put it on",
)
_TOTAL_RE = re.compile(r"\b\d[\d,]{1,5}\s*/\s*\d[\d,]{1,5}\s*(?:cal|calorie)", re.I)


def _claims_save(reply: str) -> bool:
    r = (reply or "").lower()
    return any(w in r for w in _CLAIM_WORDS) or bool(_TOTAL_RE.search(reply or ""))


def _has(rows, frag: str) -> bool:
    frag = frag.lower()
    return any(frag in (r.parsed_food_name or "").lower() for r in rows)


async def run_scenario(H, model, name, turns, fails):
    """Drive one scenario end to end. Returns list of per-turn verdicts."""
    from core.chat_service import run_chat_turn
    from db.queries import reload_user
    import simulate_logging_discipline as S

    uid = await H.new_user()
    # Scenarios whose name ends in ":strict" run under food_logging_mode='strict'
    # (Danny's real setting — the reason a default-user harness missed the failure).
    if name.endswith(":strict"):
        from sqlalchemy import update as _upd
        from db.models import UserPreferences as _UP
        async with await H.session() as db:
            await db.execute(_upd(_UP).where(_UP.user_id == uid)
                             .values(food_logging_mode="strict"))
            await db.commit()
    verdicts = []
    last_log_id = None
    transcript = [f"### scenario={name} model={model}"]

    for i, turn in enumerate(turns):
        say = turn["say"]
        # resolve [EDIT] → real prior conversation-log id
        if say.startswith("[EDIT]"):
            say = f"[EDIT:{last_log_id}]" + say[len("[EDIT]"):]

        before = await S.db_food_rows(H, uid)
        bubbles: list[str] = []

        async with await H.session() as db:
            user = await reload_user(db, uid)
            try:
                tr = await run_chat_turn(
                    db, user, say, platform="ios", schedule_background=False,
                    on_text_bubble=lambda b: bubbles.append(b) or asyncio.sleep(0),
                )
                await db.commit()
                last_log_id = getattr(tr, "log_id", None) or last_log_id
                fired = [tc.get("name") for tc in (getattr(tr, "tool_calls", None) or [])]
                reply = " ||| ".join(bubbles) if bubbles else _resp_text(tr)
            except Exception as e:
                verdicts.append(("ERROR", name, i))
                transcript.append(f"[T{i}] USER: {say}\n  !! EXCEPTION: {e!r}")
                continue

        after = await S.db_food_rows(H, uid)
        new = after[len(before):]
        newnames = [r.parsed_food_name for r in new]
        mn = turn.get("min", 0)
        need = turn.get("need", [])
        max_total = turn.get("max_total")
        must_log = turn.get("must_log", False)
        claimed = _claims_save(reply)

        # A genuine repeat ("had another one") RECONCILES: it bumps an existing row's
        # quantity/calories instead of adding a new row — a valid log with 0 new rows.
        # Count a calorie-increasing bump (no new row) as one logged item so the scorer
        # doesn't false-MISS a correct reconcile.
        _cal_before = round(sum(float(r.calories or 0) for r in before))
        _cal_after = round(sum(float(r.calories or 0) for r in after))
        _bumped = 1 if (len(new) == 0 and _cal_after > _cal_before) else 0
        logged = len(new) + _bumped

        need_ok = all(_has(after, f) for f in need)
        verdict = "PASS"
        if max_total is not None and len(after) > max_total:
            verdict = "DOUBLE"
        elif logged < mn and claimed:
            verdict = "PHANTOM"          # said saved, DB says no
        elif not need_ok and claimed:
            verdict = "PHANTOM"          # claimed complete, an item is missing
        elif logged < mn and must_log:
            verdict = "MISS"             # should've logged, logged nothing, didn't lie
        elif not need_ok and must_log:
            verdict = "DROP"             # partial — a named item didn't land
        elif logged < mn:
            verdict = "SOFT"             # under, but a clarify (no claim) — acceptable-ish

        verdicts.append((verdict, name, i))
        _bump_note = f" bump(+{_cal_after - _cal_before}cal)" if _bumped else ""
        transcript.append(
            f"[T{i}] USER: {say}\n"
            f"  fired={fired} new_rows={newnames}{_bump_note} claimed={claimed} → {verdict}\n"
            f"  ARNIE: {reply[:280]!r}"
        )

    if any(v[0] in ("PHANTOM", "DROP", "MISS", "DOUBLE", "ERROR") for v in verdicts):
        fails.append("\n".join(transcript))
    return verdicts


def _resp_text(tr) -> str:
    resp = getattr(tr, "response", None)
    if resp is None:
        return ""
    b = getattr(resp, "bubbles", None)
    if b:
        return " ||| ".join(str(x) for x in b)
    return str(resp)


async def main(runs, model, only):
    if model:
        os.environ["DEFAULT_MODEL"] = model
    import simulate_logging_discipline as S  # noqa
    H = S.Harness()
    await H.setup()

    names = list(SCENARIOS)
    if only:
        keys = [k.strip() for k in only.split(",")]
        names = [n for n in names if any(k in n for k in keys)]

    tally: dict[str, int] = {}
    per_scenario: dict[str, list] = {n: [] for n in names}
    fails: list[str] = []

    for r in range(runs):
        for n in names:
            verdicts = await run_scenario(H, model, n, SCENARIOS[n], fails)
            for v, _n, _i in verdicts:
                tally[v] = tally.get(v, 0) + 1
                per_scenario[n].append(v)
        print(f"  run {r+1}/{runs} done", flush=True)

    # ── report ──
    print("\n" + "═" * 74)
    print(f"TORTURE — LOGGING  model={model or os.getenv('DEFAULT_MODEL','default')}  runs={runs}")
    print("═" * 74)
    bad = {"PHANTOM", "DROP", "MISS", "DOUBLE", "ERROR"}
    print(f"{'scenario':<22} {'turns':>5}  verdicts")
    for n in names:
        vs = per_scenario[n]
        clean = sum(1 for v in vs if v not in bad)
        flag = "" if clean == len(vs) else "  ‼"
        summary = ", ".join(f"{k}×{vs.count(k)}" for k in sorted(set(vs)))
        print(f"{n:<22} {len(vs):>5}  {summary}{flag}")
    print("─" * 74)
    total = sum(tally.values())
    for k in ("PASS", "SOFT", "PHANTOM", "DROP", "MISS", "DOUBLE", "ERROR"):
        if tally.get(k):
            print(f"  {k:<8} {tally[k]:>4}  ({tally[k]/total:.0%})")
    bad_n = sum(tally.get(k, 0) for k in bad)
    print("─" * 74)
    print(f"  CLEAN {total-bad_n}/{total} ({(total-bad_n)/total:.0%})   "
          f"BAD {bad_n}  (phantom={tally.get('PHANTOM',0)} drop={tally.get('DROP',0)} "
          f"miss={tally.get('MISS',0)} double={tally.get('DOUBLE',0)} err={tally.get('ERROR',0)})")

    if fails:
        out = Path(__file__).resolve().parent.parent / "audits" / \
            f"torture_fails_{(model or 'default').replace('/','_')}.txt"
        out.parent.mkdir(exist_ok=True)
        out.write_text("\n\n".join(fails))
        print(f"\n  {len(fails)} failing scenario transcript(s) → {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--model", default=os.getenv("EVAL_MODEL"))
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    asyncio.run(main(args.runs, args.model, args.only))
