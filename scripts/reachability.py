#!/usr/bin/env python3
"""Static reachability: who calls what, and what nothing calls.

    python scripts/reachability.py                 # write reachability.json
    python scripts/reachability.py --summary       # and print the counts

Static analysis alone must never justify a deletion — this file's whole job is
to produce CANDIDATES, which the runtime half then confirms or clears. The
codebase is full of things that look unreachable to a parser and are load
bearing at run time: FastAPI route handlers nobody calls by name, Alembic
migrations, pytest fixtures, `getattr` dispatch, and every function reached
through a string in a registry.

So this errs consistently toward "reachable". Three cheap passes catch most of
what a call graph misses:

  * ATTRIBUTE USE — `x.foo()` anywhere counts as a reference to every `foo`
    defined anywhere. Wildly imprecise, and precisely right for a report whose
    false negatives get code deleted and whose false positives only get it
    read.
  * STRING MENTION — a bare `"foo"` or `'foo'` in any file counts too. This is
    what catches registries, `getattr(mod, name)`, Celery task names, and the
    tool-name dispatch this system runs on.
  * DECORATED — anything with a decorator is assumed to be reached through it.
    A route, a fixture, a validator and a signal handler are all invisible to
    a caller search by construction.

What remains after those is a genuinely short list, and short enough to read.
"""
from __future__ import annotations

import argparse
import ast
import json
import pathlib
import re
import sys
from collections import defaultdict
from typing import Dict, List, Set

ROOT = pathlib.Path(__file__).resolve().parent.parent

SKIP_DIRS = {".venv", "__pycache__", ".git", ".claude", "alembic", "landing",
             "node_modules", "audits", "docs", "memory"}

#: Definitions whose name alone means "reached by machinery, not by a caller".
DUNDER = re.compile(r"^__\w+__$")

#: Entry points nothing in-repo calls, by design.
ENTRY_HINTS = ("main", "app", "handler", "lifespan", "startup", "shutdown")


def source_files(include_tests: bool = True) -> List[pathlib.Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        # RELATIVE parts, not absolute. This repo is checked out inside a
        # `.claude/worktrees/...` path, so testing the absolute parts against
        # the skip list matched `.claude` on every file and the whole scan
        # returned nothing — a reachability report that finds no code reads
        # exactly like one that finds no problems.
        rel = p.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if not include_tests and "tests" in rel.parts:
            continue
        out.append(p)
    return sorted(out)


def _annotations(node):
    """Every annotation expression hanging off one node."""
    out = []
    if isinstance(node, ast.arg) and node.annotation is not None:
        out.append(node.annotation)
    elif isinstance(node, ast.AnnAssign) and node.annotation is not None:
        out.append(node.annotation)
    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if node.returns is not None:
            out.append(node.returns)
    return out


class Defs(ast.NodeVisitor):
    """Every function and class defined in one module, with its decorators."""

    def __init__(self, module: str):
        self.module = module
        self.rows: List[dict] = []
        self._stack: List[str] = []

    def _add(self, node, kind: str) -> None:
        qual = ".".join(self._stack + [node.name])
        self.rows.append({
            "symbol": qual,
            "name": node.name,
            "module": self.module,
            "line": node.lineno,
            "kind": kind,
            "decorated": bool(getattr(node, "decorator_list", [])),
            "private": node.name.startswith("_") and not DUNDER.match(node.name),
            "dunder": bool(DUNDER.match(node.name)),
        })

    def visit_FunctionDef(self, node):
        self._add(node, "function")
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node):
        self._add(node, "class")
        self._stack.append(node.name)
        self.generic_visit(node)
        self._stack.pop()


def collect() -> Dict[str, object]:
    defs: List[dict] = []
    called: Set[str] = set()          # bare Name(...) and attribute .name(...)
    attributed: Set[str] = set()      # any .name access at all
    imported: Set[str] = set()        # from x import name
    stringed: Set[str] = set()        # any string literal equal to a name
    annotated: Set[str] = set()       # named in a type annotation
    referenced: Set[str] = set()      # named without being called
    per_file_calls: Dict[str, Set[str]] = defaultdict(set)

    files = source_files()
    for path in files:
        rel = str(path.relative_to(ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel)
        except SyntaxError:
            continue
        d = Defs(rel)
        d.visit(tree)
        defs.extend(d.rows)

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                f = node.func
                if isinstance(f, ast.Name):
                    called.add(f.id)
                    per_file_calls[rel].add(f.id)
                elif isinstance(f, ast.Attribute):
                    called.add(f.attr)
                    per_file_calls[rel].add(f.attr)
            elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                # A REFERENCE IS NOT A CALL, and this codebase is full of the
                # difference: `CommandHandler("today", cmd_today)`,
                # `on_first_food=_early_heads_up`, `key=_sort_key`,
                # `add_done_callback(_reap)`. Counting only `f(...)` reported
                # every Telegram command handler as dead, and flagged a
                # callback added to this repo an hour earlier — which is how
                # the gap was found rather than shipped.
                referenced.add(node.id)
                per_file_calls[rel].add(node.id)
            elif isinstance(node, ast.Attribute):
                attributed.add(node.attr)
            elif isinstance(node, ast.ImportFrom):
                for a in node.names:
                    imported.add(a.name)
                    if a.asname:
                        imported.add(a.asname)
            elif isinstance(node, (ast.arg, ast.AnnAssign)) or isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # ANNOTATIONS ARE REFERENCES. Every Pydantic request model in
                # this API is named only in a route signature — FastAPI reads
                # the annotation and constructs it. To a call-graph they look
                # untouched, and they are the app's entire input surface.
                for ann in _annotations(node):
                    for sub in ast.walk(ann):
                        if isinstance(sub, ast.Name):
                            annotated.add(sub.id)
                        elif isinstance(sub, ast.Attribute):
                            annotated.add(sub.attr)
                        elif isinstance(sub, ast.Constant) and isinstance(
                                sub.value, str):
                            annotated.add(sub.value.strip())
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                s = node.value.strip()
                if s and len(s) < 80:
                    stringed.add(s)
                    # A dotted string is dispatch too: "core.food_turn.run".
                    if "." in s:
                        stringed.add(s.rsplit(".", 1)[-1])

    # Where each definition is referenced FROM, so a symbol referenced only by
    # tests is distinguishable from one referenced only by production.
    by_name: Dict[str, List[dict]] = defaultdict(list)
    for row in defs:
        by_name[row["name"]].append(row)

    prod_refs: Dict[str, int] = defaultdict(int)
    test_refs: Dict[str, int] = defaultdict(int)
    for rel, names in per_file_calls.items():
        bucket = test_refs if rel.startswith("tests/") else prod_refs
        for n in names:
            if n in by_name:
                bucket[n] += 1

    for row in defs:
        n = row["name"]
        row["static_calls"] = int(n in called)
        row["prod_call_files"] = prod_refs.get(n, 0)
        row["test_call_files"] = test_refs.get(n, 0)
        row["attribute_use"] = int(n in attributed)
        row["referenced"] = int(n in referenced)
        row["imported"] = int(n in imported)
        row["string_mention"] = int(n in stringed)
        row["annotation_use"] = int(n in annotated)
        # PYTEST OWNS ITS OWN CALLERS. A `test_*` function is invoked by
        # collection, a `conftest` hook by name, a fixture by injection. None
        # of them has a caller to find, and counting them as dead buries the
        # 112 findings that are not tests under 3,096 that are.
        row["framework_entry"] = bool(
            row["module"].startswith("tests/")
            and (row["name"].startswith("test_")
                 or row["module"].endswith("conftest.py")))
        row["entry_hint"] = any(h in n.lower() for h in ENTRY_HINTS)
        row["static_inbound"] = (row["prod_call_files"] + row["test_call_files"]
                                 + row["imported"] + row["string_mention"]
                                 + row["attribute_use"] + row["annotation_use"]
                                 + row["referenced"])
    return {"defs": defs, "files": len(files)}


def classify(row: dict) -> str:
    """The static verdict only. `unknown` is the honest answer for anything
    whose reachability a parser cannot see, and it is not a synonym for dead."""
    if row["framework_entry"]:
        return "test only"
    if row["dunder"] or row["decorated"] or row["entry_hint"]:
        return "unknown"                      # machinery, not a caller
    if row["annotation_use"]:
        return "production reachable"
    if row["prod_call_files"] or row["imported"]:
        return "production reachable"
    if row["test_call_files"]:
        return "test only"                    # pending runtime confirmation
    if row["string_mention"] or row["attribute_use"]:
        return "unknown"                      # dynamic dispatch, very likely live
    return "dead"                             # CANDIDATE — never a verdict


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--out", default="reachability.json")
    args = ap.parse_args(argv[1:])

    data = collect()
    for row in data["defs"]:
        row["static_category"] = classify(row)

    out = ROOT / args.out
    out.write_text(json.dumps(data, indent=1))
    print(f"  {len(data['defs']):,} definitions across {data['files']} files "
          f"-> {out.name}")

    if args.summary:
        tally: Dict[str, int] = defaultdict(int)
        for row in data["defs"]:
            tally[row["static_category"]] += 1
        print()
        for name, n in sorted(tally.items(), key=lambda kv: -kv[1]):
            print(f"  {name:<24}{n:>7}")
        candidates = [r for r in data["defs"] if r["static_category"] == "dead"]
        print(f"\n  {len(candidates)} deletion CANDIDATES — "
              f"static only, none confirmed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
