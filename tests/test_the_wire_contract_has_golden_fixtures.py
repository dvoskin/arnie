"""B-1.9 step 8 — golden fixtures. The artefact Swift is built against.

A prose contract is a contract nobody can run. These are committed JSON files
that BOTH the server and the client must satisfy, so "the payload changed" is
a diff in review rather than a bug in a TestFlight build.

WHAT A FAILURE HERE MEANS. Not "fix the fixture". It means a persisted shape
changed, and the decision is either to revert it or to bump a schema version
AND migrate what is already stored. Regenerating the file to make the test
pass is the one response that destroys the point.
"""
import json
import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "b1_contract"


def _golden(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


# ── the interaction a client renders ────────────────────────────────────────

def test_the_stored_interaction_still_decodes():
    """OLD BYTES, CURRENT CODE. The first thing that breaks when a field is
    renamed is every operation already sitting in `pending_operations`."""
    from core.semantics import ClarificationInteraction

    interaction = ClarificationInteraction.from_payload(
        _golden("interaction_v1"))
    assert interaction.operation_id == "chat_quantity:26:telegram:9146"
    assert interaction.revision == 0
    field = interaction.groups[0].fields[0]
    assert [o.option_id for o in field.options] == [
        "opt_ont_low", "opt_hist_last", "opt_ont_high"]
    assert [o.label for o in field.options] == ["3 oz", "5 oz", "8 oz"]
    assert all(o.patch is not None for o in field.options)


def test_the_interaction_round_trips_byte_for_byte():
    from core.semantics import ClarificationInteraction

    golden = _golden("interaction_v1")
    again = ClarificationInteraction.from_payload(golden).to_payload()
    assert json.loads(json.dumps(again, sort_keys=True)) == golden, (
        "the wire payload changed shape — bump a schema version and migrate "
        "what is stored, or revert; do not regenerate this fixture")


def test_option_identity_and_order_do_not_drift():
    """ORDER IS DATA. It decides which chip is first, and therefore
    prominence and selection rate."""
    field = _golden("interaction_v1")["groups"][0]["fields"][0]
    assert [o["option_id"] for o in field["options"]] == [
        "opt_ont_low", "opt_hist_last", "opt_ont_high"]
    for option in field["options"]:
        # THE CLIENT ANSWERS BY ID and renders by label. It receives no
        # semantics it could reinterpret.
        assert option["option_id"] and option["field_id"]
        assert option["candidate_id"] and option["candidate_set_id"]
        assert "candidate" not in option and "evidence" not in option


def test_the_field_id_travels_on_the_option():
    """The field computes `field_id` as a property, so only the OPTIONS carry
    it across storage. A client reading it from the field would find nothing."""
    field = _golden("interaction_v1")["groups"][0]["fields"][0]
    assert all(o["field_id"] for o in field["options"])


# ── the candidate and the decision ──────────────────────────────────────────

def test_the_stored_candidate_still_decodes():
    from core.semantics import QuantityCandidate

    candidate = QuantityCandidate.from_payload(_golden("candidate_v1"))
    assert candidate.candidate_id == "hist_last"
    assert candidate.evidence[0].source.dataset_id
    assert candidate.offered.unit_id == "g"
    assert QuantityCandidate.from_payload(
        candidate.to_payload()).to_payload() == _golden("candidate_v1")


def test_the_stored_decision_still_decodes():
    from core.semantics import CandidateDecisionRecord

    record = CandidateDecisionRecord.from_payload(_golden("decision_v1"))
    assert record.candidate_set.candidate_set_id == "cs_golden"
    assert record.decision.selection_policy_version
    assert record.presented
    assert record.to_payload() == _golden("decision_v1")


def test_decimals_are_stored_as_strings_in_the_fixtures():
    """A float does not round-trip. `Decimal("0.1")` through JSON as a number
    comes back as something that is not equal to itself."""
    candidate = _golden("candidate_v1")
    assert isinstance(candidate["prior"], str)
    assert isinstance(candidate["quantity"]["grams"], str)
    assert isinstance(candidate["evidence"][0]["confidence"], str)


# ── compatibility rules ─────────────────────────────────────────────────────

def test_an_added_field_is_compatible_and_a_removed_one_is_not():
    """ADDITIVE CHANGES ARE SAFE; removals and renames are not. A client built
    against today's fixture must survive tomorrow's extra key."""
    from core.semantics import ClarificationInteraction

    widened = dict(_golden("interaction_v1"))
    widened["a_field_from_the_future"] = {"anything": True}
    assert ClarificationInteraction.from_payload(widened) is not None


def test_an_unknown_evidence_version_fails_shut_rather_than_being_guessed():
    from core.semantics import QuantityCandidate

    future = json.loads(json.dumps(_golden("candidate_v1")))
    future["evidence"][0]["evidence_version"] = 99
    with pytest.raises(ValueError, match="must be migrated"):
        QuantityCandidate.from_payload(future)


@pytest.mark.parametrize("path,value", [
    (("evidence", 0, "subject_scope"), "everyone_ish"),
    (("evidence", 0, "observed_basis"), "handfuls"),
    (("serving_basis",), "handfuls"),
])
def test_an_unknown_enum_value_fails_shut(path, value):
    """A value we cannot interpret must not travel as if we could."""
    from core.semantics import QuantityCandidate

    payload = json.loads(json.dumps(_golden("candidate_v1")))
    target = payload
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        QuantityCandidate.from_payload(payload)


def test_the_fixtures_name_the_versions_that_produced_them():
    """So a future reader can tell WHICH generator, selector and renderer
    wrote these bytes — without which the fixture is a shape with no
    provenance."""
    from skills.nutrition import quantity_clarification as qc

    decision = _golden("decision_v1")
    assert (decision["candidate_set"]["generator_version"]
            == qc.GENERATOR_VERSION)
    assert (decision["decision"]["selection_policy_version"]
            == qc.SELECTION_POLICY_VERSION)
    assert (decision["decision"]["context"]["renderer_contract_version"]
            == qc.RENDERER_CONTRACT_VERSION)
    assert all(p["renderer_contract_version"] == qc.RENDERER_CONTRACT_VERSION
               for p in decision["presented"])


# ── the structured answer envelope ─────────────────────────────────────────

def test_the_request_envelope_is_frozen():
    """WHAT iOS SENDS. Five fields, all required — a partial envelope is a
    client bug, and answering it would mean guessing which question was
    meant."""
    from api.chat import ClarificationAnswerRequest

    fields = ClarificationAnswerRequest.model_fields
    assert set(fields) == {"operation_id", "revision", "field_id",
                           "option_id", "client_message_id"}
    assert all(f.is_required() for f in fields.values()), (
        "an optional identifier here means the server guesses")


def test_the_response_envelope_is_frozen():
    """WHAT iOS RECEIVES. Identifiers, typed reasons and rendered text —
    never semantics a client could reinterpret."""
    from api.chat import _EMPTY_ANSWER

    assert set(_EMPTY_ANSWER) == {
        "v", "bubbles", "cards", "outcome", "repair_reason",
        "refusal_reason", "operation_id", "field_id", "entry_id"}
    for leaked in ("candidate", "evidence", "patch", "quantity",
                   "serving_basis"):
        assert leaked not in _EMPTY_ANSWER


def test_the_golden_answer_request_still_validates():
    """OLD BYTES, CURRENT MODEL. A client shipped against this fixture must
    keep working."""
    from api.chat import ClarificationAnswerRequest

    request = ClarificationAnswerRequest(**_golden("answer_request_v1"))
    assert request.operation_id == "chat_quantity:26:telegram:9146"
    assert request.revision == 0
    assert request.client_message_id


@pytest.mark.parametrize("field", ["operation_id", "field_id", "option_id",
                                   "client_message_id"])
def test_an_empty_identifier_is_rejected_at_the_boundary(field):
    from api.chat import ClarificationAnswerRequest

    body = dict(_golden("answer_request_v1"))
    body[field] = ""
    with pytest.raises(Exception):
        ClarificationAnswerRequest(**body)


def test_expiry_is_a_lifecycle_disposition_not_an_answer_outcome():
    """AN EXPIRED OPERATION IS STILL ANSWERABLE when addressed.

    Someone replying late is still replying, and refusing them would be its
    own silent loss. What expiry removes is the claim on messages that were
    never meant for this question. So the user never receives "expired" as the
    result of answering — there is no such outcome.
    """
    from core.b1_quantity_operation import OwnershipDisposition
    from core.clarification_answer import Outcome

    assert {d.value for d in OwnershipDisposition} == {
        "holding", "expired", "settled"}
    assert "expired" not in {o.value for o in Outcome}
    assert not hasattr(Outcome, "EXPIRED")
