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

#: How far the stored daily total may sit from the sum of the day's entries
#: before the total is not describing the day (correction-turn directive §7).
#: Generous, because rounding at write time is real and small: entries are
#: stored rounded and the total is recomputed from them, so agreement should be
#: near-exact and a gap this size means something is actually wrong.
RECONCILE_TOLERANCE_CAL = 25.0
RECONCILE_TOLERANCE_FRAC = 0.02

#: Only guard the claims that DEPEND on the total being right. A day 80
#: calories over reads the same whether the total is off by 30 or not, and
#: failing closed there would trade a rare wrong sentence for a common missing
#: one. An extreme overage is the opposite: it is the whole message, and it is
#: exactly what an unreconciled total manufactures.
RECONCILE_GUARD_OVER_CAL = 500


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
    entry_calories: Optional[list] = None,
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

    # ── §7: is the total describing the day? ────────────────────────────────
    #
    # `total_cal` is recomputed from the day's entries on every write, so it
    # and their sum should agree to within rounding. When they do not, one of
    # them is describing a day that does not exist — and the sentence most
    # likely to be built on the disagreement is the one that leads with a large
    # number ("that puts you 2,320 calories over"), which is also the one a
    # user acts on.
    #
    # Fail closed, and only where it matters: an extreme overage is suppressed
    # rather than voiced, the numbers are still reported so the card renders,
    # and the mismatch is flagged for whoever has to explain it. Coaching from
    # an unreconciled day state is worse than not coaching.
    unreconciled = False
    if entry_calories is not None and cal_target:
        summed = float(sum(entry_calories))
        gap = abs(summed - float(total_cal or 0))
        allowed = max(RECONCILE_TOLERANCE_CAL,
                      RECONCILE_TOLERANCE_FRAC * max(summed, 1.0))
        if gap > allowed:
            unreconciled = True
            out["day_total_unreconciled"] = True
            out["day_total_gap_cal"] = int(round(summed - float(total_cal or 0)))

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
        if unreconciled and over >= RECONCILE_GUARD_OVER_CAL:
            # §7. The overage IS the message here, and an unreconciled total is
            # exactly what manufactures a large one. Say what is known — the
            # item landed — and nothing that depends on a total we cannot
            # stand behind. The numbers still ride on the receipt, so the card
            # renders and the user can see the day for themselves; what is
            # withheld is the sentence telling them what it means.
            verdict = ("That's logged, but today's total isn't adding up "
                       "against your entries — I'd rather re-check it than "
                       "tell you something wrong about the day.")
            out["verdict"] = verdict
            return out
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


# ── the model's coach line may not contradict the committed snapshot ──────────
#
# A shipped card read "Strong protein hit — the day closes clean from here"
# directly above its own "38g protein to go", while the prose in the same turn
# said "Protein is running light". Nothing was hallucinated: the card's verdict
# is the MODEL's `coach_read`, allowed to overwrite the deterministic verdict
# because it is "varied and contextual", and the only guard was that it be
# short and carry no digits. Both were true of that sentence.
#
# The numbers it contradicts are in the very same payload. So this is not a
# judgement about tone — it is an assertion against the snapshot the card is
# built from, and the check is mechanical.

_PROTEIN_DONE = (
    "protein's handled", "protein is handled", "protein handled",
    "protein hit", "protein's hit", "protein landed", "protein's covered",
    "protein covered", "protein is covered", "protein's done",
    "protein is done", "protein's there", "hit your protein",
    "closes clean", "closes the day clean", "protein's in",
)
_PROTEIN_SHORT = (
    "protein to go", "protein's light", "protein is light",
    "protein running light", "protein's running light", "needs protein",
    "protein still needs", "short on protein", "more protein",
    "protein-forward", "protein forward",
)
_CAL_OVER = ("over target", "over for the day", "went over", "you're over",
             "past your target")
_CAL_ROOM = ("plenty of room", "plenty of flexibility", "room to play",
             "lots of room", "still have room")


def coach_read_contradicts(text: str, receipt: Optional[dict]) -> bool:
    """Does this coach line disagree with the numbers on its own card?

    Only the four claims the card also states numerically are checked, and only
    when the receipt actually carries that number. A line making none of those
    claims is not second-guessed — the point is to stop a sentence and a figure
    in the same card saying opposite things, not to police the writing.
    """
    body = (text or "").strip().lower()
    if not body or not isinstance(receipt, dict):
        return False

    def says(phrases) -> bool:
        return any(p in body for p in phrases)

    rem_p = receipt.get("remaining_protein")
    if isinstance(rem_p, (int, float)):
        if rem_p > 0 and says(_PROTEIN_DONE):
            return True
        if rem_p <= 0 and says(_PROTEIN_SHORT):
            return True

    rem_c = receipt.get("remaining_cal")
    if isinstance(rem_c, (int, float)):
        if rem_c < 0 and says(_CAL_ROOM):
            return True
        if rem_c > 0 and says(_CAL_OVER):
            return True
    return False
