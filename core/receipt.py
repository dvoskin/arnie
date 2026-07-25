"""Decision-receipt context for the inline macro card.

After a food log, the chat card should answer three things without opening the
full day log: what did I log, what did it do to my day, what should I do next.
This module computes that context DETERMINISTICALLY at log time (no LLM call,
no extra latency) so the card is a stable receipt of the moment it was logged —
scrolling back a week later still shows what the day looked like right then.

The card renders the numbers itself ("870 cal left · 68g protein to go") from
`remaining_cal` / `remaining_protein`; the one-line coach verdict and the
optional next move ship as text. Verdicts are specific, never generic praise,
and the next move only appears when the verdict alone doesn't imply it —
most logs should NOT feel coached.
"""
from __future__ import annotations

from typing import Optional


#: Above this many calories over target, "a little over" is no longer an honest
#: description. Below it the overage is a rounding-scale event on most targets;
#: above it, it is the fact of the day and the coaching has to lead with it.
SUBSTANTIALLY_OVER_CAL = 300


def build_receipt(
    *,
    calories: float,
    protein: float,
    total_cal: float,
    total_protein: float,
    cal_target: Optional[float],
    protein_target: Optional[float],
    local_hour: Optional[int],
    confidence: Optional[float] = None,
    estimated: bool = False,
    total_fats: Optional[float] = None,
    fat_target: Optional[float] = None,
    trained_today: bool = False,
    carbs: Optional[float] = None,
) -> dict:
    """Context for one logged item against the day so far.

    Returns only the keys that carry information (all optional on the wire):
      remaining_cal      int — calories left today (negative = over)
      remaining_protein  int — grams left today (negative/zero = target hit)
      verdict            str — one-sentence coach read of this log
      next               str — compact next move, only when genuinely useful
      cal_low/cal_high, protein_low/protein_high — honest ranges for vague
                         estimates instead of fake precision
    """
    out: dict = {}

    rem_c = int(round(cal_target - total_cal)) if cal_target else None
    rem_p = int(round(protein_target - total_protein)) if protein_target else None
    if rem_c is not None:
        out["remaining_cal"] = rem_c
    if rem_p is not None:
        out["remaining_protein"] = rem_p

    if confidence is not None:
        out["confidence"] = round(float(confidence), 2)

    # ── Vague estimate: show a range, admit the midpoint ────────────────────
    vague = bool(estimated) and confidence is not None and confidence < 0.6
    if vague and calories >= 100:
        out["cal_low"] = int(round(calories * 0.86 / 10.0) * 10)
        out["cal_high"] = int(round(calories * 1.14 / 10.0) * 10)
        if protein >= 10:
            out["protein_low"] = int(round(protein * 0.82))
            out["protein_high"] = int(round(protein * 1.18))

    # ── Verdict (priority-ordered; first match wins) ────────────────────────
    density = (protein * 4.0 / calories) if calories else 0.0
    behind_pace = False
    if protein_target and local_hour is not None:
        # Straight-line pace from 7am to 9pm; behind means >25g under where
        # the day "should" be by this hour.
        frac = min(1.0, max(0.0, (local_hour - 7) / 14.0))
        behind_pace = total_protein < (protein_target * frac) - 25

    nxt: Optional[str] = None
    # Day-shape signals (density above is THIS item's protein efficiency)
    protein_dense = density >= 0.30 and protein >= 15
    efficient = density >= 0.45 and calories <= 300
    rem_p_before = (rem_p + int(round(protein))) if rem_p is not None else None
    rem_c_before = (rem_c + int(round(calories))) if rem_c is not None else None
    # A banked win is only worth announcing ONCE — after protein is hit (or
    # the day closed over), every further log repeating it reads like a
    # broken record. Repeat states fall to the quiet default the client hides.
    newly_hit = (rem_p is not None and rem_p <= 0
                 and rem_p_before is not None and rem_p_before > 0)
    newly_over = (rem_c is not None and rem_c < 0
                  and rem_c_before is not None and rem_c_before >= 0)
    closes_gap = (
        rem_p is not None and rem_p_before is not None
        and rem_p_before > 45 and rem_p <= 25
    )
    # Carb-dominant, low-protein item (rice, fruit, toast) while the day's
    # protein gap is still real — name what the food did and didn't do.
    carb_add = (
        carbs is not None and calories >= 80
        and carbs * 4.0 >= 0.55 * calories and protein < 12
    )
    fat_heavy_day = (
        fat_target is not None and total_fats is not None
        and total_fats >= 0.85 * fat_target
    )
    day_open = total_cal < 900

    if vague:
        verdict = "I logged that as a range — a portion size would tighten it up."
    elif rem_c is not None and rem_c < 0:
        # THE CALORIE STATE IS PRIMARY. Protein landing is a secondary fact and
        # may be said alongside, but it may never soften or replace an adverse
        # calorie state.
        #
        # This branch used to fall through to "You're on pace, so there's
        # nothing to correct." whenever the day was ALREADY over before this
        # item — the intent was a quiet default for a repeat state, but the
        # string chosen is a claim, and it is false. A shipped card read
        # "Protein covered · 2,320 cal over" directly above it.
        over = -rem_c
        if over >= SUBSTANTIALLY_OVER_CAL:
            verdict = (f"That puts you about {int(over)} calories over for the "
                       f"day — worth knowing rather than fixing tonight.")
            if rem_p is not None and rem_p <= 0:
                verdict = (f"Protein landed, but that's about {int(over)} "
                           f"calories over for the day.")
        elif rem_p is not None and rem_p <= 0:
            verdict = ("That closes the day and protein made it, a little over "
                       "on calories.")
        else:
            verdict = "You're over target for the day, so keep the rest of it clean."
        if local_hour is not None and local_hour < 20:
            nxt = "Next: keep the rest light"
    elif rem_p is not None and rem_p <= 0:
        verdict = ("Protein's handled for the day — calories are the thing to watch now."
                   if newly_hit else "You're on pace, so there's nothing to correct.")
    elif closes_gap:
        verdict = "One more protein-forward meal gets you to your target."
    elif rem_c is not None and 0 < rem_c <= 250:
        if protein_dense:
            verdict = "That's useful protein, though calories are getting tight for the day."
        else:
            verdict = "Calories are getting tight, so keep your next meal lean."
        if rem_p is not None and rem_p > 15:
            nxt = f"Next: {rem_p}g protein, lean sources"
    elif carb_add and rem_p is not None and rem_p >= 25:
        verdict = "That was mostly carbs — protein still needs an anchor today."
    elif calories < 150 and rem_p is not None and rem_p > 40 and total_cal >= 400:
        verdict = "That's a small addition, so you still have room for a full meal."
    elif trained_today and protein_dense:
        verdict = "Good protein after training, and the carbs are working for you today."
    elif fat_heavy_day and protein_dense:
        verdict = "Protein moved nicely — keep fats low through the rest of the day."
    elif efficient:
        if rem_p is not None and rem_p > 80:
            verdict = "Efficient protein for the calories, but the day still needs a bigger anchor."
        else:
            verdict = "Efficient protein — that barely moved your calories."
    elif protein_dense and 25 <= protein < 35 and calories <= 450:
        verdict = "That's a solid anchor — protein is moving without burning through your day."
    elif protein >= 35:
        if local_hour is None:
            verdict = "Strong protein hit, which leaves your next meal flexible."
        elif local_hour < 11:
            verdict = "Strong protein hit, which leaves lunch flexible."
        elif local_hour < 17:
            verdict = "Strong protein hit, which leaves dinner flexible."
        else:
            verdict = "Strong protein hit — the day closes clean from here."
    elif calories >= 500 and density < 0.15:
        verdict = "That was calorie-heavy for the protein it returned."
        nxt = "Next: lean protein first"
    elif behind_pace and local_hour is not None and local_hour >= 14:
        verdict = "Protein's behind pace, so dinner needs to be the anchor."
        if rem_p is not None and rem_p > 0:
            when = "before dinner" if local_hour < 18 else "tonight"
            nxt = f"Next: {min(rem_p, 50)}g protein {when}"
    elif total_cal - calories <= 60 and calories >= 100:
        # First real log of the day — name the anchor, not generic praise.
        if protein < 20 and calories < 400:
            verdict = "That's a light start, so dinner needs to be the anchor."
        elif local_hour is not None and local_hour < 11:
            verdict = "That's a solid anchor to build the rest of the day on."
        else:
            verdict = "That's a clean base, though the day still needs some structure."
    elif day_open:
        verdict = "That's a clean base, though the day still needs some structure."
    else:
        verdict = "You're on pace, so there's nothing to correct."

    out["verdict"] = verdict
    if nxt:
        out["next"] = nxt
    return out
