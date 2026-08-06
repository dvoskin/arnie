"""D4's FUNNEL — can we actually answer the question we are about to ask?

D4 runs an observation window to decide whether option generation is any good,
and then B-1b builds chips on the answer. The comparison it has to support is:

    candidate source -> offered -> selected -> repaired -> corrected

so that "history candidates are selected 91% of the time and corrected 1%,
ontology 55% and 9%" is a statement the data can make. Until it is, expanding
ontology coverage versus investing in history matching is a coin flip with a
dashboard next to it.

THIS FILE EXISTS BECAUSE THE METRICS PREVIOUSLY COULD NOT MAKE IT.
`b1_shown` emitted `sources=` as a SET — enough to say "ontology was involved",
never enough to divide by. And `b1_answered` carried `modality` (tap / label /
free text), which is HOW they answered, never WHERE the value they chose came
from. Every per-source rate was therefore unanswerable, and would have been
discovered at the end of the window rather than before it.

That is the same failure as every other one in this slice, arriving one layer
up: an instrument that returns something plausible for a question it cannot
actually answer. So the funnel gets pinned before the window opens, not after.
"""
import logging

import pytest

from core import trace_buffer

# The conversation fixtures, so the durable half can be proved against a REAL
# ask and answer rather than a hand-built row. Same reasoning as `_field`
# below: the shape that matters is the one production writes.
from tests.test_a_full_day_of_food import (  # noqa: F401
    app_db, edges, seeded, rows, item,
)
from tests.test_a_conversation_across_turns import (  # noqa: F401
    CAPABLE, b1_live, say,
)


@pytest.fixture(autouse=True)
def _ring():
    trace_buffer.install()
    trace_buffer._lines.clear()
    yield
    trace_buffer._lines.clear()


def _emit_via_real_metrics(fn, **kw):
    logging.getLogger("core.b1_metrics").setLevel(logging.INFO)
    fn(**kw)
    return " ".join(l["message"] for l in trace_buffer.recent(limit=20)["lines"])


def _field(*specs):
    """A REAL `UnresolvedField` carrying REAL `ClarificationOption`s.

    Built in two steps because the field validates that every option answers
    ITS `field_id`, and `field_id` is computed from the field — so the options
    cannot be written before the field they belong to exists. That constraint
    is the point: an option that patches another field is the mixed chip row
    one level down, and the type refuses to represent it.

    Two hand-rolled doubles came before this one and each was missing an
    attribute the resolver reads (`patch`, then `send_value`), making the
    resolver look broken when the fixture was wrong. Assuming a shape instead
    of using the real one is the defect this whole slice keeps re-learning.
    """
    from decimal import Decimal

    from core.semantics import (CandidateSource, CanonicalQuantity,
                                ClarificationAttribute, ClarificationOption,
                                Provenance, ResponseType, SetQuantity,
                                UnresolvedField)

    def _build(options, response_type=ResponseType.SINGLE_SELECT):
        return UnresolvedField(
            operation_id="op_1", revision=0, event_id="ev_1",
            attribute=ClarificationAttribute.QUANTITY,
            response_type=response_type, options=tuple(options))

    # FREE_TEXT_FALLBACK to learn the id, because an empty SINGLE_SELECT is
    # (rightly) unconstructable — C15 refuses a select that cannot be selected
    # from. The id is a function of operation/revision/event/attribute, so it
    # is the same one the real field will carry.
    field_id = _build((), ResponseType.FREE_TEXT_FALLBACK).field_id
    options = [
        ClarificationOption(
            label=label, option_id=option_id, field_id=field_id,
            source=CandidateSource(source_value),
            patch=SetQuantity(
                event_id="ev_1", field_id=field_id,
                quantity=CanonicalQuantity(grams=Decimal(str(grams))),
                provenance=Provenance.USER_SELECTED))
        for option_id, label, source_value, grams in specs]
    return _build(options)


def test_offered_counts_give_acceptance_a_denominator():
    """`sources` is a set; acceptance needs counts.

    "Ontology was offered" cannot be divided into "ontology was selected". The
    offer has to be counted per source or every per-source rate is a fraction
    with no bottom half.
    """
    from core import b1_metrics

    field = _field(("a", "2 oz", "ontology", 60),
                   ("b", "4 oz", "ontology", 120),
                   ("c", "6 oz", "user_history", 170))
    line = _emit_via_real_metrics(
        b1_metrics.shown, operation_id="op_1", user_id=26, cohort="allowlist",
        locale="en", field=field)

    assert "offered=ontology:2,user_history:1" in line, line
    assert "options=3" in line, line


def test_the_answer_records_where_the_chosen_value_came_from():
    """modality says HOW, selected_source says WHERE FROM. Both, or neither
    question is answerable."""
    from core import b1_metrics

    line = _emit_via_real_metrics(
        b1_metrics.answered, operation_id="op_1", user_id=26,
        outcome="applied", modality="label", selected_source="user_history",
        provenance="user_selected", grams=110)

    assert "selected_source=user_history" in line, line
    assert "modality=label" in line, line


def test_the_commit_carries_the_source_the_correction_will_be_charged_to():
    """A correction ten minutes later is keyed on entry_id.

    If the commit event does not also carry the source, attributing that
    correction means a third hop through storage — and an attribution that is
    awkward to compute is one that quietly does not get computed.
    """
    from core import b1_metrics

    line = _emit_via_real_metrics(
        b1_metrics.committed, operation_id="op_1", user_id=26, entry_id=2860,
        calories=287.0, selected_source="ontology", repairs=1)

    assert "entry=2860" in line and "selected_source=ontology" in line, line
    assert "repairs=1" in line, line


@pytest.mark.parametrize("option_id,message,expected", [
    ("opt_ont_mid", "", "ontology"),
    ("", "4 oz", "user_history"),
    ("", "137 grams", "free_text"),
    ("opt_not_ours", "", "unknown_option"),
])
def test_the_source_resolver_names_every_route(option_id, message, expected):
    """Including free text, which is a RESULT and not a missing value.

    A typed quantity we did not offer is the signal that the option list failed
    this user. Recording it as blank would fold the single most important D4
    number into "unknown".
    """
    from core.b1_answer_turn import _selected_source

    field = _field(("opt_ont_mid", "2 oz", "ontology", 60),
                   ("opt_hist", "4 oz", "user_history", 120))
    assert _selected_source(field, option_id=option_id,
                            message=message) == expected


def test_every_funnel_field_survives_the_ring():
    """The whole chain is worthless if the ring drops it on the way out.

    This is `verify the instrument before its silence` applied to the funnel
    itself: a field the ring cannot carry is a field that reads as absent, and
    absence would be interpreted as "that source is never selected".
    """
    from core import b1_metrics

    field = _field(("a", "2 oz", "ontology", 60))
    _emit_via_real_metrics(b1_metrics.shown, operation_id="op_1", user_id=26,
                           cohort="allowlist", locale="en", field=field)
    _emit_via_real_metrics(b1_metrics.answered, operation_id="op_1",
                           user_id=26, outcome="applied", modality="chip",
                           selected_source="ontology")
    _emit_via_real_metrics(b1_metrics.committed, operation_id="op_1",
                           user_id=26, entry_id=1, calories=1.0,
                           selected_source="ontology")

    events = {l["event"] for l in trace_buffer.recent(limit=20)["lines"]}
    assert {"b1_shown", "b1_answered", "b1_committed"} <= events, events
    joined = " ".join(l["message"] for l in trace_buffer.recent(limit=20)["lines"])
    for token in ("offered=", "selected_source=", "entry="):
        assert token in joined, f"{token} did not survive the ring: {joined}"


# ── The window has to survive the thing that empties the ring ─────────────────

@pytest.mark.asyncio
async def test_a_real_conversation_leaves_a_durable_observation(
        edges, b1_live, app_db):
    """The funnel must land in a TABLE, not only in the ring.

    `core/trace_buffer` is `deque(maxlen=2000)` in process memory, shared by
    every watched event, and it empties on restart — measured in production
    minutes after a deploy: zero lines, and the dropped counter reset with it.
    An observation window read from there is a window over "since the last
    deploy" that cannot say what it lost.

    So this drives a real ask and a real answer and then reads the DATABASE.
    """
    from sqlalchemy import select

    import db.database as D
    from db.models import B1AnswerObservation
    from tests.test_a_conversation_across_turns import B1_ELIGIBLE, say

    edges.plans.append(B1_ELIGIBLE)
    await say(b1_live, "I had some chicken breast")
    await say(b1_live, "6 oz")

    async with D.AsyncSessionLocal() as s:
        rows = list((await s.execute(
            select(B1AnswerObservation)
            .order_by(B1AnswerObservation.id))).scalars().all())

    assert rows, "a real answer left no durable observation"
    landed = rows[-1]
    assert landed.outcome == "applied", landed.outcome
    assert landed.selected_source, "the source was not recorded"
    assert landed.offered, "the offer mix was not recorded — no denominator"
    assert landed.attribute == "quantity", landed.attribute
    assert landed.entry_id, (
        "the committed row was never stamped onto the answer — a correction "
        "could then be counted per user but never per SOURCE, which is the "
        "comparison the window exists to make")


@pytest.mark.asyncio
async def test_a_repair_and_its_answer_are_two_rows_in_order(
        edges, b1_live, app_db):
    """A repair is an answer that did not land, and the funnel needs both.

    Counting only successful answers would report a repair rate of zero and an
    acceptance rate of one hundred percent — the two numbers most likely to be
    quoted, and both wrong in the flattering direction.
    """
    from sqlalchemy import select

    import db.database as D
    from db.models import B1AnswerObservation
    from tests.test_a_conversation_across_turns import B1_ELIGIBLE, say

    edges.plans.append(B1_ELIGIBLE)
    await say(b1_live, "I had some chicken breast")
    await say(b1_live, "somewhere thereabouts")     # unreadable -> repair
    await say(b1_live, "6 oz")                      # then the real answer

    async with D.AsyncSessionLocal() as s:
        rows = list((await s.execute(
            select(B1AnswerObservation)
            .order_by(B1AnswerObservation.id))).scalars().all())

    assert len(rows) >= 2, [ (r.outcome, r.round_index) for r in rows ]
    assert [r.round_index for r in rows] == list(range(1, len(rows) + 1)), (
        f"rounds are not ordered: {[(r.outcome, r.round_index) for r in rows]}")
    assert rows[-1].outcome == "applied", [r.outcome for r in rows]
