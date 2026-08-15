"""⭐ THE INTERPRETATION BOUNDARY — surface language in, canonical identity out.

> **Surface language is for DISPLAY and AUDIT. Canonical identity comes from
> INTERPRETED FOOD MEANING.** *(Danny, 2026-08-14)*

⛔ WHY THIS EXISTS, MEASURED RATHER THAN ASSUMED. Over 691 real production food
entries the committed pricing artifact is the DECIDING rung on 13 — 1.9% — and
the largest unreachable population by a factor of three is food named in a
non-Latin script: 30.4%, versus 9.8% branded and 7.7% modifier-qualified. The
cause is not coverage. `Помидор` cannot reach `tomato|` however many identities
the artifact holds, because the identity key is built from the SURFACE STRING.

⭐ THE ARCHITECTURE ALREADY DECLARED THE SLOT. `EvidenceContext` requires a
non-empty `canonical_entity_id`, candidate sets refuse a candidate whose entity
differs from the set's subject, and `candidate_repository` persists it as
`subject_entity_id`. Its only producer is `quantity_clarification._entity_id_for`,
whose first branch reads a `FoodIdentity.canonical_entity_id` that **does not
exist as a field** — so the fallback always fires and the entity id is
`food:<surface lowercased>`. This module is the missing producer, not a new
identity system.

⭐⭐ THREE STATES, BECAUSE COLLAPSING DISTINCT FOODS IS THE FAILURE MODE.

    RESOLVED    this surface form denotes an entity the evidence layer already
                addresses               'Помидор' -> 'tomato'
    DISTINCT    a real food with NO faithful equivalent in the current entity
                space — it keeps its own canonical identity rather than being
                forced into a convenient English approximation
    UNRESOLVED  no judgement was reached; the caller keeps today's behaviour

`DISTINCT` is the one that does the work. `творог` is not "cottage cheese", and
the food interpreter's own prompt already warns that renaming a food can
quietly change which grade is the default — it is right. A design that could
only say RESOLVED or nothing would have to choose between a false mapping and
no mapping, and would take the false one every time the approximation looked
close enough.

⭐⭐⭐ AND `UNRESOLVED` REPRODUCES CURRENT BEHAVIOUR EXACTLY. That is the
monotonicity guarantee this slice is built around: resolution can only improve
reachability, and failing to resolve cannot make live traffic worse. It is why
the containment in `memory_key_is_addressable` could ship first and why this can
follow without a flag on the read path.

⚠ NOTHING HERE CALLS A MODEL. Settlement consumes the durable result and only
the durable result — `resolve()` is a lookup. Production of a resolution
belongs to the interpretation stage, where a model call is already being made
and its latency already paid, never to the settle path where `price()` is
synchronous by design (Gate B).
"""
from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

#: Bumped when the MEANING of a stored resolution changes — a new state, a
#: different target namespace, a changed key function. Stored on every row, so
#: a resolution written under an older contract is recognisably about a
#: different question rather than silently reused. See `is_current`.
RESOLVER_VERSION = "entity_resolution_v1"

#: The namespace `RESOLVED` targets. TODAY THIS IS THE EXISTING ARTIFACT ENTITY
#: SPACE — `tomato`, `rice`, `chicken` — and that is a deliberate migration
#: boundary (Danny, 2026-08-14): opaque ids are cleaner long-term, but adopting
#: them now would fuse two independent migrations and force a re-key and
#: re-freeze of the 27 signed winners before a single non-English food had been
#: resolved. The existing space already has the property that matters — the
#: evidence layer knows how to address it.
ENTITY_NAMESPACE = "artifact_entity_v1"


class ResolutionState(str, Enum):
    RESOLVED = "resolved"
    DISTINCT = "distinct"
    #: ⛔ A BRANDED PRODUCT, WHICH THIS LAYER DOES NOT OWN. Added 2026-08-14
    #: after a live probe returned `Simple Wolf Wrap (Original Dough)` as a
    #: DISTINCT FOOD. It is not a food identity — it is a product, and products
    #: belong to `Rung.PRODUCT`, whose producer is a later tranche.
    #:
    #: ⭐ THE STATE EXISTS SO THE POPULATION IS PRESERVED RATHER THAN
    #: MISFILED. Without it, PRODUCT-shaped traffic silently becomes DISTINCT
    #: merely because the resolver had three semantic states and none of them
    #: fitted — the same shape as `matched: 0` from an unmatched regex, where
    #: an unaskable question gets answered anyway.
    PRODUCT = "product"
    UNRESOLVED = "unresolved"


#: The states this layer may bind an identity from. PRODUCT is deliberately NOT
#: here: it names something real and records it durably, but the entity space it
#: belongs to does not exist yet, so binding it would let a product masquerade
#: as a generic food identity — precisely the ownership error being fixed.
BINDING = frozenset({ResolutionState.RESOLVED, ResolutionState.DISTINCT})

#: States that MAY carry an id. PRODUCT carries the product identity forward for
#: the tranche that will own it; UNRESOLVED must never carry anything.
MAY_NAME_AN_ENTITY = BINDING | {ResolutionState.PRODUCT}


def contract_fingerprint() -> str:
    """What a stored resolution was an answer TO.

    ⭐ A MOVED CONTRACT MAKES A STORED ANSWER UNVERIFIED, NOT WRONG — the same
    property `candidate_universe_fingerprint` gives a signed winner. A
    resolution recorded when `RESOLVED` targeted one namespace is not evidence
    about a different one, and reusing it would be answering a question nobody
    asked. Comparing fingerprints lets that expire honestly instead of either
    silently persisting or being thrown away wholesale.
    """
    raw = f"{RESOLVER_VERSION}|{ENTITY_NAMESPACE}".encode()
    return "erc_" + hashlib.sha256(raw).hexdigest()[:16]


def surface_key(surface: str) -> str:
    """A stable lookup key for a food name IN ANY SCRIPT.

    ⛔ DELIBERATELY NOT `normalize_name`. That function keeps `[a-z0-9 ]`, so
    every non-Latin character is deleted and `Творог 2%` becomes `'2'` — which
    is exactly how a user's cottage cheese came to be priced from their boiled
    corn (see `memory_key_is_addressable`). A key for the interpretation
    boundary must be able to TELL THESE FOODS APART, which is the one thing
    that key could not do.

    NFKC first so visually identical strings normalize together (full-width
    forms, composed vs decomposed accents), then casefold rather than lower()
    because casefold is the case-insensitive-comparison operation for non-ASCII
    scripts and `lower()` is not. Punctuation becomes a BOUNDARY rather than
    being deleted in place — gluing words together was how `steak/roast` became
    `steakroast` once already.
    """
    text = unicodedata.normalize("NFKC", surface or "").casefold().strip()
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return " ".join(text.split())


def normalize_entity_id(entity_id: str) -> str:
    """One spelling per identity, before anything else compares them.

    ⛔ MEASURED 2026-08-14: one live batch produced `tvorog`, `tvorog_5%` and
    `tvorog 5% fat` for one food family — three ids differing in PUNCTUATION and
    in SEMANTICS. This closes the punctuation half deterministically so the
    semantic half is the only thing the reuse step has to judge; without it the
    reuse step would spend a model call deciding that `tvorog_5%` and
    `tvorog 5%` are the same food, which is a question about typography.

    Percent signs survive as the word they mean, because a fat percentage is
    part of what the food IS and dropping it would merge 2% and 5% curd.
    """
    text = unicodedata.normalize("NFKC", entity_id or "").casefold().strip()
    text = text.replace("%", " percent ")
    text = "".join(ch if (ch.isalnum() or ch.isspace()) else " " for ch in text)
    return " ".join(text.split())


@dataclass(frozen=True)
class EntityResolution:
    """One surface form, and what it was judged to mean.

    PROVENANCE-BEARING FROM DAY ONE (Danny, 2026-08-14). Every field here
    answers a question someone will ask of a resolution later: what was asked,
    what was decided, by what, under which contract, and when. A resolution
    that cannot say which resolver produced it cannot be invalidated when that
    resolver is found to be wrong.
    """
    surface_form: str
    surface_key: str
    state: ResolutionState
    #: Empty unless the state BINDS. An UNRESOLVED row carrying an entity would
    #: be a decision wearing a non-decision's label.
    canonical_entity_id: str = ""
    #: The interpreted meaning, in whatever representation the producer used.
    #: Kept because the entity id alone cannot be audited — "why did Помидор
    #: become tomato" needs the interpretation, not just its conclusion.
    interpreted_meaning: str = ""
    #: BCP-47-ish when the producer could tell, empty when it could not. NEVER
    #: inferred from the script here: a script is not a language, and guessing
    #: would put a second unreviewed judgement inside a durable record.
    source_language: str = ""
    resolver_version: str = RESOLVER_VERSION
    #: The model that assisted, if any. Empty for a deterministic or human
    #: resolution — and those are different things from an unknown one, which
    #: is why this is not defaulted to a model name.
    model_id: str = ""
    contract_fingerprint: str = ""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    #: ⚠ ADVISORY ONLY, AND STRUCTURALLY SO. Neither field may be read by
    #: `resolve()` or by any consumer deciding what a food IS. Confidence
    #: thresholds are how a stochastic judgement becomes a silent policy: the
    #: state is the decision, and if a producer is unsure the honest output is
    #: UNRESOLVED rather than RESOLVED with a low number attached.
    confidence: Optional[float] = None
    reason: str = ""

    def __post_init__(self):
        if self.state in BINDING and not self.canonical_entity_id.strip():
            raise ValueError(
                f"{self.state.value} without a canonical_entity_id: a binding "
                f"state must name the entity it binds to")
        if (self.state not in MAY_NAME_AN_ENTITY
                and self.canonical_entity_id):
            raise ValueError(
                "UNRESOLVED carrying a canonical_entity_id — an absent answer "
                "must never be representable as a present one")

    @property
    def binds(self) -> bool:
        return self.state in BINDING

    def is_current(self, fingerprint: Optional[str] = None) -> bool:
        """Was this an answer to the question being asked NOW?

        A row from an older contract is not wrong; it is UNVERIFIED, and the
        caller must treat it exactly as it treats no row at all — which the
        monotonicity guarantee makes safe.
        """
        return self.contract_fingerprint == (fingerprint or contract_fingerprint())


def canonical_entity_id_for(resolution: Optional[EntityResolution]) -> str:
    """The entity id a settled turn should use, or `""` to keep today's path.

    ⭐ THE ONE FUNCTION SETTLEMENT CALLS, and every way of having no answer
    collapses here into the same empty string: no row, a stale contract, an
    UNRESOLVED judgement. That is the monotonicity guarantee expressed as code
    rather than as a promise — there is no branch in which a caller receives
    something it must interpret.
    """
    if resolution is None or not resolution.binds:
        return ""
    if not resolution.is_current():
        return ""
    return resolution.canonical_entity_id


# ══ THE DURABLE STORE ═══════════════════════════════════════════════════════
#
# ⭐ THE REPOSITORY LIVES BESIDE THE TYPES, not in `db.queries`, and the reason
# is an invariant rather than taste. `EntityResolution.__post_init__` is what
# forbids an UNRESOLVED row from carrying an entity; a writer that built its
# own row dict would bypass that check entirely. Every write here goes through
# the type, so the schema's guarantees and the type's cannot diverge.


def _to_domain(row) -> EntityResolution:
    return EntityResolution(
        surface_form=row.surface_form or "",
        surface_key=row.surface_key,
        state=ResolutionState(row.state),
        canonical_entity_id=row.canonical_entity_id or "",
        interpreted_meaning=row.interpreted_meaning or "",
        source_language=row.source_language or "",
        resolver_version=row.resolver_version or "",
        model_id=row.model_id or "",
        contract_fingerprint=row.contract_fingerprint or "",
        created_at=row.created_at, updated_at=row.updated_at,
        confidence=row.confidence, reason=row.reason or "")


async def resolve(db, surface: str) -> Optional[EntityResolution]:
    """This surface form's stored resolution, or None. A LOOKUP — never a model.

    ⚠ THE STALE-CONTRACT ROW IS RETURNED, NOT HIDDEN. `is_current` is the
    caller's question and `canonical_entity_id_for` already answers it by
    falling back; swallowing the row here would also hide it from the audit and
    from any tool that wants to re-resolve exactly the expired ones.
    """
    from sqlalchemy import select

    from db.models import FoodEntityResolution

    key = surface_key(surface)
    if not key:
        return None
    row = (await db.execute(
        select(FoodEntityResolution)
        .where(FoodEntityResolution.surface_key == key))).scalar_one_or_none()
    return None if row is None else _to_domain(row)


async def entity_id_for_surface(db, surface: str) -> str:
    """⭐ THE ONE CALL SETTLEMENT MAKES. `""` means "keep today's behaviour".

    Every way of having no answer — no row, a stale contract, an UNRESOLVED
    judgement — arrives here as the same empty string, so there is no branch in
    which a caller receives something it must interpret. That IS the
    monotonicity guarantee: resolution can improve reachability and failing to
    resolve cannot make live traffic worse.
    """
    return canonical_entity_id_for(await resolve(db, surface))


async def record(db, resolution: EntityResolution) -> EntityResolution:
    """Persist a resolution, replacing any earlier answer for the same surface.

    ⭐ THE FINGERPRINT IS STAMPED HERE, NOT ACCEPTED FROM THE CALLER. A producer
    that could choose its own contract id could claim currency it does not have,
    and the expiry mechanism would answer to whoever wrote last.

    ⚠ REPLACEMENT IS DELIBERATE AND NOT A MERGE. A newer resolution of the same
    string is a NEW ANSWER to the same question, so keeping fields from the old
    one would produce a row no single resolver ever asserted — the shape of
    defect that made a partial abstention read as a confident negative.
    """
    from sqlalchemy import select

    from db.models import FoodEntityResolution

    stamped = EntityResolution(**{**resolution.__dict__,
                                  "contract_fingerprint": contract_fingerprint(),
                                  # ⭐ NORMALIZED AT THE DOOR, not by the
                                  # producer. Every writer — model, human,
                                  # backfill — lands on one spelling, so two
                                  # rows can never disagree about an identity
                                  # purely typographically.
                                  "canonical_entity_id": normalize_entity_id(
                                      resolution.canonical_entity_id),
                                  "surface_key": surface_key(
                                      resolution.surface_form
                                      or resolution.surface_key)})
    row = (await db.execute(
        select(FoodEntityResolution).where(
            FoodEntityResolution.surface_key == stamped.surface_key)
    )).scalar_one_or_none()
    if row is None:
        row = FoodEntityResolution(surface_key=stamped.surface_key)
        db.add(row)
    row.surface_form = stamped.surface_form
    row.state = stamped.state.value
    row.canonical_entity_id = stamped.canonical_entity_id
    row.interpreted_meaning = stamped.interpreted_meaning
    row.source_language = stamped.source_language
    row.resolver_version = stamped.resolver_version
    row.model_id = stamped.model_id
    row.contract_fingerprint = stamped.contract_fingerprint
    row.confidence = stamped.confidence
    row.reason = stamped.reason
    await db.commit()
    return stamped


async def distinct_entities(db) -> dict:
    """`{canonical_entity_id: interpreted_meaning}` for every stored DISTINCT.

    ⭐ THE GROWING STORE THAT MAKES REUSE POSSIBLE WITHOUT A CATALOGUE. This is
    not a curated table: every entry got here by being resolved once, so the
    only foods it can offer are ones the system has already met. That is the
    difference between "which of the identities we have already established is
    this" — a legitimate question — and handing a model a list of 27 blessed
    entities, which would make everything outside the list DISTINCT by
    construction.
    """
    from sqlalchemy import select

    from db.models import FoodEntityResolution

    rows = (await db.execute(
        select(FoodEntityResolution.canonical_entity_id,
               FoodEntityResolution.interpreted_meaning)
        .where(FoodEntityResolution.state == ResolutionState.DISTINCT.value)
    )).all()
    # Last meaning wins per id; they describe the same food by construction.
    return {entity: meaning for entity, meaning in rows if entity}
