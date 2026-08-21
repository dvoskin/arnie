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

    # ⛔ THE MODE ALONE CANNOT ANSWER "IS ANYTHING BEING CONSUMED", and that is
    # the question a shadow canary has to answer before consumption is turned
    # on. `shadow` used to mean persist-only on legacy traffic and CONSUME on
    # `new_execute` traffic, so a reader who saw `shadow` learned nothing about
    # whether prices could move. `consumes_identity` reports the PREDICATE
    # itself — the same function `stamp_canonical_identity` asks — rather than
    # re-deriving it from the mode string here, because a diagnostic that
    # recomputes what it reports can disagree with it.
    try:
        from core.turns.stages.food import (entity_resolution_mode,
                                            identity_is_consumable)
        out["ENTITY_RESOLUTION_MODE"] = _flag(
            "ENTITY_RESOLUTION_MODE", entity_resolution_mode())
        # ⭐ THE COHORT, NOT JUST THE MODE. `consume` with an empty cohort
        # enrols nobody, so reporting the mode alone would say "consuming"
        # about a deployment that consumes for no one — and reporting a bare
        # boolean would hide WHO. Sizes and ids, never env content.
        from core.turns.stages.food import _consume_allowlist
        _consume = sorted(_consume_allowlist())
        out["ENTITY_RESOLUTION_CONSUME_ALLOWLIST"] = {
            "effective": _consume,
            "env_set": os.getenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST") is not None}
        out["consumes_identity"] = {
            "effective_for_anyone": bool(_consume) and
            entity_resolution_mode() == "consume",
            "cohort_size": len(_consume)}
    except Exception as e:                           # pragma: no cover
        out["ENTITY_RESOLUTION_MODE"] = {"error": str(e)}

    # ⛔ THE MODE ALONE IS NOT THE ANSWER, AND READING IT AS ONE COST A
    # DIAGNOSIS ON 2026-08-14. `lane_executes_natively` is an AND of three
    # conditions — mode, lane enrolled, user allowlisted — so
    # `TURN_COORDINATOR_MODE: new_execute` beside no enabled lane means legacy
    # executes every turn, while this block said the coordinator was executing.
    # A canary spent two runs asking why canonical pricing never fired.
    #
    # Reported through `lane_executes_natively` itself rather than by
    # re-deriving the conjunction here: a diagnostic that recomputes the
    # predicate it reports can disagree with it, which is the failure being
    # fixed. `structured_food` is named because it is the lane this migration
    # promotes; the raw vars ride alongside so an unenrolled lane is
    # distinguishable from an unset var.
    try:
        from core.turns.coordinator import (_allowlist, _enabled_lanes,
                                            lane_executes_natively)
        _allow = sorted(_allowlist())
        out["TURN_COORDINATOR_LANES"] = _flag(
            "TURN_COORDINATOR_LANES", sorted(_enabled_lanes()))
        out["TURN_COORDINATOR_ALLOWLIST"] = _flag(
            "TURN_COORDINATOR_ALLOWLIST", _allow)
        out["structured_food_executes_natively"] = {
            # For a user IN the allowlist — the only cohort for which native
            # execution is reachable at all when one is set.
            "allowlisted_user": lane_executes_natively(
                "structured_food", _allow[0] if _allow else None),
            # And for everyone else, which is the fleet.
            "fleet": lane_executes_natively("structured_food", None)
            if not _allow else False,
        }
    except Exception as e:                           # pragma: no cover
        out["TURN_COORDINATOR_LANES"] = {"error": str(e)}

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
            # DROP `env_raw`; KEEP THE REST. The rule this implements is
            # "never echo arbitrary environment content on a public
            # endpoint" — and writing it as a two-field allowlist made it
            # silently destructive to any entry shaped differently from a
            # flag. B1_QUANTITY reports {halted, percent, allowlist_size};
            # it arrived here as {"effective": null, "env_set": null},
            # which is not "B-1 is off" but "this endpoint cannot say" —
            # and those read identically to anyone checking a deploy.
            #
            # Caught by the B-1 probe's Stage 1 on the first real deploy,
            # which is what that stage exists for: verify OFF from outside
            # rather than inferring it from nothing having happened.
            #
            # Counts and booleans are not env content. `allowlist_size` is a
            # SIZE, deliberately, and not the ids.
            summary = {k: v for k, v in entry.items() if k != "env_raw"}
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


async def identity_adoption_summary() -> dict:
    """⭐ IS THE PRODUCER RUNNING, AND IS ANYTHING BEING CONSUMED — from outside.

    The two questions a shadow canary must answer, and neither was answerable
    without reading container logs:

        step 7  non-zero resolution ACTIVITY      -> `recorded`, by state
        step 8  ZERO consumption / zero price movement
                -> `memory_rows_not_keyed_by_their_own_name`

    ⛔⛔ `memory_rows_not_keyed_by_their_own_name` IS THE DETERMINISTIC FORM OF
    "NO PRICE MOVED", and it is the only one that does not depend on sampling a
    nondeterministic model. `memory_key(food, entity)` returns
    `normalize_name(entity)` when an identity is present and
    `normalize_name(food)` otherwise, with NOTHING marking which — so the only
    available detector is the inequality: a row whose key is not its own
    normalized display name was keyed by something else, and the only something
    else is an identity. Under `shadow` this must be **0**.

    ⭐ AND COINCIDENTAL EQUALITY IS NOT A MISS. If the identity key happens to
    equal the surface key, consumption addressed the same row and no price
    could have moved — the case this cannot see is by definition a non-event.

    ⚠ ITS ONE FALSE POSITIVE, NAMED. The check assumes the display name IS the
    string the key was derived from. Every production writer satisfies that —
    all three `upsert_user_food_match` call sites pass one string as both — but
    a HAND-SEEDED row does not: `prove_memory_addressing` writes
    `display_name='Tomato, raw'` under the key `'tomato'` deliberately, and a
    scratch database therefore reports 2 where production reports 0. Read this
    number on production, not on a scratch DB you have been proving things in.

    ⚠ ZERO IS ONLY MEANINGFUL BESIDE `recorded`. A store with no rows at all
    also reports zero identity-keyed rows, and that is the ambiguous zero this
    project keeps paying for — "nothing consumed" and "nothing ran" have one
    spelling unless both numbers are read together. They are returned together
    for exactly that reason.

    ⚠ COUNTS AND STATES ONLY — no food names, no user ids, no env content. This
    endpoint sits beside ones that already refuse to echo `env_raw`.

    Never raises: a diagnostic that 500s has turned an observability gap into
    an outage.
    """
    out: dict = {"resolutions": {}, "memory_rows_not_keyed_by_their_own_name": None}
    try:
        from sqlalchemy import func, select

        from core.food_intelligence import normalize_name
        from core.turns.stages.food import (entity_resolution_mode,
                                            identity_is_consumable)
        from db.models import FoodEntityResolution, UserFoodMatch

        from core.turns.stages.food import _consume_allowlist
        out["mode"] = entity_resolution_mode()
        out["consume_cohort"] = sorted(_consume_allowlist())
        out["consumes_identity_for_anyone"] = bool(
            out["consume_cohort"]) and out["mode"] == "consume"

        async with AsyncSessionLocal() as db:
            rows = (await db.execute(
                select(FoodEntityResolution.state,
                       func.count(FoodEntityResolution.id))
                .group_by(FoodEntityResolution.state))).all()
            by_state = {getattr(state, "value", str(state)): int(count)
                        for state, count in rows}
            out["resolutions"] = by_state
            out["recorded"] = sum(by_state.values())

            # ⚠ COMPARED IN PYTHON, NOT IN SQL. `normalize_name` is the
            # production normalizer and it has no SQL equivalent; reimplementing
            # it in a query would be a second definition of the predicate, which
            # is how an instrument comes to disagree with the runtime it
            # measures. Bounded so a diagnostic can never become a table scan
            # that matters.
            matches = (await db.execute(
                select(UserFoodMatch.name_norm, UserFoodMatch.display_name)
                .limit(5000))).all()
            stamped = [1 for key, display in matches
                       if key and display and key != normalize_name(display)]
            out["memory_rows_not_keyed_by_their_own_name"] = len(stamped)
            out["memory_rows_examined"] = len(matches)
    except Exception as e:
        out["error"] = type(e).__name__
    return out


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


def settlement_gates_summary() -> dict:
    """⭐ WHICH GATES ARE ACTUALLY OPEN, AS THE PROCESS SEES THEM.

    ⛔⛔ THIS EXISTS BECAUSE A CANARY FAILED SILENTLY AND NEITHER OF US COULD
    SAY WHY *(2026-08-16)*. The general settlement canary was enabled, the code
    was confirmed deployed, and a fully-supported meal was still settled by
    legacy. Four gates decide that turn, and NOT ONE of them was readable from
    outside the container — so the diagnosis came from archaeology on
    `turn_metrics.stages_json` instead of from a single question with an answer.

    ⛔⛔ AND THAT ARCHAEOLOGY RESTED ON AN INFERENCE NOW KNOWN TO BE FALSE,
    RETIRED HERE *(Tranche D2, 2026-08-21)*. It read: "a long
    `pricing.qualification` proves legacy settled the turn, because canonical
    settlement structurally cannot retrieve." It does not prove that.
    `core/food_turn.py` launches a FIRE-AND-FORGET speculative USDA/OFF
    prewarm from the interpreter's token stream — before settlement ownership
    is decided at all — and `core/request_trace.timed()` records onto the
    AMBIENT trace, so the stage lands in the turn's `stages_json` whichever
    lane settles. Measured on `ios:5F861208…`: `pricing.qualification` 5379 ms
    beside `llm` 6601 ms in a turn whose `total_ms` was 9523 — the two MUST
    overlap by ≥2457 ms, so the stage was not even on the critical path.

    ⭐ THE REPLACEMENT IS THIS ENDPOINT, which is why it exists: settlement
    ownership is a question with an answer, not something to infer from a
    duration. Read the gates, not the timings.

    ⭐ AND EACH VALUE IS REPORTED AS THE CODE READS IT, not as the environment
    spells it. `TURN_COORDINATOR_LANES` unset is an EMPTY SET that enables
    NOTHING — a fact invisible in a list of raw strings, and the exact gate that
    cost a live diagnosis. So the effective predicate is reported beside the
    raw value, because the raw value is not the behaviour.

    ⚠ NO SECRETS, AND NO USER DATA. Cohorts are reported as SIZES and as
    whether they are empty, never as ids — an operator needs "is anyone
    enrolled", not who.
    """
    import os

    def _cohort(name: str) -> dict:
        raw = os.getenv(name, "") or ""
        ids = [p for p in raw.replace(",", " ").split() if p.strip().isdigit()]
        return {"set": bool(raw.strip()), "size": len(ids)}

    try:
        from core.turns.coordinator import coordinator_mode
        mode = coordinator_mode()
    except Exception:                                   # pragma: no cover
        mode = "unreadable"

    lanes = [p.strip() for p in
             (os.getenv("TURN_COORDINATOR_LANES", "") or "").split(",")
             if p.strip()]

    # THE ONE LINE THAT ANSWERS THE QUESTION. Every gate must be open for an
    # ordinary food turn to reach the general settlement owner; this says
    # whether they are, without the reader having to know the conjunction.
    reachable = bool(mode == "new_execute"
                     and "structured_food" in lanes
                     and _cohort("GENERAL_SETTLEMENT_ALLOWLIST")["set"])

    return {
        "coordinator_mode": mode,
        "coordinator_mode_executes": mode == "new_execute",
        "coordinator_lanes": lanes,
        "structured_food_lane_enabled": "structured_food" in lanes,
        "coordinator_cohort": _cohort("TURN_COORDINATOR_ALLOWLIST"),
        "general_settlement_cohort": _cohort("GENERAL_SETTLEMENT_ALLOWLIST"),
        "general_settlement_reachable": reachable,
        "why": ("every gate must be open: mode=new_execute AND "
                "structured_food in TURN_COORDINATOR_LANES AND a non-empty "
                "GENERAL_SETTLEMENT_ALLOWLIST (which fails closed when unset). "
                "An unset TURN_COORDINATOR_LANES is an EMPTY SET and enables "
                "nothing."),
    }
