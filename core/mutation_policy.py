"""What contract each mutating route owes, declared route by route (B2).

THE POINT OF THIS FILE IS THAT THERE ARE NO UNKNOWNS.

The first cut of B2 measured one thing — how many routes carried the
food-logging architecture — and answered "3 of 60". That number is not a
safety property. It counts conformance to ONE contract, and most of these
routes should not have that contract: an idempotency claim on a
last-write-wins settings PATCH buys nothing, and a ledger event for a device
token records something no one will ever undo. Chasing the number would have
meant bolting machinery onto 57 routes to make a percentage move.

So every route declares its policy instead, including — explicitly — the
policy "idempotency is not required here, because the operation is naturally
idempotent". A declared "not required" is a decision on the record. An absent
declaration is the thing B2 exists to eliminate.

DECLARED vs OBSERVED
────────────────────
This file holds INTENT. `scripts/mutation_inventory.py` reads the source for
what is actually there (turn identity, build attribution, a concurrency test)
and fails when the two disagree. Neither half is trusted alone: a declaration
with no implementation is a wish, and an implementation with no declaration is
an accident nobody reviewed.

THE CLASSES
───────────
Class A — mutates the user's canonical logged history, and duplicating or
    losing the write corrupts a record they rely on. Food, exercise, water,
    weight, health imports, undo. These get the full contract: canonical turn
    id, an idempotency claim, ONE transaction holding the row + its ledger
    event + the claim completion, a request trace, and proof under
    concurrency and replay.

Class B — user-scoped state that is naturally idempotent (a settings PATCH is
    last-write-wins: applying it twice is applying it once) or user content
    whose duplication is visible but not corrupting. Requires authentication,
    a canonical turn id, a request trace and an audit trail. An idempotency
    claim is NOT required, and each route below says so in its own words.

Class C — operational, administrative and transport surfaces that do not own
    a user's logged history: admin tools, auth/session, webhook ingress.
    Requires authorization and logging. The transport routes carry no
    contract of their own on purpose — the lane they hand off to owns it, and
    a second contract at the edge would be a second place to get it wrong.

Adding a mutating route without a line here fails CI. That is the gate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

#: What each class must be able to demonstrate. `mutation_inventory` checks
#: these against what it can actually observe in the source and the tests.
CLASS_REQUIREMENTS = {
    "A": ("canonical_turn_id", "idempotency", "ledger_event", "request_trace",
          "durable_result", "concurrency_test"),
    "B": ("canonical_turn_id", "request_trace", "audit_trail"),
    "C": ("authorized", "logged"),
}

#: Idempotency policies. Every route names one; "unknown" is not available.
IDEMPOTENCY = {
    # A client key is required and enforced by a claim. Replay returns the
    # ORIGINAL committed result.
    "claim_required",
    # Applying the request twice leaves the same state as applying it once —
    # last-write-wins settings, toggles that carry their target state,
    # deletes-by-id, upserts keyed on natural identity. No claim needed.
    "natural",
    # Deduplicated further in, by the lane this route hands off to.
    "delegated",
    # Read-modify-write with no durable effect worth replaying (debug and
    # admin tools). Repeating it repeats the operation, and that is acceptable
    # because a human triggered it deliberately.
    "operator_initiated",
}


@dataclass(frozen=True)
class Policy:
    """One route's declared contract. Every field is a decision, not a default."""
    method: str
    route: str
    mutation_class: str            # A | B | C
    auth: str                      # how the caller is authorized
    idempotency: str               # one of IDEMPOTENCY
    transaction_owner: str         # who owns the transaction the write lands in
    ledger: str                    # what history this write leaves
    replay: str                    # what a repeated delivery does
    rollback: str                  # how it is taken back
    owner: str                     # the module accountable for it
    notes: str = ""

    @property
    def key(self) -> tuple:
        return (self.method, self.route)


def _p(method, route, cls, auth, idem, txn, ledger, replay, rollback, owner,
       notes=""):
    return Policy(method=method, route=route, mutation_class=cls, auth=auth,
                  idempotency=idem, transaction_owner=txn, ledger=ledger,
                  replay=replay, rollback=rollback, owner=owner, notes=notes)


# Shorthand for the repeated values, so the table below reads as decisions
# rather than as boilerplate.
_SESSION = "session"              # iOS/native bearer identity (api.auth)
_TOKEN = "capability_token"       # dashboard per-user URL token
_ADMIN = "admin"                  # admin header/cookie (B7)
_HMAC = "webhook_signature"
_PUBLIC = "public"

_LAST_WRITE = "last write wins — applying it twice equals applying it once"
_ROW_TXN = "the domain write (db.queries) — row + ledger event + claim in one"
_HANDLER_TXN = "the handler's session, single commit"


POLICIES: tuple[Policy, ...] = (

    # ── Class A: the user's logged history ──────────────────────────────────
    # iOS tap-log (the reference implementation).
    _p("POST", "/api/v1/food", "A", _SESSION, "claim_required", _ROW_TXN,
       "created, in the row's transaction", "returns the original entry_id",
       "ledger undo → delete_food_entry", "api/quick_log.py"),
    _p("POST", "/api/v1/exercise", "A", _SESSION, "claim_required", _ROW_TXN,
       "created, in the row's transaction", "returns the original entry_id",
       "ledger undo → delete_exercise_entry", "api/quick_log.py"),
    _p("POST", "/api/v1/weight", "A", _SESSION, "claim_required", _ROW_TXN,
       "created or updated, in the row's transaction",
       "returns the original metric_id",
       "uninvertible by design — the per-day upsert makes delete-as-undo "
       "lossy without a captured before-state",
       "api/quick_log.py",
       notes="add_body_metric collapses to one row per (user, day, source), "
             "so a retry could not duplicate it. The claim is still taken so "
             "the replay answers identically and one contract covers all "
             "three tap-log routes."),

    # iOS water lane.
    _p("POST", "/api/v1/water", "A", _SESSION, "claim_required", _ROW_TXN,
       "created, in the row's transaction", "returns the original entry_id",
       "ledger undo → delete_water_entry", "api/water.py"),
    _p("PATCH", "/api/v1/water/{entry_id}", "A", _SESSION, "claim_required",
       _ROW_TXN, "updated, carrying the before-amount",
       "returns the committed state, does not re-apply",
       "the before-state in the updated event", "api/water.py"),
    _p("DELETE", "/api/v1/water/{entry_id}", "A", _SESSION, "claim_required",
       _ROW_TXN, "deleted, carrying the row's full state",
       "reports the original success rather than 404",
       "restore from the deleted event's payload", "api/water.py"),

    # iOS editors.
    _p("PATCH", "/api/v1/food/{entry_id}", "A", _SESSION, "claim_required",
       _ROW_TXN, "updated, carrying the before-state",
       "returns the committed state, does not re-apply",
       "ledger undo → update_food_entry with the before-state",
       "api/food_edit.py"),
    _p("DELETE", "/api/v1/food/{entry_id}", "A", _SESSION, "claim_required",
       _ROW_TXN, "deleted, carrying the row + its daily_log_id",
       "reports the original success rather than 404",
       "restore_food_entry from the deleted payload", "api/food_edit.py"),
    _p("PATCH", "/api/v1/exercise/{entry_id}", "A", _SESSION, "claim_required",
       _ROW_TXN, "updated, carrying the before-state",
       "returns the committed state, does not re-apply",
       "ledger undo → update_exercise_entry with the before-state",
       "api/exercise_edit.py"),
    _p("DELETE", "/api/v1/exercise/{entry_id}", "A", _SESSION,
       "claim_required", _ROW_TXN,
       "deleted, carrying the row + its daily_log_id",
       "reports the original success rather than 404",
       "restore_exercise_entry from the deleted payload",
       "api/exercise_edit.py"),

    # Dashboard equivalents. Same data, different auth — they owe the same
    # contract, and none of them carry it yet.
    _p("POST", "/api/food/log", "A", _TOKEN, "claim_required", _ROW_TXN,
       "created, in the row's transaction", "returns the original entry_id",
       "ledger undo → delete_food_entry", "api/app.py"),
    _p("PATCH", "/api/food/{entry_id}", "A", _TOKEN, "claim_required",
       _ROW_TXN, "updated, carrying the before-state",
       "returns the committed state", "the before-state in the updated event",
       "api/app.py"),
    _p("DELETE", "/api/food/{entry_id}", "A", _TOKEN, "claim_required",
       _ROW_TXN, "deleted, carrying the row + its daily_log_id",
       "reports the original success", "restore from the deleted payload",
       "api/app.py"),
    _p("POST", "/api/exercise/log", "A", _TOKEN, "claim_required", _ROW_TXN,
       "created, in the row's transaction", "returns the original entry_id",
       "ledger undo → delete_exercise_entry", "api/app.py"),
    _p("PATCH", "/api/exercise/{entry_id}", "A", _TOKEN, "claim_required",
       _ROW_TXN, "updated, carrying the before-state",
       "returns the committed state", "the before-state in the updated event",
       "api/app.py"),
    _p("DELETE", "/api/exercise/{entry_id}", "A", _TOKEN, "claim_required",
       _ROW_TXN, "deleted, carrying the row + its daily_log_id",
       "reports the original success", "restore from the deleted payload",
       "api/app.py"),
    _p("POST", "/api/water/log", "A", _TOKEN, "claim_required", _ROW_TXN,
       "created, in the row's transaction", "returns the original entry_id",
       "ledger undo → delete_water_entry", "api/app.py"),
    _p("PATCH", "/api/water/{entry_id}", "A", _TOKEN, "claim_required",
       _ROW_TXN, "updated, carrying the before-amount",
       "returns the committed state", "the before-state in the updated event",
       "api/app.py"),
    _p("DELETE", "/api/water/{entry_id}", "A", _TOKEN, "claim_required",
       _ROW_TXN, "deleted, carrying the row's full state",
       "reports the original success", "restore from the deleted payload",
       "api/app.py"),
    _p("POST", "/api/weight/log", "A", _TOKEN, "claim_required", _ROW_TXN,
       "created or updated, in the row's transaction",
       "returns the original metric_id",
       "uninvertible by design — see /api/v1/weight", "api/app.py"),

    # Health imports. The reconciliation surface: these replace-on-sync, and a
    # delete must survive the next sync or the row resurrects.
    _p("POST", "/api/v1/health/snapshot", "A", _SESSION, "natural", _ROW_TXN,
       "created/updated per imported row",
       "re-importing the same sample is an upsert on its source_ref, not a "
       "second row",
       "HealthImportTombstone — a user delete is final and survives re-sync",
       "api/health_sync.py",
       notes="Naturally idempotent BECAUSE each sample carries a stable "
             "`source_ref` the import upserts on. That is the property the "
             "claim would otherwise provide, so requiring one here would be "
             "redundant machinery. The property that actually needs proving "
             "is the tombstone: without it a deleted import comes back."),
    _p("POST", "/api/v1/health/weights", "A", _SESSION, "claim_required",
       _ROW_TXN, "one health_import event per sync",
       "returns the original ingest count",
       "a manual weigh-in outranks a passive import; the tombstone covers "
       "deletes", "api/health_sync.py",
       notes="DECLARED `natural` UNTIL A TEST DISPROVED IT. The per-day dedup "
             "is a read-then-write — it SELECTs the days already covered, "
             "then inserts the rest — with no constraint behind it, so two "
             "concurrent syncs both read an empty set and both insert "
             "(`test_two_concurrent_weight_backfills_ingest_each_day_once` "
             "failed with 2 rows for one day). The claim closes the common "
             "case, a retried sync. The RESIDUAL race, two syncs with "
             "different keys submitting overlapping history, is still open; "
             "the root fix is a uniqueness constraint on (user, source, "
             "logging day), which needs a stored day column and a migration. "
             "Tracked by the xfail in that test file."),
    _p("POST", "/health/apple", "A", _TOKEN, "natural", _ROW_TXN,
       "created/updated per imported row",
       "upsert on source_ref", "HealthImportTombstone", "api/app.py",
       notes="Naturally idempotent on each sample's stable `source_ref`. "
             "HealthKit redelivers the same samples routinely, so this path "
             "has to be replay-safe by construction rather than by claim."),
    _p("POST", "/api/whoop/sync/{token}", "A", _TOKEN, "natural", _ROW_TXN,
       "created/updated per imported workout",
       "ref-upsert — a repeated sync updates rather than duplicates",
       "HealthImportTombstone", "api/app.py",
       notes="Naturally idempotent on Whoop's own activity id. A poll-based "
             "sync re-reads the same window every run, so duplicate delivery "
             "is the normal case, not the exceptional one."),

    # Undo is itself a mutation of logged history.
    _p("POST", "/api/v1/ledger/undo", "A", _SESSION, "claim_required",
       _ROW_TXN, "the inverse operation's own created/deleted event",
       "returns the original outcome — undoing twice must not undo two things",
       "the inverse is itself a ledger event, so redo falls out",
       "api/undo.py"),

    # The conversational lane. It mutates logged history through the executor,
    # which owns the turn contract; these routes own the turn's IDENTITY.
    _p("POST", "/api/v1/chat", "A", _SESSION, "claim_required", "the turn "
       "coordinator (core/turns) — the executor owns the write transaction",
       "written by the tool executor per operation",
       "ProcessedTurn returns the original reply",
       "ledger undo reaches every write the turn made", "api/chat.py"),
    _p("POST", "/api/v1/chat/photo", "A", _SESSION, "claim_required",
       "the turn coordinator", "written by the tool executor per operation",
       "ProcessedTurn returns the original reply", "ledger undo",
       "api/chat.py"),
    _p("POST", "/api/v1/chat/voice", "A", _SESSION, "claim_required",
       "the turn coordinator", "written by the tool executor per operation",
       "ProcessedTurn returns the original reply", "ledger undo",
       "api/chat.py"),
    _p("POST", "/api/chat/{token}", "A", _TOKEN, "claim_required",
       "the turn coordinator", "written by the tool executor per operation",
       "ProcessedTurn returns the original reply", "ledger undo",
       "api/app.py"),

    # ── Class B: user-scoped state, naturally idempotent ────────────────────
    _p("PATCH", "/api/v1/profile", "B", _SESSION, "natural", _HANDLER_TXN,
       "profile change audit row", _LAST_WRITE,
       "re-PATCH with the previous value", "api/profile_edit.py",
       notes="A profile PATCH carries the target state, not a delta. Two "
             "deliveries leave the same row, so a claim would add a failure "
             "mode without removing one."),
    _p("PATCH", "/api/v1/targets", "B", _SESSION, "natural", _HANDLER_TXN,
       "target change audit row — downstream coaching reads these", _LAST_WRITE,
       "re-PATCH with the previous targets", "api/profile_edit.py",
       notes="Targets steer every later coaching decision, so the audit trail "
             "matters more here than duplicate protection does: the question "
             "asked later is 'when did this change and to what', not 'did it "
             "apply twice'."),
    _p("POST", "/api/v1/auto-targets", "B", _SESSION, "natural", _HANDLER_TXN,
       "target change audit row",
       "recomputes from the same inputs to the same numbers",
       "re-PATCH targets", "api/profile_edit.py"),
    _p("PATCH", "/api/profile/{token}", "B", _TOKEN, "natural", _HANDLER_TXN,
       "profile change audit row", _LAST_WRITE, "re-PATCH", "api/app.py"),
    _p("POST", "/api/profile/{token}/auto-targets", "B", _TOKEN, "natural",
       _HANDLER_TXN, "target change audit row", "recomputes deterministically",
       "re-PATCH targets", "api/app.py"),
    _p("POST", "/api/profile/attribute/hide", "B", _TOKEN, "natural",
       _HANDLER_TXN, "attribute visibility audit row",
       "hiding an already-hidden attribute is a no-op", "unhide",
       "api/app.py"),
    _p("POST", "/api/v1/preferences", "B", _SESSION, "natural", _HANDLER_TXN,
       "preference change audit row", _LAST_WRITE, "re-POST",
       "api/settings_api.py"),
    _p("POST", "/api/v1/supplements/toggle", "B", _SESSION, "natural",
       _HANDLER_TXN, "supplement state audit row",
       "the request carries the target state, so a repeat is a no-op",
       "toggle back", "api/supplements_api.py",
       notes="Idempotent BECAUSE the payload names the desired state. A "
             "toggle that flipped whatever it found would NOT be, and would "
             "need a claim — the distinction is the payload, not the verb."),
    _p("POST", "/api/v1/devices/apns-token", "B", _SESSION, "natural",
       _HANDLER_TXN, "device registration audit row",
       "upsert on the token — re-registering is a no-op", "DELETE the token",
       "api/devices.py"),
    _p("DELETE", "/api/v1/devices/apns-token/{token}", "B", _SESSION,
       "natural", _HANDLER_TXN, "device registration audit row",
       "deleting an absent token succeeds", "re-register",
       "api/devices.py"),
    _p("POST", "/api/v1/location", "B", _SESSION, "natural", _HANDLER_TXN,
       "location update audit row", _LAST_WRITE, "DELETE /api/v1/location",
       "api/location_api.py"),
    _p("DELETE", "/api/v1/location", "B", _SESSION, "natural", _HANDLER_TXN,
       "location update audit row", "clearing an empty location succeeds",
       "re-POST", "api/location_api.py"),
    _p("POST", "/api/v1/workout_program", "B", _SESSION, "natural",
       _HANDLER_TXN, "program version audit row",
       "rebuilding replaces the active program rather than stacking one",
       "deactivate, or rebuild from the previous inputs",
       "api/workout_api.py"),
    _p("DELETE", "/api/v1/workout_program", "B", _SESSION, "natural",
       _HANDLER_TXN, "program version audit row",
       "deactivating an inactive program succeeds", "rebuild",
       "api/workout_api.py"),
    _p("DELETE", "/api/workout/{token}", "B", _TOKEN, "natural", _HANDLER_TXN,
       "program version audit row", "deactivating twice succeeds", "rebuild",
       "api/app.py"),
    _p("POST", "/api/workout/{token}/parse", "B", _TOKEN, "natural",
       _HANDLER_TXN, "program version audit row",
       "re-parsing the same text replaces the same program", "rebuild",
       "api/app.py"),
    _p("POST", "/api/workout/{token}/auto-fill", "B", _TOKEN, "natural",
       _HANDLER_TXN, "program version audit row",
       "auto-fill is deterministic from the program", "rebuild",
       "api/app.py"),
    _p("POST", "/api/v1/onboarding/complete", "B", _SESSION, "natural",
       _HANDLER_TXN, "onboarding completion audit row",
       "completing twice leaves the flag set", "n/a — a one-way flag",
       "api/profile_edit.py"),
    _p("POST", "/api/v1/oura/disconnect", "B", _SESSION, "natural",
       _HANDLER_TXN, "integration state audit row",
       "disconnecting a disconnected integration succeeds", "reconnect",
       "api/oura_api.py"),
    _p("POST", "/api/v1/whoop/disconnect", "B", _SESSION, "natural",
       _HANDLER_TXN, "integration state audit row",
       "disconnecting a disconnected integration succeeds", "reconnect",
       "api/whoop_api.py"),
    _p("POST", "/api/v1/brain/resync", "B", _SESSION, "operator_initiated",
       _HANDLER_TXN, "resync audit row",
       "recomputes derived state from the same source rows",
       "n/a — derived state, rebuilt on the next resync",
       "api/dashboard_api.py"),
    _p("POST", "/api/brain/insights/{token}", "B", _TOKEN,
       "operator_initiated", _HANDLER_TXN, "insight generation audit row",
       "regenerates derived insights", "n/a — derived state",
       "api/app.py"),
    _p("POST", "/api/v1/feedback", "B", _SESSION, "natural", _HANDLER_TXN,
       "the feedback row is its own record",
       "duplicate feedback is visible but harmless", "resolve it",
       "api/settings_api.py"),
    _p("POST", "/api/v1/chat/feedback", "B", _SESSION, "natural",
       _HANDLER_TXN, "the rating row is its own record",
       "upsert per (user, message) — re-rating replaces", "re-rate",
       "api/chat.py"),

    # Groups. User-visible content rather than logged health history: a
    # duplicate post is embarrassing, not corrupting, and it is reversible by
    # the user with unsend.
    _p("POST", "/api/v1/groups/{group_id}/join", "B", _SESSION, "natural",
       _HANDLER_TXN, "membership audit row", "joining twice is a no-op",
       "leave", "api/groups.py"),
    _p("POST", "/api/v1/groups/{group_id}/leave", "B", _SESSION, "natural",
       _HANDLER_TXN, "membership audit row", "leaving twice is a no-op",
       "re-join", "api/groups.py"),
    _p("POST", "/api/v1/groups/{group_id}/messages", "B", _SESSION,
       "natural", _HANDLER_TXN, "the message row is its own record",
       "a retry posts a second message — visible, and the user can unsend it",
       "unsend", "api/groups.py",
       notes="The one Class B route whose duplicate is user-visible. It stays "
             "B because the user can see and undo it themselves, which is not "
             "true of a silently duplicated meal. Revisit if groups leaves "
             "beta."),
    _p("DELETE", "/api/v1/groups/{group_id}/messages/{message_id}", "B",
       _SESSION, "natural", _HANDLER_TXN, "the unsend is recorded on the row",
       "unsending twice succeeds", "n/a — the user chose to remove it",
       "api/groups.py"),
    _p("POST", "/api/v1/groups/{group_id}/messages/{message_id}/react", "B",
       _SESSION, "natural", _HANDLER_TXN, "reaction state on the message",
       "the request carries the target state", "react again to clear",
       "api/groups.py"),

    # ── Class C: operational, auth and transport ────────────────────────────
    _p("POST", "/api/v1/auth/session", "C", _PUBLIC, "natural", _HANDLER_TXN,
       "auth event log", "issues a session for the same identity",
       "signout", "api/auth_routes.py"),
    _p("POST", "/api/v1/auth/link", "C", _SESSION, "natural", _HANDLER_TXN,
       "auth event log", "linking an already-linked account is a no-op",
       "unlink", "api/auth_routes.py"),
    _p("POST", "/api/v1/auth/link-code", "C", _SESSION, "natural",
       _HANDLER_TXN, "auth event log", "issues a fresh short-lived code",
       "the code expires", "api/auth_routes.py"),
    _p("POST", "/api/v1/auth/exchange-pairing-code", "C", _PUBLIC, "natural",
       _HANDLER_TXN, "auth event log", "a code is single-use; a replay fails",
       "n/a", "api/auth_routes.py"),
    _p("POST", "/api/v1/auth/signout", "C", _SESSION, "natural", _HANDLER_TXN,
       "auth event log", "signing out twice succeeds", "sign in",
       "api/settings_api.py"),
    _p("POST", "/api/preregister", "C", _PUBLIC, "natural", _HANDLER_TXN,
       "preregistration row", "upsert on email", "n/a", "api/app.py"),

    _p("POST", "/admin/broadcast", "C", _ADMIN, "operator_initiated",
       _HANDLER_TXN, "admin action log",
       "sends again — deliberately, an operator triggered it", "n/a",
       "api/app.py"),
    _p("POST", "/admin/debug/send-push", "C", _ADMIN, "operator_initiated",
       _HANDLER_TXN, "admin action log", "sends again", "n/a", "api/app.py"),
    _p("POST", "/admin/run-reminders", "C", _ADMIN, "operator_initiated",
       _HANDLER_TXN, "admin action log",
       "the reminder scheduler's own dedup applies", "n/a", "api/app.py"),
    _p("POST", "/admin/proactive-debug", "C", _ADMIN, "operator_initiated",
       _HANDLER_TXN, "admin action log", "re-runs the debug pass", "n/a",
       "api/app.py"),
    _p("POST", "/admin/profile-sync", "C", _ADMIN, "operator_initiated",
       _HANDLER_TXN, "admin action log", "re-syncs deterministically", "n/a",
       "api/app.py"),
    _p("POST", "/admin/profile-consolidate", "C", _ADMIN, "operator_initiated",
       _HANDLER_TXN, "admin action log", "re-consolidates deterministically",
       "n/a", "api/app.py"),
    _p("POST", "/admin/feedback/{feedback_id}/resolve", "C", _ADMIN,
       "natural", _HANDLER_TXN, "admin action log",
       "resolving a resolved item is a no-op", "re-open", "api/app.py"),

    # Transport ingress. No contract of its own on purpose — the chat lane it
    # hands off to owns turn identity and idempotency, and a second contract
    # at the edge would be a second place to get it wrong.
    _p("POST", "/webhook/{token}", "C", _HMAC, "delegated",
       "the turn coordinator", "delegated to the chat lane",
       "the chat lane's ProcessedTurn claim", "ledger undo", "api/app.py"),
    _p("POST", "/imessage", "C", _HMAC, "delegated", "the turn coordinator",
       "delegated to the chat lane", "the chat lane's ProcessedTurn claim",
       "ledger undo", "api/app.py"),
    _p("POST", "/imessage/start", "C", _HMAC, "natural", _HANDLER_TXN,
       "conversation start log", "starting an active thread is a no-op",
       "n/a", "api/app.py"),
    _p("POST", "/stripe-webhook", "C", _HMAC, "natural", _HANDLER_TXN,
       "subscription state audit row",
       "Stripe redelivers; the event id makes it an upsert", "n/a",
       "api/app.py"),
)


BY_KEY: dict = {p.key: p for p in POLICIES}


def policy_for(method: str, route: str) -> Optional[Policy]:
    return BY_KEY.get((method.upper(), route))


def _validate() -> None:
    """A malformed declaration is worse than none — it reads as a decision."""
    seen = set()
    for p in POLICIES:
        if p.key in seen:
            raise ValueError(f"duplicate policy for {p.method} {p.route}")
        seen.add(p.key)
        if p.mutation_class not in CLASS_REQUIREMENTS:
            raise ValueError(f"{p.route}: unknown class {p.mutation_class!r}")
        if p.idempotency not in IDEMPOTENCY:
            raise ValueError(
                f"{p.route}: unknown idempotency policy {p.idempotency!r}")
        for name in ("auth", "transaction_owner", "ledger", "replay",
                     "rollback", "owner"):
            if not getattr(p, name):
                raise ValueError(f"{p.route}: {name} is not declared")


_validate()
