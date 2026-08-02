"""Per-user gate for NUTRITION_ACCURACY_V2 (the canary the flag never had).

`NUTRITION_ACCURACY_V2` was global — on for everyone or no one — so "trial V2 on
my account first" was impossible without shipping it to the whole fleet. This adds
an allowlist scoped to the ambient turn user, mirroring the resolver canary's
shape (skills/nutrition/canary.py).

Precedence, highest first:
  1. the global flag  -> everyone (unchanged; how the evals run V2)
  2. the allowlist    -> only those user ids
  3. otherwise        -> off

Outside a turn the ambient user is unset and ONLY the global flag applies, so
eval scripts and any non-turn caller behave exactly as before. `run_turn` binds
the user for the turn's duration via `for_user`, which spans both the interpreter
pass and the later tool execution where the matcher runs.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Optional

#: The ambient user for V2 gating, bound by `run_turn`. A contextvar (not a
#: global) so concurrent turns on one event loop never read each other's user.
_USER: ContextVar[Optional[int]] = ContextVar("nutrition_v2_user", default=None)


def _global_on() -> bool:
    return os.getenv("NUTRITION_ACCURACY_V2", "").lower() in ("1", "true", "yes")


def _allowlist() -> set:
    out: set = set()
    for part in (os.getenv("NUTRITION_ACCURACY_V2_ALLOWLIST", "") or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


@contextmanager
def for_user(user_id):
    """Bind the ambient user for V2 gating for the duration of a turn."""
    try:
        uid = int(user_id) if user_id is not None else None
    except (TypeError, ValueError):
        uid = None
    token = _USER.set(uid)
    try:
        yield
    finally:
        try:
            _USER.reset(token)
        except Exception:                                    # pragma: no cover
            pass


def v2_active() -> bool:
    """Whether the V2 accuracy capability is on for the turn in flight.

    Never raises: any trouble reads as the global flag alone, so a bug in the
    per-user path can only ever fall back to the pre-canary behaviour."""
    try:
        if _global_on():
            return True
        allow = _allowlist()
        if not allow:
            return False
        uid = _USER.get()
        return uid is not None and uid in allow
    except Exception:                                        # pragma: no cover
        return _global_on()


def cohort_label() -> str:
    """How V2 is scoped right now, for /health and traces: global | allowlist | off.
    (No user in scope at /health time, so this reports the shape, not a verdict.)"""
    if _global_on():
        return "global"
    if _allowlist():
        return "allowlist"
    return "off"
