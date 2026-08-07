"""B-1.9 step 8 — the frozen contract.

Client work begins after this file, so everything it names is now a thing that
changes DELIBERATELY, with a version bump and a migration of what is already
stored — not as a side effect of an edit.

Three surfaces are frozen:

    the WIRE contract          what a client receives and sends back
    the SEMANTIC candidate     what a candidate and its evidence mean
    the DECISION telemetry     what we record about a clarification

A frozen contract is not a claim that it is right. It is a claim that changing
it is visible.
"""
import pytest

from core import clarification_answer as answers
from core import semantics
from skills.nutrition import candidate_selection as policy
from skills.nutrition import quantity_clarification as qc


# ── the wire ────────────────────────────────────────────────────────────────

def test_the_option_a_client_receives_has_a_frozen_shape():
    """IDENTIFIERS AND LABELS, never semantics a client could reinterpret.

    The typed candidate stays server-side deliberately: a client that received
    it could form its own view of what an option means, and then there are two
    owners of one fact.
    """
    from core.semantics import ClarificationOption

    payload = ClarificationOption(label="6 oz", option_id="opt_x",
                                  field_id="f", candidate_id="cand_x",
                                  candidate_set_id="cs_x").to_payload()
    assert set(payload) == {
        "label", "value", "option_id", "field_id", "confidence", "patch",
        "source", "adapter_built", "candidate_id", "candidate_set_id"}
    assert "candidate" not in payload
    assert "evidence" not in payload
    assert "quantity" not in payload


def test_the_answer_a_client_sends_back_is_four_identifiers():
    """`(operation_id, revision, field_id, option_id)` — and the meaning comes
    from storage. A label travelling back as semantics is C11's defect."""
    import inspect

    chip = inspect.signature(answers.answer_from_chip).parameters
    assert set(chip) == {"interaction", "field_id", "option_id", "revision"}


@pytest.mark.parametrize("version,expected", [
    ("QUESTION_VERSION", "b1_quantity_q2"),
    ("GENERATOR_VERSION", "b1_quantity_gen_v1"),
    ("RENDERER_CONTRACT_VERSION", "b1_labels_v1"),
    ("SELECTION_POLICY_VERSION", "b1_quantity_select_v1"),
])
def test_every_version_stamp_is_frozen(version, expected):
    """A VERSION NAMES ONE BEHAVIOUR FOREVER. Changing a value here without
    changing the string is how two populations become one."""
    from core import b1_quantity_operation as ops

    holder = ops if version == "QUESTION_VERSION" else qc
    assert getattr(holder, version) == expected


def test_the_evidence_schema_version_is_frozen():
    assert semantics.EVIDENCE_SCHEMA_VERSION == 1
    from core import unit_registry
    assert unit_registry.UNIT_DISPLAY_VERSION == "unit_display_v1"


# ── the semantic candidate ──────────────────────────────────────────────────

@pytest.mark.parametrize("enum,members", [
    ("ServingBasis", {"mass", "volume", "count", "piece", "package",
                      "fraction_of_package", "fraction_of_entity",
                      "standard_serving"}),
    ("EvidenceScope", {"this_user", "this_product_quantity", "population"}),
    ("ExclusionReason", {"semantic_duplicate", "render_collision",
                         "selection_cap"}),
    ("GenerationRejectionReason", {"no_quantity", "unknown_basis",
                                   "unsupported_conversion", "missing_subject",
                                   "malformed_quantity"}),
    ("SelectionSurface", {"label_text", "id_addressed"}),
    ("RoundingMode", {"half_up", "half_even", "down", "up"}),
])
def test_a_frozen_vocabulary_cannot_grow_silently(enum, members):
    """Every persisted enum. A new member is a migration of meaning for every
    row already written, so it must be a decision rather than an edit."""
    assert {m.value for m in getattr(semantics, enum)} == members


def test_the_candidate_payload_keys_are_frozen():
    """These are on disk now. A renamed key is unreadable history."""
    from decimal import Decimal

    from tests._typed_candidates import candidate

    payload = candidate("c1", 100.0).to_payload()
    assert set(payload) == {"candidate_id", "canonical_entity_id", "quantity",
                            "serving_basis", "offered", "semantic_hash",
                            "prior", "evidence"}
    assert set(payload["evidence"][0]) == {
        "evidence_version", "source_type", "source", "observed_quantity",
        "observed_basis", "observed_at", "subject_scope", "subject_user_id",
        "product_variant_id", "conversion_evidence", "confidence",
        "uncertainty_g"}
    assert set(payload["source" if "source" in payload
                        else "evidence"][0]["source"]) == {
        "dataset_id", "dataset_version", "record_key", "record_version",
        "immutable_within_version"}
    assert set(payload["offered"]) == {
        "amount", "unit_id", "basis", "normalized", "quantize_exponent",
        "rounding_mode", "policy_version", "conversion_evidence"}
    assert isinstance(payload["prior"], str), (
        "decimals cross as strings; a float does not round-trip")


# ── the decision telemetry ──────────────────────────────────────────────────

def test_the_observation_columns_are_frozen():
    from db.models import B1AnswerObservation

    assert {c.name for c in B1AnswerObservation.__table__.columns} == {
        "id", "operation_id", "user_id", "source_turn_id", "attribute",
        "outcome", "modality", "selected_source", "offered", "round_index",
        "latency_ms", "entry_id", "observed_at", "interaction_revision",
        "question_version", "policy_version", "repair_reason", "cohort"}


@pytest.mark.parametrize("enum,members", [
    ("AnswerModality", {"option_id", "label_selection", "user_text",
                        "command", "repair", "unknown"}),
    ("Outcome", {"applied", "cancelled", "repair", "refused"}),
    ("RepairReason", {"no_amount_in_answer", "unusable_amount",
                      "estimate_unsupported", "universe_unavailable"}),
    ("RefusalReason", {"unknown_option", "foreign_field",
                       "revision_mismatch", "option_without_patch"}),
])
def test_the_answer_vocabularies_are_frozen(enum, members):
    assert {m.value for m in getattr(answers, enum)} == members


def test_there_is_no_legacy_outcome():
    """C10. Once owned, an operation finishes canonically — apply, repair,
    cancel or commit. Adding a fourth door is the thing this forbids."""
    assert not hasattr(answers.Outcome, "LEGACY")


def test_an_outage_is_not_reported_as_a_fact_about_a_user():
    """`universe_unavailable` stays separate from `estimate_unsupported`.

    Pooled, a storage failure would read as a population of users whose
    logging history we lack — and the second number is one the roadmap uses to
    decide what to build.
    """
    assert (answers.RepairReason.UNIVERSE_UNAVAILABLE
            is not answers.RepairReason.ESTIMATE_UNSUPPORTED)


# ── the refusal contract for an unrelated report ────────────────────────────

def test_a_reask_names_the_food_and_disowns_what_it_did_not_log():
    """THE FROZEN BEHAVIOUR FOR AN UNRELATED REPORT.

    Measured live: "I had some salmon too" while chicken was awaiting drew
    "How much was it? A rough amount is fine." — no food named. A user reads
    that as a question about the salmon, answers it, and the amount prices the
    CHICKEN.

    The contract: name the active food, state that anything else is not
    logged, and CLAIM NOTHING ABOUT SAVING IT. The deferred report is not
    persisted, and copy that implied a queue would be a promise the system
    does not keep.
    """
    from core.b1_answer_turn import CanonicalResponseFacts, copy_for

    said = copy_for(CanonicalResponseFacts(
        outcome="repair", internal_failure=False, operation_id="op",
        field_id="f", name="Chicken breast", entry_id=None, calories=None,
        protein=None, day_calories=None, estimated=False,
        system_supplied_figure=False))
    assert "chicken breast" in said.lower(), "the re-ask does not name a food"
    assert "?" in said, "a re-ask must read as a question"
    low = said.lower()
    assert "isn't logged" in low or "not logged" in low, (
        "the re-ask does not say the other food was not logged")
    for promise in ("saved", "queued", "hold on to", "i'll log", "remember"):
        assert promise not in low, (
            f"the copy implies {promise!r} — nothing is persisted, and a "
            f"promise the system does not keep is worse than the refusal")


def test_the_unrelated_report_reason_is_not_invented():
    """`unrelated_report_while_awaiting` IS NOT A MEMBER, deliberately.

    The answer turn runs BEFORE the interpreter and sees only the raw message
    — that ordering is how "6 oz" stopped becoming a second meal. It therefore
    cannot distinguish a message that reported another food from one that was
    simply unusable, and recording that distinction would record knowledge the
    turn does not have.

    The copy covers the user-facing case without the claim.
    """
    assert "unrelated_report_while_awaiting" not in {
        r.value for r in answers.RepairReason}


# ── the selector's purity, proven per evidence record ───────────────────────

def test_the_policy_reads_only_confidence_off_an_evidence_record():
    """TIGHTENED. The earlier proxy returned real evidence objects, so a
    policy could branch on `evidence[0].source_type` — a hidden source-name
    authority — without tripping it."""
    from decimal import Decimal

    from core.semantics import CandidateSelectionContext, SelectionSurface
    from tests._typed_candidates import candidate

    class _EvidenceTrap:
        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def __getattr__(self, name):
            if name.startswith("__"):
                return getattr(object.__getattribute__(self, "_inner"), name)
            if name != "confidence":
                raise AssertionError(
                    f"the selector read evidence.{name!r}; only `confidence` "
                    f"is an approved ranking feature, and reading a source "
                    f"type here would be source-name authority by another "
                    f"name")
            return object.__getattribute__(self, "_inner").confidence

    class _CandidateTrap:
        APPROVED = {"candidate_id", "quantity", "serving_basis", "evidence",
                    "prior"}

        def __init__(self, inner):
            object.__setattr__(self, "_inner", inner)

        def __getattr__(self, name):
            if name.startswith("__"):
                return getattr(object.__getattribute__(self, "_inner"), name)
            if name not in self.APPROVED:
                raise AssertionError(f"the selector read candidate.{name!r}")
            inner = object.__getattribute__(self, "_inner")
            if name == "evidence":
                return tuple(_EvidenceTrap(e) for e in inner.evidence)
            return getattr(inner, name)

    real = (candidate("c1", 85.0, prior=0.2),
            candidate("c2", 141.7, prior=0.55, confidence=0.9),
            candidate("c3", 400.0, prior=0.3))

    class _Watched:
        candidate_ids = {c.candidate_id for c in real}
        candidates = tuple(_CandidateTrap(c) for c in real)

    chosen, excluded = policy.select(
        _Watched(),
        context=CandidateSelectionContext(
            surface=SelectionSurface.LABEL_TEXT, locale="en",
            maximum_options=3,
            renderer_contract_version=qc.RENDERER_CONTRACT_VERSION))
    assert len(chosen) + len(excluded) == 3


def test_the_policy_reads_only_the_option_capacity_off_a_context():
    """Narrowed to what the baseline actually uses. Surface, locale and
    renderer version are persisted for REPRODUCIBILITY, not consumed by v1 —
    and a policy quietly reading one would make its decisions depend on a
    field nobody expected it to."""
    seen = []

    class _ContextTrap:
        def __getattr__(self, name):
            if name.startswith("__"):
                raise AttributeError(name)
            assert name == "maximum_options", (
                f"the baseline policy read context.{name!r}")
            seen.append(name)
            return 3

    from tests._typed_candidates import candidate

    real = (candidate("c1", 85.0), candidate("c2", 500.0))

    class _Watched:
        candidate_ids = {c.candidate_id for c in real}
        candidates = real

    policy.select(_Watched(), context=_ContextTrap())
    assert seen == ["maximum_options"] * len(seen) and seen
