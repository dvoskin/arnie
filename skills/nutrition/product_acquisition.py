"""⭐ P17f.5 — EXACT-PRODUCT ACQUISITION. THE ONLY PLACE A BARCODE MEETS A NETWORK.

    iOS scan -> raw barcode (SEPARATE from prose) -> THIS module, at INGRESS
             -> exact OFF fetch -> append immutable snapshot -> snapshot id
             -> bound to the turn's single food item
             -> settlement LOADS the snapshot locally. Zero provider calls.

⛔⛔ ACQUISITION MAY ADD EVIDENCE; SETTLEMENT MAY ONLY READ EVIDENCE. This module
is imported by the API ingress and by nothing on the settle path — enforced by
test, because "the wire must not reopen network-at-settlement" is the exact
boundary P17 spent a tranche closing.

⛔ THE BARCODE IS NEVER RECONSTRUCTED FROM PROSE. There is no text parsing in
this module and must never be: the scan message ("I scanned a barcode — ...")
remains presentation/context only, and a client that did not send the code
separately has not sent a code.

⚠ FAILURE IS ALWAYS None, NEVER AN ERROR. A dead OFF, a malformed code, an
unknown product — the meal continues UNBOUND and prices exactly as it does
today. Acquisition is an enrichment of the turn, not a gate on it.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# THE SCAN STATE OF ONE TURN *(P17 closure directive, Phase 1 — Danny's design)*
#
#     UnverifiedScanAttachment            what ingress has: a snapshot id
#             ↓ repository validation     ONE database read, in one place
#     VerifiedScanEvidence                immutable: id · provider · code ·
#                                         revision · fingerprint · brand ·
#                                         product identity
#             ↓ pure classification       core.scan_authority.decide_from_plan
#     ScanDecision                        outcome · evidence · disposition ·
#                                         reason — immutable, kept for audit
#
# Rules *(verbatim from the review)*:
#   · same snapshot id but different metadata is a CONFLICT, not a duplicate;
#     only field-identical evidence dedupes
#   · several distinct attachments produce an explicit ATTACHMENT_CONFLICT —
#     not a fake evidence sentinel
#   · a live turn with only a partial object fails closed; arbitrary partial
#     evidence is never silently "completed" from the database
#   · a persisted canonical-operation retry reconstructs evidence from its
#     stored snapshot reference + fingerprint through a SEPARATELY NAMED
#     repository path (`evidence_from_stored_reference`)
#   · downstream consumers accept only VerifiedScanEvidence; none reloads or
#     reinterprets it
#   · a DISCARDED decision keeps its evidence for logs; it cannot confer
#     settlement authority — only `require_bound_evidence()` exposes evidence
#     to settlement
#   · the state is REQUEST-SCOPED: a fresh holder per ingress, claimed by the
#     request's turn id at `run_turn`; a holder claimed by another turn is
#     stale and discarded, never read
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class UnverifiedScanAttachment:
    """What ingress hands over when it has only an id (tests, older callers).
    Carries no authority: the repository validates it into evidence, once."""
    snapshot_id: int


@dataclass(frozen=True)
class VerifiedScanEvidence:
    """The immutable statement of WHICH snapshot rode this turn — built from
    the persisted row (acquisition, or the repository path) and handed, as
    is, to every consumer. `disagrees_with_row` lets a consumer that holds a
    row prove it is the same evidence; `identical` is the dedupe test."""
    snapshot_id: int
    provider: str
    code: str
    revision: str
    fingerprint: str
    brand: str
    product_name: str

    def __post_init__(self):
        # ⛔ NO PARTIAL EVIDENCE. A live turn with a half-filled object fails
        # closed at construction rather than somewhere downstream.
        if not (isinstance(self.snapshot_id, int) and self.snapshot_id > 0):
            raise ValueError("VerifiedScanEvidence requires a snapshot id")
        for name in ("provider", "code", "fingerprint"):
            if not str(getattr(self, name) or "").strip():
                raise ValueError(f"VerifiedScanEvidence requires {name}")
        # ⛔ P17 Phase 1 finishing patch (finding 5): EXACT-PRODUCT authority
        # needs a usable product identity BEFORE classification — a nameless
        # snapshot must be refused at the authority gate (identity_unknown),
        # not discovered later by the executor. Brand may be empty; the
        # product name may not.
        if not str(self.product_name or "").strip():
            raise ValueError("VerifiedScanEvidence requires a product identity")

    @classmethod
    def from_row(cls, row) -> "VerifiedScanEvidence":
        return cls(snapshot_id=int(getattr(row, "id")),
                   provider=str(getattr(row, "provider", "") or ""),
                   code=str(getattr(row, "canonical_code", "") or ""),
                   revision=str(getattr(row, "provider_revision", "") or ""),
                   fingerprint=str(getattr(row, "source_fingerprint", "") or ""),
                   brand=str(getattr(row, "brands", "") or ""),
                   product_name=str(getattr(row, "product_name", "") or ""))

    def identical(self, other) -> bool:
        return isinstance(other, VerifiedScanEvidence) and other == self

    def disagrees_with_row(self, row) -> str:
        """'' when the persisted row IS this evidence, else the first field
        that disagrees — a refusal names it."""
        if row is None:
            return "missing"
        checks = (("snapshot_id", int(getattr(row, "id", -1)), int(self.snapshot_id)),
                  ("provider", str(getattr(row, "provider", "") or ""), self.provider),
                  ("code", str(getattr(row, "canonical_code", "") or ""), self.code),
                  ("revision", str(getattr(row, "provider_revision", "") or ""), self.revision),
                  ("fingerprint", str(getattr(row, "source_fingerprint", "") or ""), self.fingerprint))
        for name, theirs, mine in checks:
            if theirs != mine:
                return name
        return ""


# outcomes of the authority's decision
BOUND = "bound"
MULTI_ITEM = "multi_item"
EXPLICIT_OTHER_FOOD = "explicit_other_food"
PRIOR_CONFLICT = "prior_conflict"
IDENTITY_CONFLICT = "identity_conflict"
ATTACHMENT_CONFLICT = "attachment_conflict"
UNDECIDABLE = "undecidable"
#: compatibility alias — logs emit the semantic outcome (`multi_item`)
SKIPPED_MULTI_ITEM = MULTI_ITEM
#: pre-decision / post-settlement markers reported by `ScanBinding.kind`
ATTACHED = "attached"
CONSUMED = "consumed"

# dispositions of a decision
DISP_BOUND = "BOUND"
DISP_DISCARDED = "DISCARDED"
DISP_REFUSED = "REFUSED"


@dataclass(frozen=True)
class ScanDecision:
    """The authority's immutable ruling for this turn. `evidence` is retained
    whatever the disposition — audit, logs, the reply note — but only a
    BOUND disposition lets `require_bound_evidence()` hand it to settlement."""
    outcome: str
    evidence: Optional[VerifiedScanEvidence]
    disposition: str
    reason: str = ""

    @property
    def is_bound(self) -> bool:
        return self.disposition == DISP_BOUND and self.outcome == BOUND

    @property
    def snapshot_id(self) -> Optional[int]:
        return self.evidence.snapshot_id if self.evidence is not None else None


@dataclass
class ScanTurnState:
    """ONE holder per request. Everything the turn knows about its scan lives
    here, and nowhere else; `begin_turn()` creates a fresh one at ingress and
    `claim()` binds it to the request's turn id."""
    claimed_by: Optional[str] = None
    attachments: list = None                 # every attach call, for audit
    unverified: Optional[UnverifiedScanAttachment] = None
    evidence: Optional[VerifiedScanEvidence] = None
    attachment_conflict: Optional[str] = None
    verification_failure: Optional[str] = None
    decision: Optional[ScanDecision] = None
    consumed: bool = False

    def __post_init__(self):
        if self.attachments is None:
            self.attachments = []

    @property
    def attached(self) -> bool:
        return (self.unverified is not None or self.evidence is not None
                or self.attachment_conflict is not None)

    @property
    def attached_snapshot_id(self) -> Optional[int]:
        if self.evidence is not None:
            return int(self.evidence.snapshot_id)
        if self.unverified is not None:
            return int(self.unverified.snapshot_id)
        return None


SCAN_TURN: ContextVar[Optional[ScanTurnState]] = ContextVar("SCAN_TURN",
                                                            default=None)
#: the evidence acquisition built from the row it just persisted/loaded —
#: consumed by `attach_acquired()` so ingress hands the holder VERIFIED
#: evidence without a second read. Cleared at `begin_turn`.
_LAST_ACQUIRED: ContextVar[Optional[VerifiedScanEvidence]] = ContextVar(
    "_LAST_ACQUIRED", default=None)


def begin_turn() -> None:
    """A FRESH holder, unconditionally, at ingress — the PRIOR_REPLY_UNSEEN
    lesson applied to the whole scan state. Called at ingress before anything
    else, and by tests that need a clean turn."""
    SCAN_TURN.set(ScanTurnState())
    _LAST_ACQUIRED.set(None)


def state() -> Optional[ScanTurnState]:
    return SCAN_TURN.get()


def claim(turn_id: str) -> ScanTurnState:
    """⛔ REQUEST-SCOPED. `run_turn` claims the holder for its request. A
    holder already claimed by ANOTHER turn id outlived its request (an ingress
    that forgot `begin_turn`): it is discarded — logged, never read — and a
    fresh empty holder takes its place. Same id: idempotent."""
    st = SCAN_TURN.get()
    tid = str(turn_id or "")
    if st is None:
        st = ScanTurnState()
        SCAN_TURN.set(st)
    elif st.claimed_by not in (None, tid):
        logger.warning("event=scan_state_stale_discarded claimed_by=%s now=%s",
                       st.claimed_by, tid)
        st = ScanTurnState()
        SCAN_TURN.set(st)
    st.claimed_by = tid
    return st


def attach(snapshot) -> None:
    """A barcode was acquired for this turn. `snapshot` is the
    `VerifiedScanEvidence` acquisition built from the persisted row, or a bare
    snapshot id / `UnverifiedScanAttachment` (tests, older callers) that the
    repository path validates once, in the validation stage.

    ⛔ TWO DIFFERENT ATTACHMENTS IN ONE TURN REFUSE: a second attach with
    another id, OR the same id with different metadata, is a turn with two
    product statements and no way to know which one the words are about. Both
    stay in `attachments` for audit; neither is the turn's evidence; the turn
    is ATTACHMENT_CONFLICT. Only field-identical evidence dedupes."""
    if snapshot is None:
        return
    st = SCAN_TURN.get()
    if st is None:
        st = ScanTurnState()
        SCAN_TURN.set(st)
    if isinstance(snapshot, VerifiedScanEvidence):
        item = snapshot
    elif isinstance(snapshot, UnverifiedScanAttachment):
        item = snapshot
    else:
        item = UnverifiedScanAttachment(int(snapshot))
    st.attachments.append(item)
    if st.attachment_conflict is not None:
        return                                       # already refused; stays so
    existing = st.evidence if st.evidence is not None else st.unverified
    if existing is None:
        if isinstance(item, VerifiedScanEvidence):
            st.evidence = item
        else:
            st.unverified = item
        return
    # a second attachment: identical dedupes, anything else conflicts
    if isinstance(existing, VerifiedScanEvidence) and isinstance(item, VerifiedScanEvidence):
        if existing.identical(item):
            return
        why = ("same id, different metadata"
               if existing.snapshot_id == item.snapshot_id else "two snapshots")
    elif isinstance(existing, UnverifiedScanAttachment) and isinstance(item, UnverifiedScanAttachment):
        if existing.snapshot_id == item.snapshot_id:
            return
        why = "two snapshots"
    else:
        # one verified, one bare id: the same id is the same attachment seen
        # twice at different levels of proof — keep the VERIFIED one. A
        # different id is two attachments.
        a, b = (existing, item) if isinstance(existing, VerifiedScanEvidence) else (item, existing)
        if a.snapshot_id == b.snapshot_id:
            st.evidence, st.unverified = a, None
            return
        why = "two snapshots"
    logger.warning("event=scan_attachment_conflict reason=%r attachments=%s",
                   why, [getattr(x, "snapshot_id", None) for x in st.attachments])
    st.attachment_conflict = why
    st.evidence, st.unverified = None, None


async def verify(db) -> Optional[VerifiedScanEvidence]:
    """⛔ THE ONE REPOSITORY VALIDATION. A bare attachment becomes evidence by
    ONE read of its persisted row; evidence acquisition already built from the
    row needs no read. Anything that cannot be verified is recorded as a
    verification failure and the turn fails closed (UNDECIDABLE)."""
    st = SCAN_TURN.get()
    if st is None or st.attachment_conflict is not None:
        return None
    if st.evidence is not None:
        return st.evidence
    if st.unverified is None:
        return None
    if db is None:
        st.verification_failure = "no_session"
        return None
    try:
        from db.models import ProductEvidenceRecord
        row = await db.get(ProductEvidenceRecord, int(st.unverified.snapshot_id))
    except Exception as exc:                             # noqa: BLE001
        logger.warning("scan verify: snapshot %s unreadable",
                       st.unverified.snapshot_id, exc_info=True)
        st.verification_failure = f"unreadable:{type(exc).__name__}"
        return None
    if row is None:
        st.verification_failure = "missing"
        return None
    try:
        st.evidence = VerifiedScanEvidence.from_row(row)
    except ValueError as exc:
        st.verification_failure = f"partial:{exc}"
        return None
    return st.evidence


async def evidence_from_stored_reference(db, snapshot_id, fingerprint: str
                                         ) -> Optional[VerifiedScanEvidence]:
    """⛔ THE SEPARATELY NAMED RECONSTRUCTION PATH for a persisted canonical-
    operation retry (the CF9 answer turn): the stored operation references a
    snapshot id AND the fingerprint of the facts it held. Both must match the
    persisted row, or nothing is returned — a reprice against changed facts is
    not the operation the user answered."""
    if db is None or snapshot_id is None or not fingerprint:
        return None
    try:
        from db.models import ProductEvidenceRecord
        row = await db.get(ProductEvidenceRecord, int(snapshot_id))
    except Exception:                                    # noqa: BLE001
        logger.warning("scan evidence: stored reference %s unreadable",
                       snapshot_id, exc_info=True)
        return None
    if row is None or str(getattr(row, "source_fingerprint", "") or "") != str(fingerprint):
        return None
    try:
        return VerifiedScanEvidence.from_row(row)
    except ValueError:
        return None


def decide(decision: ScanDecision) -> ScanDecision:
    """Record the authority's ruling — TERMINAL for this turn *(P17 Phase 1
    finishing patch, finding 1)*. An identical second decision is idempotent
    (a retry of the same gate); a DIFFERENT second decision, or any decision
    after the binding was consumed, is a lifecycle violation and REFUSES —
    it would let a later stage overwrite the ruling execution already read."""
    st = SCAN_TURN.get()
    if st is None:
        st = ScanTurnState()
        SCAN_TURN.set(st)
    if st.decision is not None:
        if st.decision == decision and not st.consumed:
            return st.decision                       # idempotent retry
        from core.scan_authority import ScanAuthorityRefusal
        raise ScanAuthorityRefusal(
            "decision_conflict",
            f"a decision is already recorded for this turn "
            f"({st.decision.outcome}/{st.decision.disposition}"
            f"{', consumed' if st.consumed else ''}) and cannot be replaced "
            f"by {decision.outcome}/{decision.disposition}")
    st.decision = decision
    return decision


def consume_binding() -> None:
    """The binding has been settled, or handed to an ask that holds the
    snapshot. It is no longer live for this turn's later stages."""
    st = SCAN_TURN.get()
    if st is not None and st.decision is not None and st.decision.is_bound:
        st.consumed = True


def scan_is_bound() -> bool:
    """MECHANICAL DELEGATE to `core.scan_authority.is_bound` *(CF5c cleanup)*.
    Kept only so callers that imported it keep working."""
    from core.scan_authority import is_bound
    return is_bound()


@dataclass(frozen=True)
class ScanBinding:
    """A READ-ONLY VIEW of the holder for log lines and for tests that still
    read `.kind` / `.snapshot_id` — built by `binding_view()`; never the
    store. `kind` is the decision outcome, `attached` before a decision,
    `consumed` after settlement."""
    kind: str
    snapshot_id: Optional[int] = None
    reason: Optional[str] = None

    @property
    def is_bound(self) -> bool:
        return self.kind == BOUND

    def __str__(self) -> str:                            # for log lines
        return (f"{self.kind}({self.snapshot_id})" if self.snapshot_id
                else self.kind)


# ── COMPATIBILITY ADAPTERS (tests only; production never imports them) ──────
#
# The historical contextvars `SCANNED_PRODUCT_EVIDENCE` (the attached id) and
# `SCAN_BINDING` (the binding record) are kept as ADAPTERS over the one holder
# so the existing proof suites keep driving the real state. They are views,
# not stores: `get` reads the holder, `set`/`reset` translate into the
# holder's own operations and return/restore the holder object as the token.
# An AST gate asserts no production module references either name.

def _fork_holder():
    """The adapters' `set` works on a NEW holder (a copy of the current one) so
    `reset(token)` restores the UNTOUCHED previous holder — mutating the same
    object in place would make reset a no-op, and an "unscanned" second run
    would silently inherit the first run's attachment."""
    prev = SCAN_TURN.get()
    if prev is None:
        nxt = ScanTurnState()
    else:
        nxt = ScanTurnState(claimed_by=prev.claimed_by,
                            attachments=list(prev.attachments),
                            unverified=prev.unverified, evidence=prev.evidence,
                            attachment_conflict=prev.attachment_conflict,
                            verification_failure=prev.verification_failure,
                            decision=prev.decision, consumed=prev.consumed)
    SCAN_TURN.set(nxt)
    return prev


class _AttachmentAdapter:
    def get(self) -> Optional[int]:
        st = SCAN_TURN.get()
        return st.attached_snapshot_id if st is not None else None

    def set(self, snapshot_id):
        prev = _fork_holder()
        if snapshot_id is None:
            begin_turn()
        else:
            attach(snapshot_id)
        return prev

    def reset(self, token) -> None:
        SCAN_TURN.set(token)


class _BindingAdapter:
    def get(self) -> Optional[ScanBinding]:
        return binding_view()

    def set(self, view):
        prev = _fork_holder()
        if view is None:
            begin_turn()
            return prev
        st = SCAN_TURN.get()
        if st is None or not st.attached:
            if getattr(view, "snapshot_id", None) is not None:
                attach(int(view.snapshot_id))
            st = SCAN_TURN.get()
        kind = getattr(view, "kind", None)
        reason = getattr(view, "reason", None) or "adapter"
        if kind == ATTACHED:
            st.decision, st.consumed = None, False
        elif kind == CONSUMED:
            st.decision = ScanDecision(BOUND, st.evidence, DISP_BOUND, reason)
            st.consumed = True
        elif kind == BOUND:
            st.decision = ScanDecision(BOUND, st.evidence, DISP_BOUND, reason)
        elif kind in (MULTI_ITEM, EXPLICIT_OTHER_FOOD):
            st.decision = ScanDecision(kind, st.evidence, DISP_DISCARDED, reason)
        else:
            st.decision = ScanDecision(kind, st.evidence, DISP_REFUSED, reason)
        return prev

    def reset(self, token) -> None:
        SCAN_TURN.set(token)


SCANNED_PRODUCT_EVIDENCE = _AttachmentAdapter()
SCAN_BINDING = _BindingAdapter()


def binding_view() -> Optional[ScanBinding]:
    st = SCAN_TURN.get()
    if st is None or not st.attached:
        return None
    if st.attachment_conflict is not None and st.decision is None:
        return ScanBinding(ATTACHMENT_CONFLICT, None, st.attachment_conflict)
    if st.decision is None:
        return ScanBinding(ATTACHED, st.attached_snapshot_id)
    if st.consumed and st.decision.is_bound:
        return ScanBinding(CONSUMED, st.decision.snapshot_id, st.decision.reason)
    return ScanBinding(st.decision.outcome, st.decision.snapshot_id,
                       st.decision.reason)


def attach_acquired(snapshot_id) -> None:
    """Ingress: attach what `acquire_product_evidence` just returned. If the
    evidence object acquisition built carries this very id, THAT is attached
    (verified, complete); otherwise the bare id is attached unverified and the
    validation stage's single repository read validates it."""
    if snapshot_id is None:
        return
    ev = _LAST_ACQUIRED.get()
    _LAST_ACQUIRED.set(None)
    if ev is not None and int(ev.snapshot_id) == int(snapshot_id):
        attach(ev)
    else:
        attach(UnverifiedScanAttachment(int(snapshot_id)))


async def acquire_product_evidence(db, barcode, *, serving_unit: str = "",
                                   package_unit: str = "") -> Optional[int]:
    """Fetch the exact product ONCE, persist the snapshot, return its id.

    ⭐ FETCH FIRST, LOCAL FALLBACK SECOND. A live fetch captures the provider's
    current facts as a fresh immutable snapshot (append-only — identical facts
    dedupe, changed facts insert). When the provider is unreachable, the NEWEST
    local snapshot for this code still binds: yesterday's evidence is evidence,
    and a network flake must not turn a scanned product into an estimate.
    """
    from skills.nutrition.product_store import (append_product_evidence,
                                                canonical_code,
                                                latest_product_evidence)

    code = canonical_code(barcode)
    if not code or not (6 <= len(code) <= 14):
        return None

    record = None
    try:
        from skills.nutrition.off import fetch_product

        record = await fetch_product(code)
    except Exception:                                    # noqa: BLE001
        logger.warning("acquisition: OFF fetch failed for %s", code,
                       exc_info=True)

    if record is not None:
        try:
            row = await append_product_evidence(
                db, record=record, serving_unit=serving_unit,
                package_unit=package_unit)
            if row is not None:
                logger.info("event=product_acquired code=%s snapshot=%s "
                            "rev=%s", code, row.id, row.provider_revision)
                try:
                    _LAST_ACQUIRED.set(VerifiedScanEvidence.from_row(row))
                except ValueError:
                    # a snapshot without a usable identity: nothing stashed;
                    # the bare id attaches, verify() refuses identity_unknown
                    logger.warning("acquisition: snapshot %s has no usable "
                                   "identity — evidence not stashed", row.id)
                # ⭐ P17-UA — deterministic unit enrichment AT ACQUISITION:
                # if the record's structured serving/quantity text names a
                # consumer unit (sources 2/3), persist that fact beside the
                # snapshot. If it does not, nothing is persisted and the
                # bound path will ASK (source 4). Failure here binds nothing
                # extra and costs nothing.
                try:
                    from skills.nutrition.off import consumer_unit_alias_from_off
                    from skills.nutrition.product_store import append_unit_evidence
                    alias = consumer_unit_alias_from_off(record)
                    if alias is not None:
                        unit, ups, provenance, ref = alias
                        await append_unit_evidence(
                            db, product_evidence_id=int(row.id),
                            consumer_unit=unit, units_per_serving=ups,
                            provenance=provenance, source_reference=ref)
                except Exception:                        # noqa: BLE001
                    logger.warning("acquisition: unit enrichment failed for %s",
                                   code, exc_info=True)
                return int(row.id)
        except Exception:                                # noqa: BLE001
            logger.warning("acquisition: persist failed for %s", code,
                           exc_info=True)

    try:
        existing = await latest_product_evidence(db, code)
    except Exception:                                    # noqa: BLE001
        logger.warning("acquisition: local lookup failed for %s", code,
                       exc_info=True)
        return None
    if existing is not None:
        logger.info("event=product_acquired code=%s snapshot=%s source=local",
                    code, existing.id)
        try:
            _LAST_ACQUIRED.set(VerifiedScanEvidence.from_row(existing))
        except ValueError:
            logger.warning("acquisition: snapshot %s has no usable identity — "
                           "evidence not stashed", existing.id)
        return int(existing.id)
    return None
