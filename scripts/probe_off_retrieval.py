"""RETRIEVAL SURFACE CHARACTERISATION — is the good SKU absent, or just unstable?

⛔ THIS IS NOT A RANKING PROBE AND NOT A COVERAGE PROBE. On 2026-08-31 the
identical query `Muscle Milk Pro Series Vanilla` returned a flavour-resolved
barcode-bearing SKU ONCE and a coarse flavourless row THREE times. That is
neither of the two failure modes anyone had named:

    coverage failure   the good SKU is absent            -> NOT what we see
    ranking failure    consistently retrieved, then lost -> NOT what we see

So before touching qualification, barcode preference or admission, the
retrieval surface itself gets characterised.

⭐ THE COLUMN THAT MATTERS IS THE BACKEND. `off.search` tries `cgi/search.pl`
first and falls back to Search-a-licious — and the two DO NOT SHARE A SELECTION
RULE: the fallback runs `_best_candidate(..., require_anchor=True)`. Same query,
different backend, different rule is a live explanation before any ranking bug
is invoked. Production's line for the failing turn read `OFF hit via sal`.

My first probe recorded only the returned dict and threw `used` away, so it
could not say what changed between call 1 and calls 2-4. That is the whole
reason this exists.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

CORPUS = pathlib.Path("data/corpus/branded_identity_truth_v1.json")
OUT = pathlib.Path("data/off_retrieval_probe_2026-08-31.json")
REPS = int(__import__("os").environ.get("REPS", "4"))


class _Capture(logging.Handler):
    """`used` and `ov` exist ONLY in a log line. Capturing it is not a
    convenience — without it the backend column is unavailable and the probe
    answers nothing."""
    def __init__(self):
        super().__init__(); self.lines = []

    def emit(self, record):
        try:
            self.lines.append(record.getMessage())
        except Exception:
            pass


def _shape(p: dict) -> dict:
    """What the candidate ESTABLISHES, field by field — not whether we liked it."""
    name = str(p.get("name") or "")
    low = name.lower()
    return {
        "name": name[:60],
        "code": p.get("code"),
        "has_barcode": bool(p.get("code")),
        "brand": p.get("brand"),
        "_match": p.get("_match"),
        "serving_text": p.get("serving_text") or "",
        # flavour/variant resolution is the thing the failing candidate lacked
        "names_a_flavour": any(f in low for f in (
            "vanilla", "chocolate", "cookies", "caramel", "cherry", "salt",
            "cream", "strawberry", "banana", "mocha", "peanut")),
        "nutrition_keys": sorted((p.get("per100g") or {}).keys()),
        "nutrition_complete": all(
            (p.get("per100g") or {}).get(k) is not None
            for k in ("calories", "protein", "carbs", "fat")),
    }


async def main() -> int:
    from skills.nutrition import off

    cap = _Capture()
    logging.getLogger("skills.nutrition.off").addHandler(cap)
    logging.getLogger("skills.nutrition.off").setLevel(logging.INFO)

    cases = json.loads(CORPUS.read_text())["cases"]
    # one query per distinct INTENT — the corpus pairs share intents
    queries = sorted({c["intent"] for c in cases})
    print(f"{len(queries)} distinct branded queries x {REPS} reps\n")

    rows = []
    for q in queries:
        for rep in range(1, REPS + 1):
            cap.lines.clear()
            t0 = time.monotonic()
            try:
                r = await asyncio.wait_for(off.search(q, page_size=8), timeout=60)
                err = ""
            except Exception as e:
                r, err = None, f"{type(e).__name__}"
            ms = int((time.monotonic() - t0) * 1000)
            hit = [l for l in cap.lines if "OFF hit via" in l]
            backend = (hit[0].split("OFF hit via ")[1].split(" ")[0] if hit else "-")
            ov = (hit[0].split("(ov=")[1].rstrip(")") if hit and "(ov=" in hit[0] else "")
            breaker = any("off_breaker" in l for l in cap.lines)
            row = {"query": q, "rep": rep, "backend": backend, "ov": ov,
                   "breaker_open": breaker, "latency_ms": ms, "error": err,
                   "found": r is not None,
                   **({"candidate": _shape(r)} if r else {"candidate": None})}
            rows.append(row)
            c = row["candidate"] or {}
            print(f"  {q[:34]:<34} rep{rep} {backend:<7} ov={ov or '-':<5} "
                  f"{'barcode' if c.get('has_barcode') else 'no-code':<8} "
                  f"{'flavour' if c.get('names_a_flavour') else 'NO-FLAVOUR':<11} "
                  f"{str(c.get('name'))[:38]!r}")
    OUT.write_text(json.dumps({"reps": REPS, "rows": rows}, indent=1) + "\n")
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
