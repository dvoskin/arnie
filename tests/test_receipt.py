"""Decision-receipt engine — the seven card states, pinned.

The verdict must be specific and priority-ordered (over-calories beats
strong-protein, vague beats everything), the next move must appear ONLY when
the verdict doesn't already imply it, and vague logs must show honest ranges
instead of fake precision.
"""
from core.receipt import build_receipt


BASE = dict(cal_target=2160, protein_target=180)


def r(**kw):
    return build_receipt(**{**BASE, **kw})


# ── 1. standard / strong protein ────────────────────────────────────────────

def test_strong_protein_midday_points_at_dinner():
    out = r(calories=620, protein=48, total_cal=1290, total_protein=112, local_hour=13)
    assert out["remaining_cal"] == 870
    assert out["remaining_protein"] == 68
    assert out["verdict"] == "Strong protein hit. Dinner stays flexible."
    assert "next" not in out          # verdict already implies the move


def test_strong_protein_evening_closes_clean():
    out = r(calories=550, protein=52, total_cal=1900, total_protein=150, local_hour=19)
    assert out["verdict"] == "Strong protein hit. Day closes clean."


# ── 2. low-protein calorie-heavy ────────────────────────────────────────────

def test_calorie_heavy_light_protein_gets_direction():
    out = r(calories=680, protein=12, total_cal=1500, total_protein=70, local_hour=13)
    assert out["verdict"] == "Calorie-heavy for the protein return."
    assert out["next"] == "Next: lean protein first"


# ── 3. close to calorie limit ───────────────────────────────────────────────

def test_close_to_limit_keeps_it_lean():
    out = r(calories=400, protein=20, total_cal=2000, total_protein=120, local_hour=18)
    assert out["verdict"] == "You're close on calories. Keep the rest lean."
    assert out["next"] == "Next: 60g protein, lean sources"


# ── 4. protein behind pace ──────────────────────────────────────────────────

def test_behind_pace_afternoon_anchors_next_meal():
    out = r(calories=300, protein=10, total_cal=1300, total_protein=60, local_hour=16)
    assert out["verdict"] == "Protein is behind pace. Next meal needs to anchor it."
    assert out["next"] == "Next: 50g protein before dinner"


# ── 5. over calories ────────────────────────────────────────────────────────

def test_over_calories_protein_hit_is_graceful():
    out = r(calories=520, protein=45, total_cal=2300, total_protein=185, local_hour=20)
    assert out["remaining_cal"] == -140
    assert out["remaining_protein"] == -5
    assert out["verdict"] == "Calories closed over, but protein made it."


def test_over_calories_protein_short_gets_light_next():
    out = r(calories=800, protein=15, total_cal=2400, total_protein=120, local_hour=18)
    assert out["verdict"] == "Calories are over for the day."
    assert out["next"] == "Next: keep the rest light"


def test_protein_hit_calories_open_stays_flexible():
    out = r(calories=200, protein=30, total_cal=1000, total_protein=185, local_hour=15)
    assert out["verdict"] == "Protein target hit. The rest of the day stays flexible."


# ── 6. vague estimate ───────────────────────────────────────────────────────

def test_vague_estimate_shows_ranges_not_precision():
    out = r(calories=750, protein=42, total_cal=900, total_protein=50,
            local_hour=12, confidence=0.5, estimated=True)
    assert out["verdict"] == "Logged the midpoint. Portion size would tighten this."
    assert out["cal_low"] == 640 and out["cal_high"] == 850
    assert out["protein_low"] < 42 < out["protein_high"]


def test_confident_log_never_gets_ranges():
    out = r(calories=620, protein=48, total_cal=1290, total_protein=112,
            local_hour=13, confidence=0.9, estimated=False)
    assert "cal_low" not in out


# ── 7. no targets → no impact numbers, verdict still lands ──────────────────

def test_no_targets_degrades_gracefully():
    out = build_receipt(calories=620, protein=48, total_cal=1290, total_protein=112,
                        cal_target=None, protein_target=None, local_hour=13)
    assert "remaining_cal" not in out and "remaining_protein" not in out
    assert out["verdict"].startswith("Strong protein hit")


def test_first_log_of_day_names_the_anchor():
    out = r(calories=420, protein=28, total_cal=420, total_protein=28, local_hour=9)
    assert out["verdict"] == "Solid anchor. Build the day on this."
    assert "next" not in out


def test_first_log_afternoon_names_the_structure():
    out = r(calories=300, protein=18, total_cal=310, total_protein=18, local_hour=13)
    assert out["verdict"] == "Clean base. Today still needs structure."


def test_default_is_on_pace_when_day_has_shape():
    out = r(calories=250, protein=18, total_cal=1400, total_protein=80, local_hour=12)
    assert out["verdict"] == "On pace. Nothing to correct."
    assert "next" not in out


# ── 8. day-aware branches ───────────────────────────────────────────────────

def test_closing_the_protein_gap_is_named():
    # 55g item takes remaining protein from 75 → 20: the gap-closer.
    out = r(calories=450, protein=55, total_cal=1500, total_protein=160, local_hour=18)
    assert out["verdict"] == "This meaningfully closes today's protein gap."


def test_trained_today_points_at_carbs():
    out = r(calories=208, protein=28, total_cal=1200, total_protein=90,
            local_hour=15, trained_today=True)
    assert out["verdict"] == "Good post-workout protein. Add carbs if performance matters today."


def test_fat_heavy_day_caps_added_fats():
    out = r(calories=208, protein=28, total_cal=1200, total_protein=90,
            local_hour=15, total_fats=62, fat_target=70)
    assert out["verdict"] == "Protein helps, but keep added fats low from here."


def test_efficient_protein_names_the_anchor_gap():
    out = r(calories=208, protein=28, total_cal=760, total_protein=85, local_hour=13)
    assert out["verdict"] == "Efficient protein. Today still needs a bigger anchor."


def test_calorie_heavy_low_protein_reads_the_return():
    out = r(calories=680, protein=12, total_cal=1500, total_protein=70, local_hour=13)
    assert out["verdict"] == "Calorie-heavy for the protein return."
