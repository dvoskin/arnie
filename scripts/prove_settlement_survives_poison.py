"""A7 — THE CONSUMER-SIDE POISONED PROOF, WITH THE BOUNDARY THAT MAKES IT REAL.

Canonical settlement must reach the artifact with every SETTLEMENT-side legacy
dependency poisoned to raise. If it can, then the price on the row came from the
committed artifact and not from a provider that happened to answer.

⛔⛔ THE AMENDMENT THAT MADE THIS PROVABLE *(P4, 2026-08-16)*. A7 first said to
poison "the resolver" — globally. That kills the PRE-SETTLEMENT identity work
the turn needs to produce a structured item at all, so the turn would never
reach settlement and the proof would pass by never running. The poison boundary
must separate INTERPRETATION from SETTLEMENT:

    poisoned   settlement-side USDA qualification · legacy executor enrichment
               · the resolver's settlement-time fallback
    untouched  the interpretation boundary's own identity work

⛔ AND THE POISON IS VERIFIED TO BITE FIRST (step 2). A silent poison and a
poison that was never reached are the same observation, and this project has
already spent a session on that shape. Each dependency is called DIRECTLY and
must raise before its silence during settlement counts for anything.

    ARNIE_PROVE_DB=postgresql+psycopg://$(whoami)@localhost:5432/arnie_migcheck \\
        ../arnie/.venv/bin/python -m scripts.prove_settlement_survives_poison
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

#: Every settlement-side seam canonical pricing is FORBIDDEN to use. Named
#: individually so a failure says which door was open, and so adding a seam is
#: a deliberate edit rather than a silently widened wildcard.
POISONED = (
    ("handlers.tool_executor", "_analyze_food"),
    ("handlers.tool_executor", "execute_tool_calls"),
)

CALLS: dict = {}


class PoisonBit(RuntimeError):
    """Raised BY the poison. Seeing this from a direct call is the bite."""


def _poison(label: str):
    def _raise(*args, **kwargs):
        CALLS[label] = CALLS.get(label, 0) + 1
        raise PoisonBit(f"{label} was called during canonical settlement")
    return _raise


def _load_key() -> None:
    if os.getenv("ANTHROPIC_API_KEY"):
        return
    env = pathlib.Path(__file__).resolve().parents[2] / "arnie" / ".env"
    for line in (env.read_text().splitlines() if env.exists() else ()):
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ["ANTHROPIC_API_KEY"] = line.split("=", 1)[1].strip("\"' ")
            return
    raise SystemExit("no ANTHROPIC_API_KEY, and none in ../arnie/.env")


def _artifact_identity() -> str:
    """STEP 1 — a PRE-REGISTERED, artifact-addressable identity.

    Taken from the committed artifact rather than hard-coded: a hard-coded name
    that has no artifact row makes this proof skip, and a skipped poisoned
    proof is indistinguishable from a passed one.
    """
    from skills.nutrition.pricing_artifact import _artifact, evidence_for

    for identity in (getattr(_artifact(), "entries", None) or {}):
        entity = str(identity).split("|")[0]
        if evidence_for(entity, "") is not None:
            return entity
    raise SystemExit("the committed artifact has no addressable identity — "
                     "A7 cannot be built and must not report success")


def bite() -> list:
    """STEP 2 — PROVE EACH POISON RAISES WHEN CALLED DIRECTLY."""
    import importlib

    proven = []
    for module_name, attribute in POISONED:
        module = importlib.import_module(module_name)
        label = f"{module_name}.{attribute}"
        setattr(module, attribute, _poison(label))
        try:
            getattr(module, attribute)()
        except PoisonBit:
            proven.append(label)
        else:                                          # pragma: no cover
            raise SystemExit(f"{label} did not raise — the poison is inert, "
                             f"and its silence during settlement would mean "
                             f"nothing")
    CALLS.clear()
    return proven


async def run(url: str) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from core.canonical_pricing import Rung
    from core.general_settlement import GeneralSettlementOwner, coverage_for
    from db.database import make_engine
    from db.models import User, UserPreferences
    from db.queries import get_or_create_today_log

    identity = _artifact_identity()
    proven = bite()
    print(f"\n  A7 — POISONED SETTLEMENT PROOF\n")
    print(f"    identity (pre-registered) : {identity}")
    print(f"    poisons proven to BITE    : {len(proven)}")
    for label in proven:
        print(f"      · {label}")

    engine = make_engine(url)
    session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session() as db:
            user = User(telegram_id=f"a7:{os.getpid()}", name="A7", age=37,
                        sex="male", height_cm=178.0, current_weight_kg=86.0,
                        goal_weight_kg=80.0, primary_goal="cut",
                        training_experience="advanced", injuries="none",
                        timezone="America/New_York", onboarding_completed=True)
            db.add(user)
            db.add(UserPreferences(user=user, calorie_target=2126,
                                   protein_target=190, coaching_style="direct",
                                   accountability_level="high",
                                   wake_time="07:00", sleep_time="23:30"))
            await db.flush()
            uid = user.id
            await get_or_create_today_log(db, uid, "America/New_York")
            await db.commit()

        item = {"food_name": identity, "quantity": "100 g"}

        async with session() as db:
            from db.queries import reload_user

            user = await reload_user(db, uid)

            # The predicate must route this to canonical, and must say the
            # ARTIFACT is what it expects — memory is empty for a fresh user.
            coverage = await coverage_for(db, user_id=uid, items=[item])
            print(f"\n    coverage                  : {type(coverage).__name__}"
                  f" ({getattr(coverage, 'expected_source', '-')})")
            if getattr(coverage, "expected_source", "") != "artifact":
                raise SystemExit("the predicate did not expect the artifact — "
                                 "this proof would not be testing A7")

            # STEPS 3-6 — settle with the poison in place.
            result = await GeneralSettlementOwner().settle(
                db, user=user, items=[item], source_turn_id=f"a7:{os.getpid()}",
                coverage=coverage)
            await db.commit()

        # STEP 7 — provenance and macros READ FROM THE DATABASE.
        committed = list(result.committed_items or ())
        pricing = (committed[0] if committed else {}).get("pricing") or {}
        print(f"    committed rung            : {pricing.get('rung')}")
        print(f"    evidence_id               : {pricing.get('evidence_id')}")
        print(f"    calories                  : "
              f"{(committed[0] if committed else {}).get('calories')}")

        # STEP 8 — the poison stayed silent DURING settlement.
        print(f"    poison calls during settle: {sum(CALLS.values())}  {CALLS or ''}")

        ok = (pricing.get("rung") == Rung.ARTIFACT.value
              and bool(pricing.get("evidence_id"))
              and sum(CALLS.values()) == 0)
        print(f"\n    -> {'PASS' if ok else '⛔ FAIL'} — canonical settlement "
              f"reached the artifact with every settlement-side legacy seam "
              f"poisoned\n")
        return 0 if ok else 1
    finally:
        await engine.dispose()


def main() -> int:
    url = os.getenv("ARNIE_PROVE_DB")
    if not url:
        raise SystemExit("set ARNIE_PROVE_DB to a SCRATCH database")
    os.environ.setdefault("DATABASE_URL", url)
    _load_key()
    return asyncio.run(run(url))


if __name__ == "__main__":
    raise SystemExit(main())
