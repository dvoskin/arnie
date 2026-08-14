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

from skills.nutrition import pricing_artifact as art
from skills.nutrition import semantic_annotations as sa
from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

CAPTURE_PATH = (pathlib.Path(__file__).resolve().parents[1]
                / "data" / "baseline" / "phase_0_source_capture.json")
PROOF_PATH = (pathlib.Path(__file__).resolve().parents[1]
              / "data" / "baseline" / "phase_0_build_proof.json")


class ResolverPoisoned(RuntimeError):
    """The resolver was invoked during a build that must not need it."""


def capture_from_artifact() -> dict:
    """Synthesise a source capture from the committed artifact.

    ⚠ STATED PLAINLY: this is a REPLAY CORPUS, not a fresh provider capture.
    It reconstructs what retrieval would have returned from the candidates the
    artifact already holds, which is enough to prove the build is
    DETERMINISTIC over fixed inputs and is NOT enough to prove the artifact
    matches what USDA would serve today. Those are different claims and only
    the first is being made here. A true capture needs a live retrieval run
    recorded to disk, and that is owed.
    """
    document = json.loads(art.ARTIFACT_PATH.read_text())
    capture = {}
    for identity, entry in (document.get("entries") or {}).items():
        rows = []
        for candidate in (entry.get("candidates") or ()):
            rows.append({"fdc_id": candidate.get("fdc_id"),
                         "description": candidate.get("description"),
                         "data_type": candidate.get("data_type") or "sr legacy",
                         "per100g": candidate.get("per100g") or {}})
        capture[identity] = rows
    return capture


def _fingerprint(results) -> str:
    blob = json.dumps(results, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


async def prove(runs: int = 3) -> dict:
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq

    if not CAPTURE_PATH.exists():
        CAPTURE_PATH.write_text(json.dumps(capture_from_artifact(), indent=1)
                                + "\n")
    capture = json.loads(CAPTURE_PATH.read_text())
    document = json.loads(art.ARTIFACT_PATH.read_text())
    stored = (document.get("meta") or {}).get("annotations") or {}
    if not stored:
        raise SystemExit("the semantic store is empty — populate first")

    resolver_calls = []

    async def _poisoned(*_args, **_kwargs):
        resolver_calls.append(1)
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

    original_search, original_qualify = usda._search, eq.qualify_usda_rows
    snapshots = []
    try:
        eq.qualify_usda_rows = _poisoned
        for _ in range(runs):
            store = sa.Store.from_payload(stored)
            results = {}
            with ranking_regime(PHASE_0_REGIME):
                for identity in sorted(capture):
                    entity, _, preparation = identity.partition("|")

                    async def _replay(*_a, _rows=capture[identity], **_k):
                        return list(_rows)

                    usda._search = _replay
                    result = await bp.build_one(entity, preparation,
                                                store=store)
                    results[identity] = {
                        "status": result.get("status"),
                        "candidates": [art.candidate_evidence_id(c)
                                       for c in (result.get("candidates") or ())],
                        "unresolved": list(result.get("unresolved") or ()),
                        "mechanically_refused":
                            result.get("mechanically_refused") or {},
                        "raw": result.get("raw"),
                    }
            snapshots.append({
                "resolved_this_build": len(store.resolved_this_build),
                "results": results,
                "fingerprint": _fingerprint(results),
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
            "capture_is_a_replay_corpus_not_a_fresh_provider_capture": True,
            "failures": failures}


if __name__ == "__main__":
    result = asyncio.run(prove())
    print(f"  POISONED BUILD x{result['runs']} THROUGH build_one() · "
          f"regime {result['regime']}\n")
    print(f"    poison bites (verified first)   {result['poison_bites']}")
    print(f"    resolver calls                  {result['resolver_calls']}")
    print(f"    resolved_this_build per run     {result['resolved_this_build']}")
    print(f"    identities built                {result['identities']}")
    print(f"    fingerprint                     {result['fingerprint'][:32]}")
    for failure in result["failures"]:
        print(f"    ⛔ {failure}")
    if result["failures"]:
        raise SystemExit(1)
    print(f"\n  ✅ the BUILD PATH reproduces itself from captured sources,")
    print(f"     pre-retention, with a resolver that RAISES if consulted")
    print(f"  ⚠ the capture is a REPLAY CORPUS, not a fresh provider capture")
    if "--write" in sys.argv:
        PROOF_PATH.write_text(json.dumps(result, indent=1) + "\n")
        print(f"\n  -> {PROOF_PATH.name}")
