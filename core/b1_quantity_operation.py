"""B-1's operation lifecycle: open ownership, hold it, settle it canonically.

Three calls, and between them the meal belongs to the canonical path:

    open()      the ask turn takes ownership — ONCE, after the rollout gate
    owning()    the answer turn asks "does a canonical operation own this?"
    settle()    the answer applies, the food is priced, ONE canonical commit

WHY `owning()` DOES NOT CONSULT THE ROLLOUT GATE
------------------------------------------------
It answers a question about STORED STATE, not about configuration: a row
exists, therefore this meal is ours. Re-asking the gate here is the mid-flight
fallback the directive forbids, and every way of acting on a newly-False gate
loses the meal — the answer becomes a second meal, or the pending row is
dropped, or the user answers twice. Narrowing the cohort stops new operations
and strands nothing.

WHY PRICING GOES THROUGH `_analyze_food`
-----------------------------------------
"No legacy writer is reached" is a claim about WRITES. `_analyze_food` is the
enrichment half of the legacy path — it decides what a food costs and returns
a `FoodAnalysis`; it writes nothing. Reusing it means B-1 prices food exactly
as production does today, so a divergence in the numbers can only come from
the quantity the user just gave us, which is the one thing B-1 changed.
Writing our own pricing would make every parity comparison meaningless.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)

DOMAIN = "food"

#: The pending payload's B-1 section. Versioned separately from the operation
#: payload because it is a different contract with a different owner.
B1_PAYLOAD_VERSION = 1

class OwnershipDisposition(str, Enum):
    """WHY AN OPERATION NO LONGER CLAIMS UNADDRESSED MESSAGES.

    EXPIRY IS A LIFECYCLE STATE, NOT AN ANSWER OUTCOME, and the distinction is
    load-bearing. An expired operation still accepts an answer that is clearly
    addressed to it — someone replying late is still replying, and refusing
    them would be its own silent loss. What expiry removes is the operation's
    claim on messages that were never meant for it, which is how an unanswered
    question consumed the next meal as its answer.

    So there is no `Outcome.EXPIRED`: the user never receives "expired" as the
    result of answering. They receive `applied`, `replay`, `repair`, `refused`
    or `cancelled`, and this says what the OPERATION was doing when they did.
    """
    #: Awaiting an answer and entitled to claim the lane.
    HOLDING = "holding"
    #: Past `expires_at`. Still answerable when ADDRESSED; no longer claims
    #: messages that are not.
    EXPIRED = "expired"
    #: Terminal — committed or cancelled. Replays an addressed answer.
    SETTLED = "settled"


#: Operation statuses. `awaiting_answer` is the only one `owning()` claims.
AWAITING = "awaiting_answer"
COMMITTED = "committed"
CANCELLED = "cancelled"
#: OUR failure, not the user's — an operation nobody can settle.
FAILED = "failed"

#: Ledger events that qualify as a CORRECTION of what B-1 committed. Not every
#: later event on a row is one — a rollup or a restore says something else, and
#: counting those would inflate the single metric that means "we got it wrong".
#: An edit and a deletion are both evidence; `event_type` is recorded so they
#: stay separable.
CORRECTION_EVENT_TYPES = frozenset({"updated", "deleted"})


@dataclass(frozen=True)
class OwnedOperation:
    """A canonical operation that owns a meal — in flight, or already settled.

    Settled ones are returned too, deliberately. "The user taps the chip again
    after it committed" is a real delivery, and an owner that forgot the meal
    the moment it wrote it would hand that tap to the interpreter, which is
    where a duplicate meal comes from. Ownership ends when the operation is
    terminal AND stale, not the instant it commits.
    """
    row: Any
    interaction: Any
    #: The interpreter's own reading of the food, carried across the turn
    #: boundary so the answer turn PRICES rather than re-interprets. Losing it
    #: is how a clarified meal came back as a different food thirteen hours
    #: later.
    item: dict
    #: The language the QUESTION was asked in. Read back rather than
    #: re-detected, so a later answer cannot be judged by a different lexicon
    #: than the one that produced the chips.
    locale: str = "en"
    #: THE EXACT DECISION THIS OPERATION SHOWED. A universe may hold several;
    #: this names the one whose options the user actually read, so replay
    #: reconstructs that question rather than another valid one over the same
    #: candidates. Empty on operations opened before 3b.3.
    decision_id: str = ""
    candidate_set_id: str = ""
    #: FIELDS ALREADY ANSWERED, and the patch each one carries (B-1.5).
    #:
    #: One item can raise several independent material fields, and a user may
    #: answer them across separate turns. Held here, keyed by `field_id`, so
    #: an answer given two turns ago is applied at commit rather than
    #: remembered by the screen — a client that reloads, or a second device,
    #: must see the same partially-answered operation.
    #:
    #: KEYED BY FIELD, NOT APPENDED. Answering the same field twice is a
    #: correction, not a second answer: the map holds the LATEST patch per
    #: field, so readiness counts fields and changing your mind about the
    #: portion cannot complete a question that never asked about preparation.
    answered: dict = dc_field(default_factory=dict)
    #: WHEN WE SHOWED THE QUESTION, application-stamped. `None` on operations
    #: opened before the stamp existed; `asked_at` falls back for those.
    asked_at_stamp: Any = None
    #: WHICH ROLLOUT OWNED THIS OPERATION, read back rather than re-derived.
    #: Empty on operations opened before it was persisted — and `-` in a metric
    #: is honest for those, where a freshly-derived label would be a claim about
    #: today's rollout attached to yesterday's operation.
    cohort: str = ""

    @property
    def expired(self) -> bool:
        """Past its `expires_at`, and therefore no longer entitled to claim a
        message that is not addressed to it.

        `expires_at` was written and never read: an awaiting operation owned
        the lane for as long as it existed, so a question nobody answered
        consumed the user's NEXT meal as its answer — chicken committed, the
        oatmeal lost, "Logged" said out loud. The settled-window data loss
        again, through a different door.

        NOT a reason to refuse an answer. Someone who replies late is still
        answering, and dropping that is its own silent loss. This only removes
        the operation's claim on messages that were never addressed to it —
        the same discriminator settlement already uses.
        """
        from core.clock import now as _now
        expires = getattr(self.row, "expires_at", None)
        return expires is not None and expires < _now()

    @property
    def disposition(self) -> "OwnershipDisposition":
        """WHAT THIS OPERATION IS DOING, as a typed value rather than as three
        booleans a caller has to combine correctly."""
        if not self.awaiting:
            return OwnershipDisposition.SETTLED
        return (OwnershipDisposition.EXPIRED if self.expired
                else OwnershipDisposition.HOLDING)

    @property
    def claims_unaddressed_messages(self) -> bool:
        """The ONE thing expiry changes. An addressed answer is still accepted
        in every disposition; only the claim on messages that were not meant
        for this question is withdrawn."""
        return self.disposition is OwnershipDisposition.HOLDING

    @property
    def operation_id(self) -> str:
        return self.row.operation_id

    @property
    def revision(self) -> int:
        return int(self.row.revision or 0)

    @property
    def status(self) -> str:
        return str(self.row.status or "")

    @property
    def asked_at(self):
        """When the QUESTION was sent. Latency and abandonment are properties
        of the gap between two turns, and only the row spans it — deriving
        either from anything the answer turn holds would measure the answer
        turn instead.

        THE STAMP, NOT THE ROW'S BIRTHDAY. `row.created_at` is
        `server_default=func.now()`, and Postgres `now()` is
        `transaction_timestamp()` — the time the enclosing TRANSACTION began.
        The insert rides the turn's transaction, which opens before the
        interpreter's model call, so `created_at` predates the question by
        however long interpretation took. Measured 2026-08-08: 8.3 s of a
        10.9 s "user answer latency" was ours, and abandonment thresholds
        derived from it fire early on exactly the slowest turns.

        Falls back to `created_at` for operations opened before the stamp
        existed: an older row's approximate answer beats no answer, and the
        error is bounded by that turn's own duration.
        """
        if self.asked_at_stamp is not None:
            return self.asked_at_stamp
        return self.row.created_at

    @property
    def awaiting(self) -> bool:
        return self.status == AWAITING

    @property
    def readable(self) -> bool:
        """False when the stored payload could not be decoded. The operation
        still OWNS the meal — the turn repairs, it does not fall back."""
        return self.interaction is not None


class _AnswerOperation:
    """The operation identity a settling commit claims.

    The row carries the revision it is AT; the commit belongs to the revision
    the answer PRODUCES, and the claim is `(operation_id, revision)`. Passing
    the row unchanged would claim the pre-answer revision, so a second, later
    answer to the same operation would collide with the first instead of
    forming its own claim.
    """

    def __init__(self, row, revision: int):
        self.id = row.operation_id
        self.revision = int(revision)
        self.user_id = int(row.user_id)
        self.source_turn_id = row.source_turn_id or ""


def _encode(interaction, interpreter_item: dict, locale: str,
            decision_id: str = "", candidate_set_id: str = "",
            asked_at: str = "", cohort: str = "", fingerprint: str = "",
            capability: str = "") -> str:
    if not isinstance(interpreter_item, dict):
        # NAMED, not coerced. `build_interaction` takes the STAGED item and
        # this takes the INTERPRETER's dict; they are different objects about
        # the same food, and a silent str() here would store a repr that the
        # answer turn could not price from.
        raise TypeError(
            f"the pending payload carries the interpreter's item dict, got "
            f"{type(interpreter_item).__name__} — the staged item goes to "
            f"build_interaction, not here")
    return json.dumps({
        "schema_version": B1_PAYLOAD_VERSION,
        "slice": "b1_quantity",
        # ⛔ THE FINGERPRINT AS WRITTEN, WITH THE RULES THAT WROTE IT *(P17
        # Phase 2)*. A reuse used to RECOMPUTE the stored payload under
        # TODAY's canonicalisation and compare that to today's fingerprint —
        # so a change to the rules (a field entering "meaning", a different
        # float form) would silently re-judge yesterday's row as if it had
        # been written under the new rule. The version and the digest are
        # persisted; a row written under another version cannot be compared
        # at all, and refuses rather than being reinterpreted.
        "fingerprint_version": FINGERPRINT_VERSION,
        "fingerprint": fingerprint,
        # WHAT THE CLIENT COULD DO WHEN THE QUESTION WAS ASKED. Rendering
        # depends on it (chips in the sentence, or not), so a reuse must read
        # the capability the ask was BUILT for, not the one this retry
        # happens to arrive with.
        "capability": capability or "",
        "interaction": interaction.to_payload(),
        "item": interpreter_item,
        # THE LANGUAGE THE QUESTION WAS ASKED IN, pinned to the operation.
        # The answer arrives on a later turn, possibly a later day, and must
        # be read under the same language context — re-detecting it from a
        # two-word reply ("6 oz") is a guess with a destructive command
        # behind it.
        "locale": locale,
        # WHICH QUESTION THIS OPERATION ASKED, not merely which universe it
        # could have asked from. One immutable set may hold several decisions
        # — Telegram and iOS, a newer selector, a different slot count — all
        # legitimate. Resolving by set alone on the answer turn could return a
        # different valid decision over the same universe, which is a true
        # statement about the system and a false one about this turn.
        "decision_id": decision_id,
        "candidate_set_id": candidate_set_id,
        # WHEN THE QUESTION WAS SENT, stamped by the application at the moment
        # we show it — NOT `row.created_at`.
        #
        # `created_at` is `server_default=func.now()`, and Postgres `now()` is
        # `transaction_timestamp()`: it returns when the TRANSACTION began, not
        # when the row was inserted. This INSERT rides the turn's existing
        # transaction, which opened before the interpreter's model call, so the
        # row was stamped 8.3 s before the user could see anything. Measured
        # 2026-08-08: `latency_ms=10894` for an answer given 2,560 ms after the
        # chips appeared — 76% of the reported "user latency" was our backend.
        #
        # `ONE_CLOCK_MIGRATION` settled WHICH clock is authoritative. It did not
        # cover the database freezing `now()` for the length of a transaction,
        # which is a different failure and needs a different stamp.
        "asked_at": asked_at,
        # WHICH ROLLOUT PUT THIS USER ON THE CANONICAL PATH, pinned to the
        # operation because the ANSWER turn cannot re-derive it.
        #
        # `b1_shown` carried `cohort=allowlist`; `b1_answered` and
        # `b1_committed` carried `cohort=-`, because nothing persisted it and
        # `OwnedOperation` had no such attribute for the answer turn to read.
        # So the funnel could count asks per cohort and neither answers nor
        # commits — it broke at the conversion step, which is the only step
        # promotion asks about ("100% of eligible turns canonical under the
        # rollout cohort").
        #
        # PINNED, NOT RE-READ, for the same reason `locale` is: the answer can
        # arrive days later, and a rollout that moved in between would relabel
        # an operation that was decided under the old one.
        "cohort": cohort,
    })


class PriorAskNotReleased(RuntimeError):
    """A prior awaiting operation for this user could not be released before
    opening a new one. Non-mutating; the caller must not insert."""


class OpenedElsewhere(RuntimeError):
    """The insert lost a race and the operation now awaiting for this user is
    NOT this one (a different turn, so a different product's question) — or
    this operation id exists in a non-reusable state, or it exists with a
    DIFFERENT semantic payload (same turn id, different snapshot/question).
    The caller must not present the other operation as its own; it refuses.
    Never legacy: a canonical ask that lost to another canonical ask must not
    become a legacy question beside it."""


class OpenResult:
    """⛔ THE TYPED RESULT OF `open_operation` *(review of 2db22e1)*.

    `created`  this call inserted the row; `interaction` is the one it built.
    `reused`   the row already existed (same turn retry, or a lost insert
               race to the SAME operation) — and its persisted semantic
               payload FINGERPRINT-MATCHES what this call would have stored.
               `interaction` is the STORED one, decoded from the row, so the
               caller renders what persisted — never the object it just
               built, which is how snapshot A could persist while B rendered.

    A reuse whose stored payload does NOT match is not a reuse; it is
    `OpenedElsewhere`, whatever the operation id says."""

    __slots__ = ("operation_id", "created", "interaction", "item",
                 "revision", "fingerprint", "locale", "cohort", "capability")

    def __init__(self, *, operation_id: str, created: bool, interaction,
                 item: dict, revision: int, fingerprint: str,
                 locale: str = "en", cohort: str = "", capability: str = ""):
        self.operation_id = operation_id
        self.created = created
        self.interaction = interaction
        self.item = dict(item or {})
        self.revision = int(revision or 0)
        self.fingerprint = fingerprint
        # ⛔ EVERY RENDERING FACT A CONSUMER NEEDS *(Danny)*: a reused request
        # renders ENTIRELY from persisted state — the language the question
        # was asked in and the cohort it was asked under are on the row, not
        # on the retry.
        self.locale = locale
        self.cohort = cohort
        #: the client capability the question was BUILT for — rendering
        #: depends on it, so a reuse renders under the stored one
        self.capability = capability or ""

    @property
    def reused(self) -> bool:
        return not self.created


#: The fingerprint's serialisation contract, VERSIONED. A change to how the
#: body is canonicalised (key order, float form, a field added to what counts
#: as "meaning") bumps this, so a fingerprint computed under the old rule can
#: never silently equal one computed under the new — they differ in the prefix
#: before they differ in the hash.
FINGERPRINT_VERSION = "fp1"


class FingerprintUnreadable(RuntimeError):
    """The persisted payload cannot be fingerprinted (unreadable JSON, an
    interaction that does not decode, a non-canonical value). FAIL CLOSED: a
    reuse that cannot prove it matches is not a reuse."""


def _canonical_json(obj) -> str:
    """Canonical serialisation for the fingerprint: sorted keys, no
    whitespace, ASCII-escaped, and NO lossy fallback — a value JSON cannot
    represent is an error, not `str()`'d into something that happens to
    compare equal."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def semantic_fingerprint(interaction, interpreter_item: dict) -> str:
    """What an ask MEANS, hashed: the wire interaction (question, fields,
    option ids and patches) and the interpreter item (food, quantity, and for
    a bound ask the product_evidence_id). Two asks with the same operation id
    and different fingerprints are two different questions, and only one of
    them persisted. Canonical and versioned (see FINGERPRINT_VERSION); raises
    FingerprintUnreadable rather than returning a guess."""
    import hashlib

    try:
        body = _canonical_json({"v": FINGERPRINT_VERSION,
                                "interaction": interaction.to_payload(),
                                "item": dict(interpreter_item or {})})
    except (TypeError, ValueError) as exc:
        raise FingerprintUnreadable(
            f"payload is not canonically serialisable: {exc}") from exc
    return f"{FINGERPRINT_VERSION}:" + hashlib.sha256(
        body.encode("utf-8")).hexdigest()[:24]


class StoredFingerprintVersionMismatch(RuntimeError):
    """The persisted operation was fingerprinted under DIFFERENT rules than
    this process uses. Not comparable — and recomputing it under today's
    rules would be exactly the silent reinterpretation the version exists to
    prevent. FAIL CLOSED: refuse the reuse."""


def _stored_open_result(row, *, created: bool, expect_user_id: int,
                        expect_turn_id: str,
                        expect_operation_id: str) -> "OpenResult":
    """Decode a persisted row into the OpenResult the caller renders from.

    ⛔ OWNERSHIP IS VERIFIED, NOT ASSUMED *(Danny)*: the row must carry THIS
    operation id and belong to THIS user, THIS domain and THIS turn — an
    operation id is derived from (user, turn), but a row reached by id is
    still checked against the request before anything in it is rendered, and
    a request that cannot state its turn cannot verify ownership at all.

    ⛔ THE STORED PAYLOAD IS READ STRICTLY *(P17 Phase 2)*:
      · `schema_version` must be the version this code writes;
      · `item` must be PRESENT and a dict — `data.get("item") or {}` turned
        `0`, `""`, `[]` and `null` into an empty item that then passed an
        isinstance check and rendered as a question about nothing;
      · the FINGERPRINT is read from the row, with the version that produced
        it. A different version is `StoredFingerprintVersionMismatch`; the
        same version is re-derived and must equal what was stored, which is
        an integrity check on the payload itself.

    Unreadable -> FingerprintUnreadable, never a partial result."""
    from core.semantics import ClarificationInteraction

    if str(getattr(row, "operation_id", "") or "") != str(expect_operation_id):
        raise OpenedElsewhere(
            f"row carries operation {row.operation_id!r}, not "
            f"{expect_operation_id!r}")
    if int(getattr(row, "user_id", -1)) != int(expect_user_id):
        raise OpenedElsewhere(
            f"operation {row.operation_id} belongs to user {row.user_id}, "
            f"not {expect_user_id}")
    if str(getattr(row, "domain", "") or "") != DOMAIN:
        raise OpenedElsewhere(
            f"operation {row.operation_id} is domain {row.domain!r}, not {DOMAIN!r}")
    if not expect_turn_id:
        raise OpenedElsewhere(
            f"operation {row.operation_id} cannot be verified: the request "
            f"states no source turn")
    if str(getattr(row, "source_turn_id", "") or "") != expect_turn_id:
        raise OpenedElsewhere(
            f"operation {row.operation_id} was opened on turn "
            f"{row.source_turn_id!r}, not {expect_turn_id!r}")
    try:
        data = json.loads(row.canonical_payload or "{}")
        if not isinstance(data, dict):
            raise ValueError("stored payload is not an object")
        if data.get("slice") != "b1_quantity":
            raise ValueError(f"slice {data.get('slice')!r} is not b1_quantity")
        stored_schema = data.get("schema_version")
        if stored_schema != B1_PAYLOAD_VERSION:
            raise ValueError(
                f"schema_version {stored_schema!r} is not "
                f"{B1_PAYLOAD_VERSION!r} — this code cannot read it")
        interaction = ClarificationInteraction.from_payload(data.get("interaction") or {})
        item = data.get("item")
        if not isinstance(item, dict):
            raise ValueError(
                f"stored item is {type(item).__name__}, not a dict")
    except FingerprintUnreadable:
        raise
    except Exception as exc:                             # noqa: BLE001
        raise FingerprintUnreadable(
            f"stored payload for {row.operation_id} is unreadable: "
            f"{type(exc).__name__}: {exc}") from exc

    stored_version = str(data.get("fingerprint_version") or "")
    stored_fp = str(data.get("fingerprint") or "")
    if not stored_version or not stored_fp:
        raise StoredFingerprintVersionMismatch(
            f"operation {row.operation_id} stores no fingerprint — it was "
            f"written before the fingerprint was persisted and cannot be "
            f"proved to mean the same thing")
    if stored_version != FINGERPRINT_VERSION:
        raise StoredFingerprintVersionMismatch(
            f"operation {row.operation_id} was fingerprinted under "
            f"{stored_version!r}; this process writes {FINGERPRINT_VERSION!r} "
            f"— not comparable, and not recomputed under the new rules")
    recomputed = semantic_fingerprint(interaction, item)
    if recomputed != stored_fp:
        raise FingerprintUnreadable(
            f"operation {row.operation_id} does not match the fingerprint it "
            f"stores (stored {stored_fp}, payload {recomputed})")
    return OpenResult(operation_id=row.operation_id, created=created,
                      interaction=interaction, item=item,
                      revision=int(row.revision or 0), fingerprint=stored_fp,
                      locale=str(data.get("locale") or "en"),
                      cohort=str(data.get("cohort") or ""),
                      capability=str(data.get("capability") or ""))


async def _release_prior_awaiting(db, *, user, keep: str) -> None:
    """Release every awaiting/active operation this user holds, except `keep`
    (the operation being (re)opened — a same-turn retry finds its own row).
    Clock-expired rows are marked EXPIRED (what the sweep would do); live rows
    are CANCELLED as superseded. Read under FOR UPDATE where the engine has
    it, so two workers releasing at once serialise on the rows rather than
    both proceeding to insert."""
    from datetime import timezone

    from core import pending_repository as repo
    from core.clock import now as _now

    # the row lock is the repository's SHARED primitive; this module takes no
    # lock of its own (tests/test_two_answers_at_once_do_not_lose_one)
    rows = await repo.locked_awaiting_for_user(
        db, user_id=int(user.id), domain=DOMAIN, exclude_operation_id=keep)
    now = _now()
    for row in rows:
        exp = row.expires_at
        if exp is not None and exp.tzinfo is None and now.tzinfo is not None:
            exp = exp.replace(tzinfo=timezone.utc)
        how = "expired" if (exp is not None and exp <= now) else "superseded"
        try:
            if how == "expired":
                outcome = await repo.mark_expired(
                    db, operation_id=row.operation_id,
                    expected_revision=int(row.revision or 0))
            else:
                outcome = await repo.save_revision(
                    db, operation_id=row.operation_id,
                    expected_revision=int(row.revision or 0),
                    status=CANCELLED, storage_status="closed",
                    terminal_reason="superseded by a newer ask"[:200])
        except Exception as exc:                         # noqa: BLE001
            raise PriorAskNotReleased(
                f"could not release {row.operation_id}: {type(exc).__name__}"
            ) from exc
        # ⛔⛔ THE REPOSITORY REPORTS, IT DOES NOT RAISE *(review of 22b9e7a)*.
        # `save_revision` / `mark_expired` return SaveOutcome(ok=False,
        # conflict=True) when another writer moved the row first; the first
        # cut read only exceptions, logged "released", and proceeded to
        # INSERT beside a row it had not released — the second awaiting ask
        # the constraint exists to forbid, arriving through a value the code
        # never looked at. A not-ok outcome is a refusal, by contract.
        if not getattr(outcome, "ok", False):
            raise PriorAskNotReleased(
                f"could not release {row.operation_id}: "
                f"{'revision conflict' if getattr(outcome, 'conflict', False) else 'not saved'}"
                f" (revision {getattr(outcome, 'revision', '?')})")
        logger.info("event=b1_prior_released operation=%s how=%s for=%s",
                    row.operation_id, how, keep)


async def open_operation(db, *, user, interpreter_item: dict, interaction,
                         turn_id: str, cohort: str = "",
                         locale: str = "en", decision_id: str = "",
                         candidate_set_id: str = "",
                         capability: str = "") -> "OpenResult":
    """Take ownership of this meal. Call ONLY after the rollout gate said yes.

    `interpreter_item` is the interpreter's own reading — the food name and
    its per-portion macros — stored so the ANSWER turn prices instead of
    re-interpreting. That re-interpretation is the 16-second cheesecake
    re-priced a turn later, and the sopressata that came back as "Dollar pizza
    slices" thirteen hours on.

    `locale` is RESOLVED BY THE CALLER, not read from `user` here. Reaching
    for `user.preferences` inside this module triggers a lazy relationship
    load in a sync context (MissingGreenlet), and more importantly it makes
    this module a second place that decides what language a user writes in.
    `core.language.command_locale` owns that; the turn that already holds the
    loaded preferences calls it and passes the answer.

    Persisted before the reply is sent, because ownership that exists only in
    the reply is ownership a restart loses — and the user would then answer a
    question no row remembers.
    """
    from core import pending_repository as repo
    from core.canonical_writer import operation_id_for

    from datetime import timedelta

    from sqlalchemy.exc import IntegrityError

    from core.clock import now as _now

    operation_id = operation_id_for("chat_quantity", user.id, turn_id)
    # ⛔⛔ ONE AWAITING OPERATION PER USER, ENFORCED WHERE THE INSERT IS
    # *(CF5c-B3, migration oneask001)*. The database holds a partial unique
    # index over (user_id, domain) for awaiting/active rows — the constraint
    # the code used to merely check for. Production already satisfies it
    # (0 users with >1 awaiting row, 0 unswept-expired rows). Three things
    # follow, ALL at this seam because it is the one insert site for every
    # B-1 ask, bound or ordinary *(review of 22b9e7a: "same op id -> same
    # ask" was true only for the product-bound wrapper)*:
    #
    #   REUSE    the SAME operation id already awaiting -> return it. A same-
    #            turn retry (a resend, a double-tap) must not release its own
    #            ask and re-insert — that is how a retry cancelled itself.
    #   RELEASE  a DIFFERENT prior must be released first — a clock-expired
    #            one marked expired (what the sweep would do), a live one
    #            cancelled as superseded. The newer ask is the user's current
    #            intent. If it cannot be released (the repository says so by
    #            VALUE: SaveOutcome.ok=False) the insert is not attempted.
    #   RACE     the insert lost to another worker -> reuse ONLY if the
    #            winner IS this operation (same turn, same id). A winner from
    #            a DIFFERENT turn is a different product's question, and
    #            returning it would render product B's ask in product A's
    #            reply — `OpenedElsewhere`, and the caller refuses.
    mine = semantic_fingerprint(interaction, interpreter_item)   # may raise FingerprintUnreadable
    uid = int(user.id)            # captured early: a rollback below expires `user`

    def _reuse_if_same(row, *, why: str) -> "OpenResult":
        """The row exists for THIS operation id. It is a reuse ONLY if it is
        awaiting, belongs to THIS user/domain/turn, AND its persisted
        semantics match what this call would have stored — same question,
        same item, same snapshot. The operation id is derived from (user,
        turn), and two requests on one turn with different snapshots share
        it; the id alone proves nothing. An unreadable stored payload is
        FingerprintUnreadable — a refusal, not a reuse."""
        if not (row.status == AWAITING and row.storage_status == "active"):
            raise OpenedElsewhere(
                f"operation {operation_id} exists but is {row.status}/"
                f"{row.storage_status} — not reusable")
        stored = _stored_open_result(row, created=False, expect_user_id=uid,
                                     expect_turn_id=turn_id,
                                     expect_operation_id=operation_id)
        if stored.fingerprint != mine:
            raise OpenedElsewhere(
                f"operation {operation_id} is awaiting with a DIFFERENT "
                f"semantic payload (stored {stored.fingerprint}, mine {mine}) "
                f"— {why}")
        logger.info("event=b1_open_reused operation=%s how=%s fingerprint=%s",
                    operation_id, why, mine)
        return stored

    existing = await repo.load_operation(db, operation_id)
    if existing is not None:
        return _reuse_if_same(existing, why="same turn, same ask")
    await _release_prior_awaiting(db, user=user, keep=operation_id)
    payload = _encode(interaction, interpreter_item, locale or "en",
                      decision_id=decision_id,
                      candidate_set_id=candidate_set_id,
                      asked_at=_now().isoformat(),
                      cohort=cohort or "", fingerprint=mine,
                      capability=capability or "")
    try:
        row = await repo.create_operation(
            db, operation_id=operation_id, user_id=uid, status=AWAITING,
            storage_status="active", domain=DOMAIN, source_turn_id=turn_id,
            payload=payload,
            # AN UNANSWERED QUESTION MUST NOT LIVE FOREVER. Without this the
            # row stays `awaiting_answer` indefinitely and a message weeks
            # later is read as an answer to a meal the user has long forgotten.
            expires_at=_now() + timedelta(minutes=ASK_TTL_MINUTES))
    except IntegrityError as exc:
        await db.rollback()
        winner = await repo.load_operation(db, operation_id)
        if winner is None:
            # a DIFFERENT operation holds the user (the partial unique index
            # fired): NOT ours to return, and never legacy
            raise OpenedElsewhere(
                f"insert of {operation_id} lost the race to another awaiting "
                f"operation for user {uid}") from exc
        # the SAME operation id landed from another worker — reuse ONLY if it
        # persisted what we would have (same snapshot, same question)
        try:
            return _reuse_if_same(winner, why="lost the insert race to myself")
        except (OpenedElsewhere, StoredFingerprintVersionMismatch):
            raise
        except Exception as e:                           # noqa: BLE001
            raise OpenedElsewhere(
                f"lost the race and the winner's payload is unreadable: "
                f"{type(e).__name__}") from e
    result = OpenResult(operation_id=operation_id, created=True,
                        interaction=interaction, item=dict(interpreter_item),
                        revision=0, fingerprint=mine,
                        locale=locale or "en", cohort=cohort or "",
                        capability=capability or "")
    from core import b1_metrics
    b1_metrics.shown(operation_id=operation_id, user_id=uid, cohort=cohort,
                     locale=locale or "en",
                     field=interaction.groups[0].fields[0])
    # THE JOIN KEY, ON THE ASK SIDE. The answer arrives on a different turn with
    # a different `turn_id`, so without this the two halves of one operation
    # cannot be joined from the trace stream alone.
    try:
        from core import food_trace as _ft
        _ft.note(operation_id=operation_id)
    except Exception:
        pass
    return result


#: How long an unanswered question stays answerable. Past it the operation
#: expires rather than lingering as an open row a later turn trips over.
ASK_TTL_MINUTES = 180


#: HOW A CHANNEL CAN CARRY AN ANSWER BACK. These are not equivalent and must
#: never be described as equivalent — the difference is what the answer is
#: BOUND to.
#:
#:   ID_ADDRESSED   the reply carries operation_id + revision + field_id +
#:                  option_id. The answer is bound to the exact question, and
#:                  a stale or foreign one is detectable.
#:
#:   LABEL_TEXT     the reply carries the option's rendered words and nothing
#:                  else. RESTRICTED, because binding is inferred: we match
#:                  the text against the open operation's stored options. Two
#:                  identical labels on two live operations are
#:                  indistinguishable, a label typed by hand is
#:                  indistinguishable from a press, and staleness cannot be
#:                  detected at all — the text of last turn's chip looks
#:                  exactly like this turn's.
#:
#: B-1 accepts LABEL_TEXT deliberately: it is what proves the wire on real
#: traffic without shipping Swift. It is not the chip path, its production
#: evidence does not substitute for the chip path's, and B-1b exists because
#: of that.
ID_ADDRESSED = "id_addressed"
LABEL_TEXT = "label_text"

#: THE GENERATION OF THE QUESTION ITSELF — wording and option selection, as the
#: user experiences them. Follows `core/food_ledger`'s existing convention
#: (INTERPRETER_VERSION / POLICY_VERSION / RENDERER_VERSION) rather than
#: inventing a second one.
#:
#: WHY THIS IS NOT `revision`. The operation's revision tracks SEMANTIC state,
#: and a repair deliberately does not bump it — so "v1 wording produced 30
#: repairs, v2 produced 9" is invisible to it. That comparison is the reason
#: D4.1 exists, and without a stamp it becomes unrecoverable the moment the
#: wording changes, because the observations already collected cannot say which
#: question they answered.
#:
#: BUMP IT when `_introduction()`, `CanonicalAsk.ask_copy()`, or the option
#: selection/labelling in `skills/nutrition/quantity_clarification` changes what
#: the user reads. Not when the plumbing beneath them changes.
QUESTION_VERSION = "b1_quantity_q2"

#: Channels whose chips the SERVER renders. Telegram and iMessage have no
#: client-side chip parser at all, so the canonical payload is readable by
#: construction — but their reply carries only the label.
_CHANNEL_CAPABILITY = {
    "telegram": LABEL_TEXT,
    "imessage": LABEL_TEXT,
    "bluebubbles": LABEL_TEXT,
    "sms": LABEL_TEXT,
    # ios: ADDED 2026-08-06, when the build that honours it existed and not
    # before. `arnie-ios@48cb626` decodes `interaction`, renders the options
    # from it, and answers `POST /chat/answer` with the four ids and a stable
    # `client_message_id`.
    #
    # THE ENTRY IS THE CAPABILITY CLAIM. Writing it earlier would have
    # promised behaviour no software had, and B-1 would have sent iOS a
    # canonical question the client could only read as prose — which is the
    # sentence parser surviving inside its own replacement.
    "ios": ID_ADDRESSED,
}


def channel_capability(source: Optional[str]) -> Optional[str]:
    """How this channel can answer, or None if it cannot."""
    return _CHANNEL_CAPABILITY.get(str(source or "").strip().lower())


#: Values that are a MODALITY, not a channel. Passing one of these is the
#: mistake that cost a production round: `source_type` carries text/voice/
#: photo alongside real origins, so `source_type or platform` yields "text"
#: for a Telegram message and matches no channel at all. Named here so the
#: error is loud rather than a silent decline — the same modality-vs-channel
#: conflation `feedback_arnie_platform_mislabel` already records.
_MODALITIES = frozenset({"text", "voice", "photo", "image"})


def client_renders_interactions(source: Optional[str]) -> bool:
    """Can this client read the canonical payload at all?

    Takes the CHANNEL (`platform`), never `source_type`.

    AN EXCLUSION, NOT A DOWNGRADE. A client that cannot is ineligible for B-1
    and stays wholly legacy. The alternative — sending it the canonical
    question rendered as prose — would keep the sentence parser alive INSIDE
    the replacement, which is the exact defect B-1 exists to delete, and it
    would block deleting `QuickReplyEngine.swift` at promotion.
    """
    key = str(source or "").strip().lower()
    if key in _MODALITIES:
        # LOUD, not a silent False. A modality here means the caller passed
        # `source_type`, and the symptom — every turn declining
        # `client_incapable` on a channel that is capable — looks exactly
        # like a correct exclusion.
        logger.error(
            "event=b1_capability_misused source=%s — that is a MODALITY, not "
            "a channel; pass `platform`. B-1 will decline every turn until "
            "this is fixed.", key)
        return False
    return channel_capability(source) is not None


@dataclass(frozen=True)
class CanonicalAsk:
    """A question B-1 owns, with the durable state already written."""
    operation_id: str
    revision: int
    interaction: Any
    locale: str
    cohort: str
    #: WHAT THIS CLIENT CAN DO, resolved ONCE by the lane gate and carried.
    #:
    #: Three things consume it — the selection surface, the persisted decision,
    #: and the rendered sentence — and each used to derive it separately. That
    #: is how a Telegram question came to be RECORDED as `id_addressed` while
    #: being SHOWN as label text: `selection_context` read a bool that meant
    #: "capable of anything", and `conversation.py` recomputed the real value
    #: from the platform for the copy. Both were reading the same fact and
    #: only one was right, and the persisted record was the wrong one.
    capability: Optional[str] = None

    def wire_payload(self) -> dict:
        """What the client receives. IDs, not meanings (C11)."""
        return wire_payload_for(self.interaction, locale=self.locale)


    def legacy_questions(self) -> list:
        """The same field, in the shape today's clients already read.

        A PROJECTION of the canonical interaction, not a second producer:
        both rows come from one field, so they cannot disagree. It exists so
        an older client keeps working during the rollout — and it dies with
        `QuickReplyEngine.swift` at B-1 promotion.
        """
        field = self.interaction.groups[0].fields[0]
        return [{"item": self.interaction.groups[0].label or None,
                 "text": self.interaction.introduction,
                 "options": [o.label for o in field.options]}]

    def ask_facts(self) -> "CanonicalAskFacts":
        """THE FACTS A RENDERER MAY READ, and nothing else.

        The mirror of `b1_answer_turn.facts_for()` on the ask side, and for the
        same reason: a renderer holding the interaction is a renderer that can
        re-derive the question, and a renderer that can re-derive the question
        is a second owner of it. Voice, when it arrives, renders THESE.
        """
        field = self.interaction.groups[0].fields[0]
        return CanonicalAskFacts(
            introduction=self.interaction.introduction,
            option_labels=tuple(o.label for o in field.options),
            attribute=getattr(field.attribute, "value", str(field.attribute)),
            allows_free_text=True)

    def ask_copy(self, *, capability: Optional[str] = None) -> str:
        """The DETERMINISTIC question, rendered from `ask_facts()` only.

        WHY THIS EXISTS. B-1 stored `introduction="How much Chicken breast?"`
        with options `6 oz` / `16 oz`, and production asked the user "How was
        the chicken breast cooked? Grilled, baked, or fried?" — because the
        ownership block rewrote `questions` and `options` and left `_sft["text"]`
        as the interpreter had composed it. The canonical question was written
        to the database and never spoken. The user then answered a question we
        had not asked, and the quantity parser was handed a preparation.

        CAPABILITY DECIDES WHETHER THE OPTIONS ARE IN THE SENTENCE, because on
        Telegram and iMessage the sentence IS the interface — there are no
        chips, so options omitted here are options that do not exist. A client
        that renders them itself (iOS, from B-1b) gets the introduction alone,
        or the same list appears twice.

        No model call. `copy_for`'s reasoning applies unchanged: a sentence
        that can drift from the field it describes is the defect this migration
        removes, and B-1's presentation boundary asks for the deterministic
        fallback now and voice before broad rollout.
        """
        # THE ASK'S OWN CAPABILITY, not a value the caller re-derived. The
        # parameter stays for tests that render one ask both ways, but the
        # default is no longer `LABEL_TEXT` — a silent default here is what
        # let a caller "forget" and still get a plausible sentence, which is
        # indistinguishable from asking correctly.
        capability = capability if capability is not None else self.capability
        facts = self.ask_facts()
        question = (facts.introduction or "").strip() or "How much was that?"
        if capability != LABEL_TEXT or not facts.option_labels:
            return question
        # LABELS ARE PASSED THROUGH, NEVER PARSED. "2 oz, 4 oz, or 8 oz" reads
        # worse than "2, 4, or 8 oz", and collapsing it would mean reading the
        # labels back to find a shared unit — the one thing the option contract
        # forbids, because a label that can be re-read can be re-interpreted.
        labels = list(facts.option_labels)
        if len(labels) == 1:
            offered = labels[0]
        elif len(labels) == 2:
            offered = f"{labels[0]} or {labels[1]}"
        else:
            offered = f"{', '.join(labels[:-1])}, or {labels[-1]}"
        # ALL THREE ROUTES, SAID OUT LOUD. A route the user cannot see is a
        # route whose usage rate reads zero — and we would then conclude
        # something about THEM from our own silence.
        #
        #   pick one      the offered labels
        #   your own      free text (C15)
        #   "not sure"    ESTIMATE — a real command, fully implemented, and
        #                 until now advertised NOWHERE. It takes the middle
        #                 offered option re-provenanced to MODE_DEFAULT, so
        #                 the estimate marker and disclosure survive onto the
        #                 committed row.
        #
        # "Not sure" is the literal phrase because it is the literal phrase
        # `answer_parsers` matches. Advertising wording the parser does not
        # accept would be worse than advertising nothing.
        return (f"{question} Roughly {offered} — or tell me. "
                f"Not sure? I'll estimate.")


def wire_payload_for(interaction, *, locale: str, only=None) -> dict:
    """The client's view of an interaction, optionally NARROWED TO SOME FIELDS.

    `only` is a set of field ids. It exists so a PARTIAL answer can hand back
    the fields STILL OPEN: the client would otherwise keep rendering the row it
    just answered, and the alternative — letting it work out which rows to drop
    — is the client deciding what the operation still needs. Readiness is
    server-owned, so what remains open is something the server SAYS rather than
    something the client infers.
    """
    keep = None if only is None else {str(f) for f in only}

    def _fields(group):
        return [f for f in group.fields
                if keep is None or f.field_id in keep]

    return {
            "operation_id": interaction.operation_id,
            "revision": interaction.revision,
            "interaction_id": interaction.interaction_id,
            "locale": locale,
            "groups": [{
                "event_id": g.event_id,
                "label": g.label,
                "fields": [{
                    "field_id": f.field_id,
                    "attribute": f.attribute.value,
                    "response_type": f.response_type.value,
                    # C15's FREE-TEXT ROUTE, ON THE WIRE. Without it a
                    # `single_select` tells the client "three chips and
                    # nothing else", and a user whose portion is not among
                    # them has no visible way to say so — the exact
                    # forced-"Other" failure the rollout metric exists to
                    # detect, shipped as a design instead of a bug. It is
                    # also what makes that metric measurable at all: "Other
                    # usage" is answers that arrived as text rather than as a
                    # stored option.
                    "allows_free_text": True,
                    # LABELS ONLY. The patch stays on the server; a tap sends
                    # `option_id` back and the meaning is loaded from storage,
                    # so the label can never travel as semantics.
                    "options": [{"option_id": o.option_id, "label": o.label}
                                for o in f.options],
                } for f in _fields(g)],
            } for g in interaction.groups if _fields(g)],
        }


@dataclass(frozen=True)
class CanonicalAskFacts:
    """What was asked, as facts rather than as a sentence.

    Frozen and label-only for the same reason `wire_payload` is: the patch and
    the option ids stay on the server, so nothing a renderer touches can travel
    back as semantics.
    """
    introduction: str
    option_labels: tuple
    attribute: str
    allows_free_text: bool


async def try_take_ownership(db, *, user, material: dict, turn_id: str,
                             channel: str,
                             locale: str = "en") -> Optional[CanonicalAsk]:
    """Decide whether B-1 owns this turn, and if so, take ownership durably.

    THE ONE PLACE THE PREDICATE IS EVALUATED. `food_turn` carries the material
    here rather than judging half of it, because a predicate with two owners
    drifts — and the half it could not see (client capability, locale, the
    rollout cohort) is the half that decides whether owning this turn is safe.

    ORDER MATTERS AND IS NOT INCIDENTAL:

        eligibility  ->  rollout gate  ->  candidates  ->  PERSIST  ->  return

    The gate is asked ONCE, here, before the row exists. Everything before the
    write may decline freely: nothing has been taken, so the turn simply
    proceeds as it does today. Everything after the write is owned, and
    `owning()` will find it no matter what the gate later says.

    Returning None is always safe. Raising is not, which is why the persist
    step is the last thing that can fail: a question sent with no durable row
    behind it is a question the user answers into a void.
    """
    from core.canonical_lane import canonical_food_enabled
    from skills.nutrition import quantity_clarification as qc

    # ONE GATE DECIDES LANE OWNERSHIP, and it is asked here, first, before any
    # material is examined. Cohort and client capability used to be decided in
    # two different places — the caller computed capability and passed it in,
    # this function asked the rollout gate — so no single place could be read
    # to find out what the system would do with a given user on a given
    # channel. `canonical_food_enabled` is now that place.
    lane = canonical_food_enabled(user_id=getattr(user, "id", None),
                                  channel=channel)
    if not lane.canonical:
        from core import b1_metrics
        b1_metrics.declined(user_id=getattr(user, "id", None),
                            reason=lane.reason, cohort=lane.cohort)
        return None

    decision = _MaterialDecision(material)
    verdict = qc.is_eligible(
        decision, message=material.get("message") or "",
        # THE LANE ALREADY PROVED THIS. `is_eligible` keeps its own clause as
        # defence in depth and is tested directly on it, but at runtime the
        # lane gate is the only decider — passing its verdict rather than a
        # second computation of the same fact is what makes that true.
        client_capable=lane.canonical,
        # Absent means "the caller did not say", and the only safe reading of
        # that is the pessimistic one. The pipeline branch fetches the shelf
        # and passes True; the interpreter branch does not and passes False.
        identity_evidence=bool(material.get("identity_evidence", False)))
    if not verdict.ok:
        from core import b1_metrics
        b1_metrics.declined(user_id=getattr(user, "id", None),
                            reason=verdict.reason.value)
        return None

    # THE COHORT GATE USED TO BE ASKED AGAIN HERE. It is not a second check;
    # it was the OTHER half of a decision with two owners, and it now lives
    # entirely in `canonical_food_enabled` above. Asking it twice in one
    # function is how the two halves would drift apart again.
    cohort = lane.cohort

    item = verdict.item
    interpreter_item = _interpreter_item_for(material, item)
    if not interpreter_item:
        from core import b1_metrics
        b1_metrics.declined(user_id=user.id, reason="no_interpreter_item",
                            cohort=cohort)
        return None

    from core.semantics import EvidenceContext

    # ONE FUNCTION OWNS THE ENTITY ID, and it is STAMPED INTO THE OPERATION.
    # Generation computes it from the staged item; the answer turn rebuilds
    # the evidence context from the stored row. If those two derived it
    # independently they would disagree the moment either changed, every
    # candidate would fail `applies_to`, and "not sure" would refuse in
    # production while every test passed — a silent downgrade to REPAIR with
    # no error anywhere.
    entity_id = qc._entity_id_for(item)
    interpreter_item = dict(interpreter_item)
    interpreter_item["entity_id"] = entity_id

    operation_id = _operation_id_for(user, turn_id)
    field = qc.quantity_field(operation_id=operation_id, revision=0, item=item)
    # THE UNIVERSE IS BUILT BEFORE ANYTHING IS SHOWN, and the decision is
    # taken over it — never over a list that was already reduced. Persisting
    # only what the user saw makes "history never appeared" read identically
    # whether the matcher found nothing or the selector dropped it.
    universe = await qc.generate(
        db, user_id=user.id, item=item,
        message=material.get("message") or "", operation_id=operation_id,
        revision=0, field_id=field.field_id,
        context=EvidenceContext(user_id=user.id,
                                canonical_entity_id=entity_id))
    options, decision_record = qc.reduce_universe(
        universe, field=field,
        # THE CAPABILITY THE LANE GATE RESOLVED, not a third derivation of it.
        #
        # This read `ID_ADDRESSED if client_capable else LABEL_TEXT`, and
        # `client_capable` is TRUE FOR TELEGRAM — it means "this client can
        # read the canonical payload at all", which every channel in the
        # capability table can. So a Telegram decision was recorded and made
        # under `surface=id_addressed`: the one channel that has no chips and
        # where the sentence IS the interface. Two DIFFERENT questions —
        # "capable of anything" and "capable of ids" — collapsed into one
        # bool, which is what having three derivations of one fact produces.
        context=qc.selection_context(capability=lane.capability,
                                     locale=locale),
        food_name=str(item.identity.canonical_name or ""))
    if not options:
        # No evidence, so no chips. B-1 declines rather than shipping a select
        # with nothing in it — the legacy ask is still a better question than
        # an empty canonical one, and C15 forbids the blank row either way.
        from core import b1_metrics
        b1_metrics.declined(user_id=user.id, reason="no_candidates",
                            cohort=cohort)
        return None

    # THE UNIVERSE IS DURABLE BEFORE THE QUESTION IS ASKED, and FAIL-CLOSED.
    #
    # Written before `open_operation`, so a failure here means no operation,
    # no option ids, no question — the turn simply proceeds as it does today
    # and nothing was taken. Everything before the ownership write may decline
    # freely; this is still before it.
    #
    # The alternative — ask first, persist after — produces exactly the state
    # this record exists to prevent: a user answering a question whose options
    # nothing can explain.
    from core import candidate_repository as universe_repo

    try:
        candidate_set_id = await universe_repo.save(db, decision_record,
                                                    domain=DOMAIN)
        decision_id = universe_repo.decision_id_for(decision_record)
    except Exception:
        logger.warning(
            "event=b1_universe_not_persisted operation=%s — declining rather "
            "than asking a question we could not explain afterwards",
            operation_id, exc_info=True)
        from core import b1_metrics
        b1_metrics.declined(user_id=user.id, reason="universe_not_persisted",
                            cohort=cohort)
        return None

    # THE CANONICAL LANE'S OWN DERIVATION STAGE, and the coordinator names no
    # field in it.
    #
    # This asked `qc.preparation_is_open(item)` — the interpreter's own
    # ambiguity and nothing else. Measured in production: for "I had some
    # chicken" the model identifies the food confidently and reports no
    # preparation uncertainty, so the field was reachable in tests and
    # unreachable in production. B-1.5 could not fire at all.
    #
    # Every registered field is now asked whether it is materially unresolved
    # and answers from EVIDENCE. A food-name rule here — "chicken is grilled or
    # fried" — would be domain logic in the coordinator, wrong for the first
    # food it did not list.
    #
    # RUNS HERE, AFTER THE LANE DECISION AND BEFORE ANYTHING IS PERSISTED, so
    # the staged result handed to legacy is untouched. Legacy asks exactly what
    # it asked yesterday; a shared derivation would be new food behaviour in a
    # frozen path.
    from core.semantic_fields import derive_unresolved
    from core.semantics import ClarificationAttribute

    # THE TURN'S AMBIENT CONTEXT — passing None resolves it, so this shares
    # with speculative enrichment. Constructing one here is what broke the
    # seam: two contexts, nothing shared, the free structured half unused.
    unresolved = await derive_unresolved(item)
    interaction = qc.build_interaction(
        operation_id=operation_id, revision=0, item=item, options=options,
        introduction=_introduction(item),
        ask_preparation=ClarificationAttribute.PREPARATION in unresolved)

    # ⛔ RENDER WHAT PERSISTED *(review of 2db22e1)*. `open_operation` returns
    # an OpenResult; on a reuse its `interaction` is the STORED one, decoded
    # from the row and fingerprint-checked against what this call built. The
    # first cut returned the locally built interaction whatever the seam did,
    # so a same-turn race could persist one question and render another.
    # `OpenedElsewhere` / `PriorAskNotReleased` PROPAGATE as canonical
    # refusals — `core.conversation` answers them in words; they must never
    # reach the blanket catch that falls to legacy, because one canonical ask
    # from the winner plus a legacy question from the loser is the single-
    # owner invariant lost ABOVE the database constraint.
    opened = await open_operation(db, user=user, interpreter_item=interpreter_item,
                                  interaction=interaction, turn_id=turn_id,
                                  cohort=cohort, locale=locale,
                                  decision_id=decision_id,
                                  candidate_set_id=candidate_set_id,
                                  capability=str(lane.capability or ""))
    # ⛔ P17 Phase 2 — the capability comes from the PERSISTED row too: on a
    # reuse the stored question is rendered under the capability it was built
    # for, not the one this retry arrived with.
    return CanonicalAsk(operation_id=opened.operation_id, revision=opened.revision,
                        interaction=opened.interaction,
                        locale=opened.locale, cohort=opened.cohort,
                        capability=opened.capability or lane.capability)


class _MaterialDecision:
    """`is_eligible` reads a decision's `staged_items`; this is that shape,
    rebuilt from what crossed the boundary. Not a mock — the staged items are
    the real objects, only the container is local."""

    def __init__(self, material: dict):
        self.staged_items = tuple(material.get("staged_items") or ())


def _operation_id_for(user, turn_id: str) -> str:
    from core.canonical_writer import operation_id_for

    return operation_id_for("chat_quantity", user.id, turn_id)


def _interpreter_item_for(material: dict, staged) -> dict:
    """The interpreter's row for the food being asked about.

    Matched on the staged item's ORDINAL first, because two servings of the
    same food in one turn share a name and differ only by position — and
    falling back to a name match there would price the wrong one. B-1 is
    single-item, so the fallback is exact-name and then the sole item.
    """
    items = [i for i in (material.get("items") or []) if isinstance(i, dict)]
    if not items:
        return {}
    ordinal = int(getattr(staged, "ordinal", 0) or 0)
    if 0 <= ordinal < len(items):
        return dict(items[ordinal])
    name = str(getattr(getattr(staged, "identity", None), "canonical_name", "")
               or "").strip().lower()
    for raw in items:
        if str(raw.get("food") or "").strip().lower() == name:
            return dict(raw)
    return dict(items[0]) if len(items) == 1 else {}


def _introduction(staged) -> str:
    """The question, in Arnie's voice, deterministically.

    STILL A TEMPLATE, and that is the point. A model composing this is exactly
    the defect that had production ask "How was the chicken breast cooked?"
    over a QUANTITY field — the wording drifted away from the thing being
    asked. The variable here is how well it reads, never what it asks.

    "HOW MUCH", NEVER "HOW MANY", is safe by predicate: B-1's eligibility
    requires the unresolved dimension to be MASS, so it is never asking about
    a countable thing. When B-1.5 widens that, this assumption widens with it.

    CASE FOLLOWS THE BRAND, NOT A GUESS. `canonical_name` arrives capitalized
    because it names a food ("Salmon", "White rice, steamed"), and dropping it
    mid-sentence unchanged reads like a form field. Arnie's voice is sentence
    case with proper nouns capitalized, so a generic food is lowercased here
    and a branded one is not — decided by `identity.brand` being set, which is
    a fact the interpreter supplies rather than something inferred from
    capitalisation.
    """
    identity = getattr(staged, "identity", None)
    label = ""
    # `describe()` owns "what to call this food" and guarantees the canonical
    # name is never dropped — the rule that stopped a question about "Royo
    # Everything Bagel" asking about the maker instead of the product.
    try:
        label = str(identity.describe() or "").strip()
    except Exception:
        label = ""
    if not label:
        label = str(getattr(identity, "canonical_name", "") or "").strip()
    if not label:
        return "How much was that?"
    if not (getattr(identity, "brand", None) or "").strip():
        label = label[0].lower() + label[1:]
        # THE QUALIFIER AFTER THE COMMA IS A LOG NAME, NOT A QUESTION.
        # "White rice, steamed" is exactly right on a row and reads as two
        # questions in a sentence ("How much white rice, steamed?"). Safe to
        # drop HERE and only here, because B-1's predicate admits exactly one
        # food event — so the head noun cannot be ambiguous between items, and
        # the user has just said what they ate. The committed row keeps the
        # full name; this is the question only.
        head = label.split(",", 1)[0].strip()
        if head:
            label = head
    return f"How much {label}?"


#: How long a settled operation still answers for its meal. A tap that arrives
#: after the commit inside this window is a REPLAY; outside it, the user is
#: plausibly talking about a new meal. Generous, because the failure it
#: prevents (a duplicate meal) is worse than the one it causes (a replay
#: answer to a genuinely new, identical meal, which idempotency also absorbs).
SETTLED_OWNERSHIP_MINUTES = 30


class OwnershipUnknown(RuntimeError):
    """THE LOOKUP ITSELF FAILED. Not "no operation owns this meal" — we do not
    know whether one does.

    The distinction is the whole point. `None` means the query ran and found
    nothing, so the turn proceeds legacy exactly as today. A raise means the
    query did not run, and treating that as `None` would hand a possibly-owned
    meal to the broad interpreter on a database blip — turning a transient
    error into a duplicate meal, silently, at exactly the moment nobody is
    watching. Two states cannot express three.

    The caller's only safe response is to log nothing and say so.
    """


async def owning(db, user) -> Optional[OwnedOperation]:
    """The canonical operation that owns this user's meal.

    TRI-STATE, deliberately:

        OwnedOperation   this meal is ours
        None             the query ran; nothing owns it — proceed legacy
        raise            the query FAILED; ownership is unknown

    A ROW, NOT A FLAG — and the rollout gate is deliberately not consulted
    here. This answers a question about stored state: an operation exists,
    therefore this meal is ours. Re-asking the gate would be the mid-flight
    fallback the directive forbids.

    Fails CLOSED in the opposite direction from the rest of this module: a
    payload that cannot be decoded still comes back, with `readable=False`,
    because pretending nothing is pending is how a held meal disappears.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from core.clock import now as _now
    from db.models import PendingOperation

    try:
        cutoff = _now() - timedelta(minutes=SETTLED_OWNERSHIP_MINUTES)
        rows = (await db.execute(
            select(PendingOperation)
            .where(PendingOperation.user_id == user.id,
                   PendingOperation.domain == DOMAIN)
            .order_by(PendingOperation.id.desc()).limit(5))).scalars().all()
    except Exception as exc:
        logger.error("event=b1_ownership_unknown user=%s — refusing to "
                     "proceed as unowned", getattr(user, "id", None),
                     exc_info=True)
        raise OwnershipUnknown(
            f"could not determine B-1 ownership for user "
            f"{getattr(user, 'id', None)}") from exc

    for row in rows:
        status = str(row.status or "")
        if status not in (AWAITING, COMMITTED):
            continue
        if status == COMMITTED:
            updated = row.updated_at or row.created_at
            if updated is not None and updated < cutoff:
                continue          # stale; this is a new meal, not a replay
        # EXPIRY IS NOT HANDLED HERE, DELIBERATELY. An expired operation is
        # still returned, and the answer turn decides — because "expired"
        # removes the right to claim a message that was never addressed to
        # this question, NOT the right to accept one that was. Skipping the
        # row here would drop a late but unmistakable answer on the floor,
        # which is its own silent loss. See `OwnedOperation.expired`.
        try:
            data = json.loads(row.canonical_payload or "{}")
        except Exception:
            data = {}
        if not isinstance(data, dict) or data.get("slice") != "b1_quantity":
            continue
        try:
            from core.semantics import ClarificationInteraction
            # ⛔ P17 Phase 2 — STRICT, on the answer side too. `schema_version`
            # is validated and the item must be a dict: `data.get("item") or
            # {}` turned `0`, `""`, `[]` and `null` into an EMPTY item, and an
            # empty item prices nothing while looking readable. A payload this
            # code cannot read routes to the unreadable branch below (the
            # operation still OWNS the meal — that contract is unchanged), it
            # never becomes a question about nothing.
            if data.get("schema_version") != B1_PAYLOAD_VERSION:
                raise ValueError(
                    f"schema_version {data.get('schema_version')!r} is not "
                    f"{B1_PAYLOAD_VERSION!r}")
            _item = data.get("item")
            if not isinstance(_item, dict):
                raise ValueError(
                    f"stored item is {type(_item).__name__}, not a dict")
            interaction = ClarificationInteraction.from_payload(
                data.get("interaction") or {})
        except Exception:
            logger.error(
                "event=b1_payload_unreadable operation=%s — the operation "
                "still owns this meal; the turn repairs rather than falling "
                "back", row.operation_id, exc_info=True)
            return OwnedOperation(
                row=row, interaction=None, item={},
                locale=str(data.get("locale") or "en"),
                decision_id=str(data.get("decision_id") or ""),
                candidate_set_id=str(data.get("candidate_set_id") or ""),
                asked_at_stamp=_decode_asked_at(data),
                cohort=str(data.get("cohort") or ""))
        return OwnedOperation(
            row=row, interaction=interaction,
            item=dict(_item),
            locale=str(data.get("locale") or "en"),
            decision_id=str(data.get("decision_id") or ""),
            candidate_set_id=str(data.get("candidate_set_id") or ""),
            asked_at_stamp=_decode_asked_at(data),
            cohort=str(data.get("cohort") or ""),
            answered=_decode_answered(data, row.operation_id))
    return None


def _decode_asked_at(data: dict):
    """The ask stamp, or None for a row written before it existed.

    NEVER RAISES. This feeds a metric, and an operation must not become
    unanswerable because the timestamp it carries is unreadable — the fallback
    to `created_at` is exactly as good as the behaviour this replaced.
    """
    from datetime import datetime

    raw = data.get("asked_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw))
    except Exception:
        return None


def _decode_answered(data: dict, operation_id: str) -> dict:
    """Held answers, back as CONCRETE patches (B-1.5).

    FAILS THE OPERATION, NOT THE FIELD. An unreadable held patch cannot be
    skipped: skipping it would make an answered field look unanswered, the
    question would be re-asked, and the meal would eventually commit without
    the answer the user already gave. Raising here reaches the caller's
    `except` and becomes a repair, which is the honest outcome — we cannot
    read what they told us.
    """
    from core.semantics import patch_from_payload

    held = data.get("answered") or {}
    if not isinstance(held, dict):
        raise ValueError(
            f"{operation_id} has a non-object `answered` "
            f"({type(held).__name__}) — held answers are keyed by field")
    return {str(k): patch_from_payload(v) for k, v in held.items()}


def open_fields(interaction, answered: dict) -> tuple:
    """The fields this interaction asked about and has no answer for.

    ORDERED AS ASKED, so a re-ask names them the way they were shown.
    """
    return tuple(f for g in interaction.groups for f in g.fields
                 if f.field_id not in (answered or {}))


def ready_to_settle(interaction, answered: dict) -> bool:
    """May this operation commit?

    THE QUESTION IS ANSWERED WHEN EVERY FIELD IS, not when an answer arrives.
    Those were the same sentence while B-1 asked about one field, and B-1.5 is
    where they come apart: settling on the first applied answer would commit
    the meal with the other chips still on screen, and the tap that followed
    would find a settled operation and be discarded.
    """
    return not open_fields(interaction, answered)


@dataclass(frozen=True)
class ResolvedFields:
    """EVERY FIELD THIS OPERATION ASKED ABOUT, ANSWERED — handed to settlement
    whole.

    THIS REPLACED `pricing_patch(held)`, which extracted the one patch pricing
    happened to need. That was right while quantity was the only actionable
    field and wrong the moment there were two: the next field would have added
    `preparation_patch()` beside it, and B-2 would have become a pile of
    field-specific extraction helpers in the coordinator — the coordinator
    knowing, one function at a time, what every domain field means.

    THE COORDINATOR HANDS OVER STATE; THE DOMAIN READS WHAT IT NEEDS. Adding a
    field is then a change in the domain layer and in the producer, and no
    change at all here. The accessors below live on this object rather than in
    the answer turn for the same reason.
    """
    by_field: dict

    def of_type(self, patch_type: str) -> tuple:
        """Every answered patch of a kind, by the STORED DISCRIMINATOR.

        Not by position and not by sniffing which attributes are present —
        which patch means what must not depend on the order the user tapped
        in, and `patch_type` exists precisely so it does not.
        """
        return tuple(p for p in (self.by_field or {}).values()
                     if getattr(p, "patch_type", "") == patch_type)

    def _one(self, patch_type: str):
        """The single patch of a kind, or None — and LOUD when there are more.

        This returned `found[0]`, which is correct for one food and silently
        wrong for two: `chicken.quantity` and `rice.quantity` are distinct
        fields with distinct ids, so both are held, and taking the first would
        price the chicken and drop the rice without a word. B-2 is where that
        arrives, and a silent wrong number is the worst possible way for it to.

        Raising is right for B-1.5, which asks about one event by construction
        — so this cannot fire today, and the day it does the caller is asking
        a question that no longer has one answer. B-2 replaces it with
        per-event resolution rather than by relaxing the check.
        """
        found = self.of_type(patch_type)
        if len(found) > 1:
            raise ValueError(
                f"{len(found)} {patch_type} answers across events "
                f"{sorted({getattr(p, 'event_id', '?') for p in found})} — "
                f"this accessor collapses them to one, which would commit a "
                f"number for one food and drop the other. Resolve per event.")
        return found[0] if found else None

    def for_event(self, event_id: str) -> "ResolvedFields":
        """This event's answers alone.

        The seam B-2 settles through: one operation holds several foods, and
        each is priced from its OWN resolved fields. Present now because the
        alternative is the coordinator learning to slice the state, and it is
        the coordinator's ignorance that makes the field mechanism generic.
        """
        return ResolvedFields(by_field={
            k: p for k, p in (self.by_field or {}).items()
            if str(getattr(p, "event_id", "")) == str(event_id)})

    @property
    def event_ids(self) -> tuple:
        seen, out = set(), []
        for patch in (self.by_field or {}).values():
            event = str(getattr(patch, "event_id", ""))
            if event and event not in seen:
                seen.add(event)
                out.append(event)
        return tuple(out)

    @property
    def quantity(self):
        """The patch that decides the AMOUNT. Still special — it is the only
        field the pricing path cannot proceed without."""
        return self._one("set_quantity")

    @property
    def preparation(self):
        return self._one("set_preparation")

    @property
    def preparation_id(self) -> str:
        return str(getattr(self.preparation, "preparation_id", "") or "")


def resolved_fields(held: dict) -> ResolvedFields:
    return ResolvedFields(by_field=dict(held or {}))


async def hold_answer(db, *, owned: OwnedOperation, patch) -> dict:
    """Record an answer to ONE field and leave the operation open (B-1.5).

    DURABLE, NOT REMEMBERED BY THE SCREEN. The next tap may come from a
    relaunched app, a second device, or a different worker, and each must see
    the same partially-answered operation. A held answer kept in memory is an
    answer the user gave and the system lost.

    THE REVISION DOES NOT MOVE. The chips for the still-open fields are on the
    user's screen right now; bumping the revision would make every one of them
    a stale tap and lock the user out of finishing the answer. This is the same
    reasoning REPAIR and REFUSED already follow, for the same reason.

    Returns the full held map, so the caller tests readiness against what is
    now stored rather than against what it believes it just wrote.
    """
    from core import pending_repository as repo

    # ⛔ THE MERGE HAPPENS UNDER THE LOCK, FROM THE LOCKED ROW.
    #
    # This used to read `owned.answered` — hydrated before the request even
    # reached here — and write the whole map back. Two answers arriving
    # together each read, each added their own patch, each wrote everything:
    # last write wins and one answer is silently lost, with a reply confirming
    # it. A B-1.5 live correctness defect, found while building B-1.6.
    #
    # `save_revision`'s compare-and-swap cannot fix it, because holding an
    # answer deliberately does not move the revision — both writers satisfy
    # `WHERE revision = N`. Serializing the read-modify-write is the fix, and
    # taking the lock while still merging from the pre-lock snapshot would
    # acquire the lock and keep the bug.
    locked = await repo.locked_operation(db, owned.operation_id)
    held = locked.answered()
    held[str(patch.field_id)] = patch
    data = dict(locked.payload)

    # ⭐ B-1.6: RECONCILE, DO NOT APPEND. An answer can make another field
    # irrelevant, and dropping that field from the screen is not the same as
    # retracting it. "1 tbsp of oil" followed by "actually, no oil" must
    # remove the tablespoon from settlement — leaving it in `answered` while
    # hiding its chip prices a meal with fat the user just said was not there,
    # which is a silent nutrition corruption rather than a display bug.
    held, retracted, reconciliation = _reconcile_after(owned, held, data)

    # ⭐ B-1.6b: A SHAPE CHANGE REBUILDS THE ANSWER SURFACE, UNDER THIS LOCK.
    #
    # Persisted BEFORE it is returned, and inside the same critical section
    # that produced it — a wire payload that exists only in the answer turn's
    # memory is one a reload cannot reproduce, and reload is the normal case
    # (a relaunched app, a second device, another worker).
    generation = None
    if reconciliation is not None and reconciliation.changed:
        from core import interaction_generation as gen

        rebuilt = gen.next_generation(previous=owned.interaction,
                                      reconciliation=reconciliation,
                                      answered=held, item=data.get("item"))
        if rebuilt is not None:
            data["interaction"] = rebuilt.to_payload()
            owned.interaction = rebuilt
            generation = rebuilt.revision

    data["answered"] = {k: p.to_payload() for k, p in held.items()}
    locked.write(data, revision=generation)     # ONE write, whole payload
    db.add(locked.row)
    await db.flush()
    logger.info("event=b1_answer_held operation=%s field=%s open=%d "
                "retracted=%d operation_lock_wait_ms=%d", owned.operation_id,
                patch.field_id, len(open_fields(owned.interaction, held)),
                len(retracted), locked.lock_wait_ms)
    return held


def _reconcile_after(owned: OwnedOperation, held: dict, data: dict) -> tuple:
    """Recompute the active set and invalidate what the answer turned off.

    THE HISTORY IS DURABLE AND SEPARATE FROM THE STATE. "Never active" and
    "answered, then invalidated" both leave the attribute absent from
    `answered`, and B-1.8's correction analysis cannot be written on a state
    that conflated them — so a retraction is recorded rather than merely
    performed.

    NEVER RAISES INTO THE TURN. A reconciliation that fails must not lose an
    answer the user just gave; it degrades to the pre-B-1.6 behaviour of
    holding what arrived, and says so loudly. The commit boundary asserts the
    result independently, which is where a missed retraction is caught.

    Returns `(held, retracted, reconciliation)`. The reconciliation goes to
    the caller rather than being consumed here, because B-1.6b's producer must
    CONSUME activation output instead of recomputing it — a second evaluation
    would make `active_when` advisory and give "when is this asked" two owners
    again.
    """
    from core import field_activation as fa

    try:
        item = dict(data.get("item") or {})
        previous = {fa.attribute_of_field_id(f.field_id)
                    for g in owned.interaction.groups for f in g.fields}
        previous |= {fa.attribute_of_field_id(k, p) for k, p in held.items()}
        reconciliation = fa.reconcile(
            previously_active={a for a in previous if a},
            state=fa.state_from(item, held),
            answered_by_field=held,
            attribute_of_field=fa.attribute_of_field_id)
    except Exception:
        logger.warning("event=reconciliation_failed operation=%s — holding "
                       "the answer unreconciled; settlement re-checks",
                       owned.operation_id, exc_info=True)
        return held, {}, None

    if not reconciliation.retracted:
        return held, {}, reconciliation

    history = list(data.get("retractions") or [])
    for field_id, retracted_patch in reconciliation.retracted.items():
        held.pop(field_id, None)
        history.append({
            "field_id": field_id,
            "attribute": fa.attribute_of_field_id(field_id, retracted_patch),
            "revision": int(getattr(owned.interaction, "revision", 0) or 0),
            "reason": "dependency_became_false",
            "patch": retracted_patch.to_payload(),
        })
        logger.info("event=field_retracted operation=%s field=%s attribute=%s "
                    "reason=dependency_became_false", owned.operation_id,
                    field_id, fa.attribute_of_field_id(field_id,
                                                       retracted_patch))
    data["retractions"] = history
    return held, reconciliation.retracted, reconciliation


def _assert_no_retracted_value_settles(owned: OwnedOperation,
                                       resolved: ResolvedFields) -> None:
    """RAISES rather than prices a value whose dependency the user turned off.

    Failing the settle is the correct outcome here and the uncomfortable one.
    The alternative — dropping the offending value and committing the rest —
    would write a meal the user never described while reporting success, and
    a refused settle is recoverable in a way a quietly wrong log is not.

    The item is read from the stored payload, not from the interaction, so
    this sees exactly what was persisted.
    """
    from core import field_activation as fa

    try:
        data = json.loads(owned.row.canonical_payload or "{}")
        item = dict(data.get("item") or {})
    except Exception:
        logger.warning("event=settlement_check_unreadable operation=%s",
                       owned.operation_id, exc_info=True)
        return
    fa.assert_settlement_is_consistent(item=item,
                                       answered=dict(resolved.by_field or {}))


async def settle(db, *, user, owned: OwnedOperation, resolved: ResolvedFields,
                 source_turn_id: str, cohort: str = "") -> Any:
    """Apply the answer, price the food, and commit it ONCE, canonically.

    Everything below happens inside the caller's transaction. `settle` neither
    commits nor rolls back the session — the coordinator's contract, and the
    reason a failure here leaves no partial meal.
    """
    from core.canonical_writer import MealIntent, ResolvedFood, ResolvedMeal
    from core.commit_coordinator import commit_or_load_existing
    from core.semantics import (CanonicalEvent, Confidence,
                                NutritionProvenance, ResolutionStatus)
    from core.timezones import safe_timezone
    from db.queries import _user_today

    # ⭐ B-1.6: THE COMMIT BOUNDARY RECHECKS WHAT THE ANSWER PATH RECONCILED.
    #
    # Not a second policy — an INVARIANT. The answer path already retracts,
    # and this asserts the result independently at the point of no return, so
    # an alternate caller, a future repair path or a replayed operation cannot
    # commit a payload B-1.6 would never have produced. Deriving activation
    # again here would be the two-owners defect; asserting it is what stops
    # the reconciliation from being a promise the boundary takes on trust.
    _assert_no_retracted_value_settles(owned, resolved)

    # ALREADY SETTLED — replay, never re-settle.
    #
    # The chip stays on screen after the meal lands, so a second tap is a real
    # delivery. It cannot be answered by re-running this function: `settle`
    # advances the operation's revision, so the second pass would compute a
    # DIFFERENT (operation_id, revision) pair, form its own claim, and write a
    # second meal. The coordinator's idempotency cannot see that — the two
    # claims are genuinely distinct — so the guard belongs here, where the
    # operation's terminal status is known.
    if owned.status == COMMITTED:
        stored = await replay(db, owned)
        if stored is not None:
            logger.info(
                "event=b1_replayed operation=%s user=%s cause=tapped_after_commit",
                owned.operation_id, user.id)
            return stored
        raise RuntimeError(
            f"{owned.operation_id} is committed but has no stored result — "
            f"replaying blind would write the meal twice")

    from skills.nutrition import preparation_ontology as prep_onto

    # THE FIELD THAT DECIDES THE AMOUNT, read off the resolved state rather
    # than handed in already extracted. `settle` is the domain layer; knowing
    # which of its fields prices the food is its job, not the coordinator's.
    patch = resolved.quantity
    if patch is None:
        raise ValueError(
            f"{owned.operation_id} reached settlement with no quantity answer "
            f"— the readiness gate should have held it open")
    quantity_text = _quantity_text(patch)
    item = dict(owned.item or {})

    # PREPARATION PRICES THE FOOD BY NAMING IT (B-1.5), and by naming it only.
    #
    # A preparation factor applied to calories here would be a second opinion
    # about nutrition inside an operation that has no business holding one —
    # the exact defect B-1.75 deleted on the quantity side, rebuilt on the
    # preparation side. Composing the name instead lets the enrichment lane
    # find preparation-specific evidence (USDA holds grilled and fried as
    # different foods) and lets `validators` DOWNGRADE preparation-mismatched
    # candidates. Both mechanisms already exist and are already tested; this
    # commit gives them the fact they were missing.
    #
    # It follows that the answer moves the number only where real evidence
    # distinguishes the preparations — which is the correct behaviour and is
    # why the gate asserts a DIFFERENCE for a food that has one, rather than a
    # fixed multiplier for every food.
    food_name = prep_onto.name_with(
        str(item.get("food") or item.get("name") or "").strip(),
        resolved.preparation_id)

    # THE ANSWERED QUANTITY IS THE ONLY QUANTITY AUTHORITY (B-1.75).
    #
    # This used to be `{**item, "quantity": quantity_text}`, which layered the
    # answered quantity on top of the interpreter's macros for the quantity it
    # GUESSED. `_analyze_food` reads calories/protein/carbs/fats straight out
    # of this dict, and `analyze()` documents its own tie-break — "the LLM's
    # calories/protein anchor the portion unless the quantity is an explicit
    # mass and the winner is trustworthy". So the input stated the amount
    # twice, disagreeing with itself, and a policy meant for arbitrating
    # sources ended up arbitrating the user's own answer. Measured: asking
    # "50 g" and "100 g" of the same food both committed the ask-time item's
    # 200 cal, unchanged. The question was decorative.
    #
    # A DELETION, NOT ARITHMETIC. Rescaling the stale macros here would be a
    # second opinion about nutrition inside an operation that has no business
    # holding one, and would leave the contradictory input in place for the
    # next reader to trip over. Removing the stale figures lets the real
    # pricing path do its one job against one quantity.
    #
    # `amount`/`unit` are dropped with them: today nothing in the pricing path
    # reads either, so they are inert — but they describe the DISCARDED
    # quantity, and leaving a stale copy of the exact fact under negotiation
    # is how this defect happened the first time.
    _STALE_TO_THE_ANSWER = ("amount", "unit", "quantity",
                            "calories", "protein", "carbs", "fats",
                            "fiber", "sugar", "sodium")
    inp = {k: v for k, v in item.items() if k not in _STALE_TO_THE_ANSWER}
    inp["quantity"] = quantity_text

    # NOT DISCARDED — DECLARED. Removing the stale macros is only half of it:
    # for a food no lane has a row for, they were the ONLY nutrition in the
    # system, and dropping them silently committed a zero row. The estimate is
    # still usable; it just has to say what it was an estimate OF. Paired with
    # its own quantity it is a density, which the pricing path can apply to the
    # answered amount. Unpaired it is the defect this milestone exists to fix.
    #
    # No arithmetic here on purpose: `estimate_density` converts, in the same
    # module that normalises every other candidate.
    basis_quantity = _ask_time_quantity(item)
    if basis_quantity and item.get("calories"):
        inp["estimate_basis"] = {
            "quantity": basis_quantity,
            "calories": item.get("calories"), "protein": item.get("protein"),
            "carbs": item.get("carbs"), "fats": item.get("fats"),
        }

    # THE SAME PRICING PRODUCTION USES. Writes nothing; decides what it costs.
    #
    # ⭐ TIMED, because the existing trace could not answer the question.
    # Measured 2026-08-07: a chip tap settled in 11,053 ms and `turn_metrics`
    # attributed all of it to one stage called `write` — a true measurement
    # and a useless diagnosis. `settle.pricing` separates deciding what the
    # food costs from writing the row, and the leaves below it (`usda_off`,
    # `qualification`, `ranking`) say which part of deciding is expensive.
    # `timed` is a no-op outside a traced turn, so this is free everywhere else.
    from core.request_trace import timed as _timed

    # ══ THE SEAM, CUT ══════════════════════════════════════════════════════
    #
    # This was `await _analyze_food(db, user, food_name, inp)` — the ONE thing
    # the canonical spine took from the legacy pipeline, and the far side of
    # every canonical defect measured in production:
    #
    #     settle.commit   (canonical)        17 ms
    #     pricing.ranking (deterministic)     0 ms
    #     settle.pricing  (legacy)        8,171 ms of an 8,225 ms tap
    #     entry 2932      Mackerel 80 g committed at 0.0 kcal / 0 g protein
    #     "Chicken, fried" 120 g priced 295 kcal, then 329 kcal
    #
    # ASSEMBLE THEN PRICE, and the split is the safety model: `assemble`
    # LOADS already-existing evidence (a DB read and a file read, nothing
    # else), and `price` is SYNCHRONOUS, so no provider or model call can
    # occur on this path at all. An artifact miss falls to a lower rung; it
    # never invokes the generator.
    from core.canonical_pricing import PricingRefused, price
    from core.canonical_pricing_inputs import assemble

    with _timed("settle.pricing"):
        # THE MASS THE ASK-TIME ESTIMATE DESCRIBED, so answering REPRICES it.
        # Without this the estimate rung hands its own numbers through and
        # 50 g and 100 g both commit 200 kcal — B-1.75's contract inverted.
        _basis_grams = _grams_of(_ask_time_quantity(item), item)
        # ⭐ CF9 / P17-UA: a stored item that carries a snapshot was a SCAN;
        # the answer settles BOUND — that snapshot only, MEMORY never read.
        _bound = bool(item.get("product_evidence_id"))
        _inputs = await assemble(
            db, user_id=user.id,
            entity=str(item.get("food") or item.get("name") or "").strip(),
            preparation=resolved.preparation_id or "",
            identity=food_name, item=item, basis_grams=_basis_grams,
            bound=_bound)
        # PricingRefused PROPAGATES. It is raised BEFORE any write below, so
        # a refusal is non-mutating by construction rather than by a handler
        # remembering to be careful: no food row, no ledger event, and the
        # operation cannot reach APPLIED. Catching it here to substitute a
        # number is the exact failure being deleted — see `refuse_or_return`.
        analysis = price(entity=food_name, preparation=resolved.preparation_id,
                         consumed=_consumed_quantity(patch.quantity),
                         bound=_bound, **_inputs)

    zone = str(getattr(safe_timezone(user.timezone), "zone", "UTC"))
    revision = owned.revision + 1
    operation_id = owned.operation_id
    provenance = patch.provenance

    meal = ResolvedMeal(
        operation_id=operation_id, revision=revision, user_id=user.id,
        logging_day=_user_today(user.timezone or "UTC"), user_timezone=zone,
        intent=MealIntent.CREATE, source_turn_id=source_turn_id,
        meal_type=item.get("meal_type") or None,
        assumptions=tuple(getattr(analysis, "assumptions", ()) or ()),
        items=(ResolvedFood(
            event=CanonicalEvent(
                id=patch.event_id, domain=DOMAIN,
                entity_id=str(item.get("entity_id") or ""),
                surface_text=food_name,
                quantity=patch.quantity,
                resolution_status=ResolutionStatus.RESOLVED,
                # WHO CHOSE THE NUMBER: a tap is USER_SELECTED, typing it is
                # USER_STATED. Collapsing them is the measured 2026-08-04
                # disclosure defect, and this is the last place the
                # distinction can be recorded.
                provenance=provenance,
                confidence=Confidence(score=1.0, basis=provenance.value)),
            calories=float(analysis.calories or 0.0),
            protein=analysis.protein, carbs=analysis.carbs,
            fats=analysis.fats, fiber=analysis.fiber, sugar=analysis.sugar,
            sodium=analysis.sodium,
            quantity_text=quantity_text,
            meal_type=item.get("meal_type") or None,
            source_type="structured_food",
            estimated=_is_estimated(analysis),
            micros=getattr(analysis, "micros", None),
            micros_estimated=bool(getattr(analysis, "micros_estimated", False)),
            # The RESOLVER priced it; the user chose the portion. Two axes,
            # deliberately not collapsed (B-0b).
            nutrition_provenance=NutritionProvenance.SERVER_RESOLVED,
            raw_input=food_name,
            # ⭐ THE PRICING RECEIPT, the same one general settlement writes
            # (P17f): rung, evidence, basis, conversion, and — for a scan-bound
            # answer (CF9) — the SNAPSHOT the row was priced from. B-1 rows
            # carried none of this before; "which facts did this meal use" was
            # unanswerable for every clarified meal.
            attributes={"pricing": {k: v for k, v in {
                "rung": getattr(getattr(analysis, "rung", None), "value", None),
                "evidence_id": getattr(analysis, "evidence_id", "") or None,
                "basis": getattr(analysis, "basis", "") or None,
                "scaling_factor": getattr(analysis, "scaling_factor", None),
                "resolved_grams": getattr(analysis, "resolved_grams", None),
                "conversion_evidence_ids": list(getattr(
                    analysis, "conversion_evidence_ids", ()) or ()) or None,
                "source_amount": getattr(analysis, "source_amount", None),
                "source_unit": getattr(analysis, "source_unit", "") or None,
                "product_evidence_id": (int(item["product_evidence_id"])
                                        if _bound else None),
            }.items() if v not in (None, [], "")}}),))

    # THE REAL PENDING OPERATION, at the revision the answer produces. The
    # claim is `(operation_id, revision)`, so a duplicate delivery of the same
    # answer computes the same pair and is answered from storage rather than
    # written again.
    with _timed("settle.commit"):
        result = await commit_or_load_existing(
            db, operation=_AnswerOperation(owned.row, revision),
            resolved_meal=meal, writer=_writer)

    from core import pending_repository as repo
    outcome = await repo.save_revision(
        db, operation_id=operation_id, expected_revision=owned.revision,
        status=COMMITTED, storage_status="settled")
    if not outcome.ok and not outcome.conflict:
        logger.warning("b1 could not close operation=%s", operation_id)
    logger.info(
        "event=b1_committed operation=%s revision=%d user=%s b1_cohort=%s "
        "answer_provenance=%s grams=%s items=%d",
        # `or "-"`, like every other emitter. An empty value renders as a bare
        # `cohort=` token, which a `k=v` split reads as a key with no value —
        # a different thing from "we do not know", and this line printed it on
        # every commit while its neighbours printed `-`.
        operation_id, revision, user.id, cohort or "-", provenance.value,
        getattr(patch.quantity, "grams", None), len(result.committed_items))
    return result


async def replay(db, owned: OwnedOperation):
    """The result this operation already committed, or None.

    Reads the persisted `MealCommitResult` — the SAME object the winner held,
    which is what makes "a duplicate returns the original" a statement about
    types and not just about ids.
    """
    from sqlalchemy import select

    from core.meal_commit import _result_of
    from db.models import MealCommit

    row = (await db.execute(
        select(MealCommit)
        .where(MealCommit.operation_id == owned.operation_id,
               MealCommit.status == "committed")
        .order_by(MealCommit.operation_revision.desc()).limit(1)
    )).scalar_one_or_none()
    # `_result_of`, not a local decode: it rebuilds the SAME TYPE the winner
    # held. Returning raw JSON here is exactly what made the duplicate
    # contract asymmetric once already.
    return None if row is None else _result_of(row)


async def _writer(db, *, operation, resolved_meal):
    from core.canonical_writer import write_canonical_meal
    return await write_canonical_meal(db, operation=operation,
                                      resolved_meal=resolved_meal)


async def sweep_abandoned(db, *, limit: int = 200) -> int:
    """Expire questions nobody answered, and COUNT them.

    Runs on a timer, not on a turn, because nobody is having a turn when a
    user abandons one — which is exactly why abandonment is the signal most
    likely to be missing from a dashboard that otherwise looks complete. A
    clarification the user walked away from is the loudest possible statement
    that the question was not worth asking, and without this it is invisible.

    It also stops an unanswered row lingering as `awaiting_answer` forever,
    where a message weeks later would be read as an answer to a meal the user
    has long forgotten.
    """
    import json as _json

    from sqlalchemy import select

    from core import b1_metrics
    from core import pending_repository as repo
    from core.clock import now as _now
    from db.models import PendingOperation

    # STARVATION-SAFE, and this was a real defect. `LIMIT` applied before the
    # slice filter means the batch is drawn from ALL expired food operations
    # and only then narrowed to B-1's — so a backlog of expired non-B-1
    # operations fills every page and B-1's are never reached, forever, while
    # the sweep reports success.
    #
    # The slice IS queryable (`"slice": "b1_quantity"` lives in the JSON text),
    # so it is pushed into the WHERE clause as a coarse pre-filter and
    # re-checked properly after decoding — the LIKE narrows the scan, the
    # decode decides. Deterministic ordering by id, and pagination continues
    # until `limit` B-1 operations have been PROCESSED rather than until
    # `limit` rows have been read.
    swept = 0
    seen = 0
    after_id = 0
    page = max(limit, 50)
    while swept < limit and seen < limit * 20:
        rows = (await db.execute(
            select(PendingOperation)
            .where(PendingOperation.domain == DOMAIN,
                   PendingOperation.status == AWAITING,
                   PendingOperation.expires_at.isnot(None),
                   PendingOperation.expires_at < _now(),
                   PendingOperation.id > after_id,
                   # MATCHED ON THE VALUE, not on a serialized key/value
                   # pair. `'%"slice": "b1_quantity"%'` depends on
                   # json.dumps' separator, and if that ever changes the LIKE
                   # silently matches nothing — abandonment stops being
                   # measured and the sweep still reports success. The decode
                   # below is what decides; this only narrows the scan, so it
                   # should be the loosest thing that narrows.
                   PendingOperation.canonical_payload.like('%b1_quantity%'))
            .order_by(PendingOperation.id)
            .limit(page))).scalars().all()
        if not rows:
            break
        after_id = rows[-1].id
        seen += len(rows)
        for row in rows:
            if swept >= limit:
                break
            try:
                data = _json.loads(row.canonical_payload or "{}")
            except Exception:
                data = {}
            if data.get("slice") != "b1_quantity":
                continue          # the LIKE narrowed; the decode decides
            outcome = await repo.mark_expired(
                db, operation_id=row.operation_id,
                expected_revision=int(row.revision or 0))
            if not outcome.ok:
                # Somebody answered between the query and the write. Their
                # answer wins — this is a sweep, not a race to close.
                continue
            b1_metrics.abandoned(operation_id=row.operation_id,
                                 user_id=row.user_id,
                                 asked_at=row.created_at)
            swept += 1
    return swept


async def note_corrections(db, *, limit: int = 200) -> int:
    """Count B-1 rows corrected soon after they landed.

    THE SHARPEST QUALITY SIGNAL IN THE SET: the user saw the number and it was
    wrong enough to fix. A rising rate here invalidates a green corpus, which
    is precisely why it cannot be inferred from anything inside the answer
    turn — the evidence arrives minutes later, from a different turn.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from core import b1_metrics
    from core.clock import now as _now
    from db.models import LedgerEvent, PendingOperation

    # KEYED ON THE ENTRY, not the operation: `ledger_events` records which
    # ROW changed and which turn changed it, and has no operation column. The
    # entry id comes from the operation's own stored result, which is the only
    # thing joining the two.
    window = timedelta(minutes=b1_metrics.CORRECTION_WINDOW_MINUTES)
    since = _now() - (window * 3)
    _ZERO = timedelta(0)
    rows = (await db.execute(
        select(PendingOperation)
        .where(PendingOperation.domain == DOMAIN,
               PendingOperation.status == COMMITTED,
               PendingOperation.updated_at.isnot(None),
               PendingOperation.updated_at >= since)
        .limit(limit))).scalars().all()
    if not rows:
        return 0

    noted = 0
    for row in rows:
        entry_id = await _committed_entry_id(db, row.operation_id)
        if entry_id is None:
            continue
        if await _already_observed(db, row.operation_id, entry_id):
            continue
        events = (await db.execute(
            select(LedgerEvent)
            .where(LedgerEvent.domain == DOMAIN,
                   LedgerEvent.entry_id == entry_id)
            .order_by(LedgerEvent.id))).scalars().all()
        created = next((e for e in events if e.event_type == "created"), None)
        if created is None or created.created_at is None:
            continue
        for event in events:
            if event.id == created.id or event.created_at is None:
                continue
            # QUALIFYING TYPES ONLY. Not every later event on a row is a
            # correction of its numbers — a re-log rollup or a restore says
            # something else — and counting them would inflate the one metric
            # that is supposed to mean "we got it wrong".
            if event.event_type not in CORRECTION_EVENT_TYPES:
                continue
            gap = event.created_at - created.created_at
            # BOTH ENDS. A negative gap is clock skew or a backfilled event,
            # not a correction that happened before the thing it corrects, and
            # letting it through would count an impossible ordering as
            # evidence.
            if gap < _ZERO or gap > window:
                continue
            if await _record_observation(
                    db, operation_id=row.operation_id, entry_id=entry_id,
                    user_id=row.user_id, event_type=event.event_type,
                    minutes=gap.total_seconds() / 60.0):
                b1_metrics.corrected(
                    operation_id=row.operation_id, user_id=row.user_id,
                    entry_id=entry_id, minutes=gap.total_seconds() / 60.0)
                noted += 1
            break
    return noted


async def _already_observed(db, operation_id: str, entry_id) -> bool:
    from sqlalchemy import select

    from db.models import B1CorrectionObservation

    return (await db.execute(
        select(B1CorrectionObservation.id)
        .where(B1CorrectionObservation.operation_id == operation_id,
               B1CorrectionObservation.entry_id == entry_id)
        .limit(1))).scalar_one_or_none() is not None


async def _record_observation(db, *, operation_id: str, entry_id, user_id,
                              event_type: str, minutes: float) -> bool:
    """Claim this observation, or discover somebody already did.

    THE INSERT IS THE CLAIM, contained in a savepoint, exactly as
    `claim_commit` does it: a read-then-write cannot see the row another
    worker is inserting, and two schedulers on two workers is the normal
    deployment. Returns False when the observation already exists, which is
    how the metric stays exactly-once rather than once-per-cron-tick.
    """
    from sqlalchemy.exc import IntegrityError

    from db.models import B1CorrectionObservation

    try:
        async with db.begin_nested():
            db.add(B1CorrectionObservation(
                operation_id=operation_id, entry_id=int(entry_id),
                user_id=int(user_id), event_type=str(event_type),
                minutes_after_commit=float(minutes)))
            await db.flush()
        return True
    except IntegrityError:
        return False


async def _committed_entry_id(db, operation_id: str):
    from sqlalchemy import select

    from core.meal_commit import _result_of
    from db.models import MealCommit

    row = (await db.execute(
        select(MealCommit)
        .where(MealCommit.operation_id == operation_id,
               MealCommit.status == "committed")
        .order_by(MealCommit.operation_revision.desc()).limit(1)
    )).scalar_one_or_none()
    result = None if row is None else _result_of(row)
    items = list(getattr(result, "committed_items", ()) or ())
    first = items[0] if items and isinstance(items[0], dict) else {}
    return first.get("entry_id")


async def fail(db, *, owned: OwnedOperation, user, reason: str) -> None:
    """Close an operation WE cannot serve.

    Distinct from `cancel`, which is the user's decision. This is ours: the
    stored interaction cannot be read, so no answer could be applied to it,
    and leaving the row `awaiting_answer` would collect answers into a void
    turn after turn. Terminal, logged as an error, and never dressed up as a
    question to the user.
    """
    from core import pending_repository as repo

    await repo.save_revision(db, operation_id=owned.operation_id,
                             expected_revision=owned.revision,
                             status=FAILED, storage_status="closed",
                             terminal_reason=(reason or "unserviceable")[:200])
    logger.error("event=b1_failed operation=%s user=%s reason=%s",
                 owned.operation_id, getattr(user, "id", None), reason)


async def cancel(db, *, owned: OwnedOperation, user, reason: str = "") -> None:
    """Close the operation without a write, because the user said so.

    A terminal canonical outcome, not a fallback: nothing is handed to the
    legacy lane, and the meal does not silently persist as an open row that a
    later turn trips over.
    """
    from core import pending_repository as repo

    await repo.save_revision(db, operation_id=owned.operation_id,
                             expected_revision=owned.revision,
                             status=CANCELLED, storage_status="closed",
                             terminal_reason=(reason or "user_cancelled")[:200])
    logger.info("event=b1_cancelled operation=%s user=%s reason=%s",
                owned.operation_id, user.id, reason or "user_cancelled")


def _quantity_text(patch) -> str:
    """The quantity as the pricing path reads it — grams, which is the scaling
    currency. The user's own words are preserved on the patch's quantity
    (`surface_text`) and in the interaction; this is the machine's copy."""
    grams = getattr(patch.quantity, "grams", None)
    if grams:
        return f"{float(grams):g}g"
    amount = getattr(patch.quantity, "amount", None)
    unit = getattr(patch.quantity, "unit_id", "") or ""
    return f"{float(amount):g}{unit}".strip() if amount else ""


def _grams_of(quantity_text: str, item: dict):
    """The ask-time quantity in grams, or None when it cannot be massed.

    None is a real answer: "one plate" has no stated mass, so the estimate has
    no basis to be rescaled FROM and stands as given. Guessing a mass here
    would be inventing the very number the question exists to obtain.
    """
    grams = item.get("estimated_mass_g") or item.get("grams")
    if grams:
        try:
            return float(grams)
        except (TypeError, ValueError):
            pass
    # THE SAME NORMALIZER THE ASK PATH USES. An earlier draft invented a
    # `skills.nutrition.quantity.parse_quantity` that does not exist, so this
    # silently returned None and the estimate was never repriced — the defect
    # looked fixed and was not.
    try:
        from skills.nutrition.normalize import normalize_quantity

        parsed = normalize_quantity(quantity_text,
                                    str(item.get("food")
                                        or item.get("name") or ""))
        return float(parsed.grams) if getattr(parsed, "grams", None) else None
    except Exception:
        return None


def _ask_time_quantity(item: dict) -> str:
    """The quantity the interpreter's macros were an estimate OF.

    Rebuilt from the item's own `amount`/`unit` rather than stored separately,
    so it cannot drift from the numbers it describes.
    """
    amount = item.get("amount")
    if amount in (None, ""):
        return ""
    unit = str(item.get("unit") or "").strip()
    try:
        amount = f"{float(amount):g}"
    except (TypeError, ValueError):
        amount = str(amount)
    return f"{amount} {unit}".strip() if unit else amount


def _consumed_quantity(canonical):
    """`CanonicalQuantity` -> the `NormalizedQuantity` `scaling.py` speaks.

    One conversion, at the one boundary that needs it. Building a second
    quantity model here — or teaching the pricer about `CanonicalQuantity` —
    would be the drift this migration exists to remove; `scaling` already owns
    basis-to-portion and is not being replaced.
    """
    from skills.nutrition.models import NormalizedQuantity

    if canonical is None:
        return None
    grams = getattr(canonical, "grams", None)
    grams = float(grams) if grams is not None else None
    amount = getattr(canonical, "amount", None)
    unit = str(getattr(canonical, "unit_id", "") or "g")
    # ⭐ A MASS THE USER STATED OR CHOSE IS EXACT (P17 precedence class 1).
    # A CanonicalQuantity whose dimension is MASS carries the user's own
    # answer — "110 g", or the tapped "2 servings (110 g)" option — and
    # `mass_is_exact` is how `resolve_scaling` recognises class 1. Without
    # the marking, a BOUND settle (CF9) refused the user's own answer as a
    # heuristic mass. Marked as a mass conversion — the same source the
    # normalizer stamps on "110 g" typed — never invented for a count.
    dim = str(getattr(getattr(canonical, "dimension", None), "value",
                      getattr(canonical, "dimension", "")) or "").lower()
    exact_mass = (grams is not None and dim == "mass"
                  and unit.lower() in ("g", "gram", "grams", "kg", "oz", "lb", "lbs"))
    count = (float(canonical.count) if getattr(canonical, "count", None)
             is not None else None)
    # A COUNT of a named unit ("2 servings") reaches the resolver AS a count
    # with its unit — the label's own serving conversion resolves it — not as
    # a pre-multiplied mass; the mass on the quantity is derived, not stated.
    if dim in ("count", "volume") and count:
        # the derived mass rides for the unbound heuristic path (as before);
        # `normalization_source` stays empty, so it is NEVER read as exact
        return NormalizedQuantity(
            amount=float(amount) if amount is not None else count,
            unit=unit, grams=grams, count=count, unit_label=f"{count:g} {unit}",
            user_stated_amount=count, user_stated_unit=unit)
    return NormalizedQuantity(
        amount=float(amount) if amount is not None else (grams or 0.0),
        unit=unit,
        grams=grams,
        count=count,
        normalization_source=("mass_conversion" if exact_mass else ""),
        user_stated_amount=(float(amount) if (exact_mass and amount is not None) else None),
        user_stated_unit=(unit if exact_mass else ""))


def _is_estimated(analysis) -> bool:
    """Derived from the provenance VERDICT, not the display vocabulary.

    A canonical `PricedFood` answers this directly — it knows which RUNG
    produced the number, which is a stronger statement than any confidence
    string — so it short-circuits before the legacy reading below.

    Promotion rewrites `confidence` from the tier table, so
    `confidence == "estimated"` is False for every promoted row — prod
    fe#2703/2705 committed `estimated_flag=False` while their own raw_input
    said estimated. The string check remains only for analyses with no
    provenance.
    """
    from core.canonical_pricing import PricedFood

    if isinstance(analysis, PricedFood):
        return analysis.estimated

    prov = getattr(analysis, "provenance", None)
    if prov is not None:
        return bool(getattr(prov, "macros_are_estimated", False))
    return getattr(analysis, "confidence", "") == "estimated"
