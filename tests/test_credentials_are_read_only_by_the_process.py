"""⚠ AN OPERATOR SCRIPT MAY READ `.env`. RUNTIME CODE MAY NOT.

Danny, reviewing `ee7457f`: *"The script loads the Anthropic key from a local
.env fallback if the environment variable is absent. That is acceptable for an
explicitly manual proof script, but I would keep that behavior confined to this
kind of operator-only tooling and never let it become a pattern in runtime
code."*

Agreed, and a note is not a mechanism — the next person to need a key in a hurry
will copy the nearest thing that works, and the nearest thing that works is now
in `scripts/`. So the rule is a gate.

⛔ WHY IT MATTERS BEYOND TIDINESS. A runtime module that falls back to a file on
disk is a module whose behaviour depends on the filesystem of whatever host it
lands on. In production that file does not exist, so the fallback is dead code
that cannot be exercised; in a developer's checkout it silently succeeds and
hides a missing deploy variable until the deploy. That is the same shape as
every instrument in this project that lied by silence: it works where it is
tested and is absent where it matters.

⭐ AND IT IS A CREDENTIAL BOUNDARY. Reading a secret from a path is how a secret
ends up somewhere it was not scoped to — a worktree, a container layer, a
backup. The process environment is the only place production supplies one, so
it is the only place runtime code should look.
"""
from __future__ import annotations

import pathlib

REPO = pathlib.Path(__file__).resolve().parents[1]

#: Code that runs inside a request or a background job. Scripts, simulations
#: and tests are deliberately absent — they are operator tooling, run by a
#: person, on a machine that person controls.
RUNTIME = ("core", "skills", "api", "db", "handlers")

#: Reading `.env` from disk. `os.environ` is fine and is what production uses;
#: what is refused is a module going looking for the FILE.
#:
#: ⚠ QUOTED, AND THE FIRST VERSION WAS NOT. A bare `".env"` substring matches
#: inside `environment`, so the gate reported `api/devices.py` and
#: `db/queries.py` as credential leaks on the strength of a field name. A
#: detector that matches the wrong thing is the defect this project keeps
#: finding in its own instruments; here it would have been noise loud enough to
#: get the gate deleted.
FILE_READS = ('".env"', "'.env'", "dotenv", "load_dotenv", '/ ".env"',
              'arnie" / ".env"')


def _runtime_sources():
    for package in RUNTIME:
        for path in (REPO / package).rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            yield path, path.read_text(encoding="utf-8", errors="replace")


def test_no_runtime_module_reads_an_env_file():
    offenders = []
    for path, source in _runtime_sources():
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or "os.environ" in line:
                continue
            if any(marker in line for marker in FILE_READS):
                offenders.append(f"{path.relative_to(REPO)}: {stripped[:90]}")
    assert not offenders, (
        "runtime code reached for a .env file — production supplies secrets "
        "and configuration through the process environment, and a file "
        "fallback is dead code there while silently succeeding in a "
        "checkout:\n  " + "\n  ".join(offenders))


def test_no_runtime_module_carries_a_credential_literal():
    """A key that appears in source is a key in every clone, every backup and
    every build layer, whatever `.gitignore` says today."""
    import re

    # The provider's own key shape, matched structurally rather than by name so
    # a variable called something else cannot smuggle one through.
    key_shape = re.compile(r"sk-[A-Za-z0-9_\-]{16,}")
    offenders = [str(path.relative_to(REPO))
                 for path, source in _runtime_sources()
                 if key_shape.search(source)]
    assert not offenders, f"a credential literal is in source: {offenders}"


#: MEASURED, NEVER GUESSED (2026-08-14). Operator scripts have read `.env`
#: since long before this gate, and enumerating twenty-nine of them would be
#: churn that relitigates history instead of protecting the future.
#: RAISED 29 -> 30 on 2026-08-14 for `scripts/prove_memory_addressing.py`, a
#: consumer-side proof a person runs by hand against a scratch database.
#: RAISED 30 -> 31 on 2026-08-15 for `scripts/corpus_through_the_real_turn.py`,
#: the §0 step-3 corpus driver. Same shape as the one before it: a person runs
#: it by hand, it needs a real model key, and it points at a scratch DB.
#: RAISED 31 -> 32 on 2026-08-15 for `scripts/prove_the_seam_is_reachable.py`,
#: the eight-turn consumer-side proof that ordinary traffic reaches the identity
#: producer. Same shape again: by hand, real key, scratch DB.
#:
#: ⭐ THE RATCHET FIRED ON THE COMMIT THAT ADDED IT, which is the whole design:
#: the number moved because someone decided it should, in the same commit,
#: rather than drifting while nobody was looking. It has now done that three
#: times in one day, and each time the number moved WITH ITS REASON.
SCRIPTS_READING_ENV_BASELINE = 32


def test_the_env_reading_habit_does_not_spread_beyond_scripts():
    """⭐ A RATCHET, NOT AN ALLOWLIST.

    The load-bearing rule is the one above: RUNTIME code may not read a file
    for its configuration. Inside `scripts/` the practice is legitimate — a
    person runs those by hand, on a machine they control — and this exists only
    so the count cannot drift upward unnoticed while nobody is deciding
    anything.

    ⚠ THE BASELINE IS MEASURED. Guessing it would make the first run either
    vacuously green or noisily red, and both teach the next reader to ignore
    it. If a new operator script genuinely needs `.env`, raise the number in the
    same commit — the point is that it becomes a decision rather than a copy.
    """
    found = sorted(
        str(path.relative_to(REPO))
        for path in (REPO / "scripts").rglob("*.py")
        if "__pycache__" not in path.parts
        and any(marker in path.read_text(encoding="utf-8", errors="replace")
                for marker in FILE_READS))

    assert len(found) <= SCRIPTS_READING_ENV_BASELINE, (
        f"{len(found)} scripts read .env, baseline {SCRIPTS_READING_ENV_BASELINE}. "
        f"New ones: {sorted(set(found))[-3:]}. Raise the baseline in this commit "
        f"if that is intended.")
