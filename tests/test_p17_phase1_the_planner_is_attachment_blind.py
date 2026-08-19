"""⛔⛔ P17 CLOSURE — PHASE 1: THE PROMPT OVERREACH IS REMOVED, THE AUTHORITY
IS THE MECHANISM *(Danny's P17 closure directive, 2026-08-19 evening, and the
two review rounds that followed the same night)*.

`9cf29b9` added a global instruction to the food interpreter's user turn
("SCAN ATTACHED: … NOT a correction … do not emit an update"). It acted on the
ATTACHMENT, before the typed plan existed, so it decided binding at the one
place that cannot see what the turn is about; on a mixed turn it rewrote the
clause that had nothing to do with the scan. Gone. The prompt says nothing
about scans, the planner reads nothing about scans, and the authority decides:

    UnverifiedScanAttachment  ->  VerifiedScanEvidence  ->  ScanDecision
      (ingress: an id)           (ONE repository read)     (pure, typed)

    no verifiable evidence                  UNDECIDABLE        REFUSED
    two different attachments               ATTACHMENT_CONFLICT REFUSED
    replay / prior-held only                PRIOR_CONFLICT     REFUSED
    no subjects                             UNDECIDABLE        REFUSED
    two or more fresh subjects              MULTI_ITEM         DISCARDED (+note)
    one subject, consumption denied/asked   UNDECIDABLE        REFUSED
    one subject, literal mention SAME       BOUND              BOUND
                                 OTHER      EXPLICIT_OTHER_FOOD DISCARDED (+note)
                                 CONFLICT   IDENTITY_CONFLICT  REFUSED
    one subject, no mention, fresh signal   BOUND              BOUND
    one subject, no mention, no signal      UNDECIDABLE        REFUSED

A REFUSED decision is raised at the VALIDATION GATE, before any execution. A
DISCARDED decision keeps its evidence for audit and confers no authority —
`require_bound_evidence()` is the only door to settlement.
"""
from __future__ import annotations

import logging

import pytest

from tests.test_a_scan_is_binding import (BAREBELLS_PROD, _Req, _ev, _fake_ev,
                                          _log, _prod_snapshot)
from tests.test_scan_binding_dominates_correction_claims import (
    _legacy_barebells_row, _row_bytes, _the_misrouted_plan)


CARAMEL = dict(BAREBELLS_PROD, code="0850000429093",
               product_name="Caramel Cashew", brands="Barebells", rev=218)


async def _caramel(db):
    from skills.nutrition.product_store import append_product_evidence
    return await append_product_evidence(db, record=dict(CARAMEL))


def _plan(out):
    from core.turns.stages.food import plan_from_interpretation
    return plan_from_interpretation(out)


def _log_op(food, qty):
    return {"name": "log_food", "input": {"food_name": food, "quantity": qty}}


def _outcome(plan, ev):
    from core.scan_authority import decide_from_plan
    d = decide_from_plan(plan, ev)
    return d.outcome if d is not None else None


# ═════ 1 — SCAN + A FRESH PRODUCT STATEMENT BINDS ══════════════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("message,subject,why", [
    ("I had 2 servings of this.", "Caramel Cashew", "fresh_consumption"),
    ("2 servings", "Caramel Cashew", "fresh_amount"),
    ("had 2 barebells caramel cashew", "Barebells Caramel Cashew", "mention_same"),
    ("I had a protein bar", "protein bar", "fresh_consumption"),
    ("this one", "bar", "fresh_deictic"),
])
async def test_1_a_fresh_statement_about_the_scanned_product_binds(
        db, make_user, message, subject, why):
    """The canary shape: the user's words name the scanned product, name
    nothing, or point at it — one subject, about the scan — so it BINDS."""
    from core.scan_authority import decision
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": message,
                  "tool_calls": [_log_op(subject, "2 servings")]})
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(plan, _ev(snap)) == BOUND
        assert decision().reason == why
        assert decision().evidence.snapshot_id == snap.id
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_1_twin_a_bare_id_that_is_never_verified_cannot_bind(db, make_user):
    """MUTATION TWIN: the SAME statement over an UNVERIFIED attachment (the
    repository validation never ran) refuses — a live turn with only a
    partial object fails closed; nothing "completes" it."""
    from core.scan_authority import decide_from_plan
    from skills.nutrition.product_acquisition import (DISP_REFUSED,
                                                      UNDECIDABLE, attach,
                                                      begin_turn)
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": "I had 2 servings of this.",
                  "tool_calls": [_log_op("Caramel Cashew", "2 servings")]})
    begin_turn()
    attach(snap.id)                                   # bare id, never verified
    try:
        d = decide_from_plan(plan)                     # no evidence handed in
        assert d.outcome == UNDECIDABLE and d.disposition == DISP_REFUSED
        assert d.reason.startswith("identity_unknown")
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_1_the_repository_validation_is_one_read_and_builds_complete_evidence(
        db, make_user):
    """A bare id attached at ingress is verified ONCE by `verify(db)`; the
    evidence it builds is complete (id, provider, code, revision, fingerprint,
    brand, product) and agrees with the persisted row field for field."""
    from skills.nutrition.product_acquisition import (VerifiedScanEvidence,
                                                      attach, begin_turn,
                                                      state, verify)
    snap = await _caramel(db)
    begin_turn()
    attach(snap.id)
    try:
        assert state().evidence is None and state().unverified is not None
        ev = await verify(db)
        assert isinstance(ev, VerifiedScanEvidence)
        assert ev == VerifiedScanEvidence.from_row(snap)
        assert ev.disagrees_with_row(snap) == ""
        assert ev.fingerprint == snap.source_fingerprint and ev.code == "850000429093"
        # a second verify is NOT a second read: the evidence is already there
        assert await verify(None) is ev
    finally:
        begin_turn()


# ═════ 2 — SCAN + A CORRECTION TO ANOTHER FOOD KEEPS BOTH SUBJECTS ═════════

@pytest.mark.asyncio
async def test_2_a_correction_to_another_food_survives_and_the_scan_is_discarded_with_a_note(
        db, make_user, caplog):
    """⛔ THE REGRESSION `9cf29b9` WOULD HAVE SHIPPED: "actually make the
    chicken 8 oz" while a bar is scanned. The prompt line told the model "do
    NOT emit an update" — deleting a legitimate correction of an unrelated
    food. Attachment-blind: the interpreter emits the update, the plan keeps
    it, the user's literal mention ("chicken") names another food ->
    EXPLICIT_OTHER_FOOD, DISCARDED: the correction proceeds exactly as
    unscanned and the reply SAYS the scanned product was not used."""
    from core.scan_authority import (decide_from_plan, require_shape,
                                     scan_unused_note)
    from core.turns.stages.food import FoodPlanStage
    from skills.nutrition.product_acquisition import (DISP_DISCARDED,
                                                      EXPLICIT_OTHER_FOOD,
                                                      attach, begin_turn,
                                                      verify)
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _caramel(db)
    msg = "actually make the chicken 8 oz"
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": 4242, "quantity": "8 oz",
                      "food_hint": "Grilled Chicken Breast"}}]

    async def interpreter(text, u, **kw):
        assert "prior" in kw                      # the planner still passes it
        return {"action": "update", "_message": text, "tool_calls": ops}

    req = _Req(msg, {"db": db, "user": user, "today_log": log, "messages": ()})
    begin_turn()
    attach(_ev(snap))
    try:
        plan = await FoodPlanStage(interpreter=interpreter).run(req)
        assert [op["name"] for op in plan.operations] == ["update_food_entry"]
        assert [s.name for s in plan.food_subjects] == ["Grilled Chicken Breast"]
        d = decide_from_plan(plan, await verify(db))
        assert d.outcome == EXPLICIT_OTHER_FOOD and d.disposition == DISP_DISCARDED
        assert d.evidence is not None                 # retained for audit
        require_shape(plan.operations)                # proceeds unchanged
        assert "wasn't logged" in (scan_unused_note() or "")
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_2_twin_the_same_correction_with_no_scan_is_identical(db, make_user):
    from core.scan_authority import disposition, scan_unused_note
    from core.turns.stages.food import FoodPlanStage
    from skills.nutrition.product_acquisition import begin_turn
    user = await make_user()
    log = await _log(db, user)
    ops = [{"name": "update_food_entry",
            "input": {"entry_id": 4242, "quantity": "8 oz",
                      "food_hint": "Grilled Chicken Breast"}}]

    async def interpreter(text, u, **kw):
        return {"action": "update", "_message": text, "tool_calls": ops}

    begin_turn()
    req = _Req("actually make the chicken 8 oz",
               {"db": db, "user": user, "today_log": log, "messages": ()})
    plan = await FoodPlanStage(interpreter=interpreter).run(req)
    assert [op["name"] for op in plan.operations] == ["update_food_entry"]
    assert disposition() is None and scan_unused_note() is None


# ═════ 3 — SCAN + "yes" TO AN OPEN CONFIRM: PRIOR_CONFLICT, NO MUTATION ════

@pytest.mark.asyncio
async def test_3_scan_plus_yes_with_a_pending_confirm_refuses_at_the_gate_with_zero_mutation(
        db, make_user, monkeypatch, caplog):
    """The confirm replay RUNS (the planner is attachment-blind) and the
    authority rules PRIOR_CONFLICT: a scan-attached ambiguous answer must not
    execute an earlier action. Refused AT THE VALIDATION GATE — the
    execution stage never runs — with zero writes. The confirm stays open for
    a later plain "yes"."""
    import handlers.tool_executor as te
    from core.scan_authority import ScanAuthorityRefusal, decision
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from db.models import FoodEntry
    from sqlalchemy import select
    from skills.nutrition.product_acquisition import (DISP_REFUSED,
                                                      PRIOR_CONFLICT, attach,
                                                      begin_turn)
    caplog.set_level(logging.INFO)

    async def forbidden(*a, **k):
        raise AssertionError("an executor ran on a PRIOR_CONFLICT turn")

    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    user = await make_user()
    log = await _log(db, user)
    snap = await _caramel(db)
    prior = {"kind": "confirm", "items": [
        {"food": "Chicken thighs", "amount": 2, "unit": "piece", "calories": 500}]}
    req = _Req("yes", {"db": db, "user": user, "today_log": log, "messages": (),
                       "food_prior": prior, "board": [], "day_line": "",
                       "regulars": None})

    async def must_not_run(text, u, **kw):
        raise AssertionError("the replay was suppressed on attachment")

    begin_turn()
    attach(_ev(snap))
    try:
        plan = await FoodPlanStage(interpreter=must_not_run).run(req)
        assert plan.origin == "confirm_replay"
        with pytest.raises(ScanAuthorityRefusal) as ei:
            await FoodValidationStage().run(req, plan=plan)
        assert ei.value.reason == "prior_conflict"
        d = decision()
        assert d.outcome == PRIOR_CONFLICT and d.disposition == DISP_REFUSED
        assert d.evidence.snapshot_id == snap.id           # kept for audit
    finally:
        begin_turn()
    rows = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_3_twin_a_replay_plan_that_loses_its_origin_would_bind(db, make_user):
    """MUTATION TWIN: the SAME single-subject replay plan with `origin`
    cleared (the mutation: `_lift` forgets to stamp it) binds — the defect.
    The stamp is the causal provenance."""
    from dataclasses import replace
    from core.turns.stages.deterministic import ConfirmReplayPlanStage
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    user = await make_user()
    log = await _log(db, user)
    snap = await _caramel(db)
    prior = {"kind": "confirm", "items": [
        {"food": "Chicken thighs", "amount": 2, "unit": "piece", "calories": 500}]}
    req = _Req("yes", {"db": db, "user": user, "today_log": log, "messages": (),
                       "food_prior": prior})
    plan = await ConfirmReplayPlanStage().run(req)
    assert plan is not None and plan.origin == "confirm_replay"
    # without origin the plan reads as a fresh one-subject statement; "yes"
    # carries no fresh signal, so it would refuse as no_fresh_statement —
    # make the twin sharp by giving the mutated plan a consumption message
    mutated = replace(plan, origin="",
                      source={"_message": "I had 2 of these", "action": "log"})
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(mutated, _ev(snap)) == BOUND, (
            "origin no longer decides — the replay guard is vacuous")
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_3_scan_plus_quantity_while_another_products_ask_is_pending_binds_fresh_and_leaves_the_ask(
        db, make_user, caplog):
    """REQUIRED PROOF: scan + "2 servings" while an ask about ANOTHER product
    is pending. The interpreter (attachment-blind, prior passed) produces a
    fresh statement AND the prior's held write joins the plan (causal
    provenance: `_prior_held`). The fresh subject is classified
    independently -> BOUND; the held write is shed after the decision so no
    executor answers the prior; the pending operation is byte-identical."""
    from core.scan_authority import decision
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from db.models import PendingOperation
    from sqlalchemy import select
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    caplog.set_level(logging.INFO)
    user = await make_user()
    log = await _log(db, user)
    snap = await _caramel(db)
    before = [tuple(r) for r in (await db.execute(
        select(PendingOperation.__table__).where(
            PendingOperation.user_id == user.id))).all()]
    # the interpreter's exit joins the prior's held chicken write (as
    # `_settle_deferred` does) beside the fresh statement
    prior = {"kind": "ask", "question": "How much chicken?",
             "deferred_calls": [{"name": "log_food", "input": {
                 "food_name": "Grilled Chicken Breast", "quantity": "6 oz",
                 "_prior_held": True}}]}

    async def interpreter(text, u, **kw):
        held = list((kw.get("prior") or {}).get("deferred_calls") or [])
        return {"action": "log", "_message": text,
                "tool_calls": held + [_log_op("bar", "2 servings")]}

    req = _Req("2 servings", {"db": db, "user": user, "today_log": log,
                              "messages": (), "food_prior": prior})
    begin_turn()
    attach(_ev(snap))
    try:
        plan = await FoodPlanStage(interpreter=interpreter).run(req)
        keys = [s.key for s in plan.food_subjects]
        assert any(k.startswith("prior:") for k in keys), keys
        validation = await FoodValidationStage().run(req, plan=plan)
        assert decision().outcome == BOUND
        # the held write is SHED: exactly one fresh log reaches execution
        assert [op["name"] for op in validation.plan.operations] == ["log_food"]
        assert not any((op["input"] or {}).get("_prior_held")
                       for op in validation.plan.operations)
        assert "scan_bound_sheds_prior_held" in caplog.text
    finally:
        begin_turn()
    after = [tuple(r) for r in (await db.execute(
        select(PendingOperation.__table__).where(
            PendingOperation.user_id == user.id))).all()]
    assert after == before                                 # byte-identical


@pytest.mark.asyncio
async def test_3_a_plan_that_is_only_the_priors_held_writes_is_prior_conflict(db, make_user):
    """No fresh statement, only the prior's held writes carried into the
    plan: the turn executes an EARLIER action — PRIOR_CONFLICT, refused."""
    from skills.nutrition.product_acquisition import (PRIOR_CONFLICT, attach,
                                                      begin_turn)
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": "ok",
                  "tool_calls": [{"name": "log_food", "input": {
                      "food_name": "Grilled Chicken Breast", "quantity": "6 oz",
                      "_prior_held": True}}]})
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(plan, _ev(snap)) == PRIOR_CONFLICT
    finally:
        begin_turn()


# ═════ 4 — A HIDDEN HELD SUBJECT PREVENTS SINGLE-SUBJECT BINDING ═══════════

@pytest.mark.asyncio
async def test_4_a_hidden_deferred_subject_prevents_binding(db, make_user):
    from skills.nutrition.product_acquisition import (DISP_DISCARDED,
                                                      MULTI_ITEM, attach,
                                                      begin_turn)
    from core.scan_authority import decide_from_plan
    snap = await _caramel(db)
    msg = "I had 2 servings of this and some soup"
    plan = _plan({"action": "ask", "_message": msg,
                  "tool_calls": [_log_op("Caramel Cashew", "2 servings")],
                  "deferred_calls": [_log_op("Minestrone soup", "1 bowl")],
                  "questions": []})
    assert len(plan.food_subjects) == 2
    begin_turn()
    attach(_ev(snap))
    try:
        d = decide_from_plan(plan, _ev(snap))
        assert d.outcome == MULTI_ITEM and d.disposition == DISP_DISCARDED
        assert d.reason == "multi=2"
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_4_twin_the_same_plan_without_the_hidden_subject_binds(db, make_user):
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    snap = await _caramel(db)
    msg = "I had 2 servings of this and some soup"
    plan = _plan({"action": "ask", "_message": msg,
                  "tool_calls": [_log_op("Caramel Cashew", "2 servings")],
                  "deferred_calls": [], "questions": []})
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(plan, _ev(snap)) == BOUND
    finally:
        begin_turn()


# ═════ 5 — AN UNBOUND CORRECTION IS BYTE-FOR-BYTE UNCHANGED ════════════════

@pytest.mark.asyncio
async def test_5_an_unbound_correction_is_byte_for_byte_unchanged(
        db, make_user, monkeypatch):
    import handlers.tool_executor as te
    from core.scan_authority import disposition, require_shape
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from skills.nutrition.product_acquisition import begin_turn
    user = await make_user()
    log = await _log(db, user)
    existing = await _legacy_barebells_row(db, log)
    before = await _row_bytes(db, existing)

    async def spy(calls, *a, **k):
        return {}

    monkeypatch.setattr(te, "execute_tool_calls", spy)
    ops = _the_misrouted_plan(existing)

    async def interpreter(text, u, **kw):
        return {"action": "update", "_message": text, "tool_calls": ops}

    begin_turn()                                   # NO scan
    req = _Req("make it 4", {"db": db, "user": user, "today_log": log,
                             "messages": ()})
    plan = await FoodPlanStage(interpreter=interpreter).run(req)
    validation = await FoodValidationStage().run(req, plan=plan)
    assert disposition() is None
    require_shape(validation.approved_operations)
    assert validation.plan.operations == tuple(ops)
    assert await _row_bytes(db, existing) == before


# ═════ 6 — AN ORDINARY BOUND LOG SETTLES BY THE VERIFIED IDENTITY ══════════

@pytest.mark.asyncio
async def test_6_an_ordinary_bound_log_settles_with_the_verified_identity(
        db, make_user, monkeypatch, caplog):
    """End to end through the real stages: attach (as acquisition would), scan
    + "I had 2 servings of this." -> ONE row named EXACTLY the verified
    evidence's product, priced from the label (2 x 55 g), carrying the
    snapshot id — no memory, no legacy, no reload of the row at settlement."""
    import handlers.tool_executor as te
    from db.models import FoodEntry
    from sqlalchemy import select
    from core.turns.stages.execute_native import NativeExecutionStage
    from core.turns.stages.food import FoodPlanStage, FoodValidationStage
    from skills.nutrition.product_acquisition import attach, begin_turn
    caplog.set_level(logging.INFO)

    async def forbidden(*a, **k):
        raise AssertionError("legacy executor invoked for a bound turn")

    monkeypatch.setattr(te, "execute_tool_calls", forbidden)
    user = await make_user()
    monkeypatch.setenv("GENERAL_SETTLEMENT_ALLOWLIST", str(user.id))
    log = await _log(db, user)
    snap = await _caramel(db)

    async def interpreter(text, u, **kw):
        return {"action": "log", "_message": text,
                "tool_calls": [_log_op("bar", "2 servings")]}

    req = _Req("I had 2 servings of this.",
               {"db": db, "user": user, "today_log": log, "messages": ()},
               turn_id=f"ios:p1-bound-{user.id}")
    begin_turn()
    attach(_ev(snap))
    try:
        plan = await FoodPlanStage(interpreter=interpreter).run(req)
        validation = await FoodValidationStage().run(req, plan=plan)
        assert validation.disposition == "execute"
        execution = await NativeExecutionStage().run(req, validation=validation)
    finally:
        begin_turn()
    assert execution is not None and execution.calls[0].committed
    rows = (await db.execute(select(FoodEntry).where(
        FoodEntry.daily_log_id == log.id))).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.parsed_food_name == "Barebells Caramel Cashew", row.parsed_food_name
    assert row.product_evidence_id == snap.id
    assert row.calories == pytest.approx(220.0)      # 110 g x 200 kcal/100 g
    assert row.pricing_rung == "product"
    assert "MEMORY" not in caplog.text


# ═════ 7 — IDENTITY CONFLICT FROM THE USER'S LITERAL MENTION (INVARIANT 6) ═

@pytest.mark.asyncio
async def test_7_the_barcode_and_the_words_naming_different_products_refuses(
        db, make_user):
    """The barcode says Caramel Cashew; the user wrote "Barebells Salty
    Peanut". ONE product statement, two identities: IDENTITY_CONFLICT,
    refused at the gate, nothing written."""
    from core.scan_authority import ScanAuthorityRefusal, raise_if_refused
    from skills.nutrition.product_acquisition import (IDENTITY_CONFLICT,
                                                      attach, begin_turn)
    snap = await _caramel(db)
    msg = "I had 2 Barebells Salty Peanut bars"
    plan = _plan({"action": "log", "_message": msg,
                  "tool_calls": [_log_op("Barebells Salty Peanut", "2 bars")]})
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(plan, _ev(snap)) == IDENTITY_CONFLICT
        with pytest.raises(ScanAuthorityRefusal) as ei:
            raise_if_refused()
        assert ei.value.reason == "identity_conflict"
    finally:
        begin_turn()
    from core.turns.entrypoint import _refusal_copy
    assert "isn't the one you described" in _refusal_copy(ei.value)


@pytest.mark.asyncio
async def test_7_twin_literal_salty_peanut_with_the_write_relabelled_caramel_cashew_stays_a_conflict(
        db, make_user):
    """REQUIRED PROOF: the user wrote "Barebells Salty Peanut"; the producer
    RELABELLED the write "Caramel Cashew" (a board-row name) while its raw
    interpretation row kept the user's words. The normaliser keeps the lone
    raw row on the lone write (positional), both labels ride the subject, the
    authority verifies ONLY the label the user actually wrote — and the
    conflict survives the relabel."""
    from skills.nutrition.product_acquisition import (IDENTITY_CONFLICT,
                                                      attach, begin_turn)
    snap = await _caramel(db)
    msg = "I had 2 Barebells Salty Peanut bars"
    plan = _plan({"action": "log", "_message": msg,
                  "tool_calls": [_log_op("Caramel Cashew", "2 bars")],    # relabelled
                  "b1_material": {"staged_items": (), "items": [
                      {"food": "Barebells Salty Peanut", "amount": 2,
                       "unit": "bar"}]}})
    assert len(plan.food_subjects) == 1
    assert set(plan.food_subjects[0].labels) == {"Caramel Cashew",
                                                 "Barebells Salty Peanut"}
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(plan, _ev(snap)) == IDENTITY_CONFLICT
    finally:
        begin_turn()


@pytest.mark.asyncio
async def test_7_coffee_beside_the_brand_is_not_a_flavour(db, make_user):
    """'had a Barebells bar with coffee': the mention is the producer's label
    "Barebells bar" (verified); "coffee" is never compared. BOUND."""
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": "had a Barebells bar with coffee",
                  "tool_calls": [_log_op("Barebells bar", "1 bar")]})
    begin_turn()
    attach(_ev(snap))
    try:
        assert _outcome(plan, _ev(snap)) == BOUND
    finally:
        begin_turn()


def test_7_only_the_verified_mention_is_compared_never_the_rest_of_the_message():
    """Pure: `compare_mention` sees the mention set only. 'coffee' in the
    message is invisible to it; 'salty peanut' in a verified mention beside
    the brand is a conflict; a mention that shares nothing is OTHER."""
    from core.scan_authority import (CONFLICT, OTHER, SAME, compare_mention,
                                     verified_mention)
    ev = _fake_ev(7, name="Caramel Cashew", brand="Barebells")
    assert verified_mention(["Barebells bar"], "had a Barebells bar with coffee") == {"barebells"}
    assert compare_mention({"barebells"}, ev) == SAME
    assert compare_mention({"barebells", "salty", "peanut"}, ev) == CONFLICT
    assert compare_mention({"chicken"}, ev) == OTHER
    # a label the user did NOT write contributes no mention at all
    assert verified_mention(["Caramel Cashew"], "I had 2 Barebells Salty Peanut bars") == set()


@pytest.mark.asyncio
async def test_7_a_log_that_names_another_food_is_explicit_other_food_discarded(
        db, make_user):
    """The ONE fresh statement names a food that shares nothing with the
    label ("I had 6 oz chicken" while a bar is scanned): EXPLICIT_OTHER_FOOD,
    DISCARDED — the chicken logs exactly as unscanned, the scan is not
    used, and the reply says so. (Distinct from the correction branch: this
    is a plain log subject classified by its verified mention.)"""
    from core.scan_authority import decide_from_plan, scan_unused_note
    from skills.nutrition.product_acquisition import (DISP_DISCARDED,
                                                      EXPLICIT_OTHER_FOOD,
                                                      attach, begin_turn)
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": "I had 6 oz chicken",
                  "tool_calls": [_log_op("Grilled Chicken Breast", "6 oz")]})
    begin_turn()
    attach(_ev(snap))
    try:
        d = decide_from_plan(plan, _ev(snap))
        assert d.outcome == EXPLICIT_OTHER_FOOD and d.disposition == DISP_DISCARDED
        assert d.reason == "mention=chicken", d.reason
        assert "wasn't logged" in (scan_unused_note() or "")
    finally:
        begin_turn()


def test_7_the_unused_scan_note_reaches_the_users_reply():
    """CONSUMER-SIDE: a DISCARDED decision's note becomes a bubble of the
    turn's reply in `_result_from_state`; with no scan the reply is untouched."""
    from types import SimpleNamespace as NS
    from core.platform import Response
    from core.scan_authority import decide_from_plan
    from core.turns.entrypoint import _result_from_state
    from skills.nutrition.product_acquisition import (MULTI_ITEM, attach,
                                                      begin_turn)
    ev = _fake_ev(7, name="Caramel Cashew", brand="Barebells")
    plan = _plan({"action": "log", "_message": "I had 2 of these and soup",
                  "tool_calls": [_log_op("bar", "2"), _log_op("soup", "1 bowl")]})

    def _state(text):
        return NS(response=Response.from_text(text),
                  validation=NS(approved_operations=()), request=NS(metadata={}),
                  health_flags=set(), execution=None, error=None)

    begin_turn()
    attach(ev)
    assert decide_from_plan(plan, ev).outcome == MULTI_ITEM
    result = _result_from_state(_state("Logged the soup."), {})
    joined = " ".join(result.response.bubbles).lower()
    assert "logged the soup" in joined and "scanned product" in joined
    begin_turn()
    assert _result_from_state(_state("Logged the soup."), {}).response.bubbles == [
        "Logged the soup."]


# ═════ 8 — IDENTITY-FREE BINDING NEEDS A FRESH STATEMENT ═══════════════════

@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["yes", "thanks", "👍", "", "ok cool"])
async def test_8_a_hallucinated_one_subject_plan_from_bare_text_cannot_bind(
        db, make_user, message):
    """REQUIRED PROOF: the producer falsely emits an ordinary log from bare
    "yes" (or thanks, an emoji, empty text). No verifiable mention, no amount,
    no consumption language, no deictic -> UNDECIDABLE, refused."""
    from skills.nutrition.product_acquisition import (DISP_REFUSED,
                                                      UNDECIDABLE, attach,
                                                      begin_turn)
    from core.scan_authority import decide_from_plan
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": message,
                  "tool_calls": [_log_op("Caramel Cashew", "1 bar")]})
    begin_turn()
    attach(_ev(snap))
    try:
        d = decide_from_plan(plan, _ev(snap))
        assert d.outcome == UNDECIDABLE and d.disposition == DISP_REFUSED
        assert d.reason == "no_fresh_statement", d.reason
    finally:
        begin_turn()


@pytest.mark.asyncio
@pytest.mark.parametrize("message,why", [
    ("I didn't eat this", "consumption_negated"),
    ("should I eat this?", "consumption_question"),
    ("never had it", "consumption_negated"),
])
async def test_8_negated_or_questioned_consumption_cannot_become_a_write(
        db, make_user, message, why):
    """NEGATION / QUESTION TWINS: a producer that emits a log for "I didn't
    eat this" or "should I eat this?" is refused before execution."""
    from skills.nutrition.product_acquisition import (DISP_REFUSED,
                                                      UNDECIDABLE, attach,
                                                      begin_turn)
    from core.scan_authority import decide_from_plan
    snap = await _caramel(db)
    plan = _plan({"action": "log", "_message": message,
                  "tool_calls": [_log_op("Caramel Cashew", "1 bar")]})
    begin_turn()
    attach(_ev(snap))
    try:
        d = decide_from_plan(plan, _ev(snap))
        assert d.outcome == UNDECIDABLE and d.disposition == DISP_REFUSED
        assert d.reason == why, d.reason
    finally:
        begin_turn()


# ═════ 9 — THE ATTACHMENT AUTHORITY: IDENTICAL DEDUPES, DIFFERENT REFUSES ══

def test_9_two_identical_attachments_are_one_verified_authority():
    from skills.nutrition.product_acquisition import attach, begin_turn, state
    ev = _fake_ev(7, name="Caramel Cashew", brand="Barebells")
    begin_turn()
    attach(ev)
    attach(_fake_ev(7, name="Caramel Cashew", brand="Barebells"))   # identical
    st = state()
    assert st.attachment_conflict is None
    assert st.evidence == ev and len(st.attachments) == 2        # audit keeps both


def test_9_same_id_with_differing_fingerprints_is_a_conflict():
    from skills.nutrition.product_acquisition import (ATTACHMENT_CONFLICT,
                                                      attach, begin_turn,
                                                      state)
    from core.scan_authority import ScanAuthorityRefusal, disposition, require_shape
    begin_turn()
    attach(_fake_ev(7, fingerprint="fpA"))
    attach(_fake_ev(7, fingerprint="fpB"))                       # same id, other facts
    st = state()
    assert st.attachment_conflict == "same id, different metadata"
    assert st.evidence is None and len(st.attachments) == 2
    assert disposition() == ATTACHMENT_CONFLICT
    with pytest.raises(ScanAuthorityRefusal) as ei:
        require_shape(())
    assert ei.value.reason == "attachment_conflict"


def test_9_two_distinct_attachments_are_an_attachment_conflict_decision():
    from skills.nutrition.product_acquisition import (ATTACHMENT_CONFLICT,
                                                      DISP_REFUSED, attach,
                                                      begin_turn)
    from core.scan_authority import ScanAuthorityRefusal, decide_from_plan
    begin_turn()
    attach(_fake_ev(7))
    attach(_fake_ev(8))
    plan = _plan({"action": "log", "_message": "I had 2 servings of this",
                  "tool_calls": [_log_op("bar", "2 servings")]})
    d = decide_from_plan(plan, None)
    assert d.outcome == ATTACHMENT_CONFLICT and d.disposition == DISP_REFUSED
    from core.turns.entrypoint import _refusal_copy
    assert "Two different products" in _refusal_copy(
        ScanAuthorityRefusal("attachment_conflict"))


def test_9_partial_evidence_cannot_be_constructed():
    from skills.nutrition.product_acquisition import VerifiedScanEvidence
    with pytest.raises(ValueError):
        VerifiedScanEvidence(snapshot_id=7, provider="off", code="70004199",
                             revision="1", fingerprint="", brand="B", product_name="P")
    with pytest.raises(ValueError):
        VerifiedScanEvidence(snapshot_id=0, provider="off", code="1", revision="",
                             fingerprint="fp", brand="", product_name="")


# ═════ 10 — DISCARDED EVIDENCE IS AUDITABLE, NEVER BOUND AUTHORITY ═════════

def test_10_discarded_evidence_is_retained_for_audit_and_refused_as_bound_authority():
    from core.scan_authority import (ScanAuthorityRefusal, decide_from_plan,
                                     evidence, require_bound_evidence,
                                     snapshot_id)
    from skills.nutrition.product_acquisition import (DISP_DISCARDED,
                                                      MULTI_ITEM, attach,
                                                      begin_turn)
    ev = _fake_ev(7, name="Caramel Cashew", brand="Barebells")
    plan = _plan({"action": "log", "_message": "I had 2 of these and soup",
                  "tool_calls": [_log_op("bar", "2"), _log_op("soup", "1 bowl")]})
    begin_turn()
    attach(ev)
    d = decide_from_plan(plan, ev)
    assert d.outcome == MULTI_ITEM and d.disposition == DISP_DISCARDED
    assert d.evidence == ev and evidence() == ev and snapshot_id() == 7   # audit
    with pytest.raises(ScanAuthorityRefusal):
        require_bound_evidence()                                           # no authority
    from core.turns.stages.execute_native import _bind_scanned_product
    items = [{"food_name": "bar"}]
    assert "product_evidence_id" not in _bind_scanned_product(items)[0]


def test_10_a_bound_decision_is_the_only_door_to_settlement():
    from core.scan_authority import decide_from_plan, require_bound_evidence
    from skills.nutrition.product_acquisition import BOUND, attach, begin_turn
    ev = _fake_ev(7, name="Caramel Cashew", brand="Barebells")
    plan = _plan({"action": "log", "_message": "I had 2 servings of this",
                  "tool_calls": [_log_op("bar", "2 servings")]})
    begin_turn()
    attach(ev)
    assert decide_from_plan(plan, ev).outcome == BOUND
    assert require_bound_evidence() == ev


def test_10_request_scoping_a_holder_claimed_by_another_turn_is_discarded():
    from skills.nutrition.product_acquisition import (attach, begin_turn,
                                                      claim, state)
    begin_turn()
    attach(_fake_ev(7))
    claim("ios:turn-A")
    assert state().attached
    # a new request in the same task that FORGOT begin_turn: the holder is
    # stale (claimed by A) and is discarded, not read
    claim("ios:turn-B")
    assert not state().attached and state().claimed_by == "ios:turn-B"
    # same turn re-claiming is idempotent
    begin_turn(); attach(_fake_ev(7)); claim("ios:turn-C"); claim("ios:turn-C")
    assert state().attached


# ═════ 11 — GATES BY CONSTRUCTION ══════════════════════════════════════════

def test_11_no_production_module_reads_the_compatibility_adapters():
    """`SCANNED_PRODUCT_EVIDENCE` / `SCAN_BINDING` are test adapters over the
    one holder; production imports neither."""
    import ast
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1]
    offenders = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv", "alembic/")) or \
                rel == "skills/nutrition/product_acquisition.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:                            # noqa: BLE001
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in (
                    "SCANNED_PRODUCT_EVIDENCE", "SCAN_BINDING"):
                offenders.append(rel)
            if isinstance(node, ast.ImportFrom):
                for a in node.names or ():
                    if a.name in ("SCANNED_PRODUCT_EVIDENCE", "SCAN_BINDING"):
                        offenders.append(rel)
    assert not offenders, offenders


def test_11_the_decision_has_one_caller_and_the_interpreter_takes_no_scan_parameter():
    import ast
    import inspect
    import pathlib
    import core.food_turn as FT
    for fn in (FT.run, FT._run_untraced):
        params = set(inspect.signature(fn).parameters)
        assert not {p for p in params if "scan" in p or "bound" in p}, params
    root = pathlib.Path(__file__).resolve().parents[1]
    callers = []
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv", "alembic/")):
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:                            # noqa: BLE001
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name == "decide_from_plan":
                    callers.append(rel)
    assert callers == ["core/turns/stages/food.py"], callers


def test_11_the_refusal_is_raised_at_the_validation_gate_by_construction():
    """`FoodValidationStage.run` calls verify -> decide_from_plan ->
    raise_if_refused, in that order, before any execution stage exists."""
    import inspect
    from core.turns.stages.food import FoodValidationStage
    src = inspect.getsource(FoodValidationStage.run)
    i_verify = src.index("_verify_scan(")
    i_decide = src.index("decide_from_plan(plan, ev)")
    i_raise = src.index("raise_if_refused()")
    assert i_verify < i_decide < i_raise
