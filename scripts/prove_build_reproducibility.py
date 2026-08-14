"""THE PROOF THROUGH THE ACTUAL BUILD PATH, FROM CAPTURED SOURCES.

⛔ WHAT THE EARLIER PROOF DID NOT SHOW. `prove_reproducibility.py` reads the
committed artifact and re-derives winners from the stored annotations. It
never calls `build_one`. So it proves REPLAY DETERMINISM over a frozen
artifact — real, and narrower than the closure statement claimed. Retrieval,
batching, qualification, the mechanical veto and retention were all outside
the loop, and the "pre-retention candidate universe" it reproduced was one it
READ FROM DISK rather than one it rebuilt.

This drives `build_one` itself. Sources are CAPTURED and replayed, so provider
variability is removed as a variable rather than assumed away — the question
is whether the BUILD is deterministic given identical inputs, and a live API
would make a failure unattributable between our code and theirs.

⛔ AND THE CAPTURE IS THE G1 SEAM RECORDING, KEYED BY QUERY. An earlier
version of this module synthesised its own corpus from the committed artifact
and wrote it to the authoritative capture path; when G1 started recording at
`usda._search`, the schema changed under this reader and it was never
updated. It handed `build_one` the literal string `"meta"` as an identity and
died on `'str' object has no attribute 'get'` — and because NOTHING IMPORTED
IT, the suite stayed green over a proof that could not run. Both halves of
that are fixed here: the path constant is imported from `capture_retrieval`
rather than redeclared, and `tests/test_the_build_path_reproduces_itself.py`
actually invokes this.

⭐ THE RESOLVER IS POISONED HERE TOO, AND IT MATTERS MORE. In the replay proof
the resolver could not have been reached anyway. Here the build genuinely
wants to call it — so a poisoned run that still produces the same artifact
proves the annotation store answered every question the pipeline asked.

⭐⭐ AND THE COMPARISON IS PRE-RETENTION BY CONSTRUCTION: `build_one` returns
its result before `_retain_unexplained` ever runs, so this measures what the
build DERIVED rather than what retention rescued.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import pathlib
import sys

from scripts import capture_retrieval as cr
from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa
from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

#: ⛔ ONE CONSTANT, NOT A SECOND ONE. This module used to declare its own
#: `CAPTURE_PATH` pointing at the same file `capture_retrieval` writes — and
#: when G1 rewrote that file at the retrieval seam, the schema changed
#: underneath and this reader was never updated. `sorted(capture)` started
#: yielding `['meta', 'queries']`, the build was handed the string `"meta"`
#: as an identity, and it died on `'str' object has no attribute 'get'`.
#: Nothing imported this script, so the suite stayed green over a dead proof.
#: TWO IMPLEMENTATIONS OF ONE NOTION, in the commit that named the phrase.
CAPTURE_PATH = cr.CAPTURE_PATH
PROOF_PATH = (pathlib.Path(__file__).resolve().parents[1]
              / "data" / "baseline" / "phase_0_build_proof.json")


class ResolverPoisoned(RuntimeError):
    """The resolver was invoked during a build that must not need it."""


class CaptureMissing(SystemExit):
    """There is no seam capture to replay, and one must not be invented."""


def _fingerprint(results) -> str:
    blob = json.dumps(results, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def prove(runs: int = 3) -> dict:
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq

    # ⛔ A MISSING CAPTURE IS REFUSED, NEVER INVENTED. This used to synthesise
    # a corpus from the committed artifact and WRITE IT to the authoritative
    # capture path — so the one artifact G1 exists to protect could be
    # replaced by a reconstruction of the thing it is supposed to check,
    # by a script nobody ran deliberately. Capture is `capture_retrieval`'s
    # job and only its job.
    if not CAPTURE_PATH.exists():
        raise CaptureMissing(
            f"no seam capture at {CAPTURE_PATH.name} — run "
            f"`python -m scripts.capture_retrieval --write`. This proof will "
            f"not manufacture its own inputs.")
    capture = json.loads(CAPTURE_PATH.read_text())

    # ⭐ AND A REPLAY AGAINST A MOVED CONTRACT DESCRIBES A SYSTEM THAT NO
    # LONGER EXISTS. Refuse it rather than produce numbers about the past.
    cr.verify_contract(capture)
    queries = capture["queries"]

    document = json.loads(art.ARTIFACT_PATH.read_text())
    stored = (document.get("meta") or {}).get("annotations") or {}
    if not stored:
        raise SystemExit("the semantic store is empty — populate first")

    # ⛔ AN ATTEMPT IS NOT A PAIR, AND CONFLATING THEM OVERSTATES THE WORK.
    # The first version of this counted raw invocations and the directive then
    # reported them as "333 pairs needing annotation". They are not pairs:
    # `build_one` batches unseen rows by `_QUALIFY_BATCH` and retries each
    # batch up to `_QUALIFY_ATTEMPTS` times, and the total accumulates across
    # every proof run. So one missing pair can bill as nine attempts, and the
    # headline number was roughly an order of magnitude too large.
    #
    #     attempts   raw invocations, retries and runs included
    #     batches    distinct chunks handed to the resolver
    #     pairs      unique (identity_key, evidence_id) with no annotation
    #
    # Only the last one measures how much work the populate step actually is.
    resolver_calls = []
    batch_signatures = []

    async def _poisoned(identity=None, chunk=None, *_args, **_kwargs):
        resolver_calls.append(1)
        # retries of one chunk are consecutive and identical, so the distinct
        # signature count is the batch count
        batch_signatures.append(
            (identity, tuple(str(r.get("fdc_id")) for r in (chunk or ()))))
        raise ResolverPoisoned(
            "the resolver was called during a poisoned build — the store was "
            "supposed to answer this without asking anyone")

    # the poison must BITE before its silence means anything
    poison_bites = False
    try:
        await _poisoned()
    except ResolverPoisoned:
        poison_bites = True
    resolver_calls.clear()
    batch_signatures.clear()

    original_search, original_qualify = usda._search, eq.qualify_usda_rows
    snapshots = []
    try:
        eq.qualify_usda_rows = _poisoned
        for _ in range(runs):
            store = sa.Store.from_payload(stored)
            results = {}
            calls_before, batches_before = len(resolver_calls), len(
                batch_signatures)
            with ranking_regime(PHASE_0_REGIME):
                for identity in sorted(queries):
                    entity, _, preparation = identity.partition("|")

                    # ⭐ SERVED BY QUERY, BECAUSE THE CAPTURE IS KEYED BY
                    # QUERY. `build_one` issues one `_search` per shape and
                    # dedupes keeping FIRST OCCURRENCE, so which query
                    # returned a row decides whether it survives at all.
                    # Answering every shape with one flattened row list would
                    # replay a DIFFERENT build than the one recorded — the
                    # ordering the capture went out of its way to preserve
                    # would be discarded here at the last step.
                    by_query = {record["query"]: record["rows"]
                                for record in queries[identity]}

                    async def _replay(query, *_a, _by=by_query,
                                      _identity=identity, **_k):
                        # ⛔ AN UNCAPTURED QUERY IS A FAILURE, NOT AN EMPTY
                        # RESULT. Returning [] would let a contract that grew
                        # a shape read as a food that retrieved nothing.
                        if query not in _by:
                            raise KeyError(
                                f"{_identity}: the build issued {query!r}, "
                                f"which the capture does not hold — the "
                                f"retrieval contract moved under this replay")
                        return list(_by[query])

                    usda._search = _replay
                    result = await bp.build_one(entity, preparation,
                                                store=store,
                                                identity_key=identity)
                    results[identity] = {
                        "status": result.get("status"),
                        "candidates": [art.candidate_evidence_id(c)
                                       for c in (result.get("candidates") or ())],
                        "unresolved": list(result.get("unresolved") or ()),
                        "mechanically_refused":
                            result.get("mechanically_refused") or {},
                        "raw": result.get("raw"),
                    }
            # ⭐ THE PAIR COUNT IS THE ONE THAT SIZES THE POPULATE STEP.
            # `unresolved` is what `build_one` itself could not answer from
            # the store, per identity — unique evidence ids, no retries and
            # no cross-run accumulation in it.
            unseen_by_identity = {
                identity: len(derived["unresolved"])
                for identity, derived in results.items()
                if derived["unresolved"]}
            snapshots.append({
                "resolved_this_build": len(store.resolved_this_build),
                "results": results,
                "fingerprint": _fingerprint(results),
                "resolver_attempts": len(resolver_calls) - calls_before,
                "resolver_batches": len(set(
                    batch_signatures[batches_before:])),
                "unseen_pairs": sum(unseen_by_identity.values()),
                "unseen_pairs_by_identity": unseen_by_identity,
            })
    finally:
        usda._search, eq.qualify_usda_rows = original_search, original_qualify

    first = snapshots[0]
    failures = []
    if not poison_bites:
        failures.append("the poison does not raise — its silence proves nothing")
    if resolver_calls:
        failures.append(f"the resolver was called {len(resolver_calls)} time(s)")
    for index, snapshot in enumerate(snapshots):
        if snapshot["resolved_this_build"] != 0:
            failures.append(f"run {index}: resolved_this_build="
                            f"{snapshot['resolved_this_build']}")
        if snapshot["fingerprint"] != first["fingerprint"]:
            differing = [k for k in first["results"]
                         if snapshot["results"].get(k) != first["results"][k]]
            failures.append(f"run {index}: differs at {differing[:5]}")

    # and what the BUILD derived must match what the artifact COMMITS
    committed = {
        identity: [art.candidate_evidence_id(c)
                   for c in (entry.get("candidates") or ())]
        for identity, entry in (document.get("entries") or {}).items()}
    for identity, derived in first["results"].items():
        if derived["candidates"] != committed.get(identity):
            failures.append(
                f"{identity}: build derived {len(derived['candidates'])} "
                f"candidates, artifact commits "
                f"{len(committed.get(identity) or [])}")

    return {"regime": PHASE_0_REGIME, "runs": runs,
            "poison_bites": poison_bites,
            "resolver_calls": len(resolver_calls),
            "resolved_this_build": [s["resolved_this_build"] for s in snapshots],
            "identities": len(first["results"]),
            "fingerprint": first["fingerprint"],
            # WHAT THE SOURCES ACTUALLY ARE, carried in the artifact so the
            # claim travels with the numbers. G1 replaced the synthesised
            # corpus this used to build for itself: these rows were recorded
            # AT `usda._search` while the real build issued its own queries.
            # Still a RECORDING replayed, so this proves the build is
            # deterministic over fixed real inputs — NOT that USDA would
            # serve the same rows today. Those remain different claims.
            # ⛔ THREE DIFFERENT NUMBERS, NAMED SEPARATELY SO THE BIGGEST ONE
            # CANNOT BE QUOTED AS THE SMALLEST. attempts = batches x retries x
            # runs; only `unseen_pairs` sizes the populate step, and it is
            # per-run because it must not accumulate.
            "resolver_attempts": [s["resolver_attempts"] for s in snapshots],
            "resolver_batches": [s["resolver_batches"] for s in snapshots],
            "unseen_pairs": [s["unseen_pairs"] for s in snapshots],
            "unseen_pairs_by_identity": first["unseen_pairs_by_identity"],
            "qualify_batch": bp._QUALIFY_BATCH,
            "qualify_attempts": bp._QUALIFY_ATTEMPTS,
            # ⭐ THE CLOSURE CONDITION, EXECUTABLE RATHER THAN DESCRIBED.
            # `resolved_this_build == 0` alone is NOT sufficient and reading it
            # that way is how this proof came to look stronger than it was: it
            # is zero right now while the resolver is being called 333 times
            # and refused every time. "It could not have asked" requires BOTH
            # that nothing resolved AND that nothing asked.
            "closure_condition_met": (
                poison_bites
                and all(s["resolved_this_build"] == 0 for s in snapshots)
                and len(resolver_calls) == 0
                and not failures),
            "capture": "seam_recording",
            "capture_fingerprint": (capture.get("meta") or {})
                                   .get("retrieval_fingerprint", ""),
            # PER-IDENTITY OUTCOME, because the aggregate hides the thing the
            # delta classification needs to read. An uncaptured query reaches
            # `build_one` through `asyncio.gather(return_exceptions=True)` and
            # lands as FAILED — so a replay that lost a query shape reports a
            # provider failure rather than a food that legitimately retrieved
            # less, and that distinction is only visible here.
            "statuses": {identity: derived["status"]
                         for identity, derived in first["results"].items()},
            "failures": failures}


if __name__ == "__main__":
    result = asyncio.run(prove())
    print(f"  POISONED BUILD x{result['runs']} THROUGH build_one() · "
          f"regime {result['regime']}\n")
    print(f"    poison bites (verified first)   {result['poison_bites']}")
    print(f"    resolved_this_build per run     {result['resolved_this_build']}")
    print(f"    identities built                {result['identities']}")
    print(f"    fingerprint                     {result['fingerprint'][:32]}")
    print()
    print(f"    ⭐ UNSEEN PAIRS per run         "
          f"{result['unseen_pairs']}   <- sizes the populate step")
    print(f"       resolver batches per run     {result['resolver_batches']}"
          f"   (batch size {result['qualify_batch']})")
    print(f"       resolver ATTEMPTS per run    {result['resolver_attempts']}"
          f"   (up to {result['qualify_attempts']} tries each)")
    print(f"       attempts total, all runs     {result['resolver_calls']}"
          f"   <- NOT a pair count")
    if result["unseen_pairs_by_identity"]:
        print(f"\n    unseen pairs by identity")
        for identity, count in sorted(
                result["unseen_pairs_by_identity"].items(),
                key=lambda kv: (-kv[1], kv[0])):
            print(f"      {identity:<24} {count}")
    for failure in result["failures"]:
        print(f"    ⛔ {failure}")
    if result["failures"]:
        raise SystemExit(1)
    print(f"\n  ✅ the BUILD PATH reproduces itself from captured sources,")
    print(f"     pre-retention, with a resolver that RAISES if consulted")
    print(f"  ⚠ sources are a SEAM RECORDING replayed by query "
          f"({result['capture_fingerprint'][:24]}) —")
    print(f"     this proves the BUILD is deterministic over fixed real "
          f"inputs, NOT that")
    print(f"     the provider would serve these rows today")
    if "--write" in sys.argv:
        PROOF_PATH.write_text(json.dumps(result, indent=1) + "\n")
        print(f"\n  -> {PROOF_PATH.name}")
