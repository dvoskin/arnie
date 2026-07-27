"""The clarification work is only worth what the gate in front of it admits.

Everything the staged pipeline does — ambiguity derivation, the mode-aware ask
ladder, the composer, partial commit — sits behind ONE branch in
`core/conversation.py`:

    elif not (_sft_prior or _photo_food
              or await food_relevance(text, last_assistant)
              or (_board and applies_destructive(text))
              or thread_relevance(...)):
        _to_legacy(decline_reason(text) or "not_food_shaped")

A message that fails it takes the legacy path, which has no clarification in
it at all. So `food_relevance` is not a performance knob; it decides whether
any of that code runs.

With `FOOD_GATE_MODEL` unset it is `applies()` — four English regexes whose
own docstring records 64% of real food logs missed over 1008 production
messages. Measured on this build with the flag off, 2 of these 10 messages
reached the lane. The work shipped and sat dark, because the switch in front
of it was never thrown in the deploy config.

These tests pin both halves: that the deploy config throws the switch, and
that turning it off is what makes the lane unreachable — so the next person
who reads a red test here learns which flag, not just that something broke.
"""
import pytest

#: Real shapes, all of them things a person types into a coaching app. None is
#: a corner case; the point is that they are utterly ordinary.
ORDINARY_FOOD_MESSAGES = [
    "Oh and a bag of quest chips",
    "a scoop of peanut butter",
    "two carnitas tacos",
    "cottage cheese",
    "chicken and rice",
    "The egg was poached",
    "Peanut M&Ms",
    "a bowl of oatmeal",
]


def _render_env():
    """Every env var the deploy config sets, as {key: value}."""
    import yaml

    with open("render.yaml") as fh:
        config = yaml.safe_load(fh)
    out = {}
    for service in config.get("services", []) or []:
        for entry in service.get("envVars") or []:
            if "key" in entry and "value" in entry:
                out[str(entry["key"])] = str(entry["value"])
    return out


def test_the_deploy_config_does_not_ship_the_regex_gate():
    """The regression itself. `FOOD_GATE_MODEL` and `FOOD_GATE_OPEN` both
    default to false in code, and render.yaml set NEITHER — so production ran
    the gate that its own docstring says misses two thirds of food logs, while
    `NUTRITION_RESOLVER_MODE=live` and `FOOD_COMPOSER=true` sat behind it
    doing nothing for the messages it turned away."""
    env = _render_env()
    gate = env.get("FOOD_GATE_MODEL", "").lower()
    open_gate = env.get("FOOD_GATE_OPEN", "").lower()
    assert gate in ("true", "1", "yes") or open_gate in ("true", "1", "yes"), (
        "render.yaml sets neither FOOD_GATE_MODEL nor FOOD_GATE_OPEN, so the "
        "food lane runs on the four English regexes and every message they "
        "miss skips staging, clarification and the composer entirely")


def test_the_two_gate_flags_are_not_both_on():
    """They are alternatives, not layers. `food_relevance` short-circuits on
    `if applies(t): return True` BEFORE consulting the model, so an open
    `applies()` means the model never runs — the combination pays for the
    model lane and gets the open gate's precision."""
    env = _render_env()
    both = (env.get("FOOD_GATE_MODEL", "").lower() in ("true", "1", "yes")
            and env.get("FOOD_GATE_OPEN", "").lower() in ("true", "1", "yes"))
    assert not both, (
        "FOOD_GATE_OPEN short-circuits before the model gate; setting both "
        "buys the model's cost and the open gate's precision")


@pytest.mark.parametrize("message", ORDINARY_FOOD_MESSAGES)
def test_the_regex_gate_alone_turns_ordinary_food_away(monkeypatch, message):
    """Why the flag matters, stated as behaviour rather than as a claim.

    This asserts the BROKEN state on purpose. If a future change teaches
    `applies()` to read these, this test fails — and that failure is good
    news, meaning the gate no longer needs a model behind it to see a bag of
    chips. Re-measure and delete the case; do not widen it."""
    from core.food_turn import applies

    monkeypatch.delenv("FOOD_GATE_OPEN", raising=False)
    assert not applies(message), (
        f"{message!r} now passes the regex gate on its own — re-measure the "
        f"gate's miss rate and prune this case")


@pytest.mark.parametrize("message", ORDINARY_FOOD_MESSAGES)
def test_the_open_gate_admits_them(monkeypatch, message):
    """And the other lever works: absence of an English template stops being
    read as evidence against food."""
    from core.food_turn import applies

    monkeypatch.setenv("FOOD_GATE_OPEN", "true")
    assert applies(message), f"{message!r} still turned away with the gate open"


@pytest.mark.parametrize("message", [
    "what should I eat today?",
    "going to the gym later",
    "thanks!",
])
def test_the_open_gate_still_declines_non_food(monkeypatch, message):
    """Open is not a rubber stamp. The checks that carry real signal — a
    question, an acknowledgement, a plan, another domain — still decline."""
    from core.food_turn import applies

    monkeypatch.setenv("FOOD_GATE_OPEN", "true")
    assert not applies(message), f"{message!r} admitted as food"


@pytest.mark.asyncio
async def test_the_model_gate_falls_back_to_the_regexes_on_failure():
    """Why the switch is safe to throw before the precision work lands: a
    model outage returns `applies(t)`, so the floor is exactly the behaviour
    without the flag. It can be neutral. It cannot be worse."""
    import core.food_turn as FT

    async def _boom(*a, **k):
        raise RuntimeError("simulated outage")

    original, FT.chat = getattr(FT, "chat", None), _boom
    try:
        FT._RELEVANCE_CACHE.clear()
        import os
        os.environ["FOOD_GATE_MODEL"] = "true"
        # A message the regexes DO read, and one they do not.
        assert await FT.food_relevance("I had a chicken sandwich for lunch")
        assert await FT.food_relevance("Peanut M&Ms") == FT.applies("Peanut M&Ms")
    finally:
        os.environ.pop("FOOD_GATE_MODEL", None)
        FT._RELEVANCE_CACHE.clear()
        if original is not None:
            FT.chat = original


def test_the_pipeline_behind_the_gate_is_mode_aware():
    """The far end, so a red test here separates 'the work is broken' from
    'the work never ran'. Same meal, three modes, three different answers."""
    from core.food_pipeline import plan_turn

    interpreted = {"items": [
        {"food": "Peanut M&Ms", "amount": 15, "unit": "pieces",
         "branded": True, "calories": 135},
        {"food": "Banana", "amount": 0.5, "unit": "banana", "calories": 53},
        {"food": "Peanut Butter", "amount": 1, "unit": "tbsp", "calories": 95},
    ]}
    message = ("I had like 15 peanut m&m, half a banana and a scoop of "
               "peanut butter")

    seen = {}
    for mode in ("quick", "moderate", "strict"):
        decision = plan_turn(interpreted, turn_id="t", message=message,
                             mode=mode)
        assert decision is not None, f"{mode}: pipeline bailed to legacy"
        seen[mode] = (decision.asks,
                      len(decision.clarification.ready_item_ids or ()),
                      len(decision.clarification.held_item_ids or ()))

    # quick commits the lot; moderate asks and still boards what it is sure
    # of; strict asks and holds everything.
    assert seen["quick"] == (False, 3, 0), seen
    assert seen["moderate"][0] is True and seen["moderate"][1] == 2, seen
    assert seen["strict"][0] is True and seen["strict"][2] == 3, seen
