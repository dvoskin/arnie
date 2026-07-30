"""Is this commit safe to deploy? One command, one answer.

Deploys here are a human action in the Render dashboard, so CI passing is not
a gate — it is a fact sitting somewhere nobody looks at deploy time. Five
audited fixes sat undeployed for a day this week, and on 2026-07-30 the running
SHA had to be established by inference from behavioural markers because nothing
reported it.

This closes the loop from both ends:

  * GitHub says whether the commit's checks are green.
  * `/health` says what is running RIGHT NOW, so "is the thing I am about to
    replace even what I think it is" has an answer too.

    python scripts/release_check.py                  # HEAD vs live
    python scripts/release_check.py <sha>            # a specific commit

Exit 0 means deployable. Exit 1 means something is red or unknown — and unknown
counts as not deployable, because a check nobody can read is not a check.

GITHUB_TOKEN (or GH_TOKEN) is needed for a private repo. Without one the check
status is reported as unknown rather than assumed green.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

REPO = os.getenv("ARNIE_REPO", "dvoskin/arnie")
HEALTH = os.getenv("ARNIE_HEALTH_URL", "https://arnie.onrender.com/health")


def _sh(*args: str) -> str:
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()


def _get(url: str, token: str | None) -> dict | None:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "arnie-release-check",
        **({"Authorization": f"Bearer {token}"} if token else {}),
    })
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return None


def check_runs(sha: str, token: str | None) -> tuple[str, list]:
    """('green'|'red'|'pending'|'none'|'unreadable', [(name, conclusion), ...])

    `none` and `unreadable` are kept apart deliberately. A commit pushed
    seconds ago has no check runs YET, which is a wait; a commit whose checks
    cannot be fetched is a blind spot. Reporting both as "unknown" sent the
    reader looking for a token they did not need — a tool built to stop
    guessing should not guess about itself.
    """
    body = _get(f"https://api.github.com/repos/{REPO}/commits/{sha}/check-runs",
                token)
    if body is None:
        return "unreadable", []
    runs = [(r.get("name", "?"), r.get("conclusion") or r.get("status"))
            for r in body.get("check_runs", [])]
    if not runs:
        return "none", []
    if any(c in (None, "queued", "in_progress") for _, c in runs):
        return "pending", runs
    if all(c in ("success", "neutral", "skipped") for _, c in runs):
        return "green", runs
    return "red", runs


def live_commit() -> str | None:
    try:
        with urllib.request.urlopen(HEALTH, timeout=20) as response:
            return (json.load(response) or {}).get("commit")
    except Exception:
        return None


def main() -> int:
    sha = sys.argv[1] if len(sys.argv) > 1 else _sh("git", "rev-parse", "HEAD")
    if not sha:
        print("could not resolve a commit", file=sys.stderr)
        return 1
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")

    verdict, runs = check_runs(sha, token)
    live = live_commit()

    print(f"commit   {sha[:12]}")
    print(f"live     {live or 'unknown'}"
          + ("   <-- already deployed" if live and sha.startswith(live) else ""))
    print(f"checks   {verdict}")
    for name, conclusion in runs:
        print(f"           {conclusion:<12} {name}")

    if verdict == "green":
        print("\nDEPLOYABLE")
        return 0
    if verdict == "none":
        print("\nNOT YET — no checks have started for this commit. If it was "
              "just pushed,\nwait for CI; if it is old, CI never ran on it.",
              file=sys.stderr)
        return 1
    if verdict == "pending":
        print("\nNOT YET — checks are still running.", file=sys.stderr)
        return 1
    if verdict == "unreadable":
        print("\nNOT DEPLOYABLE — the checks could not be read"
              + ("" if token else " (no GITHUB_TOKEN set)")
              + ".\nA check nobody can read is not a check.", file=sys.stderr)
        return 1
    print("\nNOT DEPLOYABLE — checks are red", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
