"""⛔⛔⛔ GUARD 5 — A PROBE MUST REACH THE BEHAVIOUR UNDER TEST BEFORE IT MAY
TEST IT.

Two D1 discrimination rounds died the same death. Round 1: two of six semantic
probes never asked, voiding the arm. Round 2: c301 asked 0/3, voiding it again.
Both times the utterance was chosen for the property being TESTED without
verifying it exhibits the behaviour the test REQUIRES.

**A probe that cannot reach the behaviour under test is an instrument that
cannot fail** — the same family as a guard whose protected input never occurs,
but with no mechanical protection until now.

⭐ THE RULE IS STRONGER THAN "we expect this to ask" (Danny, 2026-08-27):

    A probe is eligible only if the EXACT utterance reached the behaviour under
    test, under the SAME pinned config and tree, BEFORE it enters the
    experiment.

⛔⛔ AND FAILED ELIGIBILITY IS **FATAL TO THE ARM**, never "0 asks observed".
Recording a miss as data is precisely how absence of the target behaviour got
mistaken for evidence about its cause in rounds 1 and 2.

Eligibility is NOT power. A probe that asks once is eligible; whether 8 turns
yield enough asks to decide anything is the separate INSUFFICIENT rule.
"""
from __future__ import annotations

import json
import pathlib

REGISTRY = pathlib.Path("data/probe_eligibility.json")


class IneligibleProbe(Exception):
    """A probe never reached the behaviour under test. Fatal, not a data point."""


def _load() -> dict:
    return json.loads(REGISTRY.read_text())["probes"]


def is_eligible(utterance: str) -> bool:
    p = _load().get((utterance or "").strip())
    return bool(p and p.get("eligible") and (p.get("asks_observed") or 0) > 0)


def assert_eligible(cases, config: dict | None = None) -> None:
    """Refuse to start an experiment containing an unqualified probe.

    Call BEFORE the first turn. Raising here costs nothing; discovering it
    afterwards costs the whole arm — 18 turns across rounds 1 and 2.
    """
    reg = _load()
    bad = []
    for c in cases:
        u = (c.get("message") or "").strip()
        p = reg.get(u)
        if p is None:
            bad.append(f"  case {c.get('id')}: NOT QUALIFIED — no eligibility "
                       f"evidence for this exact utterance")
        elif not p.get("eligible"):
            bad.append(f"  case {c.get('id')}: INELIGIBLE — {p.get('note') or ''}")
        elif config and p.get("tree_sha") and config.get("_tree_sha") \
                and p["tree_sha"] != config["_tree_sha"]:
            bad.append(f"  case {c.get('id')}: eligibility was established on tree "
                       f"{p['tree_sha']}, this run is {config['_tree_sha']}")
    if bad:
        raise IneligibleProbe(
            "probes that have not been shown to reach the behaviour under "
            "test:\n" + "\n".join(bad) +
            "\n\nQualify each with one throwaway rep first. A probe that cannot "
            "reach the behaviour cannot produce evidence about its cause.")
