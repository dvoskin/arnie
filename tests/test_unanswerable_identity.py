"""A question whose own text contains the answer is not a question.

Live turn, 2026-07-26. The user logged a Royo Everything Bagel and was asked:

    "Which Royo Everything Bagel was it?"

The user's reaction — "that doesn't make any sense at all" — is the correct
one. The prompt is built by `clarify_policy._label`, which reads
`identity.describe()`. So the sentence is assembled out of the very name it
claims not to know, and it offers nothing to choose between: the interpreter
reported identity doubt with no candidate values attached.

The doubt itself was not imaginary — Royo does make more than one Everything
Bagel. But it is not the USER's doubt to settle. They said the most specific
thing they have. Resolving which SKU that maps to is the branded lookup's job.

The rule these tests pin: an identity ambiguity is only askable when there is
an actual choice on offer (two or more candidates) OR the label is no more
specific than the brand. "A Fairlife" is the second case and stays askable —
one brand, four products with materially different nutrition, and only the
user knows which. "Royo Everything Bagel" is neither, and goes forward.
"""
import core.food_pipeline as FP
from skills.nutrition.clarify_policy import decide

TURN = "imessage:G-royo"


def _data(items=None, ambiguities=None):
    return {"action": "log", "items": items or [], "say": "",
            "ambiguities": ambiguities or [], "_calls": []}


def _item(food, amount=None, unit=None, brand=None, **kw):
    return {"food": food, "amount": amount, "unit": unit, "brand": brand, **kw}


def _plan(food, *, brand=None, amount=1, unit=None, options=None,
          mode="strict", impact_cal=140):
    """Stage one item carrying an interpreter-reported IDENTITY ambiguity."""
    amb = {"item": food, "field": "identity", "impact_cal": impact_cal}
    if options:
        amb["options"] = list(options)
    data = _data([_item(food, amount, unit, brand=brand, is_packaged=True)],
                 [amb])
    items, _ = FP.stage_items(data, turn_id=TURN, message=food, mode=mode)
    items = FP.attach_ambiguities(items, data, mode=mode)
    return decide(list(items), mode=mode)


def _prompts(decision):
    return [q.prompt for q in decision.questions]


# ── the reported transcript ───────────────────────────────────────────────────
def test_it_does_not_ask_which_royo_everything_bagel_it_was():
    decision = _plan("Royo Everything Bagel", brand="Royo")
    assert not any("Everything Bagel" in p for p in _prompts(decision)), \
        _prompts(decision)


def test_the_bagel_is_not_held_hostage_to_that_question():
    """Dropping the question has to release the item, not silently strand it.

    A held item with no question is worse than the nonsense question: the user
    sees nothing logged and has nothing to answer.
    """
    decision = _plan("Royo Everything Bagel", brand="Royo")
    assert not decision.questions
    assert decision.ready_item_ids or not decision.held_item_ids


def test_the_second_reported_product_behaves_the_same():
    decision = _plan("Nissin Cup Noodles", brand="Nissin", unit="cup")
    assert not any(p.startswith("Which") for p in _prompts(decision)), \
        _prompts(decision)


# ── what must STILL be asked ──────────────────────────────────────────────────
def test_a_bare_brand_is_still_a_real_question():
    """"A Fairlife" names a maker, not a product. Four products, ~190 calories
    apart. The user is the only one who can settle it."""
    decision = _plan("Fairlife", brand="Fairlife", impact_cal=190)
    assert any("Fairlife" in p for p in _prompts(decision)), _prompts(decision)


def test_brand_plus_a_category_noun_is_still_a_real_question():
    """One word past the brand narrows nothing — "bar" is the packaging, not
    the product. Two words is a product name."""
    decision = _plan("Barebells bar", brand="Barebells", impact_cal=190)
    assert any("Barebells" in p for p in _prompts(decision)), _prompts(decision)


def test_a_named_product_is_still_askable_when_there_is_a_real_choice():
    """The label being specific is not on its own a reason to stay silent. If
    we can name two things it might be, there is something to pick."""
    decision = _plan("Royo Everything Bagel", brand="Royo",
                     options=["Original", "Protein"], impact_cal=190)
    assert decision.questions, "a two-candidate choice is answerable"
    assert len(decision.questions[0].options) >= 2


def test_a_quantity_question_on_a_named_product_is_untouched():
    """The rule is scoped to identity. How much of it you ate is still a
    question the user is the only one who can answer."""
    data = _data([_item("Royo Everything Bagel", 1, brand="Royo",
                        is_packaged=True)],
                 [{"item": "Royo Everything Bagel", "field": "consumed",
                   "impact_cal": 190}])
    items, _ = FP.stage_items(data, turn_id=TURN, message="a Royo bagel",
                              mode="strict")
    items = FP.attach_ambiguities(items, data, mode="strict")
    decision = decide(list(items), mode="strict")
    assert decision.questions, "consumed quantity is still asked"
