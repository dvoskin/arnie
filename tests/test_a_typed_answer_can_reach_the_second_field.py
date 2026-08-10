"""B-1.5 WAS A ONE-FIELD SYSTEM WEARING A TWO-FIELD INTERACTION.

Measured in production 2026-08-10, user 26, five turns and nothing written:

    18:39:09  "4 oz"     -> "Got it for chicken. How was it cooked?"   held
    18:39:21  "Grilled"  -> "How much chicken?"                        repaired
    18:39:28  "4 oz"     -> "Got it for chicken. How was it cooked?"
    18:39:35  "Baked"    -> "How much chicken?"

    operation: rev=0 awaiting_answer   food_entries: 0   ledger_events: 0

THE ROOT CAUSE WAS ONE LINE:

    live_field = interaction.groups[0].fields[0]

The field an unaddressed answer applies to was the FIRST field, forever. With
quantity answered and preparation open, every further answer was still read
against QUANTITY: "Grilled" matched no quantity label, parsed as no mass, and
repaired — and the repair copy, itself hardcoded to quantity, then asked "How
much chicken?" about a field already answered.

WHY IT SURVIVED EVERY GREEN RUN. The only paths that ever settled a two-field
operation carried an EXPLICIT `field_id` — structured iOS taps — which never
consult `live_field` at all. Free text has no such addressing, so it is
exactly the modality that exposed it. The reversed-order proof reported as
passing on 2026-08-10 ran through the structured endpoint; through `/chat` it
could not have worked.

Three defects, one root:

    1  live_field pinned to fields[0]    preparation unanswerable by any route
    2  a typed PARTIAL returned no       no chips re-rendered after typing
       `b1_interaction`
    3  the repair copy hardcoded to      an unreadable preparation answer
       quantity                          asked about quantity
"""
from __future__ import annotations

import pytest

from core import b1_answer_turn as at
from core import b1_quantity_operation as ops
from core.clarification_answer import Outcome


class _Attr:
    def __init__(self, value): self.value = value


class _Field:
    def __init__(self, attribute, field_id, labels=()):
        self.attribute = _Attr(attribute)
        self.field_id = field_id
        self.event_id = "food_item_1"
        self.options = [type("O", (), {"option_id": f"opt_{i}",
                                       "label": lab})()
                        for i, lab in enumerate(labels)]


class _Group:
    def __init__(self, fields, label="chicken"):
        self.fields, self.label, self.event_id = fields, label, "food_item_1"


class _Interaction:
    revision = 0

    def __init__(self, fields):
        self.groups = [_Group(fields)]

    def field(self, field_id):
        for f in self.groups[0].fields:
            if f.field_id == field_id:
                return f
        raise KeyError(field_id)


QUANTITY = _Field("quantity", "op:item:quantity:0", ("2 oz", "4 oz", "8 oz"))
PREPARATION = _Field("preparation", "op:item:preparation:0",
                     ("Grilled", "Baked or roasted", "Fried", "Not sure"))


# ── DEFECT 1: the live field must advance ──────────────────────────────────

def test_the_live_field_is_the_first_still_open_one():
    """THE ROOT CAUSE, as a rule. With quantity answered, an unaddressed
    answer belongs to preparation — not to the field that was asked first."""
    interaction = _Interaction([QUANTITY, PREPARATION])

    nothing_answered = ops.open_fields(interaction, {})
    assert nothing_answered[0].attribute.value == "quantity"

    quantity_answered = ops.open_fields(
        interaction, {"op:item:quantity:0": {"patch_type": "set_quantity"}})
    assert len(quantity_answered) == 1
    assert quantity_answered[0].attribute.value == "preparation", (
        "with quantity held, the next answer must be read against "
        "preparation — reading it against quantity is the production defect")


def test_the_answer_turn_reads_the_open_field_not_the_first_field():
    """AST over the real module: the hardcoded index must not come back.

    A behavioural test alone would not catch a regression that reintroduces
    `fields[0]` behind an equivalent-looking expression, and this is a one-line
    defect that cost five production turns and wrote nothing.
    """
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(at._handle_owned))
    tree = ast.parse(src)

    # ⭐ THIS GATE WAS VACUOUS ON ITS FIRST WRITING, and the mutation caught
    # it: it asserted that `open_fields` was called SOMEWHERE in the function,
    # which was already true in the PARTIAL branch — so restoring the exact
    # production defect (`live_field = interaction.groups[0].fields[0]`) left
    # it green. A gate on a one-line root cause that cannot fail is worse than
    # no gate, because it reports the defect as fixed.
    #
    # The claim that matters is a DATA FLOW: whatever `open_fields` returns
    # must be what `live_field` is derived from.
    open_locals = {
        t.id
        for n in ast.walk(tree) if isinstance(n, ast.Assign)
        for t in n.targets if isinstance(t, ast.Name)
        if any(isinstance(c, ast.Call)
               and (getattr(c.func, "attr", "") or getattr(c.func, "id", ""))
               == "open_fields"
               for c in ast.walk(n.value))
    }
    assert open_locals, "nothing in the answer path calls open_fields"

    live = [n for n in ast.walk(tree) if isinstance(n, ast.Assign)
            and any(getattr(t, "id", "") == "live_field" for t in n.targets)]
    assert live, "live_field is no longer assigned"
    referenced = {c.id for a in live for c in ast.walk(a.value)
                  if isinstance(c, ast.Name)}
    assert referenced & open_locals, (
        f"live_field is assigned from {referenced or 'a literal path'} and "
        f"not from open_fields ({open_locals}) — an unaddressed answer will "
        f"be read against a field that may already be answered, which is the "
        f"2026-08-10 production defect")


# ── DEFECT 3: the repair copy names the field that failed ──────────────────

def _facts(**kw):
    base = dict(outcome="repair", internal_failure=False, operation_id="op",
                field_id="f", name="Chicken", entry_id=None, calories=None,
                protein=None, day_calories=None, estimated=False,
                system_supplied_figure=False)
    base.update(kw)
    return at.CanonicalResponseFacts(**base)


def test_an_unreadable_preparation_answer_does_not_ask_about_quantity():
    """"How much chicken?" in reply to an unparseable COOKING answer is the
    copy telling the user their quantity was lost. It was not."""
    said = at.copy_for(_facts(open_attributes=("preparation",)))
    assert "how much" not in said.lower(), said
    assert "cooked" in said.lower(), said


def test_an_unreadable_quantity_answer_still_asks_about_quantity():
    """The original phrasing is preserved for the field it was written for —
    including the clause that stops a second food being silently dropped."""
    said = at.copy_for(_facts(open_attributes=("quantity",)))
    assert "how much chicken" in said.lower(), said
    assert "isn't logged yet" in said.lower(), said


def test_a_repair_carries_the_attribute_it_repaired():
    """`_turn` never set `open_attributes`, so the copy had nothing to name
    and fell back to quantity for every field."""
    answer = type("A", (), {"outcome": Outcome.REPAIR, "reason": "unreadable",
                            "repair_reason": None, "refusal_reason": None})()
    owned = type("O", (), {"operation_id": "op", "item": {"food": "Chicken"}})()
    turn = at._turn(answer, owned, PREPARATION)
    assert turn.open_attributes == ("preparation",)


# ── DEFECT 2: a typed PARTIAL returns the fields still open ────────────────

def test_a_partial_carries_the_remaining_fields_to_the_wire():
    """The client cannot render chips for a field it was never sent.

    `AnswerTurn.remaining` has existed since B-1.5 for exactly this; nothing
    read it on the text path, so a typed PARTIAL shipped prose and no chips —
    which, combined with defect 1, left preparation unreachable by BOTH
    modalities at once.
    """
    import dataclasses

    from core.conversation import TurnResult

    names = {f.name for f in dataclasses.fields(TurnResult)}
    assert "b1_interaction" in names, (
        "TurnResult cannot carry the refreshed interaction, so a canonical "
        "answer has no way to send the client what is still open")


def test_the_wire_reader_accepts_both_return_shapes():
    """The ask returns a dict; a canonical answer returns a `TurnResult`.
    Reading only the dict is why the payload existed and never reached the
    wire."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "core/conversation.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", "") == "_b1_ix" for t in node.targets):
            continue
        rendered = ast.dump(node)
        found = True
        assert "getattr" in rendered, (
            "the wire reader still only understands a dict, so a canonical "
            "answer's remaining fields cannot reach the client")
    assert found, "_b1_ix is no longer assigned"
