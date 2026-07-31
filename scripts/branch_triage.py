"""Which branches can go, and which still hold something. One command.

69 remote branches, and the only honest way to tell them apart is to ask what
each one still CONTAINS that main does not. Reading names does not do it, and
neither does `git cherry` on its own — 2026-07-31, PR #67 reported three of
four commits "missing" from main while all four were shipped. 168 commits of
drift changed the diffs, not the content.

So each branch is classified by what is actually in it:

  MERGED      ahead == 0. Every commit is an ancestor of main. There is
              nothing to lose — this is arithmetic, not judgement.
  SUPERSEDED  ahead > 0, but the distinctive lines those commits ADD are all
              present in main today. The work landed by another route
              (squash-merge, cherry-pick, reimplementation).
  UNIQUE      ahead > 0 and some added lines are nowhere in main. This branch
              still holds work. Do not delete it; extract it.
  UNSURE      the markers were too thin to judge (a commit that only deletes,
              or only touches binary/lock files). Treated as UNIQUE.

Nothing is deleted here, ever. The script prints a report and writes the
commands, so a human reads them first.

    python scripts/branch_triage.py                # report
    python scripts/branch_triage.py --script FILE  # + write cleanup commands

The cleanup it proposes is REVERSIBLE: every branch is tagged `archive/<name>`
before deletion. A tag keeps the commits reachable forever, so "deleted" means
"off the branch list", not "gone". Recovering one is
`git branch <name> archive/<name>`.

It also reports the two places WIP actually gets lost, neither of which is a
branch name: local commits that are on no remote, and worktrees with
uncommitted files.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import namedtuple

MAIN = "origin/main"

# How many added lines to sample per unique commit when asking "is this
# content in main already". More is slower, not more accurate — a handful of
# long, distinctive lines settles it.
MARKERS_PER_COMMIT = 6
MIN_MARKER_LEN = 40

Branch = namedtuple("Branch", "name ahead behind verdict detail")

# Lines that say nothing about whether the WORK landed. An import or a bare
# brace matches in a thousand places; matching one proves nothing.
_BORING = re.compile(
    r"^\s*(import |from |#|//|\*|\}|\{|\)|\]|$|def __|return$|pass$|else:$)")


def sh(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True,
                          text=True).stdout.strip()


def remote_branches() -> list[str]:
    out = sh("for-each-ref", "--format=%(refname:short)", "refs/remotes/")
    return [b for b in out.splitlines()
            if b and not b.endswith("/HEAD") and b != MAIN]


def markers_of(commit: str) -> list[str]:
    """Distinctive lines this commit ADDS — the fingerprint of its content."""
    diff = sh("show", "--format=", "--unified=0", commit)
    found = []
    for line in diff.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        text = line[1:].strip()
        if len(text) < MIN_MARKER_LEN or _BORING.match(text):
            continue
        found.append(text)
        if len(found) >= MARKERS_PER_COMMIT:
            break
    return found


def in_main(marker: str) -> bool:
    """Is this exact line present anywhere in main's tree?"""
    r = subprocess.run(["git", "grep", "-F", "-q", marker, MAIN],
                       capture_output=True, text=True)
    return r.returncode == 0


def classify(branch: str) -> Branch:
    ahead = int(sh("rev-list", "--count", f"{MAIN}..{branch}") or 0)
    behind = int(sh("rev-list", "--count", f"{branch}..{MAIN}") or 0)
    if ahead == 0:
        return Branch(branch, ahead, behind, "MERGED",
                      "every commit is an ancestor of main")

    commits = sh("rev-list", f"{MAIN}..{branch}").splitlines()
    total = missing = 0
    for commit in commits:
        for marker in markers_of(commit):
            total += 1
            if not in_main(marker):
                missing += 1
    if total == 0:
        return Branch(branch, ahead, behind, "UNSURE",
                      f"{len(commits)} commit(s), no distinctive added lines "
                      f"to test — inspect by hand")
    if missing == 0:
        return Branch(branch, ahead, behind, "SUPERSEDED",
                      f"all {total} sampled lines from {len(commits)} commit(s) "
                      f"are already in main")
    return Branch(branch, ahead, behind, "UNIQUE",
                  f"{missing}/{total} sampled lines are NOT in main")


def unpushed_locals() -> list[tuple[str, int]]:
    """Local branches holding commits that exist on no remote. This is where
    work is actually lost — a disk failure, not a branch deletion."""
    out = []
    for b in sh("for-each-ref", "--format=%(refname:short)",
                "refs/heads/").splitlines():
        if not b:
            continue
        n = sh("rev-list", "--count", b, "--not", "--remotes")
        if n and int(n) > 0:
            out.append((b, int(n)))
    return out


def dirty_worktrees() -> list[tuple[str, int, str]]:
    out = []
    for line in sh("worktree", "list", "--porcelain").splitlines():
        if not line.startswith("worktree "):
            continue
        path = line.split(" ", 1)[1]
        status = subprocess.run(["git", "-C", path, "status", "--porcelain"],
                                capture_output=True, text=True)
        if status.returncode != 0:
            continue
        n = len([x for x in status.stdout.splitlines() if x.strip()])
        if n:
            head = subprocess.run(["git", "-C", path, "rev-parse",
                                   "--abbrev-ref", "HEAD"],
                                  capture_output=True, text=True).stdout.strip()
            out.append((path, n, head))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", metavar="FILE",
                    help="write the (reversible) cleanup commands here")
    args = ap.parse_args()

    if not sh("rev-parse", "--verify", MAIN):
        print(f"{MAIN} not found — run `git fetch origin` first.")
        return 1

    branches = [classify(b) for b in remote_branches()]
    order = {"UNIQUE": 0, "UNSURE": 1, "SUPERSEDED": 2, "MERGED": 3}
    branches.sort(key=lambda b: (order[b.verdict], -b.ahead))

    print(f"\n{'BRANCH':<56} {'AHEAD':>5} {'BEHIND':>6}  VERDICT")
    print("-" * 96)
    for b in branches:
        print(f"{b.name:<56} {b.ahead:>5} {b.behind:>6}  {b.verdict}")
        if b.verdict in ("UNIQUE", "UNSURE"):
            print(f"{'':<56} {'':>5} {'':>6}    ↳ {b.detail}")

    counts = {v: sum(1 for b in branches if b.verdict == v) for v in order}
    print(f"\n{len(branches)} remote branches: "
          + ", ".join(f"{counts[v]} {v.lower()}" for v in order))

    keep = [b for b in branches if b.verdict in ("UNIQUE", "UNSURE")]
    if keep:
        print("\nKEEP — these still hold work not in main:")
        for b in keep:
            print(f"  {b.name}  ({b.detail})")

    local = unpushed_locals()
    if local:
        print("\n⚠ LOCAL COMMITS ON NO REMOTE — this is where WIP is actually")
        print("  lost. Deleting remote branches cannot touch these; a dead")
        print("  laptop can. Push or bundle them.")
        for name, n in local:
            print(f"  {name:<50} {n} unpushed commit(s)")

    dirty = dirty_worktrees()
    if dirty:
        print("\n⚠ UNCOMMITTED FILES — not in git at all. Commit or stash")
        print("  before any cleanup touches these worktrees.")
        for path, n, head in dirty:
            print(f"  {n:>4} file(s)  [{head}]  {path}")

    if args.script:
        safe = [b for b in branches if b.verdict in ("MERGED", "SUPERSEDED")]
        lines = [
            "#!/usr/bin/env bash",
            "# Generated by scripts/branch_triage.py — REVIEW BEFORE RUNNING.",
            "#",
            "# Every branch is tagged archive/<name> BEFORE deletion, so this is",
            "# reversible: the commits stay reachable through the tag and",
            "#     git branch <name> archive/<name>",
            "# brings any of them back. 'Deleted' means off the branch list.",
            "#",
            "# Branches classed UNIQUE or UNSURE are deliberately absent.",
            "set -euo pipefail",
            "",
        ]
        for b in safe:
            # `origin/feat/x` → `feat/x`. A ref with no remote prefix is not
            # something to generate a `push --delete` for; skip rather than
            # guess at what deleting it would mean.
            _, _, short = b.name.partition("/")
            if not short:
                print(f"  (skipped {b.name}: no remote prefix to delete from)")
                continue
            lines.append(f"# {b.verdict}: {b.detail}")
            lines.append(f"git tag -f archive/{short} {b.name}")
            lines.append(f"git push origin archive/{short}")
            lines.append(f"git push origin --delete {short}")
            lines.append("")
        with open(args.script, "w") as fh:
            fh.write("\n".join(lines))
        print(f"\nWrote {len(safe)} branch cleanups to {args.script} "
              f"(tag-then-delete; nothing runs until you do).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
