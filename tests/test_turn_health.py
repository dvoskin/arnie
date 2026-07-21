"""Turn-health detectors — the deterministic signals that flag a bad turn."""
from core.turn_health import (
    looks_like_stall, looks_like_dead_end, detect_frustration, detect_turn_flags,
    looks_like_phantom_log_claim, claimed_day_total, extract_stated_day_calories,
    looks_like_unlogged_food_report,
)


# ── OMISSION: reported food, quantified in the reply, never logged (starburst) ──

def test_omission_reported_food_commented_not_logged():
    # The screenshot: "I had 2 pieces of starburst" → reply states 40 cal but the
    # caller confirms no tool fired. Must be flagged so the rescue logs it.
    assert looks_like_unlogged_food_report(
        "I had 2 pieces of starburst",
        "2 Starburst, about 40 cal, no real protein, tiny hit that doesn't change "
        "anything.|||Turkey's still the move. Ping me when it's on the plate.") is True


def test_omission_catches_bare_food_name_no_verb():
    # Danny's Barebells voice-note (2026-07-21): no consumption verb, just the food
    # name; reply quantified it ("200 cal for 20g protein") but never logged.
    assert looks_like_unlogged_food_report(
        "Barebells caramel cashew",
        "Barebells caramel cashew, 200 cal for 20g protein. you're at 182g now, "
        "1,569 on the day.") is True
    # bare food + quantity, still no verb
    assert looks_like_unlogged_food_report(
        "2 eggs and toast", "eggs and toast, about 240 cal, 16g protein.") is True


def test_omission_excludes_lookups_acks_and_recaps():
    # A lookup/advice question is not a food to log.
    assert looks_like_unlogged_food_report(
        "how many calories in a banana", "about 105 cal, mostly carbs.") is False
    assert looks_like_unlogged_food_report(
        "what should I eat for dinner", "aim for a 600 cal chicken plate.") is False
    # A bare acknowledgment triggers a day-total RECAP, not a food log.
    assert looks_like_unlogged_food_report(
        "ok", "you're at 1,500 cal, 120g protein today.") is False
    assert looks_like_unlogged_food_report(
        "nice", "200 cal already in, you're at 1,500.") is False


def test_omission_excludes_plans_questions_and_non_food():
    # A plan the model correctly defers on (and asks about) — not an omission.
    assert looks_like_unlogged_food_report(
        "I'm not sure yet probably ground turkey I made yesterday",
        "Good call. Want me to log the turkey now or wait til it's on the plate?") is False
    # A clarify question — legit deferral, not a miss.
    assert looks_like_unlogged_food_report(
        "I had a chicken wrap", "nice — what size, regular or large?") is False
    # "had" with no food and no macros stated — must NOT trigger a spurious log.
    assert looks_like_unlogged_food_report(
        "I had a rough day", "rough ones happen. hang in there.") is False
    # A future plan.
    assert looks_like_unlogged_food_report(
        "gonna grab a snack later", "solid, tell me when it's real.") is False


# ── Russian phantom detection (Anya, 2026-07-21) ────────────────────────────────
# A third of the beta logs in Russian. "3 coffee 3 cokes today" fired NO tool but
# the reply stated "690 / 1,570 калорий" — an EN-only calorie unit meant the
# total-claim rescue never saw the number, so nothing logged and she had to
# re-send. The unit regexes must recognize калорий/ккал.

def test_russian_calorie_total_is_extracted():
    resp = "Кофе и кола до 3 каждого, теперь на сегодня.\n\n**690 / 1,570 калорий**, 9г белка."
    assert claimed_day_total(resp) == 690
    assert extract_stated_day_calories(resp) == 690


def test_russian_worded_claim_is_a_phantom():
    # "Кофе и кола внесены" (logged) with zero tools over a food report.
    assert looks_like_phantom_log_claim("coffee\ncoke", "Кофе и кола внесены ☕",
                                        has_tool_calls=False) is True


def test_english_totals_still_parse_and_bare_item_does_not():
    assert claimed_day_total("984 / 2,165 calories") == 984
    assert extract_stated_day_calories("Total: 1,340 cal") == 1340
    assert extract_stated_day_calories("200 calories") is None  # single item, not a day total


# ── phantom log-claim detection (dropped-set bug) ───────────────────────────────

def test_phantom_log_claim_catches_noted_without_tool():
    # The rear-delt case: user reported a set, model said "noted", fired no tool.
    assert looks_like_phantom_log_claim(
        "11 on left side 13 rig HT",
        "Unilateral, noted. Right side stronger 13 vs 11.|||One more set?",
        has_tool_calls=False,
    )
    assert looks_like_phantom_log_claim(
        "190x14 first set", "Got it, on the board.", has_tool_calls=False)
    assert looks_like_phantom_log_claim(
        "3x12 @ 70", "Logged. Nice work.", has_tool_calls=False)


def test_phantom_log_claim_no_false_positives():
    # A tool actually fired → not a phantom.
    assert not looks_like_phantom_log_claim("190x14", "Logged.", has_tool_calls=True)
    # A clarifying question (no recorded-claim) → correct behavior, not a phantom.
    assert not looks_like_phantom_log_claim(
        "30x10 and 20x10", "Was the 30 a different variation, or stepping up?",
        has_tool_calls=False)
    # Not a set report → "noted" is fine.
    assert not looks_like_phantom_log_claim(
        "what should I eat", "Noted - go for the turkey bowl.", has_tool_calls=False)
    # Contract change (bbda2dc, parallel session): detection now covers FOOD
    # reports too — "I had 200" + a bare "Noted." with no tool call IS the
    # phantom-miss the detector exists to catch. The old assertion predated
    # that enhancement.
    assert looks_like_phantom_log_claim("I had 200", "Noted.", has_tool_calls=False)


def test_phantom_log_claim_in_detect_turn_flags():
    flags = detect_turn_flags(
        user_text="11 on left side 13 rig HT",
        response_text="Unilateral, noted.|||One more?",
        has_tool_calls=False, stop_reason="end_turn", retried=False, tool_error=False,
    )
    assert "phantom_log_claim" in flags
    flags2 = detect_turn_flags(
        user_text="11 on left side 13 rig HT", response_text="Logged that set.",
        has_tool_calls=True, stop_reason="end_turn", retried=False, tool_error=False,
    )
    assert "phantom_log_claim" not in flags2


# ── dead-end detection ──────────────────────────────────────────────────────────

def test_dead_end_catches_bare_acknowledgments():
    for txt in ("done", "Done.", "done ✅", "got it", "Got it 👍", "logged",
                "noted", "all set", "ok", "Updated.", "perfect", "nice 🔥"):
        assert looks_like_dead_end(txt), f"should flag dead-end: {txt!r}"


def test_dead_end_allows_substance():
    for txt in (
        "done, you're at 450 for the day.",
        "logged it 👊|||that's 1,840/2,100.",
        "got it, what's the dinner plan?",
        "nice, that's a strong protein hit.",
        "",
    ):
        assert not looks_like_dead_end(txt), f"false positive on: {txt!r}"


# ── stall detection ────────────────────────────────────────────────────────────

def test_stall_catches_colon_and_period_narration():
    for txt in (
        "Now logging everything:",
        "estimating both:",
        "Let me do that now.",
        "On it — clearing today and relogging everything to yesterday.",
        "I need to delete all of today's entries and relog them to yesterday.",
        "Let me handle this — deleting all of today's entries first, then relogging.",
    ):
        assert looks_like_stall(txt), f"should flag stall: {txt!r}"


def test_stall_does_not_flag_legit_conversation():
    for txt in (
        "solid day. let me know what you have for dinner and we'll close it out.",
        "nice work, that's a strong protein hit.",
        "you're at 1,840/2,100. what's the dinner plan?",
        "",
    ):
        assert not looks_like_stall(txt), f"false positive on: {txt!r}"


# ── frustration detection ───────────────────────────────────────────────────────

def test_frustration_detects_user_pushback():
    for txt in (
        "wtf are you talking about",
        "you missed half the items",
        "I already told you that",
        "that's not what I said",
        "are you dumb",
        "still wrong",
    ):
        assert detect_frustration(txt), f"should detect frustration: {txt!r}"


def test_frustration_no_false_positive_on_normal_text():
    for txt in ("had a chicken wrap and a shake", "log my breakfast", "thanks man"):
        assert not detect_frustration(txt), f"false positive: {txt!r}"


# ── combined flag computation ────────────────────────────────────────────────────

def test_clean_turn_has_no_flags():
    flags = detect_turn_flags(
        user_text="had a chicken wrap", response_text="logged it, you're at 450.",
        has_tool_calls=True, stop_reason="end_turn", retried=False, tool_error=False,
    )
    assert flags == []


def test_flags_accumulate_for_a_bad_turn():
    flags = detect_turn_flags(
        user_text="wtf you missed everything",
        response_text="Let me do that now.",
        has_tool_calls=False, stop_reason="max_tokens", retried=True, tool_error=True,
    )
    assert set(flags) == {"truncated", "retried", "tool_error", "stall_shipped", "user_frustrated"}


def test_stall_only_flags_when_no_tool_calls():
    # Same stall-ish text, but a tool DID run → not a stall.
    flags = detect_turn_flags(
        user_text="move it to yesterday", response_text="On it — moving everything.",
        has_tool_calls=True, stop_reason="end_turn", retried=False, tool_error=False,
    )
    assert "stall_shipped" not in flags


def test_phantom_log_claim_catches_russian():
    """Anya 2026-07-19 13:47 verbatim: 'coffee\\ncoke' → 'Кофе и кола внесены ☕'
    with zero tools — the EN-only claim list let it through."""
    assert looks_like_phantom_log_claim(
        "coffee\ncoke",
        "Кофе и кола внесены ☕\n\nПока пусто по еде, **0/1570 калорий**, 0г белка.",
        has_tool_calls=False)
    # RU 'logged' claim over a matched food report — still caught
    assert looks_like_phantom_log_claim(
        "coffee", "Записала, кофе в дневнике.", has_tool_calls=False)
    # a genuine RU clarifying reply must NOT fire
    assert not looks_like_phantom_log_claim(
        "coffee", "Какой кофе — с молоком или чёрный?", has_tool_calls=False)
