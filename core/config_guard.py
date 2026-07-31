"""A config value the code does not recognise must be LOUD, not silent.

On 2026-07-31 the deployed `NUTRITION_RESOLVER_MODE` was `true`. The parser
accepts `off | shadow | live` and returns its default for anything else, so
production ran in SHADOW for six days while `render.yaml` recorded — in a
comment naming a person and a date — that the resolver had been live for all
users since 07-25. Nothing was broken. Nothing logged. `/health` reported
`env_set: true`, which was true and useless, because the var WAS set; it was
set to a word the code had never heard of.

`TURN_COORDINATOR_MODE` has the identical shape (`else MODE_LEGACY_ONLY`), so
this is a pattern in the codebase rather than one bad line. A typo there would
quietly run the legacy path, and the only symptom would be an improvement that
never arrives.

The registry below is the fix: one place that knows which env vars are
enumerations and what they accept. `invalid()` names the ones whose value the
code will silently ignore, `report()` says so at startup, and the diagnostics
endpoints surface `env_valid` so the question is answerable from outside the
container — which is the only place the six-day gap was ever visible from.

Deliberately NOT a hard failure at boot. Refusing to start on a bad flag turns
a degraded pipeline into an outage, and the value here is knowing, not
enforcing. The flags fall back exactly as they did before.
"""
from __future__ import annotations

import logging
import os
from typing import NamedTuple

logger = logging.getLogger(__name__)


class EnumFlag(NamedTuple):
    allowed: tuple[str, ...]
    falls_back_to: str


#: Every env var read as an enumeration, with what it accepts and what it
#: silently becomes otherwise. Add a flag here the moment its parser grows an
#: `else <default>` branch — that branch IS the silent failure.
ENUM_FLAGS: dict[str, EnumFlag] = {
    "NUTRITION_RESOLVER_MODE": EnumFlag(("off", "shadow", "live"), "shadow"),
    "TURN_COORDINATOR_MODE": EnumFlag(
        ("legacy_only", "new_observe", "new_execute"), "legacy_only"),
}


class Invalid(NamedTuple):
    name: str
    allowed: tuple[str, ...]
    falls_back_to: str


def invalid() -> list[Invalid]:
    """Env vars that are SET to something the code does not recognise.

    An UNSET var is not invalid — it is defaulted, which is a deliberate
    state. The failure this exists to catch is the one that looks configured.
    """
    out: list[Invalid] = []
    for name, flag in ENUM_FLAGS.items():
        raw = os.getenv(name)
        if raw is None:
            continue
        if raw.strip().lower() not in flag.allowed:
            out.append(Invalid(name, flag.allowed, flag.falls_back_to))
    return out


def is_valid(name: str) -> bool | None:
    """True/False for a registered enum flag that is set, None when the flag is
    unset or not an enumeration. None means "the question does not apply",
    which is not the same as passing."""
    flag = ENUM_FLAGS.get(name)
    if flag is None:
        return None
    raw = os.getenv(name)
    if raw is None:
        return None
    return raw.strip().lower() in flag.allowed


def report() -> list[Invalid]:
    """Log every ignored setting, once, at startup. Returns them so a caller
    can also surface them; never raises, never exits."""
    bad = invalid()
    for item in bad:
        # The raw value is NOT echoed. It is arbitrary environment content and
        # this line reaches the same logs everything else does; the name and
        # the allowed set are enough to fix it.
        logger.error(
            f"event=config_invalid name={item.name} "
            f"allowed={'|'.join(item.allowed)} "
            f"effective={item.falls_back_to} — the value set for this flag is "
            f"not recognised, so it is being IGNORED and the fallback is "
            f"running. This is the shape of the 2026-07-31 resolver gap.")
    return bad
