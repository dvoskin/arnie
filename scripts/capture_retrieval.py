"""G1 — CAPTURE AT THE RETRIEVAL SEAM, NOT AT A RECONSTRUCTION OF IT.

⛔ THE DEFECT THIS REPLACES. A first capture reconstructed the query shapes by
hand — `entity` and `entity + prep` — while `build_one` issues
`art.QUERY_SHAPES`. The corpus came out thinner than the one that built the
committed artifact, a rebuild on it lost three identities entirely, and the
loss was UNINTERPRETABLE: retrieval starvation and mechanical refusal are
indistinguishable once the inputs are already wrong.

That is the same failure family this migration keeps finding — TWO
IMPLEMENTATIONS OF ONE NOTION, where the second drifts from the first and
every downstream number quietly describes the wrong system.

⭐ SO NOTHING HERE KNOWS WHAT A QUERY SHAPE IS. `build_one` issues its own
queries and this records what passed through `usda._search`. If the retrieval
contract changes tomorrow, the capture changes with it and no edit here is
needed — which is the only version of "faithful" that stays true.

⭐⭐ ORDER IS PRESERVED PER QUERY. `build_one` gathers batches in query order
and dedupes keeping FIRST OCCURRENCE, so which query returned a row first can
decide whether it survives at all. A capture that flattened to a set would
replay a different build than the one it recorded.

⭐⭐⭐ AND THE CAPTURE CARRIES THE FINGERPRINT IT WAS TAKEN UNDER. A replay
against a moved retrieval contract is a replay of a system that no longer
exists; the gate refuses it rather than producing numbers about the past.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

CAPTURE_PATH = (pathlib.Path(__file__).resolve().parents[1]
                / "data" / "baseline" / "phase_0_source_capture.json")


class RetrievalContractMoved(Exception):
    """The capture was taken under a retrieval contract that no longer holds."""


def verify_contract(capture: dict) -> None:
    from skills.nutrition import pricing_artifact as art

    recorded = (capture.get("meta") or {}).get("retrieval_fingerprint")
    current = art.retrieval_fingerprint()
    if recorded != current:
        raise RetrievalContractMoved(
            f"capture was taken under {recorded}, the build now issues "
            f"{current} — replaying it would describe a system that no longer "
            f"exists")


async def capture() -> dict:
    """Run the REAL build over every committed identity, recording the seam."""
    import api.usda as usda
    import scripts.build_pricing_artifact as bp
    import skills.nutrition.evidence_qualification as eq
    from skills.nutrition import pricing_artifact as art
    from skills.nutrition.v2_gate import PHASE_0_REGIME, ranking_regime

    document = json.loads(art.ARTIFACT_PATH.read_text())
    identities = sorted(document.get("entries") or {})

    recorded: dict = {}
    original_search, original_qualify = usda._search, eq.qualify_usda_rows

    async def _recording_search(query, data_types, rows_per_shape):
        rows = await original_search(query, data_types, rows_per_shape)
        recorded.setdefault(_current[0], []).append({
            "query": query,
            "data_types": list(data_types),
            "rows_per_shape": rows_per_shape,
            "rows": list(rows or ()),          # ORDERED, as returned
        })
        return rows

    async def _never_resolve(*_args, **_kwargs):
        # capture is about RETRIEVAL; the resolver has no business here and
        # letting it run would spend model calls to learn nothing.
        from types import SimpleNamespace
        return SimpleNamespace(rows=(), disposition="resolver_down_no_candidates",
                               resolver_version="", kept_count=0)

    _current = [""]
    try:
        usda._search = _recording_search
        eq.qualify_usda_rows = _never_resolve
        with ranking_regime(PHASE_0_REGIME):
            for identity in identities:
                _current[0] = identity
                entity, _, preparation = identity.partition("|")
                await bp.build_one(entity, preparation)
    finally:
        usda._search, eq.qualify_usda_rows = original_search, original_qualify

    return {
        "meta": {
            "retrieval_fingerprint": art.retrieval_fingerprint(),
            "source": bp.SOURCE,
            "data_types": list(art.DATA_TYPES),
            "rows_per_shape": art.ROWS_PER_SHAPE,
            "query_shapes": list(art.QUERY_SHAPES),
            "captured_at_the_seam": True,
            "identities": len(identities),
        },
        "queries": recorded,
    }


def replay_rows(capture: dict, identity: str) -> list:
    """The rows `build_one` would receive, in the order it received them."""
    out = []
    for record in (capture.get("queries") or {}).get(identity, ()):
        out.append(record)
    return out


if __name__ == "__main__":
    result = asyncio.run(capture())
    meta, queries = result["meta"], result["queries"]
    total = sum(len(r["rows"]) for rows in queries.values() for r in rows)
    typed = sum(1 for rows in queries.values() for r in rows
                for row in r["rows"] if row.get("data_type"))
    print(f"  CAPTURED AT THE SEAM · fingerprint "
          f"{meta['retrieval_fingerprint']}")
    print(f"    query shapes    {meta['query_shapes']}")
    print(f"    data types      {meta['data_types']}  x{meta['rows_per_shape']}")
    print(f"    identities      {len(queries)}")
    print(f"    queries issued  {sum(len(r) for r in queries.values())}")
    print(f"    rows recorded   {total}   (data_type present on {typed})")
    missing = [i for i, r in queries.items() if not any(x["rows"] for x in r)]
    if missing:
        print(f"    ⛔ {len(missing)} identities retrieved NOTHING: {missing}")
    if "--write" in sys.argv:
        CAPTURE_PATH.write_text(json.dumps(result, indent=1) + "\n")
        print(f"\n  -> {CAPTURE_PATH.name}")
