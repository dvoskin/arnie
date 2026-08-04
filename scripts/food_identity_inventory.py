#!/usr/bin/env python3
"""Who owns food identity, counted rather than remembered.

`docs/FOOD_SEMANTICS_MIGRATION.md` asserts that five string-keyed vocabularies
independently answer "what is this food", that pluralisation is implemented in
six modules, and that identity matching has three implementations. Those are
the numbers the migration is sequenced against, so they have to be checkable —
a plan justified by a count nobody can re-run is a plan justified by a memory.

Run it before and after each migration phase. The counts should fall.

    python scripts/food_identity_inventory.py
    python scripts/food_identity_inventory.py --vocabularies
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import re
import sys

# Runnable from anywhere: the repo root is this file's parent, and the counts
# are only comparable across phases if the scan always covers the same tree.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

ROOTS = ("core", "handlers", "skills", "api", "db")

#: One entry per architectural concern the directive names. The patterns match
#: SYMBOLS rather than words, so a comment mentioning `_same_food` does not
#: inflate the count that decides whether it is safe to delete.
CONCERNS = {
    "identity-matching": (
        r"_same_food|_is_renaming_of|_name_tokens|_ordered_tokens"
        r"|_head_matches|_stems\("),
    "alias-tables": (
        r"PIECE_WEIGHTS_G|FOOD_CATEGORIES|FORM_ALIASES|_DISH_CATEGORIES"
        r"|VAGUE_MEASURES|_PIECE_GRAMS|PORTION_ONTOLOGY"),
    "pluralisation": r'rstrip\("s"\)|_plural\(|_stems\(',
    "portion-density": r"distribution_for|food_category|piece_weight|piece_key|DENSIT",
    "quantity-units": (
        r"normalize_quantity|mass_grams|NormalizedQuantity|inferred_unit"
        r"|user_stated_unit"),
    "preparation": r"_FACET_KINDS|_PREPARATION|detect_form",
    "question-options": (
        r"_question_options|_stated_options|_portion_options|_measure_options"
        r"|chip_labels|\.buttons\b"),
    "pending-state": (
        r"payload_json|record_pending_question|staged_items|_sft_prior"
        r"|pending_expired"),
    "deferred-calls": (
        r"deferred_calls|DEFERRED_KEY|_settle_deferred|_undeferred"
        r"|_settle_expired_deferred"),
    "cards": r"_logged_entry_card|macro_card|\.cards\b",
    "commit-result": r"ExecutionResult|LAST_EXECUTION|CallResult|execute_tool_calls",
}


def _modules() -> list:
    return [p for r in ROOTS for p in (_ROOT / r).rglob("*.py")]


def scan(top: int = 6) -> int:
    files = _modules()
    print(f"scanned {len(files)} modules under {'/ '.join(ROOTS)}\n")
    for concern, pattern in CONCERNS.items():
        rx = re.compile(pattern)
        hits = collections.Counter()
        for f in files:
            try:
                n = len(rx.findall(f.read_text()))
            except Exception:
                n = 0
            if n:
                hits[str(f)] = n
        print(f"{concern:20} {sum(hits.values()):>4} refs / "
              f"{len(hits):>2} modules")
        for f, n in hits.most_common(top):
            print(f"  {n:>21}  {f}")
        print()
    return 0


def vocabularies() -> int:
    """The five string-keyed tables, and whether they agree about a food."""
    from core.food_pipeline import VAGUE_MEASURES
    from core.portions import _PIECE_GRAMS
    from skills.nutrition.normalize import PIECE_WEIGHTS_G, piece_key
    from skills.nutrition.portions import (FOOD_CATEGORIES, FORM_ALIASES,
                                           PORTION_ONTOLOGY, _DISH_CATEGORIES,
                                           food_category)

    print("=== independent string-keyed vocabularies ===")
    for name, table in (
            ("portions.FOOD_CATEGORIES", FOOD_CATEGORIES),
            ("normalize.PIECE_WEIGHTS_G", PIECE_WEIGHTS_G),
            ("portions.FORM_ALIASES", FORM_ALIASES),
            ("food_pipeline.VAGUE_MEASURES", VAGUE_MEASURES),
            ("portions.PORTION_ONTOLOGY", PORTION_ONTOLOGY),
            ("portions._DISH_CATEGORIES", _DISH_CATEGORIES)):
        print(f"  {name:32} {len(table):>4} keys")

    print("\n=== the duplicate piece table ===")
    only = sorted(set(_PIECE_GRAMS) - set(PIECE_WEIGHTS_G))
    both = set(_PIECE_GRAMS) & set(PIECE_WEIGHTS_G)
    clash = []
    for k in sorted(both):
        a = PIECE_WEIGHTS_G[k][0]
        raw = _PIECE_GRAMS[k]
        b = raw[0] if isinstance(raw, (tuple, list)) else raw
        if abs(a - b) > 1:
            clash.append((k, a, b))
    print(f"  live PIECE_WEIGHTS_G   {len(PIECE_WEIGHTS_G):>4} rows")
    print(f"  advisory _PIECE_GRAMS  {len(_PIECE_GRAMS):>4} rows")
    print(f"  unique to advisory     {len(only):>4}  {only[:8]}")
    print(f"  DISAGREEMENTS          {len(clash):>4}  {clash}")

    print("\n=== do the vocabularies agree what a food IS? ===")
    for food in ("potato", "burger", "fries", "chicken noodle soup",
                 "orange chicken", "peanut butter", "coffee cake",
                 "banana bread", "rice", "chicken"):
        print(f"  {food:22} category={food_category(food):<11} "
              f"piece_key={piece_key(food)}")
    return 0


#: Conversion constants that should live in ONE unit registry and do not.
#: Counted because the expansion directive named duplicated unit conversion,
#: and this was the largest measured duplication in the codebase — 74 sites for
#: kg<->lb alone, spanning weight, height, strength and nutrition.
#:
#: THE PATTERNS ARE WRITTEN THIS WAY FOR A REASON. The first version used
#: `0\.45359\b`, and `\b` cannot match between "9" and "2" — so every
#: `0.453592` site was invisible, including four user WEIGHT-WRITE paths in
#: api/app.py. The audit reported a number lower than the truth, which is the
#: worst failure mode an audit has: it says the work is done.
#:
#: So: a trailing `(?![\d])` instead of `\b`, a leading `(?<![\d.])` so a
#: longer literal is not matched by its own prefix, and open-ended digits so a
#: sixth spelling cannot hide behind a fifth.
_CONVERSIONS = {
    "kg <-> lb": r"(?<![\d.])(?:2\.2046\d*|0\.4535\d*)(?![\d])",
    "cm <-> in": r"(?<![\d.])(?:2\.54|0\.3937\d*)(?![\d])",
    "g <-> oz": r"(?<![\d.])(?:28\.34\d*|28\.35)(?![\d])",
    "ml <-> floz": r"(?<![\d.])29\.57\d*(?![\d])",
}


def conversions() -> int:
    """Every hard-coded unit conversion, by module. Should reach zero."""
    files = _modules()
    for name, pattern in _CONVERSIONS.items():
        rx = re.compile(pattern, re.I)
        hits = collections.Counter()
        for f in files:
            n = len(rx.findall(f.read_text()))
            if n:
                hits[str(f.relative_to(_ROOT))] = n
        print(f"{name:14} {sum(hits.values()):>3} sites / "
              f"{len(hits):>2} modules")
        for f, n in hits.most_common(6):
            print(f"   {n:>16}  {f}")
        print()
    return 0


# ── consequence classification ───────────────────────────────────────────────
#
# A COUNT IS NOT A RISK. Every hit in `scan()` weighs the same, so a regex that
# formats a display string and a regex that decides whether to delete a row are
# indistinguishable — and prioritising by raw count therefore prioritises by
# verbosity. This classifies each hit by what it can actually break.
#
# Judged structurally rather than by keyword: the enclosing function is found
# by walking the AST, and the function is classified by what IT does. A hit
# inside a function that reaches a write is mutation-class no matter how
# innocent the line looks; a hit inside a docstring or an f-string is
# presentation no matter how alarming.

#: What a write looks like here, grounded by counting the codebase rather than
#: guessed: db.add( 44, db.delete( 7, await db.execute 241, update_food_entry
#: 54, delete_food_entry 28, log_food 197, execute_tool_calls 29.
_WRITES = re.compile(
    r"\bdb\.add\(|\bdb\.delete\(|\bawait db\.execute|\.commit\(\)"
    r"|update_food_entry|delete_food_entry|log_food\b|execute_tool_calls")

#: Consequence classes, most severe first. First match wins.
_CLASSES = (
    ("mutation-targeting", lambda body, mod, line: bool(_WRITES.search(body))),
    ("commit-gating", lambda body, mod, line: bool(
        re.search(r"\ballow(ed)?\b|\bblock|\bgate\b|\brefus|\bdecline", body)
        and re.search(r"return (False|None)", body))),
    ("identity-resolution", lambda body, mod, line: bool(
        re.search(r"_same_food|_head_matches|_is_renaming_of|entry_id"
                  r"|_undeferred|dedup", body))),
    ("reference-binding", lambda body, mod, line: bool(
        re.search(r"\bprior\b|pending|deferred|staged|last_|previous", body))),
    ("quantity-conversion", lambda body, mod, line: bool(
        re.search(r"grams|_g\b|mass|calorie|kcal|weight_kg|LB_PER_KG"
                  r"|G_PER_OZ", body))),
    ("routing", lambda body, mod, line: bool(
        re.search(r"_to_legacy|route|applies\(|intent|classify", body))),
    ("search-promotion", lambda body, mod, line: bool(
        re.search(r"promote|candidate|rank|score", body))),
    ("unclassified-residual", lambda body, mod, line: True),
)


def _enclosing(tree, lineno: int):
    """The innermost function containing `lineno`, or None for module level."""
    import ast as _ast
    best = None
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            end = getattr(node, "end_lineno", node.lineno)
            if node.lineno <= lineno <= end:
                if best is None or node.lineno > best.lineno:
                    best = node
    return best


def consequence(pattern: str = None) -> int:
    """Classify every heuristic hit by what it can break."""
    import ast as _ast
    rx = re.compile(pattern or (
        r"re\.compile\(|rstrip\(\"s\"\)|_same_food|_head_matches"
        r"|_is_renaming_of|re\.split\(|\.lower\(\) in "))
    # A FEATURE FLAG IS NOT AN INTERPRETATION. `os.getenv("X").lower() in
    # ("true","1")` matched the substring-gate pattern, so every boolean flag
    # in the codebase was being scored as language handling — the same
    # over-counting the `\b` bug produced, in the other direction. Config reads
    # decide deployment, never what the user meant.
    _config = re.compile(r"os\.getenv|os\.environ|_enabled\b|_ENABLED\b")
    tally = collections.Counter()
    detail = collections.defaultdict(list)
    for f in _modules():
        if f.name in ("units.py", "food_identity_inventory.py",
                      "semantics_acceptance.py"):
            continue
        text = f.read_text()
        try:
            tree = _ast.parse(text)
        except SyntaxError:
            continue
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if not rx.search(line) or _config.search(line):
                continue
            fn = _enclosing(tree, i)
            if fn is None:
                body, where = line, "<module>"
            else:
                body = "\n".join(
                    lines[fn.lineno - 1:getattr(fn, "end_lineno", fn.lineno)])
                where = fn.name
            # A hit inside the function's own docstring describes behaviour, it
            # does not cause any.
            doc = _ast.get_docstring(fn) if fn is not None else None
            if doc and line.strip() and line.strip() in doc:
                cls = "presentation-only"
            else:
                cls = next(name for name, test in _CLASSES
                           if test(body, str(f), line))
            tally[cls] += 1
            detail[cls].append(
                f"{f.relative_to(_ROOT)}:{i} ({where})  {line.strip()[:56]}")
    order = [c for c, _ in _CLASSES] + ["presentation-only"]
    print("HEURISTIC HITS BY CONSEQUENCE, most severe first\n")
    for cls in order:
        if not tally[cls]:
            continue
        print(f"  {cls:22} {tally[cls]:>4}")
        for d in detail[cls][:4]:
            print(f"      {d}")
        if len(detail[cls]) > 4:
            print(f"      … {len(detail[cls]) - 4} more")
        print()
    print(f"  {'TOTAL':22} {sum(tally.values()):>4}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--vocabularies", action="store_true",
                    help="show the tables and whether they agree")
    ap.add_argument("--conversions", action="store_true",
                    help="every hard-coded unit conversion, by module")
    ap.add_argument("--consequence", action="store_true",
                    help="classify heuristic hits by what they can break")
    args = ap.parse_args()
    if args.vocabularies:
        sys.exit(vocabularies())
    if args.conversions:
        sys.exit(conversions())
    if args.consequence:
        sys.exit(consequence())
    sys.exit(scan())
