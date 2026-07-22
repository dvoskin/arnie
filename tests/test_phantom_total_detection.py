"""Repro + regression for the phantom running-total that shipped unchecked.

Field bug (Danny, 2026-07-22, 5 screenshots): the model narrated a log AND a
running day total ("You're at 1,695 cal", "You're at 1,785 cal and 90g protein")
with NO DB write behind it — the user had to say "it's not on my log" / "Not
logged" to force the real log. The total-claim phantom guard in
core/conversation.py recomputes the claimed total vs today_log.total_calories and
rescues when the claim exceeds the DB beyond tolerance — but it only fired for the
"N / M calories" SLASH phrasing (the medjool-dates incident). The everyday voice
phrasing "you're at N cal" slipped past claimed_day_total() → None → no guard.

These pin the detector so the guard can see the real phrasing. The guard ACTS
only when the claim EXCEEDS the DB (an over-claim = a phantom add), so catching
more phrasings can only catch more real phantoms — a legit recap where the claim
equals the DB total never trips it.
"""
from core.turn_health import claimed_day_total, _FOOD_REPORT_RE, DAY_TOTAL_TOLERANCE


# ── the exact phantom replies from the screenshots ───────────────────────────

def test_youre_at_phrasing_is_detected():
    r = ("Got it, second round of buttered toast, 180 cal. You're at 1,695 cal "
         "and 69g protein now, 470 left to play with.")
    assert claimed_day_total(r) == 1695


def test_youre_at_second_instance_detected():
    r = "You're at 1,785 cal and 90g protein, 380 left to play with."
    assert claimed_day_total(r) == 1785


def test_sitting_at_phrasing_detected():
    r = "You're sitting at 1,705 cal, 87g protein, with 460 cal left and 93g still to close."
    assert claimed_day_total(r) == 1705


def test_puts_you_at_phrasing_detected():
    assert claimed_day_total("that puts you at 2,219 cal for the day") == 2219


def test_slash_phrasing_still_detected():
    # The original medjool-dates format must keep working.
    assert claimed_day_total("That puts you at 2,219 / 2,165 calories.") == 2219


# ── precision: per-item calories and 'remaining' must NOT read as the total ──

def test_per_item_calories_not_mistaken_for_total():
    # "180 cal" is the item; the only DAY TOTAL here is the 1,695 after "you're at".
    r = "Toast logged, 180 cal and 5g protein. You're at 1,695 cal now."
    assert claimed_day_total(r) == 1695


def test_no_total_claim_returns_none():
    # A pure per-item confirmation with no running-total idiom → nothing to check.
    assert claimed_day_total("Toast logged, 180 cal and 5g protein.") is None
    assert claimed_day_total("Nice, that's a solid protein hit 💪") is None


def test_remaining_left_alone_is_not_a_total():
    # "470 left" is the remaining budget, not the day total — must not be picked
    # up as a claimed total on its own.
    assert claimed_day_total("470 left to play with today.") is None


def test_protein_grams_ratio_not_a_calorie_total():
    # "Protein's at 0 / 180g" is a protein-gram ratio, not calories → ignored.
    assert claimed_day_total("Protein's at 0 / 180g, go protein-first next.") is None


def test_logged_at_item_calories_not_a_total():
    # "logged at 180 cal" is a per-item figure — no running-total idiom → ignored.
    assert claimed_day_total("Toast logged at 180 cal, cheap calories.") is None


# ── the guard arithmetic the detector feeds ──────────────────────────────────

def test_guard_would_fire_on_screenshot_case():
    """End-to-end at the guard's logic: phantom reply + a food-report user msg +
    a DB total below the claim → the guard's condition is satisfied."""
    reply = ("Got it, second round of buttered toast, 180 cal. You're at 1,695 "
             "cal and 69g protein now, 470 left to play with.")
    user_msg = "Just had some more son"
    claim = claimed_day_total(reply)
    db_total = 1515                       # toast never written → DB is behind
    assert claim is not None
    assert _FOOD_REPORT_RE.search(user_msg)                     # user reported food
    assert claim > db_total + DAY_TOTAL_TOLERANCE               # → phantom → rescue


def test_guard_does_not_fire_when_claim_matches_db():
    """A legit recap: the claimed total equals what's actually on the board →
    the over-claim condition is false → no false phantom."""
    reply = "You're at 1,695 cal for the day, 470 left."
    claim = claimed_day_total(reply)
    db_total = 1695
    assert claim == 1695
    assert not (claim > db_total + DAY_TOTAL_TOLERANCE)
