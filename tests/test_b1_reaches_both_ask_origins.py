"""B-1 must see BOTH ask origins, not just the one it was wired to.

MEASURED IN PRODUCTION, 2026-08-05. `"I had some chicken breast"` — B-1's own
canonical example — was sent on Telegram by an allowlisted user and produced
ZERO B-1 events. Not a decline: nothing. The predicate was never consulted.

`food_turn` has two ask origins and they are not variants of one thing:

    the MODEL proposed the ask     -> returns at the interpreter branch
    the SYSTEM overrode a log      -> returns at the pipeline branch

The pipeline branch is gated on `any(k == "log")`, so a turn where the model
itself noticed the uncertainty never reached staging at all — no
`StagedFoodItem`, no ambiguities, nothing the canonical layer reads. B-1 was
wired to the minority producer, and my own notes record the interpreter branch
as where MOST asks come from.

What this file pins:

  * both origins produce the SAME evidence, via one `derive_semantics`;
  * a branded item on a turn that never fetched the shelf is DECLINED rather
    than claimed — "we did not look" may not read as "we know";
  * the interpreter branch keeps working unchanged when B-1 declines.
"""
import pytest

from core.food_pipeline import derive_semantics, identity_evidence_fetched
from skills.nutrition import quantity_clarification as qc


def _data(food="chicken breast", *, branded=False, amount=None, unit=None,
          points=("how much chicken breast?",)):
    item = {"food": food, "calories": 280, "protein": 43, "carbs": 0,
            "fats": 10}
    if branded:
        item["branded"] = True
        item["brand"] = "Fairlife"
    if amount is not None:
        item["amount"], item["unit"] = amount, unit
    return {"items": [item], "points": list(points), "action": "ask"}


def _staged(data, message="I had some chicken breast", mode="moderate",
            variant_spreads=None):
    from core.food_pipeline import stage_items

    items, _ = stage_items(data, turn_id="t_1", message=message, mode=mode)
    return derive_semantics(items, data, message=message, mode=mode,
                            variant_spreads=variant_spreads)


class _Decision:
    def __init__(self, items):
        self.staged_items = tuple(items)


# ── one evidence pass, two origins ───────────────────────────────────────────

def test_the_interpreter_branch_now_produces_staged_evidence():
    """The gap that made B-1 invisible: this branch had no staged items at
    all, so the predicate could not even decline."""
    items = _staged(_data())
    assert items, "the interpreter's items must reach staging"
    assert items[0].identity.canonical_name
    assert hasattr(items[0], "material_ambiguities")


def test_both_origins_run_the_same_derivation():
    """ONE function, so the two cannot grow two definitions of 'what is
    unresolved here' — that drift is why there are four producers to
    collapse."""
    import inspect

    from core import food_pipeline

    src = inspect.getsource(food_pipeline.plan_turn)
    assert "derive_semantics(" in src, \
        "plan_turn must use the shared pass, or the extraction was cosmetic"

    from core import food_turn
    assert "derive_semantics" in inspect.getsource(food_turn._b1_material)


# ── fail closed on evidence nobody fetched ───────────────────────────────────

def test_a_branded_item_without_a_shelf_lookup_is_declined():
    """`derive_variant_ambiguity` can only find a variant question when the
    caller fetched the shelf. Absent that, a branded item comes back looking
    unambiguous — indistinguishable from being so. Claiming it would ask "how
    much?" about a food we cannot yet name."""
    data = _data("Core Power", branded=True)
    verdict = qc.is_eligible(_Decision(_staged(data)), message="I had a Core Power",
                             client_capable=True, identity_evidence=False)
    assert verdict.reason is qc.Ineligible.IDENTITY_UNVERIFIED


def test_an_unbranded_item_needs_no_shelf_lookup():
    """`_variant_spreads` only ever fetches branded and packaged names, so
    "chicken breast" is fully judged without one. Declining it would make B-1
    unreachable rather than safe."""
    assert identity_evidence_fetched(_data(), None) is True
    assert identity_evidence_fetched(_data("Core Power", branded=True),
                                     None) is False
    assert identity_evidence_fetched(_data("Core Power", branded=True),
                                     {"core power": {}}) is True


def test_missing_evidence_defaults_to_the_pessimistic_reading():
    """A caller that does not say must not be read as a caller that looked."""
    from core import b1_quantity_operation as b1
    import inspect

    src = inspect.getsource(b1.try_take_ownership)
    assert 'material.get("identity_evidence", False)' in src, \
        "absent evidence must default False, not True"


# ── the decline path stays harmless ──────────────────────────────────────────

def test_deriving_material_never_raises_into_the_ask(monkeypatch):
    """B-1 declining costs nothing — the turn is exactly the turn it is today
    — so this may never cost the question."""
    from core import food_turn

    def _boom(*a, **kw):
        raise RuntimeError("staging exploded")

    monkeypatch.setattr("core.food_pipeline.stage_items", _boom)
    assert food_turn._b1_material(_data(), message="x", mode="moderate") is None


def test_material_is_absent_when_the_pipeline_is_off(monkeypatch):
    from core import food_turn

    monkeypatch.setenv("FOOD_PIPELINE", "false")
    assert food_turn._b1_material(_data(), message="x", mode="moderate") is None


# ── the fixtures must match what production emits ────────────────────────────

def test_the_predicate_is_keyed_on_what_the_pipeline_actually_emits():
    """THE ERROR THIS FILE EXISTS TO PREVENT REPEATING.

    The first predicate keyed on `field_name == "estimated_mass_g"` and
    rejected every real turn — that name is not an ambiguity field at all, it
    is a `FoodAssumption` field answering a different question. The portion
    question the pipeline emits carries CONSUMED_QUANTITY /
    "consumed_fraction".

    152 tests passed against that predicate because the FIXTURES constructed
    the ambiguity I had assumed existed. The assertion was fine; the fixture
    was fictional. So this test builds its evidence from the real derivation
    and asserts the shape, which is the only version that could have failed.
    """
    from skills.nutrition.ambiguity import AmbiguityType

    items = _staged(_data())
    ambiguities = items[0].ambiguities
    assert ambiguities, "a vague portion must produce an ambiguity"

    kinds = {a.ambiguity_type for a in ambiguities}
    assert AmbiguityType.CONSUMED_QUANTITY in kinds, (
        f"the portion question's TYPE moved: {kinds}. The predicate keys on "
        f"this enum; if it changes, B-1 silently stops claiming turns."
    )
    assert "estimated_mass_g" not in {a.field_name for a in ambiguities}, (
        "if this ever becomes an ambiguity field name, the two shapes have "
        "converged and the comment explaining the original error is stale"
    )


def test_the_canonical_example_is_eligible_end_to_end():
    """`"I had some chicken breast"` — B-1's own example, through the real
    interpreter shape, staged and derived exactly as production does it.

    Sent on Telegram 2026-08-05 by an allowlisted user and produced zero B-1
    events. This is the assertion that would have caught it before the deploy.
    """
    verdict = qc.is_eligible(_Decision(_staged(_data())),
                             message="I had some chicken breast",
                             client_capable=True, identity_evidence=True)
    assert verdict.ok, f"B-1 is unreachable again: {verdict.reason.value}"
    assert verdict.item.identity.canonical_name == "chicken breast"


@pytest.mark.parametrize("message,item,expected", [
    ("I had 6 oz of chicken breast",
     {"food": "chicken breast", "calories": 280, "amount": 6, "unit": "oz"},
     qc.Ineligible.QUANTITY_ALREADY_STATED),
    ("actually make that 8oz", {"food": "chicken breast", "calories": 280},
     qc.Ineligible.CORRECTION_TURN),
])
def test_out_of_scope_shapes_still_decline_against_real_derivation(
        message, item, expected):
    data = {"items": [item], "points": ["?"], "action": "ask"}
    verdict = qc.is_eligible(_Decision(_staged(data, message=message)),
                             message=message, client_capable=True,
                             identity_evidence=True)
    assert verdict.reason is expected


# ── capability takes the CHANNEL, never the modality ─────────────────────────

def test_a_modality_is_refused_loudly_not_silently():
    """MEASURED IN PRODUCTION 2026-08-05, the first real B-1 event ever
    recorded: `b1_declined reason=client_incapable` on Telegram — the one
    channel B-1 exists to prove.

    `_source = source_type or platform`, and `source_type` carries
    text/voice/photo alongside real origins. So a Telegram TEXT message
    arrived as "text", matched no channel, and declined. The symptom is
    indistinguishable from a correct exclusion, which is why it now logs an
    error rather than returning a quiet False.

    Same modality-vs-channel conflation `feedback_arnie_platform_mislabel`
    already records.
    """
    from core import b1_quantity_operation as b1

    for modality in ("text", "voice", "photo", "image"):
        assert b1.client_renders_interactions(modality) is False
        assert modality in b1._MODALITIES, \
            f"{modality} must be named, or its misuse is silent again"

    assert b1.client_renders_interactions("telegram") is True
    assert b1.client_renders_interactions("imessage") is True
    # iOS IS CAPABLE SINCE `arnie-ios@48cb626`. It is asserted here because
    # this gate's whole point is that "text" and "ios" must not be confused —
    # and now that iOS is capable, passing the MODALITY where the CHANNEL
    # belongs is the more expensive mistake, not the cheaper one: it declines
    # a client that can answer.
    assert b1.client_renders_interactions("ios") is True


def test_the_call_site_passes_the_platform():
    """Checked at the call site, because that is where the two were confused.
    A test of the helper alone would have passed throughout the outage.

    THE INVARIANT IS UNCHANGED; THE MECHANISM MOVED. The call site used to
    compute capability itself (`client_renders_interactions(platform)`) and
    pass a bool. Lane ownership now has one owner, so it passes the CHANNEL
    and `canonical_food_enabled` decides. What must still be true — and what
    cost this slice a production round when it was not — is that the value
    handed over is `platform` and never `_source`, which is
    `source_type or platform` and can therefore be a MODALITY.
    """
    import inspect

    from core import conversation

    src = inspect.getsource(conversation)
    idx = src.find("channel=")
    assert idx > 0, "the call site stopped passing a channel"
    call = src[idx:idx + 60]
    assert "platform" in call, f"the lane must read the channel: {call!r}"
    assert "_source" not in call, \
        "`_source` is `source_type or platform` — it can be a modality"
