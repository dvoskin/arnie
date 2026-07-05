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
    if vague:
        verdict = "Logged the midpoint. Portion size would tighten this."
    elif rem_c is not None and rem_c < 0:
        if rem_p is not None and rem_p <= 0:
            verdict = "Calories closed over, but protein made it."
        else:
            verdict = "Calories are over for the day."
            if local_hour is not None and local_hour < 20:
                nxt = "Next: keep the rest light"
    elif rem_p is not None and rem_p <= 0:
        verdict = "Protein target hit. The rest of the day stays flexible."
    elif rem_c is not None and 0 < rem_c <= 250:
        verdict = "You're close on calories. Keep the rest lean."
        if rem_p is not None and rem_p > 15:
            nxt = f"Next: {rem_p}g protein, lean sources"
    elif protein >= 35 or (calories >= 300 and density >= 0.30):
        if local_hour is None:
            verdict = "Strong protein hit. The next meal stays flexible."
        elif local_hour < 11:
            verdict = "Strong protein hit. Lunch stays flexible."
        elif local_hour < 17:
            verdict = "Strong protein hit. Dinner stays flexible."
        else:
            verdict = "Strong protein hit. Day closes clean."
    elif calories >= 500 and density < 0.15:
        verdict = "Good meal, but light protein for the calories."
        nxt = "Next: lean protein first"
    elif behind_pace and local_hour is not None and local_hour >= 14:
        verdict = "Protein is behind pace. Next meal needs to anchor it."
        if rem_p is not None and rem_p > 0:
            when = "before dinner" if local_hour < 18 else "tonight"
            nxt = f"Next: {min(rem_p, 50)}g protein {when}"
    elif total_cal - calories <= 60 and calories >= 150:
        # First real log of the day — name the anchor, not generic praise.
        if local_hour is not None and local_hour < 11:
            verdict = "Solid anchor. Build the day on this."
        else:
            verdict = "First log in. Plenty of room to work with."
    else:
        verdict = "Clean log. No correction needed."

    out["verdict"] = verdict
    if nxt:
        out["next"] = nxt
    return out
