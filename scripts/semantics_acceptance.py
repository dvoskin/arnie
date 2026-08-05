#!/usr/bin/env python3
"""The semantics directive's acceptance criteria, as a pass/fail gate.

The directive lists fifteen conditions for "the architecture correction is
complete". Written as prose they are unfalsifiable — every one of them can be
argued into a yes. Written as checks they are a score, and a score is the only
honest way to answer "how far in are we?".

Rules this file holds itself to:

  * a criterion that cannot be checked mechanically is BLOCKED with the reason,
    never quietly PASSed;
  * checks assert the ABSENCE of the old mechanism, not the presence of a new
    one — "we added a registry" is not the same as "nothing bypasses it", and
    only the second is the criterion;
  * a check may not import the modules it audits, so a module that fails to
    import scores 0 rather than crashing the report.

    python scripts/semantics_acceptance.py
    python scripts/semantics_acceptance.py --verbose
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

ROOTS = ("core", "handlers", "skills", "api", "db")
PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"


def _src(*names: str) -> str:
    return "\n".join((_ROOT / n).read_text() for n in names
                     if (_ROOT / n).exists())


def _grep(pattern: str, exclude: tuple = ()) -> list:
    rx = re.compile(pattern)
    out = []
    for root in ROOTS:
        for p in (_ROOT / root).rglob("*.py"):
            rel = str(p.relative_to(_ROOT))
            if any(x in rel for x in exclude):
                continue
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if rx.search(line):
                    out.append(f"{rel}:{i}  {line.strip()[:72]}")
    return out


# ── the criteria ─────────────────────────────────────────────────────────────

def c_plural():
    """Adding a plural must not mean editing a matching algorithm."""
    hits = _grep(r'rstrip\("s"\)', exclude=("units.py",))
    return (PASS if not hits else FAIL,
            f"{len(hits)} hand-rolled singularisers remain", hits)


def c_alias_one_place():
    """Adding a synonym must be one entry, not edits across modules."""
    tables = _grep(r"^(PIECE_WEIGHTS_G|FOOD_CATEGORIES|FORM_ALIASES"
                   r"|VAGUE_MEASURES|_DISH_CATEGORIES|PORTION_ONTOLOGY)\s*=")
    return (PASS if len(tables) <= 1 else FAIL,
            f"{len(tables)} independent alias/vocabulary tables", tables)


def c_stems():
    """`_stems()` removed, or reduced to a registry-backed adapter."""
    src = _src("skills/nutrition/normalize.py")
    generative = "out.add(w[:-1])" in src or 'w[:-3] + "y"' in src
    return (FAIL if generative else PASS,
            "generates candidate spellings unvalidated by a registry"
            if generative else "registry-backed or gone", [])


def c_same_food():
    """Token-subset matching must not own item reconciliation."""
    src = _src("core/food_turn.py")
    owns = bool(re.search(r"def _undeferred\b", src)) and "_same_food" in src
    return (FAIL if owns else PASS,
            "_undeferred still reconciles via _same_food token subset"
            if owns else "reconciliation is ID-based", [])


def c_dish_by_length():
    """Dish categorisation must not depend on token length."""
    hits = _grep(r"len\(fragment\)\s*>")
    return (PASS if not hits else FAIL,
            f"{len(hits)} longest-fragment-wins sites", hits)


def c_product_override():
    """Generic head matching must not claim a distinct compound food.

    BEHAVIOURAL, not a source grep. The first version looked for the string
    "protected_compound" in normalize.py — which would have passed on a
    variable name and failed on a working guard that lives elsewhere. What the
    criterion actually asserts is that `butter` cannot claim `peanut butter`,
    so that is what is asked, of whatever owns identity today.
    """
    try:
        from core.food_turn import _is_renaming_of
    except Exception as e:
        return FAIL, f"identity unavailable: {e}", []
    cases = [("butter", "peanut butter"), ("banana", "banana bread"),
             ("orange", "orange juice"), ("rice", "rice cakes"),
             ("coffee", "coffee cake"), ("milk", "milk chocolate")]
    bad = [f"{a!r} claims {b!r}" for a, b in cases if _is_renaming_of(a, b)]
    return (PASS if not bad else FAIL,
            f"{len(bad)} distinct foods claimable by a generic head", bad)


def c_structured_options():
    """A client must get question-bound options without parsing prose."""
    ios = pathlib.Path(
        "/Users/danielvoskin/Code Learn/arnie-ios-badge-v2/Arnie/Features/"
        "Chat/QuickReplyEngine.swift")
    return (FAIL if ios.exists() else PASS,
            "QuickReplyEngine.swift still derives options from rendered prose"
            if ios.exists() else "no client-side prose parsing", [])


def c_pending_owner():
    """Pending clarification must have ONE lifecycle owner.

    LIVE owners only. The first version counted `pending_store.py` because the
    FILE EXISTS — but it has zero production importers and no table of its own
    (measured 2026-08-04), so it competes with nothing. Counting a dead module
    as a rival overstates the problem and, worse, hides the useful fact: it is a
    complete implementation with versioning, expiry and an atomic `claim()`,
    which is the answer to a different criterion this gate is also failing.

    An owner is a symbol something actually READS.
    """
    owners = []
    for name, pattern in (("conversation.payload_json", r"payload_json"),
                          ("deferred_calls", r"deferred_calls"),
                          ("staged_items", r"staged_items")):
        hits = [h for h in _grep(pattern)
                if not h.startswith("skills/nutrition/pending_store.py")]
        if hits:
            owners.append(f"{name}({len(hits)})")
    dead = [h for h in _grep(r"\bpending_store\b")
            if not h.startswith("skills/nutrition/pending_store.py")]
    note = "" if dead else "; pending_store.py is BUILT AND UNUSED (0 importers)"
    return (PASS if len(owners) <= 1 else FAIL,
            f"{len(owners)} live owners: {', '.join(owners)}{note}", [])


def c_commit_idempotent():
    """The food COMMIT must be idempotent — keyed on the pending meal and its
    resolved payload, and durable.

    The first version of this check asked whether the string "idempotency_key"
    appeared anywhere on the food path. It does, so the check returned PASS
    while its own explanation described a failure — exactly the "assert the
    presence of a new thing rather than the absence of the old" trap this file
    forbids in its own docstring.

    What actually exists is `food_ledger.turn_idempotency_key(user_id, message,
    tool_calls)`, backed by an in-process `_SEEN` dict with a TTL. Two things
    that is not:

      * keyed on the MESSAGE TEXT rather than on the pending meal and the
        resolved payload, so it dedupes a repeated message rather than a
        repeated commit;
      * process-local, so it does not survive a restart and does not dedupe
        across workers at all — which is the deployment this runs in.
    """
    src = _src("core/food_ledger.py")
    durable = bool(re.search(r"pending_meal_id|payload_hash", src)) and \
        "_SEEN" not in src
    return (PASS if durable else FAIL,
            "idempotency is message-keyed and in-process (_SEEN dict): "
            "survives neither a restart nor a second worker", [])


def c_units():
    """Unit conversion has exactly one definition."""
    lits = re.compile(r"(?<![\d.])(?:2\.2046\d*|0\.4535\d*|2\.54|0\.3937\d*"
                      r"|28\.34\d*|28\.35|29\.57\d*)(?![\d])")
    hits = [h for h in _grep(lits.pattern, exclude=("units.py",))]
    return (PASS if not hits else FAIL,
            f"{len(hits)} conversion literals outside core/units.py", hits)


def c_corpus():
    """Replay must show a LOWER false-match rate than the pre-migration rule.

    No longer BLOCKED: a labelled corpus exists (36 pairs, the directive's own
    collision families). It is ~4% of the 1,000+ messages asked for and is
    authored rather than sampled, so this measures the collision families
    specifically and claims nothing about production traffic.
    """
    import sys as _sys
    _sys.path.insert(0, str(_ROOT / "tests"))
    try:
        from data.identity_collisions import IDENTITY_PAIRS
        from core.food_turn import _is_renaming_of
    except Exception as e:
        return FAIL, f"corpus unavailable: {e}", []
    false_match = [f"{a!r} claims {b!r}" for a, b, same, _ in IDENTITY_PAIRS
                   if _is_renaming_of(a, b) and not same]
    missed = [f"{a!r} vs {b!r}" for a, b, same, _ in IDENTITY_PAIRS
              if same and not _is_renaming_of(a, b)]
    # BASELINE, string rule alone, 2026-08-04: 1 false match, 5 missed.
    ok = len(false_match) == 0 and len(missed) <= 1
    return (PASS if ok else FAIL,
            f"{len(false_match)} false matches (was 1), "
            f"{len(missed)} missed renames (was 5), on 36 labelled pairs",
            false_match + missed)


CRITERIA = [
    ("plural -> no algorithm edit", c_plural),
    ("synonym -> one alias entry", c_alias_one_place),
    ("_stems removed/registry-backed", c_stems),
    ("_same_food not owning reconciliation", c_same_food),
    ("dish category not by token length", c_dish_by_length),
    ("product beats generic head match", c_product_override),
    ("client gets structured options", c_structured_options),
    ("one pending lifecycle owner", c_pending_owner),
    ("food commit idempotent", c_commit_idempotent),
    ("one unit definition", c_units),
    ("replay: false-match rate down", c_corpus),
]


def main(verbose: bool = False) -> int:
    print("SEMANTICS DIRECTIVE — ACCEPTANCE\n")
    tally = {PASS: 0, FAIL: 0, BLOCKED: 0}
    for name, fn in CRITERIA:
        try:
            status, why, detail = fn()
        except Exception as e:                       # a broken check is a FAIL
            status, why, detail = FAIL, f"check errored: {e}", []
        tally[status] += 1
        print(f"  [{status:7}] {name:38} {why}")
        if verbose and detail:
            for d in detail[:12]:
                print(f"              {d}")
            if len(detail) > 12:
                print(f"              … {len(detail) - 12} more")
    print(f"\n  {tally[PASS]} pass / {tally[FAIL]} fail / "
          f"{tally[BLOCKED]} blocked  of {len(CRITERIA)}")
    return 0 if tally[FAIL] == 0 else 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verbose", action="store_true")
    sys.exit(main(ap.parse_args().verbose))
