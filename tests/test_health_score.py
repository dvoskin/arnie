"""Day nutrition-quality score (core/health_score.py) — the Coach Health Score card."""
from core.health_score import compute_health_score, _processing_class


def _e(name, cal, protein=0, fiber=0, sugar=0, sodium=0, micros=None,
       processing_level=None):
    return {"name": name, "calories": cal, "protein": protein, "fiber": fiber,
            "sugar": sugar, "sodium": sodium, "micros": micros or {},
            "processing_level": processing_level}


def test_too_little_signal_returns_none():
    assert compute_health_score([]) is None
    assert compute_health_score([_e("Coffee", 25)]) is None   # < 300 kcal


def test_whole_protein_forward_day_scores_high():
    day = [
        _e("Grilled chicken and rice", 650, protein=55, fiber=4, sodium=400,
           micros={"iron": 2, "b12": 1, "zinc": 3, "selenium": 20, "magnesium": 60}),
        _e("Greek yogurt with berries", 220, protein=20, fiber=4, sugar=12,
           micros={"calcium": 250, "potassium": 300, "vitamin_c": 30}),
        _e("Salmon with broccoli and potato", 700, protein=45, fiber=9, sodium=350,
           micros={"vitamin_d": 400, "omega_3": 1, "folate": 100, "vitamin_k": 90}),
    ]
    s = compute_health_score(day)
    assert s is not None
    assert s["score"] >= 80 and s["band"] == "excellent"
    assert s["processed_pct"] <= 15
    labels = [d["label"] for d in s["drivers"]]
    assert "Protein density" in labels


def test_ultra_processed_day_scores_low():
    day = [
        _e("McDonald's fries", 500, protein=6, fiber=4, sodium=400),
        _e("Coca Cola soda", 300, sugar=75),
        _e("Snickers candy bar", 500, protein=8, sugar=54, sodium=250),
        _e("Doritos chips", 450, protein=6, sodium=700),
    ]
    s = compute_health_score(day)
    assert s is not None
    assert s["score"] <= 40 and s["band"] == "poor"
    assert s["processed_pct"] >= 90
    labels = [d["label"] for d in s["drivers"]]
    assert "Ultra-processed load" in labels


def test_mixed_day_lands_between():
    day = [
        _e("Chicken bowl", 700, protein=50, fiber=6, sodium=800,
           micros={"iron": 3, "zinc": 2}),
        _e("Barebells protein bar", 200, protein=20, sugar=2, sodium=120),
        _e("Pizza slice", 400, protein=15, sugar=6, sodium=900),
    ]
    s = compute_health_score(day)
    assert s is not None
    assert 40 <= s["score"] <= 79


def test_processing_classifier():
    assert _processing_class("Grilled chicken breast") == 0
    assert _processing_class("Barebells protein bar") == 1
    assert _processing_class("Doritos chips") == 2
    # No keyword hit = UNKNOWN (-1), never "processed" — the old default
    # scored non-English whole-food days as processed_pct=100.
    assert _processing_class("Mystery casserole") == -1
    # RU vocabulary is first-class now (Cyrillic tokenizer + keywords)
    assert _processing_class("Куриное филе запечённое") == 0
    assert _processing_class("Помидоры черри") == 0
    assert _processing_class("Чипсы Lays") == 2
    assert _processing_class("Хлеб бородинский") == 1


def test_score_is_portion_normalized():
    # The same food profile at 2x portions scores identically — per-1000-kcal
    # normalization means quality, not quantity, drives the number.
    small = [_e("Chicken and rice", 600, protein=45, fiber=5, sodium=500)]
    large = [_e("Chicken and rice", 1200, protein=90, fiber=10, sodium=1000)]
    assert compute_health_score(small)["score"] == compute_health_score(large)["score"]


def test_unclassified_day_is_not_100_processed():
    """The Denys shape generalized: names with NO keyword hit (any language)
    must read unknown — the old default headlined them processed_pct=100."""
    day = [
        _e("Xlorbo special", 160, protein=12),
        _e("Mystery casserole", 165, protein=31),
        _e("Zzyzx plate", 200),
    ]
    s = compute_health_score(day)
    assert s["processed_pct"] == 0          # nothing CLASSIFIED as processed
    assert s["coverage"]["classified"] == 0  # honesty: we classified none of it


def test_russian_whole_food_day_reads_whole():
    """Denys 2026-07-02 exactly — now classifies as the whole-food day it was."""
    day = [
        _e("Омлет из 2 яиц", 160, protein=12),
        _e("Куриное филе запечённое", 165, protein=31),
        _e("Помидоры", 9),
    ]
    s = compute_health_score(day)
    assert s["processed_pct"] == 0
    assert s["whole_pct"] == 100
    assert s["coverage"]["classified"] == 100


def test_ultra_pct_splits_staples_from_ultra():
    day = [
        _e("Turkey sandwich", 500, protein=30, processing_level="processed"),
        _e("Doritos chips", 250, processing_level="ultra_processed"),
        _e("Apple", 250, processing_level="whole"),
    ]
    s = compute_health_score(day)
    assert s["processed_pct"] == 75          # staples + ultra
    assert s["ultra_pct"] == 25              # the alarming fact, alone
    assert s["whole_pct"] == 25
    assert s["coverage"]["classified"] == 100
