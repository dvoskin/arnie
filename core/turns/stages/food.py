"""Native structured-food stages (P0.2 Phase 2).

The food lane already has the coordinator's shape internally — interpret →
validate → execute → snapshot → render — so it migrates first. These stages
call the SAME functions the legacy lane calls (core.food_turn.run, the
deterministic policy engine), which is what makes observe-mode comparison
meaningful: any divergence is a wiring bug, not two different opinions.

Nothing here executes. Execution stays with the legacy lane until a lane is
explicitly enabled via TURN_COORDINATOR_MODE=new_execute.
"""
from __future__ import annotations

import logging

from core.turns.models import TurnPlan, ValidationResult

logger = logging.getLogger(__name__)

FOOD_PLANNER_VERSION = "food_planner_v1"


class FoodPlanStage:
    """Runs the interpreter and lifts its result into a typed plan. The
    interpreter's own ask/confirm decisions arrive as ambiguities so the
    validation stage — not the planner — decides the disposition."""

    def __init__(self, interpreter=None):
        self._interpreter = interpreter

    async def run(self, request, context=None, route=None) -> TurnPlan:
        # A "yes" answering an open confirm is already decided (P0.2 Phase 3):
        # replay the stashed items rather than paying for a re-parse. Anything
        # else answering a confirm is a correction, and falls through.
        from core.turns.stages.deterministic import ConfirmReplayPlanStage
        replay = await ConfirmReplayPlanStage().run(request, context, route)
        if replay is not None:
            return replay
        run_interpreter = self._interpreter
        if run_interpreter is None:
            from core.food_turn import run as run_interpreter
        meta = request.metadata or {}
        try:
            out = await run_interpreter(
                request.text, meta.get("user"),
                prior=meta.get("food_prior"),
                day_line=meta.get("day_line", ""),
                board=meta.get("board"),
                last_assistant=meta.get("last_assistant", ""),
                regulars=meta.get("regulars"),
                thread_active=bool(meta.get("thread_active")))
        except Exception as e:
            logger.warning(f"food plan stage failed: {e}")
            out = None
        await stamp_canonical_identity(out, meta.get("db"))
        return plan_from_interpretation(out)


def entity_resolution_mode() -> str:
    """`off` | `shadow`. DEFAULT OFF, and off is the whole safety story.

    ⭐ SHADOW IS NOT A HALF-MEASURE HERE, IT IS THE POINT. Resolution POPULATES
    a durable store; CONSUMPTION is a separate change that nothing has made yet.
    So a shadow turn writes what a food means and alters no price, no card and
    no row — the store fills from real traffic while the blast radius stays
    exactly zero, and the 691-entry instrument can be re-run against a store
    built by users rather than by a backfill script.
    """
    import os

    mode = (os.getenv("ENTITY_RESOLUTION_MODE", "off") or "").strip().lower()
    return mode if mode in ("off", "shadow") else "off"


async def record_identities(out, db) -> dict:
    """Resolve this turn's foods and PERSIST what they mean. Annotates nothing.

    ⛔⛔ THIS EXISTS BECAUSE THE PRODUCER HAD ONE CALL SITE AND ORDINARY TRAFFIC
    NEVER REACHED IT. Measured 2026-08-15 on the real turn path: the same foods
    that write four resolutions when `stamp_canonical_identity` is called
    directly wrote ZERO through `run_chat_turn`, because the only caller is
    `FoodPlanStage.run` and production runs `TURN_COORDINATOR_MODE=legacy_only`,
    where no stage runs at all. A shadow canary would have reported "no
    behaviour change" — produced by the feature never running.

    ⭐ AND THE SPLIT IS THE WHOLE POINT: PERSISTENCE AND ANNOTATION ARE
    DIFFERENT DECISIONS. Stamping `canonical_entity_id` onto an item is not
    cosmetic — it travels through `_log_call` into `_analyze_food`, where
    `memory_key(food, entity)` addresses a DIFFERENT memory row, which changes
    the price. That is consumption, and consumption is a later step with its own
    canary.

    So the ordinary legacy turn calls THIS, which writes durable resolution
    evidence and changes nothing a user or a row can see. `shadow` means
    annotation-only: same operations, same food rows, same prices, same
    narration, and exactly one new side effect — the store filling up.

    ⚠ IT CANNOT FAIL A TURN, and that is not decoration either: a food turn must
    not break over an identity annotation nothing yet consumes.
    """
    if entity_resolution_mode() == "off" or db is None or not out:
        return {}
    items = [item for item in (out.get("items") or ()) if isinstance(item, dict)]
    surfaces = [str(item.get("food") or "").strip() for item in items]
    if not any(surfaces):
        return {}
    try:
        from skills.nutrition.entity_resolver import ensure_resolved

        resolved = await ensure_resolved(db, [s for s in surfaces if s])
    except Exception as e:
        logger.warning(f"entity resolution unavailable, identity unchanged: {e}")
        return {}
    # ⭐ ATTEMPTED, not just resolved. A count of successes cannot distinguish
    # "the producer ran and this turn's foods were unresolvable" from "the
    # producer never ran" — and telling those apart is the entire reason this
    # function exists.
    logger.info("event=entity_identity_recorded attempted=%d resolved=%d",
                len([s for s in surfaces if s]),
                sum(1 for s in surfaces if resolved.get(s)))
    return resolved


async def stamp_canonical_identity(out, db) -> None:
    """Resolve this turn's foods and hang the canonical entity on each item.

    ⛔ INTERPRETATION TIME, NOT SETTLE TIME. A model call belongs where one is
    already being made and its latency already paid; `price()` is synchronous by
    design and must stay reachable with every provider poisoned (Gate B). This
    also runs BEFORE the plan is lifted, so the identity travels with the item
    rather than being recovered later from a surface string — which is the whole
    defect being closed.

    ⚠ MOST TURNS COST NOTHING. `ensure_resolved` consults the durable store
    first and only asks about foods it has never seen, so a user's regular meals
    are interpreted once ever and every later turn is a lookup.

    ⚠⚠ AND IT CANNOT FAIL A TURN. Every error path inside the producer already
    returns no resolution; this adds the outer guard for everything else,
    because a food turn must not break over an identity annotation that nothing
    yet consumes.

    ⚠ THE RESOLUTION HALF NOW LIVES IN `record_identities`, and this is the
    ANNOTATING caller. Two producers would be two answers to one question, so
    there is one — this adds only the stamp, which is the part that makes the
    identity CONSUMABLE and therefore the part an ordinary shadow turn must NOT
    do. See `record_identities` for why that line matters.
    """
    resolved = await record_identities(out, db)
    if not resolved:
        return
    items = [item for item in (out.get("items") or ()) if isinstance(item, dict)]
    for item in items:
        entity = resolved.get(str(item.get("food") or "").strip())
        if entity:
            # ⚠ THIS IS CONSUMPTION'S DOORWAY. The stamp travels through
            # `_log_call` into `_analyze_food`, where it changes which memory
            # row `memory_key` addresses — and so the price.
            item["canonical_entity_id"] = entity
    logger.info("event=entity_identity_stamped foods=%d resolved=%d",
                len(items), sum(1 for i in items
                                if i.get("canonical_entity_id")))


def plan_from_interpretation(out) -> TurnPlan:
    """Lift an interpreter result into a typed plan. Pure — no model call.

    Split out of `FoodPlanStage.run` so shadow observation can lift the plan
    THE TURN ALREADY COMPUTED instead of running the interpreter a second time.
    That second run cost 2.6 s per food turn, after the reply had already
    shipped, and what it bought was worse than nothing: measured on one
    production session, the same message seconds apart gave "bag of Takis" as
    1330 cal and then 460, and "It was actually a double…" as an update to
    entry 2545 and then to entry 123, which does not exist. `agree=NO` was
    conflating "the native lane would decide differently" with "Sonnet is
    nondeterministic", so the promotion gate was reading its own noise.

    One lift, two callers, so the comparison stays a comparison of WIRING —
    which is the whole premise of observe mode — rather than of two samples
    from the same model.
    """
    if not out:
        return TurnPlan(operations=(), response_intent="pass",
                        planner_version=FOOD_PLANNER_VERSION)
    action = out.get("action")
    if action == "ask":
        return TurnPlan(
            # AN ASK IS NOT AN EMPTY TURN (audit A1). `core.food_turn` returns
            # an ask carrying the READY items' calls — the ones the
            # clarification veto already cleared — and legacy executes them
            # while asking about the rest. Dropping them here turned moderate's
            # PARTIAL_COMMIT contract into ATOMIC_HOLD, which is the exact
            # regression conversation.py records having fixed once already: the
            # whole meal waits on its least certain item.
            operations=tuple(out.get("tool_calls") or ()),
            response_intent=("confirm" if out.get("kind") == "confirm"
                             else "ask"),
            ambiguities=(out,),
            planner_version=FOOD_PLANNER_VERSION)
    return TurnPlan(
        operations=tuple(out.get("tool_calls") or ()),
        response_intent=action or "",
        ambiguities=(),
        narration_hint=str(out.get("say") or ""),
        planner_version=FOOD_PLANNER_VERSION)


class FoodValidationStage:
    """Disposition is the SYSTEM's call, never the interpreter's: a plan with
    operations executes; an ask/confirm holds the write; anything else passes
    to the conversational lane."""

    # NOT `food_policy_v1`. `core/food_ledger.POLICY_VERSION` is that string
    # already, and the two ride the SAME log stream for the same turn:
    # `core.conversation` prints the ledger's as `pv=`, and
    # `core.turns.stages.finalize` prints this one as `policy=`. Two migrations,
    # two policy engines, one identifier — so `policy=food_policy_v1` could not
    # be read as evidence that the native stage ran, which is the exact question
    # it exists to answer when P0.2 executes `structured_food` natively.
    POLICY_VERSION = "food_policy_native_v1"

    async def run(self, request, context=None, route=None, plan=None) -> ValidationResult:
        intent = getattr(plan, "response_intent", "") or ""
        ops = tuple(getattr(plan, "operations", ()) or ())
        if intent in ("ask", "confirm"):
            # The question holds the UNCERTAIN items, not all of them. Anything
            # the veto already cleared is approved and travels with the ask —
            # partial commit is the contract in moderate mode, and an ask that
            # approves nothing is a hold wearing a question's clothes.
            #
            # A confirm approves nothing on purpose: it asks whether the whole
            # parse is right, so committing part of it pre-empts the answer.
            return ValidationResult(
                disposition="ask",
                approved_operations=(ops if intent == "ask" else ()),
                clarification=(plan.ambiguities[0] if plan.ambiguities else None),
                policy_version=self.POLICY_VERSION)
        if ops:
            return ValidationResult(disposition="execute",
                                    approved_operations=ops,
                                    policy_version=self.POLICY_VERSION)
        return ValidationResult(disposition="pass",
                                policy_version=self.POLICY_VERSION)
