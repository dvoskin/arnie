"""Generative gate matrix — 2,500 seeded random compositions asserting the
routing invariants of the deterministic layer (Danny 2026-07-24: '18 cases is
too small — we need thousands'). Pure functions, runs in milliseconds, in CI
on every push. The LIVE model battery (scripts/sim_food_random.py) samples the
same space against the real logger.
"""
import random
import core.food_turn as FT

CONSUMED = ["had", "ate", "just had", "grabbed", "got", "bought", "ordered",
            "picked up", "finished", "drank"]
FOODS = ["grilled chicken breast", "white rice", "a barebells bar",
         "caesar salad", "french press coffee", "clear broth soup",
         "chicken curry", "2 sets of ribs", "greek yogurt", "beef stew",
         "protein shake", "an apple", "quest chips", "oatmeal"]
PORTIONS = ["", "6 oz ", "100g ", "2 ", "a bowl of ", "some ", "half a ",
            "3.5 servings of "]
PAST_TAILS = ["", " this morning", " after work", " later than usual",
              " while walking home", " at my desk"]
PLAN_TAILS = [" for tonight", " for the fridge", " to eat later",
              " for tomorrow", " for the week"]
PLAN_LEADS = ["gonna get", "going to have", "might grab", "thinking about",
              "planning to eat", "will have"]
DESTRUCTIVE = ["remove the", "delete the", "undo the", "clear my log of",
               "scratch the"]
WORKOUT = ["did 3 sets of bench at 185", "bench press 3x10",
           "ran 5k on the treadmill", "walked 30 min", "20 minutes of cardio",
           "squats 5x5", "deadlift 225 for 3"]
ACKS = ["ok", "thanks", "leave it like this", "keep it as is", "that's fine",
        "yep", "lol", "don't change it"]


def test_generative_routing_2500():
    rng = random.Random(4242)
    checked = 0
    for _ in range(2500):
        shape = rng.random()
        if shape < 0.40:      # consumption report → IN
            msg = (f"{rng.choice(CONSUMED)} {rng.choice(PORTIONS)}"
                   f"{rng.choice(FOODS)}{rng.choice(PAST_TAILS)}")
            assert FT.applies(msg), f"report excluded: {msg!r}"
        elif shape < 0.55:    # plan → OUT
            if rng.random() < 0.5:
                msg = f"{rng.choice(PLAN_LEADS)} {rng.choice(FOODS)}"
            else:
                msg = (f"{rng.choice(['got', 'bought', 'picked up'])} "
                       f"{rng.choice(FOODS)}{rng.choice(PLAN_TAILS)}")
            assert not FT.applies(msg), f"plan leaked in: {msg!r}"
        elif shape < 0.70:    # destructive → OUT (legacy owns deletes)
            msg = f"{rng.choice(DESTRUCTIVE)} {rng.choice(FOODS)}"
            assert not FT.applies(msg), f"destructive leaked in: {msg!r}"
            assert not FT.thread_routes(msg), f"destructive thread-routed: {msg!r}"
        elif shape < 0.85:    # workout → OUT
            msg = rng.choice(WORKOUT)
            assert not FT.applies(msg), f"workout leaked in: {msg!r}"
        else:                 # acks/keep-as-is → OUT everywhere
            msg = rng.choice(ACKS)
            assert not FT.applies(msg), f"ack leaked in: {msg!r}"
            assert not FT.thread_routes(msg), f"ack thread-routed: {msg!r}"
        checked += 1
    # Verbless portion-shape reports (no consumed verb at all) route IN —
    # the quantity+unit shape IS the food signal.
    for _ in range(400):
        msg = (f"{rng.choice(['2', '6', '100', 'half a', 'a few'])} "
               f"{rng.choice(['oz', 'g', 'slices', 'bars', 'cups', 'bowls'])} "
               f"{rng.choice(FOODS)}")
        assert FT.applies(msg), f"verbless report excluded: {msg!r}"
        checked += 1
    # Negated intent (declining/canceling) is coach conversation — never a
    # report, in cold OR thread state (the chicken-bowl/carrots incident).
    NEG = ["I don't think I'll have the", "won't be having the",
           "not going to eat the", "decided against the", "skipping the",
           "changed my mind on the", "passing on the"]
    for _ in range(300):
        msg = f"{rng.choice(NEG)} {rng.choice(FOODS)} later"
        assert not FT.applies(msg), f"negation leaked in: {msg!r}"
        assert not FT.thread_routes(msg), f"negation thread-routed: {msg!r}"
        checked += 1
    assert checked == 3200


def test_generative_say_contract_800():
    rng = random.Random(99)
    for _ in range(800):
        qty = f"{rng.choice([1, 2, 3, 6, 100])} {rng.choice(['oz', 'g', 'cup', 'bar'])}"
        name = rng.choice(["Fage 0% yogurt", "5-hour Energy", "Chicken breast",
                           "Rice", "Barebells bar"])
        calls = [{"input": {"food_name": name, "quantity": qty, "calories": 200}}]
        clean = f"{name} logged, {{batch_cal}} cal. You're at {{day_cal}} with {{cal_left}} left."
        assert FT.enforce_say_contract(clean, calls) == clean, (name, qty)
        dirty = f"{name} logged, 347 cal and 22g protein."
        out = FT.enforce_say_contract(dirty, calls)
        assert "347" not in out and "22g" not in out.replace("{batch", "")
        q = f"{name} logged, {{batch_cal}} cal. Was that whole milk for real?"
        assert "?" not in FT.enforce_say_contract(q, calls)
