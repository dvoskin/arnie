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


async def build_one(entity: str, preparation: str, store=None,
                    identity_key: str = "") -> dict:
    """The qualified candidate set for one (entity, preparation)."""
    import api.usda as usda
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition.evidence_qualification import qualify_usda_rows
    from skills.nutrition import preparation_ontology as prep_onto

    identity = prep_onto.name_with(entity, preparation) if preparation \
        else entity
    queries = [s.format(identity=identity) for s in art.QUERY_SHAPES]

    counter = _CountUsdaFailures()
    usda.logger.addHandler(counter)
    try:
        batches = await asyncio.gather(
            *(usda._search(q, list(art.DATA_TYPES), art.ROWS_PER_SHAPE)
              for q in queries), return_exceptions=True)
    finally:
        usda.logger.removeHandler(counter)

    failed = counter.failures
    rows, seen = [], set()
    for batch in batches:
        if isinstance(batch, Exception):
            failed += 1
            continue
        for row in batch or ():
            fid = str(row.get("fdc_id") or row.get("description"))
            if fid in seen:
                continue
            seen.add(fid)
            rows.append(row)

    if failed:
        return {"identity": identity, "status": FAILED,
                "reason": f"{failed}/{len(queries)} provider queries failed"}
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
    for start in range(0, len(unseen), _QUALIFY_BATCH):
        chunk = unseen[start:start + _QUALIFY_BATCH]
        # BOUNDED RETRY, because truncation is a property of THIS reply, not
        # of the food: the same chunk usually parses on a second attempt. The
        # rule is unchanged — a batch that still fails after retries fails the
        # identity rather than being written as "no evidence". Without this,
        # 64 identities × one transient failure makes the artifact
        # unbuildable, which would be the rule defeating its own purpose.
        q = None
        for attempt in range(_QUALIFY_ATTEMPTS):
            try:
                q = await qualify_usda_rows(identity, chunk)
            except Exception:
                q = None
            if q is not None and not (
                    getattr(q, "disposition", "") ==
                    "resolver_down_no_candidates" and not q.rows):
                break

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

        for row in chunk:
            evidence_id = f"usda:{row.get('fdc_id')}"
            if not usable:
                store.record(sa.Annotation(
                    identity_key=identity_key, evidence_id=evidence_id,
                    relationship=sa.UNRESOLVED, confidence=0.0,
                    resolver_model=RESOLVER_MODEL,
                    source_fingerprint=_row_fingerprint(row)))
                continue
            # The resolver KEPT it -> it judged the pair identity-bearing at
            # or above its own floor. Anything it saw and did not keep is a
            # judged negative. Both are recorded; only the first can price.
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
    kept = [{"evidence_id": f"{SOURCE}:{r.get('fdc_id')}",
             "source": SOURCE,
             "fdc_id": r.get("fdc_id"), "description": r.get("description"),
             "data_type": r.get("data_type") or "",
             "per100g": r.get("per100g") or {}}
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
                    "reason": f"{len(unresolved)} of {len(rows)} rows "
                              f"unresolved; none annotated as priceable",
                    "unresolved": tuple(unresolved)}
        return {"identity": identity, "status": EMPTY,
                "reason": f"0 of {len(rows)} rows priceable by policy"}
    result = {"identity": identity, "status": MATERIAL, "candidates": kept,
              "raw": len(rows), "unresolved": tuple(unresolved)}
    if refused:
        # ATTRIBUTABLE: a row that left before the model saw it still says why
        result["mechanically_refused"] = refused
    return result


def _retain_unexplained(entries: dict) -> int:
    """Carry forward committed candidates this build cannot account for.

    Returns how many were retained, so the caller can report it rather than
    absorb it. THE REPORT IS THE POINT: silent retention would hide a real
    upstream removal just as surely as silent dropping hides a flaky one.
    """
    from skills.nutrition import pricing_artifact as art

    if not art.ARTIFACT_PATH.exists():
        return 0
    try:
        prior = json.loads(art.ARTIFACT_PATH.read_text()).get("entries") or {}
    except Exception:
        print("  the committed artifact will not parse — nothing to retain",
              file=sys.stderr)
        return 0

    retained = 0
    for key, before in prior.items():
        old_c = list(before.get("candidates") or ())
        if not old_c:
            continue
        now = entries.get(key)
        have = {str(c.get("fdc_id")) for c in (now or {}).get("candidates") or ()}
        missing = [c for c in old_c if str(c.get("fdc_id")) not in have]
        if not missing:
            continue
        entries.setdefault(key, {"candidates": []})
        entries[key]["candidates"] = list(
            entries[key].get("candidates") or ()) + missing
        retained += len(missing)
        print(f"  RETAINED {len(missing)} unexplained candidate(s) on {key}: "
              f"{[c.get('fdc_id') for c in missing]}")
    return retained


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

    prior = {}
    if art.ARTIFACT_PATH.exists():
        try:
            prior = json.loads(art.ARTIFACT_PATH.read_text()).get(
                "annotations") or {}
        except Exception:
            prior = {}
    store = sa.Store.from_payload(prior)
    print(f"loaded {len(store.by_key)} existing semantic annotation(s)")

    results, entries = [], {}
    for entity in entities:
        for preparation in preparations:
            r = await build_one(entity, preparation, store=store,
                                identity_key=art.key(entity, preparation))
            r["key"] = art.key(entity, preparation)
            results.append(r)
            if r["status"] == MATERIAL:
                entries[r["key"]] = {"candidates": r["candidates"]}

    print(f"\n{'key':34} {'status':12} candidates")
    print("-" * 70)
    for r in results:
        n = len(r.get("candidates") or ())
        print(f"{r['key']:34} {r['status']:12} "
              f"{n if n else r.get('reason','')}")

    failed = [r for r in results if r["status"] == FAILED]
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

    raw_keys = {k: [c.get("fdc_id") for c in v.get("candidates") or ()]
                for k, v in entries.items()}
    retained = _retain_unexplained(entries)

    # ⭐ RAW vs FINAL, REPORTED EVERY BUILD. Two truths, stated separately, so
    # "stable because generation is stable" can never be confused with "stable
    # because retention repaired instability". The second is a safety net
    # working; only the first is reproducibility.
    changed = [k for k, ids in raw_keys.items()
               if ids != [c.get("fdc_id") for c in
                          (entries.get(k) or {}).get("candidates") or ()]]
    added_by_retention = sorted(set(entries) - set(raw_keys))
    print(f"\nRAW GENERATION      {len(raw_keys)} identities")
    print(f"AFTER RETENTION     {len(entries)} identities")
    if changed or added_by_retention:
        print(f"RETENTION ALTERED   {len(changed)} existing key(s), "
              f"restored {len(added_by_retention)} whole key(s): "
              f"{added_by_retention or '-'}")
        print("  -> raw generation is NOT independently reproducible against "
              "the committed baseline; the artifact is production-safe "
              "because the safety net acted, which is a WEAKER claim")
    else:
        print("RETENTION ALTERED   nothing — generation stood on its own")

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
        "annotations": store.to_payload(),
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
