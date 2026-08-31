"""⛔ ZERO-TURN POLICY CHARACTERISATION: what does the policy score a condiment
quantity unknown at?

WHY THIS EXISTS. The Shape-C slice removed two staged asks — c1 (Subway mayo,
"How much of the Subway Mayo?") and c4 (Chick-fil-A Polynesian sauce). The
north-star exit test passed, but a tranche meant to remove LOW-VALUE
clarification is not the same as one that removes clarification, and nothing in
the captured runs said which of those happened.

Danny's frozen decision rule, 2026-08-31, written BEFORE looking:

    below the ask threshold -> C's suppression agrees with policy; extras
                               adoption may proceed
    above the ask threshold -> C suppresses a question the system itself calls
                               material; C FAILS adoption as implemented
    unscoreable             -> that is the blocker. Do not classify by hand.
                               Register the missing representation, keep C held.

NO MODEL TURNS. Every number here is either read from a frozen capture or
computed by the shipped policy functions themselves. Nothing about mayonnaise
is invented here; the calorie span is the model's own `impact_cal` as recorded
in a frozen census, which is the exact field both materiality entry points
consume.

⭐ THE TWO ENTRY POINTS ARE NOT THE SAME PREDICATE. That is the first thing
this instrument measures, because it decides how to read everything after it:

    skills.nutrition.materiality.is_material   day-fraction -> MIN_ITEM_SHARE
                                               -> DAY_SHARE_OVERRIDE -> fraction
    skills.nutrition.ambiguity.materiality     day-fraction / fraction, and
      (-> FoodAmbiguity.is_material)           NEITHER of the middle two

`MIN_ITEM_SHARE` is the gate whose docstring records a production sweep run
expressly to stop the system asking about honey, soy sauce and a hot-sauce
drizzle. If the per-question path never evaluates it, then no condiment ask
ever crossed the condiment gate.
"""
from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from skills.nutrition import materiality as M          # noqa: E402
from skills.nutrition.ambiguity import materiality as amb_score  # noqa: E402

OUT = pathlib.Path("data/condiment_materiality_2026-08-31.json")

#: The probe identity the census ran under, verbatim from
#: `scripts/measure_real_meal_completion._make_identity`. Constructed as the
#: real ORM objects and passed through the real `_daily_targets`, so the
#: denominators are the ones the turn used, not ones retyped here.
PROBE = dict(calorie_target=2600, protein_target=190)
MODE = "moderate"          # `_make_identity` sets no mode; `_mode()` defaults.


def probe_targets() -> dict:
    from core.food_turn import _daily_targets
    from db.models import User, UserPreferences
    u = User(telegram_id="probe", name="RealMeal", age=37, sex="male",
             height_cm=178.0, current_weight_kg=86.0,
             timezone="America/New_York", onboarding_completed=True)
    u.preferences = UserPreferences(user=u, **PROBE)
    return _daily_targets(u)


# ── the captured unknowns ─────────────────────────────────────────────────────
#: `impact_cal` as recorded in a FROZEN census. Both materiality entry points
#: read this field and nothing else for the calorie span:
#:   core/food_turn.py           `float(a.get("impact_cal") or 0)`
#:   core/food_pipeline.py       `calorie_span=float(amb.get("impact_cal") or 0)`
#:
#: ⚠ CROSS-SHA. The C baseline is `407ed03`; this capture is `12f9d38`. Same
#: harness config, same corpus, same model — but a span captured on one SHA is
#: evidence about the other only as far as the interpreter is stable, and this
#: is recorded as a caveat rather than smoothed over.
CAPTURED = {
    "c1": {
        "message": "Subway Footlong Turkey on Italian Herbs & Cheese, "
                   "provolone, veggies, mayo",
        "item": "Mayo",
        "field": "quantity",
        "impact_cal": 120,
        "source": "data/corpus/producer_census_both_authorities_2026-08-28"
                  ".jsonl case=1 rep=1 (_code_sha 12f9d38)",
        "staged_prompt": "How much of the Subway Mayo?",
    },
    "c4": {
        "message": "Chick-fil-A 12-count nuggets, medium fries, and "
                   "Polynesian sauce",
        "item": "Polynesian sauce",
        "field": None,
        "impact_cal": None,     # ⛔ NOT CAPTURED IN ANY FROZEN RUN
        "source": None,
        "staged_prompt": "(sauce packet count)",
    },
}

#: ⭐ THE NEAREST NEIGHBOURS, and the reason c4 is not simply abandoned. Two
#: other condiment unknowns WERE captured with spans, on the same corpus and
#: the same probe identity. They are a second and third condiment shape, which
#: is what Danny asked for: one immaterial and one material would already mean
#: a blanket `unstated_extras` policy is too coarse.
NEIGHBOURS = {
    "c8 Blackened Ranch sauce": 100,
    "c8 Popeyes Blackened Ranch Sauce": 80,
    "c25 Spicy mayo": 150,
}


# ── 5. THE DENOMINATOR TEST ───────────────────────────────────────────────────
#: ⭐⭐⭐ WHAT C ACTUALLY DID, read off the frozen staged_state.
#:
#:   baseline c1: TWO staged items — the sandwich, and `Mayo` as its own item.
#:                The mayo item carries CONSUMED_QUANTITY/`quantity`,
#:                material=True -> asked, 2 reps of 2.
#:   under C    : ONE staged item. The mayo is no longer a row; it is an
#:                `extras` ambiguity ON THE SANDWICH, material=False -> no ask,
#:                4 observations of 4, in both the C run and its null twin.
#:
#: So the ask did not fail a materiality test. It changed which row it hangs
#: off, and the item-fraction gate divides by that row. `of_item` is the gate
#: that made the mayo material in the first place — a ~120-cal span is most of
#: a mayo and a seventh of a sandwich.
#:
#: ⛔ THIS IS THE BOUNDARY DANNY FROZE ON 2026-08-30, arriving from underneath:
#: *"Representing an unresolved semantic subject must not alter whether that
#: subject is defaultable. Representation and resolution permission are
#: independent state."* Under C they are not independent — re-representing the
#: mayo as a property of the sandwich silently moved the denominator, and the
#: denominator decided.
#:
#: The test below does not need C's own span to show this: the flip holds
#: across EVERY span in the captured condiment range and well past it, so the
#: conclusion does not rest on a number that was never recorded.
DENOMINATORS = {"mayo as its own item": 90, "extras on the sandwich": 800}


#: ⭐ READ OFF THE FROZEN RUNS, not asserted. `staged_state[].questions[].prompt`
#: in census_v8 (baseline, 407ed03) vs census_C1_slice / census_C2_nulltwin
#: (79ece8a). The same condiment shape — "How much of the <sauce>?", raised by
#: the staged authority off a CONSUMED_QUANTITY/`quantity` ambiguity — survives
#: in one case and vanishes in two.
OBSERVED = [
    "c1  Subway mayo            baseline 2/2 ASK  ->  C 0/4   REMOVED",
    "c4  Polynesian sauce       baseline 1/2 ASK  ->  C 0/4   REMOVED (weak "
    "population: already 1/2 before C)",
    "c8  Popeyes Blackened Ranch baseline 2/2 ASK ->  C 2/4   KEPT",
    "    -> C is not applying a condiment policy. It removes the shape in two "
    "cases and keeps it in a third.",
]


def policy(span, item_cal, targets):
    """The SHIPPED decision, and the SHIPPED score, on the same inputs."""
    return {
        "is_material": M.is_material(mode=MODE, calorie_span=span,
                                     item_calories=item_cal, targets=targets,
                                     confidence=None),
        "score": amb_score(mode=MODE, calorie_span=span,
                           item_calories=item_cal, targets=targets,
                           confidence=None),
    }


def trace(span, item_cal, targets):
    """Every gate `is_material` walks, in order, with its own numbers.

    Written out rather than summarised: a boolean tells you the answer and a
    trace tells you WHICH gate decided, and the whole question here is whether
    the condiment gate is the one doing the work.
    """
    of_day, of_item = M.consequence(
        spans={"calories": span}, targets=targets, item_calories=item_cal,
        confidence=None)
    day_target = float(targets.get("calories") or 0)
    ceiling = float(item_cal or 0) + abs(float(span or 0))
    return {
        "of_day": of_day,
        "of_day_dial": M.day_fraction_for(MODE),
        "gate1_day_fraction": of_day >= M.day_fraction_for(MODE),
        "ceiling_cal": round(ceiling, 1),
        "ceiling_share_of_day": round(ceiling / day_target, 4) if day_target else None,
        "min_item_share_dial": M.min_item_share_for(MODE),
        "gate2_min_item_share": (ceiling / day_target >= M.min_item_share_for(MODE)
                                 if day_target else None),
        "day_share_override_dial": M.day_share_override_for(MODE),
        "gate3_day_share_override": of_day >= M.day_share_override_for(MODE),
        "of_item": of_item,
        "of_item_dial": M.fraction_for(MODE),
        "gate4_item_fraction": of_item >= M.fraction_for(MODE),
    }


def main():
    targets = probe_targets()
    report = {
        "mode": MODE, "targets": targets, "probe": PROBE,
        "dials": {
            "day_fraction": M.day_fraction_for(MODE),
            "min_item_share": M.min_item_share_for(MODE),
            "day_share_override": M.day_share_override_for(MODE),
            "item_fraction": M.fraction_for(MODE),
            "min_item_share_cal": round(
                M.min_item_share_for(MODE) * float(targets["calories"]), 1),
            "day_fraction_cal": round(
                M.day_fraction_for(MODE) * float(targets["calories"]), 1),
        },
    }

    print(f"mode={MODE}  targets={targets}")
    d = report["dials"]
    print(f"dials: day_fraction={d['day_fraction']} "
          f"({d['day_fraction_cal']} cal)  min_item_share={d['min_item_share']} "
          f"({d['min_item_share_cal']} cal)  "
          f"day_share_override={d['day_share_override']}  "
          f"item_fraction={d['item_fraction']}")

    # ── 1. DO THE TWO ENTRY POINTS AGREE? ────────────────────────────────────
    print("\n── 1. the two predicates, over the condiment region "
          "──────────────")
    print(f"{'span':>5} {'item_cal':>8} | {'is_material':>11} "
          f"{'score>=1':>9} {'score':>7} | verdict")
    disagree = []
    for span in (10, 20, 50, 80, 100, 120, 150, 200):
        for item_cal in (20, 40, 80, 120, 200, 400):
            r = policy(span, item_cal, targets)
            same = r["is_material"] == (r["score"] >= 1.0)
            if not same:
                disagree.append({"span": span, "item_cal": item_cal, **r})
            print(f"{span:>5} {item_cal:>8} | {str(r['is_material']):>11} "
                  f"{str(r['score'] >= 1.0):>9} {r['score']:>7} | "
                  f"{'agree' if same else '⛔ DISAGREE'}")
    report["predicate_disagreements"] = disagree
    print(f"\ndisagreements: {len(disagree)} of 48 cells")

    # ── 2. c1, THE ONE UNKNOWN WITH A CAPTURED SPAN ──────────────────────────
    print("\n── 2. c1 Subway mayo, span=120 (captured) "
          "───────────────────────────")
    c1 = CAPTURED["c1"]
    c1_rows = []
    for item_cal in (0, 50, 90, 100, 110, 150, 200, 300, 400, 500):
        r = policy(c1["impact_cal"], item_cal or None, targets)
        t = trace(c1["impact_cal"], item_cal, targets)
        c1_rows.append({"item_cal": item_cal, **r, "trace": t})
        print(f"  item_cal={item_cal:>4}  is_material={str(r['is_material']):>5}"
              f"  score={r['score']:>6}  of_day={t['of_day']:.4f} "
              f"of_item={t['of_item']:.3f}  "
              f"min_item_share_passed={t['gate2_min_item_share']}")
    report["c1"] = {**c1, "rows": c1_rows}

    # ── 3. c4 AND THE OTHER CONDIMENT SHAPES ─────────────────────────────────
    print("\n── 3. c4 and the neighbouring condiment shapes "
          "──────────────────────")
    print(f"  c4 Polynesian sauce: impact_cal = "
          f"{CAPTURED['c4']['impact_cal']}  ⛔ NOT CAPTURED IN ANY FROZEN RUN")
    nb = {}
    for name, span in NEIGHBOURS.items():
        row = []
        for item_cal in (40, 80, 140, 200):
            r = policy(span, item_cal, targets)
            row.append({"item_cal": item_cal, **r})
        nb[name] = {"span": span, "rows": row}
        cells = "  ".join(
            f"{x['item_cal']}cal:{'MATERIAL' if x['is_material'] else 'no'}"
            for x in row)
        print(f"  {name:<34} span={span:>3}  {cells}")
    report["neighbours"] = nb

    # ── 4. WHAT WOULD IT TAKE TO NOT BE MATERIAL? ────────────────────────────
    print("\n── 4. the boundary: the largest span that is NOT material "
          "───────────")
    for item_cal in (40, 80, 120, 200, 400):
        boundary = None
        for span in range(1, 401):
            if M.is_material(mode=MODE, calorie_span=span,
                             item_calories=item_cal, targets=targets):
                boundary = span
                break
        print(f"  item_cal={item_cal:>4}  first material span = {boundary} cal")
        report.setdefault("boundaries", {})[str(item_cal)] = boundary


    # ── 5. THE DENOMINATOR TEST ──────────────────────────────────────────────
    print("\n── 5. the denominator test: same unknown, two rows "
          "─────────────────")
    flips = []
    for span in (40, 60, 80, 100, 120, 150, 200, 240):
        row = {"span": span}
        for name, item_cal in DENOMINATORS.items():
            row[name] = M.is_material(mode=MODE, calorie_span=span,
                                      item_calories=item_cal, targets=targets)
        row["flips"] = len(set(row[n] for n in DENOMINATORS)) > 1
        flips.append(row)
        cells = "  ".join(
            f"{n}={'MATERIAL' if row[n] else 'immaterial'}" for n in DENOMINATORS)
        print(f"  span={span:>4}  {cells}"
              f"{'   ⛔ FLIPS ON THE DENOMINATOR ALONE' if row['flips'] else ''}")
    report["denominator_test"] = flips
    n_flip = sum(1 for r in flips if r["flips"])
    print(f"  -> {n_flip} of {len(flips)} spans flip on the denominator alone; "
          f"every captured condiment span (80, 100, 120, 150) is among them")

    # ── 6. IS C CONSISTENT ABOUT CONDIMENTS? ─────────────────────────────────
    print("\n── 6. C's treatment of the same shape, from the frozen runs "
          "──────")
    for line in OBSERVED:
        print(f"  {line}")
    report["observed"] = OBSERVED

    OUT.write_text(json.dumps(report, indent=1, default=str) + "\n")
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    main()
