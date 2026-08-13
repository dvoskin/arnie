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


# ── AS-EATEN, SPLIT OUT OF V2 ─────────────────────────────────────────────
#
# ⭐ V2 IS NOT ONE THING, AND FREEZING A BASELINE UNDER IT AS THOUGH IT WERE
# WOULD SIGN A TRANSITIONAL MISTAKE INTO THE RECORD. Measured 2026-08-13,
# it contains two behaviours of different maturity:
#
#   STRUCTURAL SAFETY — folded morphology, the identity/coverage gate,
#   cross-food refusal, cooked-by-default, the typed artifact refusal. These
#   only ever decline to seat a wrong row or reach a right one. Over 600 real
#   production food names, V2 refused 15 rows v1 seats and at least 8 of them
#   were flatly the wrong food: asparagus for "boiled egg", shrimp for
#   "squash", tofu for "fried lamb", portabella for "grilled shrimp".
#
#   PREFERENCE POLICY — `as_eaten_over_trimmed`, a ±0.4 tie-break. It works
#   as designed and it is still not safe to freeze against, because a ±0.4
#   nudge can only overturn a NEAR-TIE: of the six winners it moves, five are
#   decided by this term alone with every other term within 0.16, so the row
#   it selects also differs in dimensions the rule never evaluated. It picked
#   striploin-with-fat over knuckle (+123 kcal, mostly CUT, not trim) and a
#   BATTERED chicken row over meat-only (+7.7 g carbs, which is added food).
#
# These are cut choices wearing a trim rule's clothes. A rule named
# `as_eaten_over_trimmed` must not decide knuckle vs striploin unless cut is
# separately modelled — so the preference gets its own switch and its own
# canary, and the structural half can become canonical without it.
#
# DEFAULT OFF, including for the V2 allowlist. Turning it on is a deliberate
# act with its own release proof, exactly like V2 itself.


def _as_eaten_global_on() -> bool:
    return os.getenv("NUTRITION_AS_EATEN_PREFERENCE",
                     "").lower() in ("1", "true", "yes")


def _as_eaten_allowlist() -> set:
    out: set = set()
    for part in (os.getenv("NUTRITION_AS_EATEN_PREFERENCE_ALLOWLIST",
                           "") or "").split(","):
        part = part.strip()
        if part.isdigit():
            out.add(int(part))
    return out


def as_eaten_active() -> bool:
    """Whether the as-eaten PREFERENCE applies to the turn in flight.

    Independent of `v2_active`: the caller still requires V2 for the rest of
    the V2 scoring, but this term can be off while V2 is on. That separation
    is the point — it is what lets the structurally safe half be promoted
    without carrying an unproven selector into the frozen baseline.
    """
    try:
        if _as_eaten_global_on():
            return True
        allow = _as_eaten_allowlist()
        if not allow:
            return False
        uid = _USER.get()
        return uid is not None and uid in allow
    except Exception:                                        # pragma: no cover
        return _as_eaten_global_on()


def as_eaten_cohort_label() -> str:
    if _as_eaten_global_on():
        return "global"
    if _as_eaten_allowlist():
        return "allowlist"
    return "off"


#: The ranking regime a winner was produced under. Recorded rather than
#: assumed, because "which policy picked this row" is exactly the question
#: the mode-divergence finding showed nobody could answer.
def ranking_policy_version() -> str:
    return (f"rank_v{'2' if v2_active() else '1'}"
            f"{'+as_eaten' if (v2_active() and as_eaten_active()) else ''}")


# ── THE PROOF REGIME IS DECLARED, NOT INHERITED ───────────────────────────
#
# ⭐ A BASELINE THE CALLER'S SHELL CAN MOVE IS NOT FROZEN. The winner review,
# the artifact rebuild, the population run and the reproducibility proof must
# all be computed under ONE named policy — and until now each of them set
# `NUTRITION_ACCURACY_V2` by hand and inherited `NUTRITION_AS_EATEN_PREFERENCE`
# from whatever the process happened to carry. Two of those tools would have
# produced different winners under a developer's exported flag, silently.
#
# `RANK_V2` is the regime Phase 0 freezes against: V2's structural half with
# the as-eaten preference OFF. Naming it makes "which policy proved this"
# answerable from the artifact rather than from shell history.
RANK_V1 = "rank_v1"
RANK_V2 = "rank_v2"
RANK_V2_AS_EATEN = "rank_v2+as_eaten"

_REGIME_FLAGS = {
    RANK_V1: {"NUTRITION_ACCURACY_V2": "", "NUTRITION_AS_EATEN_PREFERENCE": ""},
    RANK_V2: {"NUTRITION_ACCURACY_V2": "1", "NUTRITION_AS_EATEN_PREFERENCE": ""},
    RANK_V2_AS_EATEN: {"NUTRITION_ACCURACY_V2": "1",
                       "NUTRITION_AS_EATEN_PREFERENCE": "1"},
}

#: What Phase 0 proves against. Changing this is a policy migration, not a
#: configuration tweak.
PHASE_0_REGIME = RANK_V2


@contextmanager
def ranking_regime(regime: str):
    """Pin BOTH policy dimensions, and refuse to trust the ambient shell.

    Every flag the ranking regime depends on is set explicitly — including the
    ones the caller wanted OFF, because an unset variable and a variable set
    elsewhere are the same thing to `os.getenv` and only one of them is a
    decision.
    """
    if regime not in _REGIME_FLAGS:
        raise ValueError(f"{regime!r} is not a ranking regime; "
                         f"known: {sorted(_REGIME_FLAGS)}")
    previous = {k: os.environ.get(k) for k in _REGIME_FLAGS[regime]}
    os.environ.update(_REGIME_FLAGS[regime])
    try:
        import importlib

        import core.food_intelligence as fi
        importlib.reload(fi)
        if ranking_policy_version() != regime:
            raise RuntimeError(
                f"the regime did not take effect: asked for {regime}, running "
                f"{ranking_policy_version()}")
        yield regime
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import importlib

        import core.food_intelligence as fi
        importlib.reload(fi)
