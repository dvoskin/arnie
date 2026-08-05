"""
Read-only diagnostics for the authenticated user. No write paths; no PII
beyond what the user already sees in their Profile sheet. Designed for
debugging "Arnie can't see my X" complaints — surfaces the exact rows +
env-gate state the chat path reads, so we don't have to guess whether a
field is set or whether an env var actually loaded.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends

from api.auth import current_identity
from core import config_guard
from db.database import AsyncSessionLocal
from db.queries import resolve_user, location_enabled, get_or_create_user

router = APIRouter(prefix="/api/v1/debug", tags=["debug"])


@router.get("/me")
async def get_me(identity: str = Depends(current_identity)) -> dict:
    """The exact user row the chat path operates on, plus the env gates
    that decide which tools the LLM sees. Use this to confirm Location
    coords/city/timezone, food_logging_mode, primary platform identity,
    and whether features are environmentally enabled — without piecing
    it together from /profile + /preferences."""
    async with AsyncSessionLocal() as db:
        raw = await get_or_create_user(db, identity)
        user = await resolve_user(db, identity)  # follows linked_to_user_id
        prefs = user.preferences
        return {
            "identity_sent": identity,
            "raw_user": {
                "id": raw.id,
                "telegram_id": raw.telegram_id,
                "linked_to_user_id": raw.linked_to_user_id,
            },
            "canonical_user": {
                "id": user.id,
                "telegram_id": user.telegram_id,
                "name": user.name,
            },
            "location": {
                "lat": user.lat,
                "lng": user.lng,
                "city": user.city,
                "timezone": user.timezone,
                "location_updated_at": user.location_updated_at.isoformat()
                    if user.location_updated_at else None,
            },
            "preferences": {
                "food_logging_mode": getattr(prefs, "food_logging_mode", None) if prefs else None,
                "coaching_style": getattr(prefs, "coaching_style", None) if prefs else None,
                "accountability_level": getattr(prefs, "accountability_level", None) if prefs else None,
                "reminder_frequency": getattr(prefs, "reminder_frequency", None) if prefs else None,
                "preferred_response_length": getattr(prefs, "preferred_response_length", None) if prefs else None,
            },
            "food_pipeline": _food_pipeline(user.id),
            "env_gates": {
                "LOCATION_ENABLED": location_enabled(),
                "SEARCH_ENABLED": os.getenv("SEARCH_ENABLED", "false").lower() in ("true", "1", "yes"),
                "WHOOP_CLIENT_ID_set": bool(os.getenv("WHOOP_CLIENT_ID")),
                "GOOGLE_PLACES_API_KEY_set": bool(os.getenv("GOOGLE_PLACES_API_KEY")),
                "DEV_AUTH_ENABLED": os.getenv("DEV_AUTH_ENABLED", "false").lower() in ("true", "1", "yes"),
                # Deep-research + model wiring — the three things that decide
                # whether smart turns actually work post-deploy. If a deep turn
                # gives a generic no-specifics plan, check these first.
                "DEFAULT_MODEL": _default_model(),
                "TAVILY_API_KEY_set": bool(os.getenv("TAVILY_API_KEY")),
                "DEEP_RESEARCH_MODEL": os.getenv("DEEP_RESEARCH_MODEL", "claude-sonnet-5"),
                "DEEP_RESEARCH_DAILY_CAP": os.getenv("DEEP_RESEARCH_DAILY_CAP", "8"),
            },
        }


def _flag(name: str, effective) -> dict:
    """One rollout flag, reported so DEFAULTED is distinguishable from SET.

    `effective` is resolved by the caller through the SAME accessor the
    runtime uses — the only value that answers "what is production actually
    doing". The raw env reading rides alongside because the two answer
    different questions: a var that never loaded and a var deliberately set
    to its own default produce identical behaviour and need opposite fixes
    (fix the deploy vs. change the value). Reporting only the effective mode
    cannot tell those apart, which is the entire reason this block exists.
    """
    raw = os.getenv(name)
    return {"effective": effective, "env_set": raw is not None, "env_raw": raw}


def _food_pipeline(user_id: Optional[int] = None) -> dict:
    """Which food pipeline a turn actually takes, resolved at runtime.

    Every flag here has a CODE default that differs from what render.yaml
    declares, so repo state cannot answer "what is deployed": an env var that
    silently failed to load runs a different pipeline than the config file
    describes, with no error anywhere. Specifically, unset means
    coordinator=legacy_only, resolver=shadow, composer=off — while
    render.yaml declares new_observe / live / true.

    Resolved through the real accessors rather than re-read from the
    environment here, so this block cannot drift from the behaviour it
    reports. Each entry is independently guarded: a diagnostic that 500s on
    one bad import is useless exactly when it is needed most.
    """
    out: dict = {}

    try:
        from core.turns.coordinator import coordinator_mode
        out["TURN_COORDINATOR_MODE"] = _flag(
            "TURN_COORDINATOR_MODE", coordinator_mode())
    except Exception as e:                           # pragma: no cover
        out["TURN_COORDINATOR_MODE"] = {"error": str(e)}

    # A FLAG NOBODY CAN SEE IS A DECISION NOBODY MAKES. The master audit's own
    # finding was flags parked in shadow with no owner and no review date
    # (`FOOD_FAST_PATH_SHADOW`, "shadow since 07-29, no decision date"). This
    # one ships OFF with a written enable condition, and reporting it here is
    # what turns "remember to switch it on" into something visible from
    # outside the container, for free, on every deploy check.
    try:
        from core.food_pipeline import identity_ask_enabled
        out["FOOD_IDENTITY_ASK"] = _flag(
            "FOOD_IDENTITY_ASK", identity_ask_enabled())
    except Exception as e:                           # pragma: no cover
        out["FOOD_IDENTITY_ASK"] = {"error": str(e)}

    try:
        from skills.nutrition.promotion import (owns_committed_values,
                                                resolver_mode)
        out["NUTRITION_RESOLVER_MODE"] = _flag(
            "NUTRITION_RESOLVER_MODE", resolver_mode())
        # The mode alone does not decide the resolver's authority: live mode
        # still filters through the canary cohort (allowlist / percentage /
        # halt flag). This is the value that actually decides whether the
        # resolver owns THIS user's committed numbers — and, because the
        # promotion telemetry sits behind the same call, whether their turns
        # emit `event=nutrition_promotion` lines at all.
        out["resolver_owns_committed_values"] = owns_committed_values(user_id)
    except Exception as e:                           # pragma: no cover
        out["NUTRITION_RESOLVER_MODE"] = {"error": str(e)}

    # The accuracy matcher's gate was invisible here — the redesign flag could be
    # on or off and /health said nothing, so "is V2 actually live for the canary
    # user?" had to be answered by log-grep. `effective` is the cohort shape
    # (global | allowlist | off); the authed view also carries the allowlist and,
    # for the user asked about, whether V2 resolves ON for them.
    try:
        from skills.nutrition.v2_gate import (_allowlist, cohort_label,
                                              for_user, v2_active)
        _v2_set = (os.getenv("NUTRITION_ACCURACY_V2") is not None
                   or os.getenv("NUTRITION_ACCURACY_V2_ALLOWLIST") is not None)
        entry = {"effective": cohort_label(), "env_set": _v2_set,
                 "allowlist": sorted(_allowlist())}
        if user_id is not None:
            with for_user(user_id):
                entry["active_for_user"] = v2_active()
        out["NUTRITION_ACCURACY_V2"] = entry
    except Exception as e:                           # pragma: no cover
        out["NUTRITION_ACCURACY_V2"] = {"error": str(e)}

    try:
        from core.food_response import _composer_model, composer_enabled
        out["FOOD_COMPOSER"] = _flag("FOOD_COMPOSER", composer_enabled())
        out["FOOD_COMPOSER_MODEL"] = _composer_model()
    except Exception as e:                           # pragma: no cover
        out["FOOD_COMPOSER"] = {"error": str(e)}

    # THE TWO FLAGS THE 2026-08-03 REPAIR TURNS ON, AND NEITHER WAS VISIBLE.
    # This block's own opening argument applies to both: a code default that
    # differs from what render.yaml declares, so repo state cannot answer "what
    # is deployed". After that repair went live the only way to answer "is an
    # ask still writing rows in production?" was to ask a human to open the
    # Render dashboard — which is precisely the "flag nobody can see" the
    # FOOD_IDENTITY_ASK note above objects to.
    #
    # FOOD_PARTIAL_COMMIT is the load-bearing one. Its code default is now
    # false (an ask writes nothing, held food rides the pending question), and
    # a dashboard override of `true` silently restores the defect the whole
    # repair exists to remove: a card that reads as finished above a question
    # that says it is not.
    try:
        from core.food_turn import partial_commit_enabled
        out["FOOD_PARTIAL_COMMIT"] = _flag(
            "FOOD_PARTIAL_COMMIT", partial_commit_enabled())
    except Exception as e:                           # pragma: no cover
        out["FOOD_PARTIAL_COMMIT"] = {"error": str(e)}

    # FOOD_PORTION_PRICING decides whether a generic food is priced from a
    # calibrated portion or from the model's calorie guess — a 3% vs 15% median
    # error difference against published portion weights. It ships ON, so its
    # interesting state is somebody having turned it OFF.
    try:
        from core.food_intelligence import portion_pricing_enabled
        out["FOOD_PORTION_PRICING"] = _flag(
            "FOOD_PORTION_PRICING", portion_pricing_enabled())
    except Exception as e:                           # pragma: no cover
        out["FOOD_PORTION_PRICING"] = {"error": str(e)}

    # THE CANONICAL MIGRATION'S OWN FLAGS, for the reason this whole block
    # exists — and learned the hard way on the 593bd19 deploy, where the
    # shadow's entire purpose is to produce parity data and there was no way to
    # tell from outside whether it was running.
    #
    # That ambiguity is worse than an off flag. An unset shadow produces a
    # clean, empty, zero-divergence window that looks exactly like a lane in
    # perfect agreement — so the evidence used to promote a mutation owner and
    # DELETE its predecessor could be the evidence of nothing having run.
    try:
        from api.quick_log import FOOD_WRITER
        out["QUICK_LOG_FOOD_WRITER"] = FOOD_WRITER
    except Exception as e:                           # pragma: no cover
        out["QUICK_LOG_FOOD_WRITER"] = {"error": str(e)}

    # B-1's rollout state, published for the same reason the shadow flag is:
    # a deploy has to be verifiable as OFF from outside before anything is
    # enabled. Inferring "it must be off, nothing happened" is how an unset
    # flag once produced a clean empty window that looked like perfect
    # agreement. Stage 1 of the live probe reads exactly this.
    try:
        from skills.nutrition.quantity_rollout import state as _b1_state
        out["B1_QUANTITY"] = _b1_state()
    except Exception as e:                           # pragma: no cover
        out["B1_QUANTITY"] = {"error": str(e)}

    try:
        from core.canonical_shadow import shadow_enabled
        out["CANONICAL_WRITER_SHADOW"] = _flag(
            "CANONICAL_WRITER_SHADOW", shadow_enabled())
    except Exception as e:                           # pragma: no cover
        out["CANONICAL_WRITER_SHADOW"] = {"error": str(e)}

    try:
        from core.pending_repository import (commit_enforce_enabled,
                                             persist_shadow_enabled)
        out["PENDING_OPERATION_PERSIST_SHADOW"] = _flag(
            "PENDING_OPERATION_PERSIST_SHADOW", persist_shadow_enabled())
        out["COMMIT_COORDINATOR_ENFORCE"] = _flag(
            "COMMIT_COORDINATOR_ENFORCE", commit_enforce_enabled())
    except Exception as e:                           # pragma: no cover
        out["COMMIT_COORDINATOR_ENFORCE"] = {"error": str(e)}

    return out


def public_pipeline_summary() -> dict:
    """The same effective modes, shaped for an UNAUTHENTICATED endpoint.

    `/health` is the only way to check a deployed container without holding a
    user token, and "did the env var take" is exactly the question it already
    exists to answer for the log voice. The modes are not secret — they are
    the same strings render.yaml documents in the clear.

    What is deliberately dropped is `env_raw`. Echoing arbitrary environment
    content on a public endpoint is a habit worth not starting, even for
    values that only ever hold mode names today; a typo puts whatever was
    actually typed into the response. `env_set` keeps the distinction that
    matters — defaulted vs. deliberately set — without echoing the content.
    """
    out: dict = {}
    for key, entry in _food_pipeline().items():
        if not isinstance(entry, dict):
            out[key] = entry
        elif "error" in entry:
            out[key] = {"error": entry["error"]}
        else:
            summary = {"effective": entry.get("effective"),
                       "env_set": entry.get("env_set")}
            # `env_set: true` was true and useless during the six-day resolver
            # gap: the var WAS set — to `true`, a word the parser does not
            # accept, so it silently ran the fallback. `env_valid: false` is
            # the field that would have said so. Absent when the flag is not an
            # enumeration or is unset, because "does not apply" is not "passed".
            valid = config_guard.is_valid(key)
            if valid is not None:
                summary["env_valid"] = valid
            out[key] = summary
    return out


_EXPECTED_HEAD: Optional[str] = None


def _expected_head() -> Optional[str]:
    """The migration head this BUILD expects, read once from the script dir.

    Static for the life of the process — the versions directory ships inside
    the image — so it is computed on first ask and cached. Returns None if
    alembic cannot be read rather than raising: a health check must not fail
    because it could not describe itself.
    """
    global _EXPECTED_HEAD
    if _EXPECTED_HEAD is None:
        try:
            from alembic.config import Config
            from alembic.script import ScriptDirectory
            # Resolved from THIS file, not the working directory. `python
            # main.py` happens to start at the repo root today, but a health
            # check that silently reports "expected: unknown" because someone
            # changed the start command is the kind of quiet degradation this
            # endpoint exists to prevent.
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cfg = Config(os.path.join(root, "alembic.ini"))
            cfg.set_main_option("script_location", os.path.join(root, "alembic"))
            heads = ScriptDirectory.from_config(cfg).get_heads()
            # Multiple heads is itself a deployable defect (CI has a one-head
            # check); report them all rather than picking one.
            _EXPECTED_HEAD = ",".join(sorted(heads)) if heads else ""
        except Exception:
            _EXPECTED_HEAD = ""
    return _EXPECTED_HEAD or None


async def schema_summary() -> dict:
    """Which migration the live database is ACTUALLY on.

    Until this existed, "did the migration run" was unanswerable from outside
    the container. `render.yaml` documents `alembic upgrade heads` as the
    pre-deploy command, but the service is configured by hand in the Render
    dashboard and Render never reads that file — so the file documents an
    intention, not a fact, and nothing reported the difference. A deploy whose
    pre-deploy step is missing looks completely healthy right up until the
    first write to a column that was never added.

    `in_sync` is the whole point: it compares what the database is on against
    what this build expects, and a false there is a deploy to stop.

    Never raises — a health endpoint that 500s because it could not read the
    schema has turned an observability gap into an outage.
    """
    applied = None
    error = None
    try:
        from sqlalchemy import text as _text

        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                _text("SELECT version_num FROM alembic_version"))).scalars().all()
        applied = ",".join(sorted(rows)) if rows else None
    except Exception as e:
        # An unmigrated database has no alembic_version table at all, which is
        # a legitimate answer and not the same as "could not ask".
        error = type(e).__name__

    expected = _expected_head()
    out: dict = {"applied": applied, "expected": expected}
    if error:
        out["error"] = error
    if applied and expected:
        out["in_sync"] = applied == expected
    return out


def _default_model() -> str:
    """The model the chat path actually resolves — so a deploy can confirm the
    Sonnet 5 bump took (a Render DEFAULT_MODEL env var OVERRIDES the code
    fallback, so this is the source of truth, not the code default)."""
    try:
        from core.llm import DEFAULT_MODEL
        return DEFAULT_MODEL()
    except Exception:
        return os.getenv("DEFAULT_MODEL", "unknown")
