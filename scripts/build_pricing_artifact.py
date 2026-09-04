"""Build the qualified PRICING evidence artifact from real provider records.

    python scripts/build_pricing_artifact.py             # the seed identities
    python scripts/build_pricing_artifact.py chicken     # named entities
    python scripts/build_pricing_artifact.py --dry-run

THE ONLY THING THAT MAY ACQUIRE PRICING EVIDENCE. The runtime reader loads and
nothing else — no provider, no model, no generation on miss — which is what
lets `canonical_pricing.price()` be synchronous and still honest.

STORES THE QUALIFIED CANDIDATE SET, NOT A WINNER. `best_candidate` ranks at
runtime, deterministically. Committing a chosen record would move ranking
authority into whichever record the model preferred on generation day, and the
defect being fixed is precisely that a fresh qualification changed the winner:
"Chicken, fried" 120 g priced 295 kcal, then 329 kcal.

THE SAME FAILURE RULE AS THE MATERIALITY GENERATOR, for the same reason:

    provider/retrieval failure  ->  build FAILS, nothing written or replaced
    resolver batch failure      ->  build FAILS for that identity, and no
                                    authoritative negative result is written

An identity absent from the artifact is READ as "no qualified pricing evidence
exists", which sends pricing to the estimate rung. Writing that because USDA
503'd would be asserting a fact nobody established.
"""
from __future__ import annotations

#: The provider this adapter speaks for. Every candidate it emits is named
#: SOURCE-QUALIFIED, because an evidence id is a namespace plus a local id and
#: never the local id alone.
SOURCE = "usda"

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
from datetime import datetime, timezone

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.WARNING, format="%(message)s")
for _noisy in ("httpx", "httpcore", "anthropic", "openai", "urllib3"):
    logging.getLogger(_noisy).setLevel(logging.ERROR)

#: Rows per qualification call. The bound is on the model's OUTPUT,
#: which USDA's verbose descriptions inflate — see build_one.
_QUALIFY_BATCH = 3

#: Attempts per batch. Truncation is per-reply, so a retry usually
#: parses; a batch that fails all attempts fails the identity.
_QUALIFY_ATTEMPTS = 3
#: Retrieval rounds per identity when a provider query gives NO answer
#: (timeout / non-200). Provider-only: a semantic abstention is never retried.
_PROVIDER_ATTEMPTS = 3
_PROVIDER_BACKOFF_S = 1.5

MATERIAL, EMPTY, FAILED = "ok", "no_evidence", "failed"

#: Identities to prewarm: each seed entity crossed with "" (no preparation)
#: and every registered preparation. NOT a claim about which foods matter —
#: the qualifier decides what survives, and an entity that yields nothing
#: simply gets no entry.
#:
#: ⭐ THE ADMISSION RULE FOR THIS LIST *(Danny, 2026-08-11)*:
#:
#:     A seed entry may be added ONLY when a shipped canonical policy requires
#:     deterministic pricing support for it, or when observed production
#:     demand demonstrates repeated need.
#:
#: "Seems likely someone will log this" is NOT a criterion. It turns a curated
#: set into an intuition-driven catalog, and the directive's own rule is
#: measure before generalize.
SEED = ("chicken", "potato", "egg", "beef", "salmon", "rice", "shrimp",
        "tofu", "cauliflower", "mushrooms", "mackerel", "tilapia",
        "asparagus", "broccoli", "oats", "banana",
        # B-1.7a — REQUIRED VOCABULARY BACKING, not speculation. These are
        # exactly the five ids `added_fat_ontology.OFFERED` declares, and the
        # field cannot be offered at all until they price: an id the pricer
        # cannot act on is inert, and a chip that changes nothing is worse
        # than no chip because its usage rate looks like engagement.
        "olive oil", "butter", "vegetable oil", "coconut oil", "mayonnaise")


class _CountUsdaFailures(logging.Handler):
    """`api.usda._search` swallows every non-200 and returns []. The only
    honest signal a query failed is the warning it already emits."""

    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.failures = 0

    def emit(self, record):
        if "USDA search" in str(record.getMessage()):
            self.failures += 1


def _row_fingerprint(row: dict) -> str:
    """What the annotation was made ABOUT. If the source row changes, the
    judgement is about something else and `source_changed` is an attributable
    invalidation cause rather than silent drift."""
    import hashlib

    material = json.dumps({k: row.get(k) for k in
                           ("fdc_id", "description", "data_type", "per100g")},
                          sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(material.encode()).hexdigest()[:16]


def retrieval_queries(identity: str, expanded) -> list:
    """THE ONE PLACE the retrieval query list is spelled: the (stored or fresh)
    expansion first, then every fixed shape not already in it. The capture gate
    calls this too, so it can never drift into a second implementation."""
    from skills.nutrition import pricing_artifact as art
    expanded = [str(q) for q in (expanded or ())]
    return expanded + [s.format(identity=identity) for s in art.QUERY_SHAPES
                       if s.format(identity=identity) not in expanded]


async def build_one(entity: str, preparation: str, store=None, expansion=None, expansions_out=None,
                    identity_key: str = "") -> dict:
    """The qualified candidate set for one (entity, preparation)."""
    import api.usda as usda
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition.evidence_qualification import qualify_usda_rows
    from skills.nutrition import preparation_ontology as prep_onto

    identity = prep_onto.name_with(entity, preparation) if preparation \
        else entity

    # ⭐⭐⭐ QUERY EXPANSION — RECALL ONLY, AUTHORITY UNTOUCHED. Proven
    # 2026-09-01 on the 86-item dev census: 20 identities recovered, 0
    # qualification regressions, 16 of the 20 non-Latin. It returns QUERIES
    # and nothing else; every candidate it surfaces still faces the unchanged
    # `qualify_usda_rows`. It fails OPEN to the two fixed shapes below, so a
    # model outage degrades recall to exactly today's, never to nothing.
    #
    # IR-PUBLISH (2026-09-03): re-applied for publication. No new retrieval
    # ideas — this is the mechanism as measured.
    from skills.nutrition.retrieval_intent import expand

    # ⭐ EXPANSION IS MEMOIZED IN THE ARTIFACT (2026-09-03), like annotations.
    # `expand()` is a model call: rebuilds #2→#3→#4 of identical code moved the
    # retrieved pool of 3 of 9 pinned seeds and made beef|grilled reprice under
    # V2 off on the 4th build. A publication gate cannot be stably green over a
    # re-rolled retrieval. Stored queries are reused under the same
    # EXPANSION_VERSION; a version bump re-rolls everything, deliberately.
    if expansion:
        expanded = [str(q) for q in expansion]
    else:
        intent = await expand(identity)
        expanded = list(intent.queries)
    if expansions_out is not None:
        expansions_out[identity_key or art.key(entity, preparation)] = list(expanded)
    queries = retrieval_queries(identity, expanded)

    # ⛔ A PROVIDER BLIP IS RETRIED HERE, BOUNDED, AND NOTHING ELSE IS. One
    # timed-out shape query out of five failed `egg|fried`, and because the
    # build refuses to write on ANY failure, 83 identities' qualification
    # (annotations live in the written artifact) was discarded with it —
    # 10.5 minutes to learn one HTTP call had timed out. Retrying a query
    # that gave NO ANSWER asks the same question again; the semantic path
    # below never re-enters this loop (a judge that answered is not re-asked).
    attempt, failed, batches = 0, 0, ()
    for attempt in range(1, _PROVIDER_ATTEMPTS + 1):
        counter = _CountUsdaFailures()
        usda.logger.addHandler(counter)
        try:
            batches = await asyncio.gather(
                *(usda._search(q, list(art.DATA_TYPES), art.ROWS_PER_SHAPE)
                  for q in queries), return_exceptions=True)
        finally:
            usda.logger.removeHandler(counter)
        failed = counter.failures + sum(isinstance(b, Exception) for b in batches)
        if not failed:
            if attempt > 1:
                print(f"    {identity:28} provider recovered on attempt {attempt}")
            break
        if attempt < _PROVIDER_ATTEMPTS:
            await asyncio.sleep(_PROVIDER_BACKOFF_S * attempt)

    rows, seen = [], set()
    for batch in batches:
        if isinstance(batch, Exception):
            continue
        for row in batch or ():
            fid = str(row.get("fdc_id") or row.get("description"))
            if fid in seen:
                continue
            seen.add(fid)
            rows.append(row)

    import hashlib as _hl

    def _population_fp(rs):
        """What the judgement was ABOUT: sorted provider ids of the retrieved
        pool. A review bound to this expires the moment retrieval changes."""
        return "sha256:" + _hl.sha256(",".join(sorted(
            str(r.get("fdc_id") or r.get("description") or "") for r in rs
        )).encode()).hexdigest()[:16]

    if failed:
        # ⛔ RETRYABLE, and ONLY this is. The query returned NO ANSWER — retrying
        # asks the same question again. A semantic abstention is a judge that
        # DID answer; re-asking it until it agrees is sampling, not retrying.
        return {"identity": identity, "status": FAILED,
                "failure_class": "RETRYABLE_PROVIDER",
                "reason": f"{failed}/{len(queries)} provider queries failed "
                          f"after {attempt} attempt(s)",
                "provider_attempts": attempt}
    if not rows:
        return {"identity": identity, "status": EMPTY,
                "reason": "no curated rows"}

    # ── ⭐ MECHANICAL ELIGIBILITY, ON THE RETRIEVAL POPULATION, BEFORE THE
    # RESOLVER IS CONSULTED.
    #
    # Phases 0.1-0.3 and 0.5 built this layer and NOTHING CALLED IT. The
    # module had no non-test importer at all, so every veto it can prove was
    # exercised only by its own tests — the same shape as the enum member that
    # was present in main and constructed exactly once. A capability that is
    # correct, tested, and unreachable is not a capability.
    #
    # Placement is the point: run after qualification and the semantic layer
    # has already removed these rows, making the veto ceremonial. Run HERE and
    # a record that never mentions the requested food is refused for a typed
    # mechanical reason, is never sent to the model, and costs nothing.
    from types import SimpleNamespace

    from skills.nutrition import eligibility as el

    def _as_record(row):
        """Adapt a provider row to what the eligibility layer reads."""
        return SimpleNamespace(
            evidence_id=f"usda:{row.get('fdc_id')}",
            title=row.get("description") or "",
            structured={"data_type": row.get("data_type") or ""},
            nutrition=row.get("per100g") or {},
            provider_record_id=str(row.get("fdc_id") or ""))

    mechanical = el.vetoes([_as_record(r) for r in rows],
                           generic_intent=True,
                           requested_identity=identity,
                           base_entity=entity,
                           # ⭐ THE ADAPTER ASSERTS ITS OWN NAMESPACE. This
                           # module speaks USDA English, the lexical veto was
                           # measured at precision 1.00 against exactly that,
                           # and naming the provider HERE is legitimate —
                           # source belongs to evidence.
                           lexical_veto_validated=(SOURCE == "usda"))
    # ⛔ EVERY REASON THE LAYER EMITS, NOT ONE OF THEM. The first wiring
    # filtered to BASE_FOOD_MISMATCH alone, so `vetoes()` computed the
    # cooking-state conflict, the heat-medium conflict, the branded-for-generic
    # exclusion, the duplicate and the no-energy refusal — and the build threw
    # all five away. "Phases 0.1-0.3 are wired" was a stronger claim than the
    # code supported: the CALL was there and the RESULT was discarded, which
    # looks identical to being wired from any distance except this line.
    refused = {v.evidence_id: v.reason for v in mechanical}
    if refused:
        print(f"    {identity_key or entity:<28} {len(refused)} row(s) "
              f"MECHANICALLY REFUSED before the resolver "
              f"({el.BASE_FOOD_MISMATCH})")
        rows = [r for r in rows
                if f"usda:{r.get('fdc_id')}" not in refused]
        if not rows:
            # ⛔ Refusing every row is a RETRIEVAL outcome, not an admission
            # one — the same reasoning that stops a rejection emptying an
            # entry. Say so rather than reporting an empty identity.
            return {"identity": identity, "status": EMPTY,
                    "reason": f"all rows mechanically refused: "
                              f"{el.BASE_FOOD_MISMATCH}",
                    "mechanically_refused": refused}

    # QUALIFICATION IS THE EXPENSIVE STEP, and moving it here is the entire
    # point: measured 6,538-13,546 ms per call on the settle path.
    #
    # ⭐ BATCHED, because the failure mode is OUTPUT LENGTH, not record count.
    # Measured 2026-08-08: eight mackerel rows produced a reply truncated
    # mid-string — `JSONDecodeError: Unterminated string` — after 30,958 ms,
    # and `resolve` correctly abstained the WHOLE batch. That is the root
    # cause of entry 2932: qualification kept nothing, USDA contributed
    # nothing, and the legacy ladder priced 80 g of mackerel at 0.0 kcal.
    # Long USDA descriptions ("Fish, mackerel, Atlantic, raw") make the reply
    # longer per record, so a fixed record cap cannot bound it — smaller
    # batches can, and offline they are free.
    # ⭐ PHASE 0.4 — REUSE BEFORE RESOLVING. A pair this artifact has already
    # judged is not re-judged: not because the model would probably agree,
    # but because an ordinary rebuild is not authority to change a semantic
    # fact. Only rows with no resolved annotation reach the resolver at all.
    from skills.nutrition import semantic_annotations as sa
    from skills.nutrition.evidence_semantics import RESOLVER_MODEL

    store = store if store is not None else sa.Store()
    identity_key = identity_key or f"{entity}|{preparation}"
    unseen = [r for r in rows
              if store.needs_resolution(identity_key,
                                        f"usda:{r.get('fdc_id')}",
                                        _row_fingerprint(r))]
    restated = [r for r in unseen
                if store.stale_source(identity_key, f"usda:{r.get('fdc_id')}",
                                      _row_fingerprint(r))]
    if restated:
        print(f"    {identity_key:<28} {len(restated)} row(s) CHANGED "
              f"UPSTREAM — re-annotating with cause=source_changed")
    if not unseen:
        print(f"    {identity_key:<28} {len(rows)} rows, ALL ANNOTATED — "
              f"resolver not called")

    kept, seen_ids = [], set()

    async def _qualify(chunk):
        """One chunk's `Qualification`, with the bounded retry.

        BOUNDED RETRY, because truncation is a property of THIS reply, not of
        the food: the same chunk usually parses on a second attempt. The rule is
        unchanged — a batch that still fails after retries fails the identity
        rather than being written as "no evidence". Without this, 64 identities
        × one transient failure makes the artifact unbuildable, which would be
        the rule defeating its own purpose.
        """
        q = None
        for _attempt in range(_QUALIFY_ATTEMPTS):
            try:
                q = await qualify_usda_rows(identity, chunk)
            except Exception:
                q = None
            if q is not None and not (
                    getattr(q, "disposition", "") ==
                    "resolver_down_no_candidates" and not q.rows):
                break
        return q

    # ⭐⭐⭐ CHUNKS QUALIFY CONCURRENTLY, AND THAT WAS ONLY SAFE ONCE THE
    # ASSESSMENT KEY WAS SCOPED TO ITS ROWS *(2026-09-01)*. `EvidenceContext`
    # is SINGLE-FLIGHT: while the key said merely "an assessment of chicken",
    # concurrent chunks would every one of them receive the FIRST chunk's
    # result — the serial loop was already suffering that inside a turn, and
    # gathering would have made it universal.
    #
    # ⭐ LATENCY WAS LINEAR IN ROW COUNT, WHICH PENALISED EXACTLY THE WRONG
    # FOODS. Measured: monkfish (few rows) 2.43 s, brown rice (13 rows)
    # 17.04 s, sweet potato (16 rows) 21.67 s — six sequential model calls.
    # The MOST logged foods have the MOST candidate rows, so the common case
    # was the slowest and the least likely to fit any user-facing budget.
    # Concurrent, the cost is ~ONE chunk regardless of how many there are.
    #
    # ⛔ THE AWAIT IS PARALLEL; THE PROCESSING BELOW STAYS SERIAL AND ORDERED.
    # `gather` preserves input order, and the loop that consumes these results
    # writes annotations and appends candidates — order-dependent work that
    # must not race. Nothing about WHICH rows are qualified, or how, changes.
    _chunks = [unseen[i:i + _QUALIFY_BATCH]
               for i in range(0, len(unseen), _QUALIFY_BATCH)]
    _qualifications = await asyncio.gather(
        *(_qualify(c) for c in _chunks), return_exceptions=True)

    for chunk, q in zip(_chunks, _qualifications):
        if isinstance(q, BaseException):
            # An exception that escaped the retry is an UNAVAILABLE resolver,
            # not a negative verdict — same rule the serial version obeyed.
            q = None

        # ⭐ A RESOLVER OUTAGE NO LONGER FAILS THE IDENTITY. It leaves these
        # rows UNRESOLVED — preserved, recorded, revisitable — while every
        # pair already annotated prices exactly as before. That is gate
        # 0.4.2: model availability cannot change known output. Previously
        # this returned FAILED and the whole identity was refused, which is
        # why one bad reply could cost `mackerel|roasted` three valid rows.
        usable = q is not None and not (
            getattr(q, "disposition", "") == "resolver_down_no_candidates"
            and not q.rows)
        judged = {str(r.get("fdc_id")) for r in ((q.rows if q else None) or ())}
        # rows the model declined to assess — never a negative verdict
        abstained_ids = {str(r.get("fdc_id"))
                         for r in (getattr(q, "abstained", None) or ())}

        for row in chunk:
            evidence_id = f"usda:{row.get('fdc_id')}"
            if not usable:
                store.record(sa.Annotation(
                    identity_key=identity_key, evidence_id=evidence_id,
                    relationship=sa.UNRESOLVED, confidence=0.0,
                    resolver_model=RESOLVER_MODEL,
                    source_fingerprint=_row_fingerprint(row)))
                continue
            # ⛔ AN ABSENT ANSWER IS NOT A NEGATIVE ANSWER. "Anything it saw
            # and did not keep is a judged negative" was FALSE for the rows the
            # model ABSTAINED on. Only an ALL-abstain batch is treated as an
            # outage upstream; a PARTIAL abstention returns `qualified`, the
            # unjudged rows fall out of `kept`, and this line then wrote
            # DIFFERENT_IDENTITY at confidence 0.95 — a durable, confident
            # verdict about a row nobody assessed. `needs_resolution` sees a
            # resolved annotation and never reopens it, so the row is gone for
            # good, and afterwards it is indistinguishable from a real
            # rejection.
            #
            # This is `541ed12` one layer down: the qualifier stopped deleting
            # evidence, and the store write underneath it kept doing so.
            if str(row.get("fdc_id")) in abstained_ids:
                store.record(sa.Annotation(
                    identity_key=identity_key, evidence_id=evidence_id,
                    relationship=sa.UNRESOLVED, confidence=0.0,
                    resolver_model=RESOLVER_MODEL,
                    resolver_version=getattr(q, "resolver_version", "") or "",
                    source_fingerprint=_row_fingerprint(row)))
                # deliberately NOT appended to resolved_this_build: nothing was
                # resolved, and counting it would let a population run report
                # work it did not do.
                continue

            # The resolver KEPT it -> it judged the pair identity-bearing at
            # or above its own floor. Anything it saw, ASSESSED, and did not
            # keep is a judged negative. Both are recorded; only the first can
            # price.
            hit = str(row.get("fdc_id")) in judged
            fingerprint = _row_fingerprint(row)
            cause = (sa.SOURCE_CHANGED
                     if store.stale_source(identity_key, evidence_id,
                                           fingerprint) else "")
            store.record(sa.Annotation(
                identity_key=identity_key, evidence_id=evidence_id,
                relationship=(sa.SAME_IDENTITY if hit
                              else sa.DIFFERENT_IDENTITY),
                confidence=(0.95 if hit else 0.95),
                resolver_model=RESOLVER_MODEL,
                resolver_version=getattr(q, "resolver_version", "") or "",
                source_fingerprint=fingerprint), cause=cause)
            store.resolved_this_build.append((identity_key, evidence_id))

    # ⭐ THE CANDIDATE SET IS NOW A POLICY RESULT OVER STORED ANNOTATIONS,
    # not whatever the resolver happened to return this run. Reused and newly
    # written annotations are read the same way, by the same code.
    unresolved = []
    for row in rows:
        evidence_id = f"usda:{row.get('fdc_id')}"
        annotation = store.get(identity_key, evidence_id)
        if sa.eligible(annotation):
            fid = str(row.get("fdc_id"))
            if fid not in seen_ids:
                seen_ids.add(fid)
                kept.append(row)
        elif sa.disposition(annotation).startswith("unresolved"):
            unresolved.append(evidence_id)

    # ⛔ THE SOURCE QUALIFICATION WAS APPLIED TO THE DATA AND NOT TO THE
    # PRODUCER. `candidate_evidence_id` was added, the committed artifact was
    # backfilled, gates were written — and this line kept emitting candidates
    # carrying only `fdc_id`, so THE NEXT REAL BUILD WOULD HAVE WRITTEN AN
    # ARTIFACT WITH NO NAMESPACES AT ALL, silently reverting the portability
    # fix while every existing gate stayed green against the backfilled file.
    #
    # Naming the provider HERE is legitimate and is why the portability gates
    # exclude evidence adapters: source belongs to evidence. What may not
    # happen is a bare provider-local number escaping into the artifact, where
    # a second source's identical id would merge with it.
    # ⚠ `data_type` IS CARRIED, and leaving it out disabled a veto silently.
    # The artifact's candidates never stored it, so a capture built from the
    # artifact had to default every row to a curated type — which means
    # `BRANDED_FOR_GENERIC` could not fire, and two HOUSE FOODS rows that the
    # mechanical layer would refuse for free had to be rejected by hand
    # instead. A corpus that cannot exercise a veto is a corpus that quietly
    # proves less than it appears to.
    # ⛔⛔ AND THE SERVING PANEL IS CARRIED FOR EXACTLY THE SAME REASON — P17c,
    # 2026-08-17. `api.usda` has extracted `serving_text` / `serving_mass_g` /
    # `serving_ml` on every candidate the whole time, with a comment saying it
    # is "carried so a COUNT portion ('15 pieces') can be given a mass from the
    # record that is answering" — and this line then threw all three away.
    # Measured: 0 of 124 committed candidates carried a panel.
    #
    # So the sourced measure that would let "2 eggs" resolve was being FETCHED
    # AND DISCARDED at build time, one field over from the `data_type` drop
    # above. A count-only portion was left unpriceable by construction, which is
    # 142 of 207 declining items and the largest single mechanism P16 found.
    kept = [{"evidence_id": f"{SOURCE}:{r.get('fdc_id')}",
             "source": SOURCE,
             "fdc_id": r.get("fdc_id"), "description": r.get("description"),
             "data_type": r.get("data_type") or "",
             "per100g": r.get("per100g") or {},
             "serving_text": r.get("serving_text") or "",
             "serving_mass_g": r.get("serving_mass_g"),
             "serving_ml": r.get("serving_ml")}
            for r in kept if (r.get("per100g") or {}).get("calories")]
    if not kept:
        # UNRESOLVED IS NOT "NO EVIDENCE". If nothing priced because nothing
        # is annotated yet, that is a gap to revisit, not a verdict — and it
        # must not be written as an authoritative negative.
        if unresolved:
            # ⛔ THE LIST IS CARRIED, NOT JUST ITS LENGTH. This branch quoted
            # `len(unresolved)` in the reason and dropped the list itself, so
            # every consumer reading `result["unresolved"]` saw nothing for
            # exactly the identities in the worst shape — nothing priceable
            # and rows still outstanding. A caller counting outstanding work
            # would undercount precisely where it mattered most.
            return {"identity": identity, "status": FAILED,
                    "failure_class": "SEMANTIC_UNRESOLVED",
                    "reason": f"{len(unresolved)} of {len(rows)} rows "
                              f"unresolved; none annotated as priceable",
                    "unresolved": tuple(unresolved),
                    "candidate_fingerprint": _population_fp(rows)}
        return {"identity": identity, "status": EMPTY,
                "reason": f"0 of {len(rows)} rows priceable by policy",
                "candidate_fingerprint": _population_fp(rows)}
    # ⭐ WHAT THIS JUDGEMENT WAS ABOUT. A reviewed pin or decline is a
    # statement about a SPECIFIC candidate population; it must expire when the
    # population moves, or an old review silently suppresses new evidence.
    result = {"identity": identity, "status": MATERIAL, "candidates": kept,
              "raw": len(rows), "unresolved": tuple(unresolved),
              "candidate_fingerprint": _population_fp(rows)}
    if refused:
        # ATTRIBUTABLE: a row that left before the model saw it still says why
        result["mechanically_refused"] = refused
    return result


def _retain_unexplained(entries: dict, store=None) -> int:
    """Carry forward committed candidates this build cannot account for.

    Returns how many were retained, so the caller can report it rather than
    absorb it. THE REPORT IS THE POINT: silent retention would hide a real
    upstream removal just as surely as silent dropping hides a flaky one.

    ⛔⛔ THE CODE NOW MATCHES THE CONTRACT *(IR-PUBLISH, 2026-09-03)*. This
    docstring always said "unless something can attribute its removal", and the
    loop below retained UNCONDITIONALLY — every prior candidate absent from the
    new build came back, explained or not. That is how a safety net becomes a
    liability: it cannot tell "a flaky build lost this row" from "a corrected
    rule deliberately rejected it", and it will silently reinstate the second.
    It nearly re-admitted the potato SKIN rows the whole-vs-part rule had just
    learned to refuse.

    ATTRIBUTION IS NOW READ FROM THIS BUILD'S OWN ANNOTATIONS: a prior candidate
    that this build judged — any RESOLVED relationship, positive or negative,
    or a policy drop after a positive one — is EXPLAINED and stays out. Only a
    candidate this build never reached a judgement on (no annotation, or
    UNRESOLVED) is unexplained and is retained. Absence of a judgement is the
    only thing retention may repair.
    """
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition import semantic_annotations as sa

    if not art.ARTIFACT_PATH.exists():
        return 0
    try:
        prior = json.loads(art.ARTIFACT_PATH.read_text()).get("entries") or {}
    except Exception:
        print("  the committed artifact will not parse — nothing to retain",
              file=sys.stderr)
        return 0

    # ⭐ A SIGNED NON-DECISION IS A DECISION (2026-09-03). `mayonnaise|` carried
    # usda:173594 — a row a reviewer signed UNRESOLVED ("declined to rule") —
    # because this predicate read every UNRESOLVED as "nobody looked" and
    # retained the loss. `sa.reviewed()` makes the person's refusal attributable.
    def _explained(key: str, cand: dict) -> bool:
        if store is None:
            return False                                  # no judgements to consult
        ann = store.get(key, str(cand.get("evidence_id") or ""))
        return ann is not None and (ann.relationship != sa.UNRESOLVED or sa.reviewed(ann))

    retained = 0
    for key, before in prior.items():
        old_c = list(before.get("candidates") or ())
        if not old_c:
            continue
        now = entries.get(key)
        have = {str(c.get("fdc_id")) for c in (now or {}).get("candidates") or ()}
        missing = [c for c in old_c if str(c.get("fdc_id")) not in have]
        explained = [c for c in missing if _explained(key, c)]
        if explained:
            print(f"  ATTRIBUTED {len(explained)} removal(s) on {key} to this "
                  f"build's own judgement — NOT retained: "
                  f"{[c.get('fdc_id') for c in explained]}")
        missing = [c for c in missing if not _explained(key, c)]
        if not missing:
            continue
        entries.setdefault(key, {"candidates": []})
        entries[key]["candidates"] = list(
            entries[key].get("candidates") or ()) + missing
        retained += len(missing)
        print(f"  RETAINED {len(missing)} unexplained candidate(s) on {key}: "
              f"{[c.get('fdc_id') for c in missing]}")
    return retained


def _apply_reviewed_pins(_by_key, entries, pins):
    """Hold reviewed seeds on their v1 candidate set. Pure over its inputs so the
    contract has its negative cases (tests/test_a_pin_holds_under_its_instrument_and_expires_with_it.py):
    a pin under another resolver/retrieval instrument does NOT apply and says so;
    expansion pool drift does NOT expire it; empty candidates never pin."""
    from skills.nutrition import pricing_artifact as art
    pinned_doc = {}
    for key, pin in pins.items():
        r = _by_key.get(key)
        want = pin.get("expanded_candidate_fingerprint")
        got = (r or {}).get("candidate_fingerprint")
        # ⭐ A PIN IS BOUND TO THE INSTRUMENT, NOT TO ONE EXPANSION'S POOL
        # (2026-09-03). beef| and oats| populations moved between rebuilds #2
        # and #3 with nothing but expansion nondeterminism in between; a hold
        # that expires on a coin flip is not a hold. The reviewed conclusion —
        # "v1's candidates are this seed's evidence under this resolver and
        # this retrieval instrument" — does not depend on which extra rows the
        # pool happened to contain. Resolver/retrieval change -> re-review.
        # Pool drift -> noted, applied. (Declines stay pool-bound: their
        # conclusion IS about the pool.)
        if (pin.get("resolver_version") != art.resolver_version()
                or pin.get("retrieval_fingerprint") != art.retrieval_fingerprint()):
            print(f"  PIN DOES NOT APPLY to {key}: reviewed under {pin.get('resolver_version')} / "
                  f"{str(pin.get('retrieval_fingerprint'))[:18]} — re-review before publishing")
            continue
        if not pin.get("candidates"):
            print(f"  PIN DOES NOT APPLY to {key}: no reviewed candidates")
            continue
        if want and got and want != got:
            print(f"  PIN NOTE {key}: population moved {want} -> {got} since review (expansion drift); held")
        entries[key] = {"candidates": list(pin["candidates"])}
        pinned_doc[key] = {k: v for k, v in pin.items() if k != "candidates"}
        pinned_doc[key]["observed_candidate_fingerprint"] = got
        pinned_doc[key]["pinned_evidence_ids"] = [c.get("evidence_id") for c in pin["candidates"]]
        print(f"  PINNED {key}: held on reviewed candidate set ({pin.get('reason')})")
    return pinned_doc


def _candidate_ids(entries: dict) -> dict:
    """fdc_id lists per key — the shape the raw-vs-final report compares.

    A SNAPSHOT, not a view: `_retain_unexplained` and `_apply_reviewed_pins`
    both rewrite `entries` in place, so a snapshot taken before a stage runs is
    the only record of what that stage started from."""
    return {k: [c.get("fdc_id") for c in (v or {}).get("candidates") or ()]
            for k, v in entries.items()}


def _attribute_alterations(raw_ids: dict, after_retention_ids: dict,
                           final_ids: dict, pinned_doc: dict,
                           declined_doc: dict) -> dict:
    """Charge every altered key to the mechanism that altered it. Pure.

    ⛔ ONE DIFF WAS CARRYING THREE MECHANISMS (2026-09-03, rebuild #8). The
    report diffed the raw snapshot against `entries` AFTER pins had run and
    printed "RETENTION ALTERED 5 existing key(s)" on a build where retention
    printed no RETAINED line at all: the five were the pinned seeds, held by
    `_apply_reviewed_pins`. That is the safety-net tally absorbing a reviewed
    hold — stating the WEAKER claim ("the net acted") on a build where the
    stronger one was true (generation stood on its own; a person held five
    seeds on purpose). tests/test_a_pin_is_not_charged_to_retention.py

      retention     raw snapshot -> snapshot taken after `_retain_unexplained`
                    and BEFORE pins
      pins          that snapshot -> final, on the keys `pinned_doc` names
      declines      never touch `entries` (a declined seed is FAILED and was
                    never generated); counted from their own doc
      unattributed  a key that moved after retention and is in no pin doc —
                    a mechanism this report does not know. Named, never absorbed.
    """
    retention_changed = [k for k, ids in raw_ids.items()
                         if ids != (after_retention_ids.get(k) or [])]
    retention_restored = sorted(set(after_retention_ids) - set(raw_ids))
    pinned = sorted(pinned_doc or ())
    moved_after_retention = [
        k for k in sorted(set(after_retention_ids) | set(final_ids))
        if (after_retention_ids.get(k) or []) != (final_ids.get(k) or [])]
    return {
        "retention_changed": retention_changed,
        "retention_restored": retention_restored,
        "pinned": pinned,
        "pinned_altered": [k for k in moved_after_retention if k in pinned],
        "declined": sorted(declined_doc or ()),
        "unattributed": [k for k in moved_after_retention if k not in pinned],
    }


def _report_raw_vs_final(raw_ids: dict, after_retention_ids: dict,
                         final_ids: dict, pinned_doc: dict,
                         declined_doc: dict) -> dict:
    """Two truths, stated separately, so "stable because generation is stable"
    can never be confused with "stable because retention repaired instability".
    The second is a safety net working; only the first is reproducibility. A
    reviewed pin is neither — it is a person's decision, and is reported as one.
    Returns the attribution so a test can assert on the numbers it printed."""
    a = _attribute_alterations(raw_ids, after_retention_ids, final_ids,
                               pinned_doc, declined_doc)
    changed, restored = a["retention_changed"], a["retention_restored"]
    print(f"\nRAW GENERATION      {len(raw_ids)} identities")
    print(f"AFTER RETENTION     {len(after_retention_ids)} identities")
    if changed or restored:
        print(f"RETENTION ALTERED   {len(changed)} existing key(s), "
              f"restored {len(restored)} whole key(s): {restored or '-'}")
        if changed:
            print(f"  altered: {changed}")
        print("  -> raw generation is NOT independently reproducible against "
              "the committed baseline; the artifact is production-safe "
              "because the safety net acted, which is a WEAKER claim")
    else:
        print("RETENTION ALTERED   nothing — generation stood on its own")
    print(f"PINNED (held on reviewed set) {len(a['pinned'])} key(s), "
          f"{len(a['pinned_altered'])} differ from generation: {a['pinned'] or '-'}")
    print(f"DECLINED            {len(a['declined'])} key(s): {a['declined'] or '-'}")
    if a["unattributed"]:
        print(f"UNATTRIBUTED        {len(a['unattributed'])} key(s) moved after "
              f"retention by no mechanism this report knows: {a['unattributed']}")
    return a


def _stored_annotations(doc) -> dict:
    """Every annotation the committed artifact carries, from BOTH layouts.

    ⛔⛔ THE HUMAN LAYER WAS SILENTLY DROPPED BY EVERY REBUILD SINCE THE LAYOUT
    MOVED (found 2026-09-03). The committed artifact stores annotations under
    `meta.annotations` — 272 rows, 84 of them `baseline_reviewed` (a person
    ADMITTED omelet/scrambled for `egg|`, microwaved potato, all four cooked
    mackerel rows for `mackerel|roasted`, …). The producer read and wrote
    `annotations` at the TOP LEVEL, so `loaded 0 existing semantic annotation(s)`
    was true on every build, the model re-rolled the 84 signed pairs, labelled
    them DIFFERENT_IDENTITY, and attribution-aware retention correctly refused to
    reinstate a "judged" rejection. Two implementations of one notion — the
    failure family this migration keeps finding. Where the same pair appears in
    both layouts, a REVIEWED row wins; otherwise the newer (top-level) row wins.
    """
    from skills.nutrition import semantic_annotations as sa
    doc = doc or {}
    legacy = ((doc.get("meta") or {}).get("annotations")) or {}
    current = doc.get("annotations") or {}
    merged = dict(legacy)
    for k, v in current.items():
        old = merged.get(k)
        if old and isinstance(old, dict) and old.get("review_status") == sa.BASELINE_REVIEWED \
                and not (isinstance(v, dict) and v.get("review_status") == sa.BASELINE_REVIEWED):
            continue                                   # a person's decision outranks a model's
        merged[k] = v
    return merged


def _stored_expansions(doc) -> dict:
    """Expansion queries the committed artifact was built with, reusable ONLY
    under the same EXPANSION_VERSION. Anything else is a different instrument
    and re-rolls (tests/test_expansion_is_memoized_in_the_artifact.py)."""
    from skills.nutrition.retrieval_intent import EXPANSION_VERSION
    stored = (doc or {}).get("expansions") or {}
    if stored.get("version") != EXPANSION_VERSION:
        return {}
    return {k: [str(q) for q in v] for k, v in (stored.get("queries") or {}).items() if v}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("entities", nargs="*", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    for candidate in (pathlib.Path.home() / "Code Learn/arnie/.env",
                      pathlib.Path(__file__).resolve().parent.parent / ".env"):
        if candidate.exists():
            load_dotenv(candidate)
    if not os.getenv("USDA_API_KEY"):
        print("USDA_API_KEY is not set — every query would return nothing and "
              "the artifact would be silently empty.", file=sys.stderr)
        return 2

    from core.semantic_fields import spec_for, _ensure_installed
    from skills.nutrition import pricing_artifact as art

    _ensure_installed()
    preparations = ("",) + tuple(spec_for("preparation").vocabulary)
    entities = [art.normalize(e) for e in (args.entities or SEED)]

    # ⭐ ANNOTATIONS ARE LOADED FROM THE COMMITTED ARTIFACT AND REUSED. This
    # is what makes a rebuild a controlled migration rather than a fresh
    # sample: every pair judged before is read, not re-asked.
    from skills.nutrition import semantic_annotations as sa

    prior, prior_doc = {}, {}
    if art.ARTIFACT_PATH.exists():
        try:
            prior_doc = json.loads(art.ARTIFACT_PATH.read_text())
            prior = _stored_annotations(prior_doc)
        except Exception:
            prior, prior_doc = {}, {}
    store = sa.Store.from_payload(prior)
    print(f"loaded {len(store.by_key)} existing semantic annotation(s)")
    from skills.nutrition.retrieval_intent import EXPANSION_VERSION
    prior_expansions = _stored_expansions(prior_doc)
    expansions_out = {}
    print(f"loaded {len(prior_expansions)} stored expansion(s) under {EXPANSION_VERSION}")

    results, entries = [], {}
    for entity in entities:
        for preparation in preparations:
            r = await build_one(entity, preparation, store=store,
                                expansion=prior_expansions.get(art.key(entity, preparation)),
                                expansions_out=expansions_out,
                                identity_key=art.key(entity, preparation))
            r["key"] = art.key(entity, preparation)
            results.append(r)
            if r["status"] == MATERIAL:
                entries[r["key"]] = {"candidates": r["candidates"]}

    print(f"\n{'key':34} {'status':12} {'cands':>5}  population_fp")
    print("-" * 78)
    for r in results:
        n = len(r.get("candidates") or ())
        print(f"{r['key']:34} {r['status']:12} {n if n else '-':>5}  "
              f"{r.get('candidate_fingerprint') or ''}  {r.get('reason','') if not n else ''}")

    # ⭐⭐ REVIEWED DECLINES — a seed that is NOT authoritatively buildable, for
    # a reason a human checked, bound to the exact subject that was checked.
    # ⛔ NOT a quota; ⛔ NOT permanent; ⛔ ONLY for a BLOCKING failure. An
    # EMPTY never refused a write and needs no permission. And a missing
    # fingerprint means the review DOES NOT APPLY — the build refuses, prints
    # what it saw, and the pin is filled deliberately. The `None`-matches-
    # anything placeholder let a stale review apply to a moved population once;
    # it is not repeated.
    REVIEWED_DECLINES = {
        # `egg|roasted`: the unresolved row is a whole egg with NO preparation
        # stated, genuinely unsettleable against "roasted" — INSUFFICIENT_EVIDENCE
        # is correct. Absent from the v1 artifact; zero coverage cost.
        # Fill `candidate_fingerprint` from a single-identity build_one run.
        "egg|roasted": {"reason": "IDENTITY_UNRESOLVED",
                        "resolver_version": "food_evidence_semantics_v2",
                        "retrieval_fingerprint": art.retrieval_fingerprint(),
                        # observed 2026-09-03 via a single-identity build_one:
                        # 15 rows retrieved under expansion, 1 unresolved =
                        # usda:748967 "Eggs, Grade A, Large, egg whole".
                        "candidate_fingerprint": "sha256:a33a5128be741225"},
    }
    _declined_doc = {}
    _declined_keys = set()
    for r in results:
        if r["status"] != FAILED or r.get("failure_class") != "SEMANTIC_UNRESOLVED":
            continue
        rev = REVIEWED_DECLINES.get(r["key"])
        if not rev:
            continue
        got = r.get("candidate_fingerprint")
        applies = (rev.get("candidate_fingerprint") and rev["candidate_fingerprint"] == got
                   and rev["resolver_version"] == art.resolver_version()
                   and rev["retrieval_fingerprint"] == art.retrieval_fingerprint())
        if not applies:
            print(f"  REVIEW DOES NOT APPLY to {r['key']}: observed population {got} "
                  f"(reviewed {rev.get('candidate_fingerprint')}) — re-review before pinning")
            continue
        _declined_keys.add(r["key"])
        _declined_doc[r["key"]] = {**rev, "observed_candidate_fingerprint": got,
                                    "detail": str(r.get("reason", ""))}
        print(f"  DECLINED {r['key']}: {rev['reason']} (reviewed, subject-bound)")

    failed = [r for r in results if r["status"] == FAILED and r["key"] not in _declined_keys]
    if failed:
        print(f"\n{len(failed)}/{len(results)} identities FAILED — refusing to "
              f"write. A failure is not an authoritative negative:",
              file=sys.stderr)
        for r in failed:
            print(f"    {r['key']:34} {r['reason']}", file=sys.stderr)
        return 3

    # ⭐ NON-DESTRUCTIVE BY DEFAULT: a rebuild is a controlled migration, not a
    # fresh probabilistic sample. A candidate that was in the committed
    # artifact and is absent now is RETAINED unless something can attribute
    # its removal — the source dropped it, the policy version moved, or the
    # identity was invalidated. Otherwise `mackerel|roasted` silently loses
    # three valid rows because one reply was cut short, which is exactly what
    # happened on 2026-08-11.
    # ⭐ TWO TRUTHS, EMITTED EVERY BUILD. The raw snapshot is what GENERATION
    # produced; the artifact is what production reads after the safety net has
    # run. Testing only the artifact would let generation quietly degrade
    # while retention held the output steady — "stable because generation is
    # stable" and "stable because retention repaired instability" are not the
    # same claim, and only the first closes a determinism blocker.
    raw_path = art.ARTIFACT_PATH.with_name("pricing_evidence_v1.raw.json")
    raw_doc = {"generated_entries": dict(sorted(entries.items()))}
    if not args.dry_run:
        raw_path.write_text(json.dumps(raw_doc, indent=2) + "\n",
                            encoding="utf-8")
        print(f"raw generation snapshot -> {raw_path}")

    raw_keys = _candidate_ids(entries)
    retained = _retain_unexplained(entries, store)
    # ⭐ SNAPSHOT BETWEEN THE TWO MECHANISMS. Retention and pins both rewrite
    # `entries` in place; the report charges each key to the stage that moved
    # it, so retention's delta is measured HERE, before a pin can touch a key.
    after_retention = _candidate_ids(entries)

    # ⭐⭐ REVIEWED PINS — IR-PUBLISH containment, NOT consumed-form authority.
    # Query expansion surfaced raw/dry base forms for these seeds and the ranker
    # had no reason to demote them (`oats|` cooked -> DRY, +434%). The general
    # fix is a registered blocker (docs/REGISTERED_CONSUMED_FORM_AUTHORITY.md);
    # publication does not wait for it. Each pin keeps the seed on the candidate
    # set the frozen 222 was measured against, and is bound to the INSTRUMENT
    # (resolver_version + retrieval_fingerprint) so it expires the moment the
    # resolver or the retrieval contract changes — but NOT on expansion's pool
    # drift between otherwise identical builds (see the PIN NOTE below).
    #
    # ⛔ FAIL CLOSED. A pin with no fingerprint does NOT apply — the build then
    # publishes the expanded set, the gate catches the reprice, and the
    # fingerprint gets filled in DELIBERATELY. The `None`-matches-anything
    # placeholder is how a stale review silently applied to a moved population
    # last time; it is not repeated here.
    # ⛔ A PIN CARRIES ITS OWN CANDIDATE LIST. The first draft looked the
    # prior set up from the artifact ON DISK — but by the build that applies a
    # pin, that file is the previous EXPANDED build, not v1. The pin would have
    # pinned to the thing it exists to hold off. So each pin is self-contained:
    # the reviewed candidates travel with the review, are visible in the diff,
    # and cannot drift with whatever happens to be on disk.
    # ⭐ PINS LIVE IN A COMMITTED, SELF-CONTAINED FILE (2026-09-03). Eight seeds
    # were held after the publication gate blocked v2's first expanded build:
    # each carries its v1 candidate dicts and is bound to the population
    # fingerprint it was reviewed against, so it expires the moment retrieval
    # or the resolver moves. See docs/REVIEWED_SEED_DECLINES.md.
    _pins_path = pathlib.Path("data/reviewed_seed_pins.json")
    REVIEWED_PINS = (json.loads(_pins_path.read_text()).get("pins") or {}) if _pins_path.exists() else {}
    _by_key = {r["key"]: r for r in results}
    _pinned_doc = _apply_reviewed_pins(_by_key, entries, REVIEWED_PINS)

    # ⭐ RAW vs FINAL, REPORTED EVERY BUILD, each altered key charged to the
    # mechanism that moved it — see _report_raw_vs_final.
    _report_raw_vs_final(raw_keys, after_retention, _candidate_ids(entries),
                         _pinned_doc, _declined_doc)

    document = {
        "resolver_version": art.resolver_version(),
        "vocabulary_fingerprint": art.vocabulary_fingerprint(),
        "retrieval_fingerprint": art.retrieval_fingerprint(),
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0)
                                .isoformat().replace("+00:00", "Z"),
        "entries": dict(sorted(entries.items())),
        # The durable semantic facts, versioned and reviewable. Their presence
        # here is what lets the NEXT build reuse rather than re-roll.
        "semantic_policy_version": sa.SEMANTIC_POLICY_VERSION,
        # A reader can tell a REVIEWED hold from an identity nobody looked at.
        "pinned_seed_identities": _pinned_doc,
        "declined_seed_identities": _declined_doc,
        # ⭐ THE POPULATION EACH ENTRY WAS RANKED OVER, per identity, so a pin's
        # expiry condition is verifiable FROM THE FILE. Kept as a sibling map,
        # not inside `entries[key]`: `evidence_for()` and every other consumer
        # read `entry["candidates"]` and must not meet a new field there.
        "candidate_fingerprints": {r["key"]: r.get("candidate_fingerprint")
                                   for r in results if r.get("candidate_fingerprint")},
        # ⭐ ONE LOCATION. `meta.annotations` is where the committed artifact, the
        # human review round (scripts/human_review_round.py) and the review-seam
        # tests keep annotations. The top-level copy this producer wrote was the
        # second implementation of one notion, and it cost the human layer.
        "meta": {"annotations": store.to_payload(),
                 "store_writer": "scripts/build_pricing_artifact.py"},
        "expansions": {"version": EXPANSION_VERSION,
                       "queries": dict(sorted(expansions_out.items()))},
    }
    print(f"\n{len(entries)}/{len(results)} identities carry qualified evidence")
    print(f"semantic annotations: {len(store.by_key)} stored, "
          f"{len(store.resolved_this_build)} resolved THIS BUILD "
          f"({'REUSE ONLY' if not store.resolved_this_build else 'new evidence seen'})")
    if retained:
        print(f"{retained} candidate(s) RETAINED from the committed artifact "
              f"with no attributable removal reason — a rebuild may not delete "
              f"evidence it cannot explain losing")
    if args.dry_run:
        print("--dry-run: nothing written")
        return 0
    art.ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    art.ARTIFACT_PATH.write_text(json.dumps(document, indent=2) + "\n",
                                 encoding="utf-8")
    print(f"wrote {art.ARTIFACT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
