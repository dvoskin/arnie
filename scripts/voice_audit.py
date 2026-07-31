"""Measure Arnie's voice against the contract — the evaluation §8 lacked.

Runs `core.voice.check_voice` over the voice corpus twice: on the raw bubble
string a surface produces (PRE-seam), and on what actually ships after
`platform.Response.from_text` runs the seam (POST-seam). The gap between the two
columns is exactly how much work the seam is doing; the POST column is what the
user sees, and the only one that can hold a real defect.

    python scripts/voice_audit.py                 # the report
    python scripts/voice_audit.py --json FILE      # machine-readable
    python scripts/voice_audit.py --strict         # exit 1 on a shipped violation

A POST-seam violation on a NON-negative shape is a genuine finding: the seam
normalizes characters and case, but it cannot rewrite a joke emoji, helpdesk
filler, or a piled-on exclamation out of a hand-written string — those are the
author's to fix at the source. The four `bad:*` shapes carry such violations on
purpose, to prove the linter bites; they are excluded from the gate.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./_voice_audit.db")


def _shipped(text: str) -> str:
    """What actually ships: the bubbles after the platform seam, rejoined. This
    is `Response.from_text`, i.e. the real _sanitize_bubble + sentence case."""
    from core.platform import Response
    return "|||".join(Response.from_text(text).bubbles)


def audit() -> list[dict]:
    from core.voice import check_voice
    from tests.corpus.voice_corpus import corpus, NEGATIVE_SHAPES

    rows = []
    for shape, text in corpus():
        pre = check_voice(text)
        post = check_voice(_shipped(text))
        rows.append({
            "shape": shape,
            "negative": shape in NEGATIVE_SHAPES,
            "text": text,
            "pre": [v.code.value for v in pre],
            "post": [v.code.value for v in post],
            "post_detail": [str(v) for v in post],
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", metavar="FILE")
    ap.add_argument("--strict", action="store_true")
    args = ap.parse_args()

    rows = audit()
    pre = Counter(c for r in rows for c in r["pre"])
    post = Counter(c for r in rows for c in r["post"])

    # A finding = a POST-seam violation on a shape that is supposed to be clean.
    findings = [r for r in rows if r["post"] and not r["negative"]]

    print(f"\nvoice corpus: {len(rows)} cases "
          f"({sum(1 for r in rows if r['negative'])} negative controls)\n")
    print(f"{'rule':<20} {'pre-seam':>9} {'post-seam':>10}   seam fixes")
    print("-" * 60)
    for code in sorted(set(pre) | set(post)):
        fixed = pre[code] - post[code]
        print(f"{code:<20} {pre[code]:>9} {post[code]:>10}   "
              f"{('-' + str(fixed)) if fixed > 0 else ''}")

    print(f"\nseam fixed {sum(pre.values()) - sum(post.values())} of "
          f"{sum(pre.values())} pre-seam violations")

    # Prove the negative controls still trip the linter — a linter that stopped
    # catching them would pass everything silently.
    caught = sum(1 for r in rows if r["negative"] and r["post"])
    negs = sum(1 for r in rows if r["negative"])
    print(f"negative controls caught: {caught}/{negs}"
          + ("  ⚠ LINTER BLIND" if caught < negs else ""))

    print(f"\nFINDINGS (shipped violations on clean shapes): {len(findings)}")
    for r in findings:
        print(f"  [{r['shape']}] {r['post_detail']}")
        print(f"      {r['text'][:88]}")
    if not findings:
        print("  none — every non-negative shape ships in voice")

    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(rows, indent=2))
        print(f"\nwrote {len(rows)} rows to {args.json}")

    return 1 if (args.strict and findings) else 0


if __name__ == "__main__":
    sys.exit(main())
