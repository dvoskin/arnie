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
        # ⛔⛔ CF5c PRE-PLAN HOOK — AN ATTACHED SCAN SUPPRESSES CONFIRM REPLAY
        # *(Danny, 2026-08-19)*. "yes" to an open confirm replays the stashed
        # items VERBATIM, so scan + "yes" would log an EARLIER confirmed food
        # and then attach THIS scan's snapshot to it: one product's nutrition
        # committed under another product's name. That is the identity failure
        # the snapshot guards exist to prevent, arriving through a door
        # upstream of all of them — the replay stage runs before the
        # interpreter, before the plan, before any binding decision.
        #
        # Keyed on ATTACHMENT, deliberately: the disposition is not decided
        # until the plan exists, and the whole point is that the earlier
        # question must not shape this turn's plan. The confirm is left
        # exactly as it is — its own row, its own expiry; it simply does not
        # get to absorb a scanned turn.
        from core.scan_authority import suppresses_replay_and_prior
        if suppresses_replay_and_prior():
            logger.info("event=scan_suppresses_confirm_replay turn=%s — a "
                        "scan is a fresh exact statement, not a 'yes' to an "
                        "older meal", getattr(request, "turn_id", "-"))
        else:
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
        # ⛔⛔ THE INTERPRETER MUST SEE THE BOARD *(B-1.8 canary, 2026-08-18)*.
        # These keys were read here and written by NOBODY: `build_request`
        # carries db / user / today_log, not the derived board, day line,
        # thread state or regulars legacy computes inline. Blind, the native
        # interpreter could not name entry 3026 for "actually … 8 oz",
        # produced no op, and the correction lane never fired (see
        # core/turns/planner_inputs.py). Computed here from the same handles,
        # unless the request already carries them (tests, shadow hooks).
        if "board" not in meta:
            from core.turns.planner_inputs import planner_inputs
            derived = await planner_inputs(
                text=request.text or "", db=meta.get("db"), user=meta.get("user"),
                today_log=meta.get("today_log"), messages=meta.get("messages"),
                has_pending=bool(meta.get("food_pending")
                                 or meta.get("food_prior") is not None))
            meta = {**meta, **derived}
        # ⛔⛔ A SCAN-BOUND TURN IS A FRESH, EXACT STATEMENT — NOT AN ANSWER TO
        # WHATEVER QUESTION IS OPEN *(P17 live canary #2, 2026-08-18)*. Legacy
        # had asked "Salty Peanut or Caramel Cashew?" at 18:10; that pending
        # carries a log_date, so it stays live until tomorrow, and every later
        # Barebells message was routed as its ANSWER: the interpreter ran with
        # the prior, either "pass"ed or re-asked and `run()` refused the re-ask
        # (reask_refused) -> None -> no op -> native_no_plan -> legacy. The
        # scan had bound (product_acquired) and the bound predicate never got
        # a turn. A barcode is the strongest identity statement the user can
        # make; an open identity question does not outrank it. So a bound turn
        # is interpreted cold — no prior — and the pending question is left
        # exactly as it is (legacy's row, legacy's expiry); it simply does not
        # get to hijack this turn.
        prior = meta.get("food_prior")
        if prior is not None and suppresses_replay_and_prior():
            logger.info("event=scan_ignores_pending_prior turn=%s — a scanned "
                        "turn is a fresh statement, not an answer",
                        getattr(request, "turn_id", "-"))
            prior = None
        try:
            out = await run_interpreter(
                request.text, meta.get("user"),
                prior=prior,
                day_line=meta.get("day_line", ""),
                board=meta.get("board"),
                last_assistant=meta.get("last_assistant", ""),
                regulars=meta.get("regulars"),
                thread_active=bool(meta.get("thread_active")))
        except Exception as e:
            logger.warning(f"food plan stage failed: {e}")
            out = None
        await stamp_canonical_identity(
            out, meta.get("db"),
            user_id=getattr(meta.get("user"), "id", None))
        if isinstance(out, dict):
            # the user's words, for the bound-scan unit restoration; not a
            # field the interpreter produces, so it cannot be spoofed by one
            out = {**out, "_message": request.text or ""}
        return plan_from_interpretation(out)


#: The three states, and the middle one is the whole safety story.
#:
#:     off      resolve nothing, persist nothing — today's behaviour exactly
#:     shadow   resolve + PERSIST, never annotate — no price can move
#:     consume  resolve + persist + ANNOTATE — the identity reaches settlement
#:
#: ⛔⛔ `shadow` USED TO MEAN TWO DIFFERENT THINGS DEPENDING ON THE COORDINATOR
#: *(Danny, 2026-08-15)*. The legacy seams call `record_identities` (persist
#: only) while `FoodPlanStage.run` calls `stamp_canonical_identity` (annotate),
#: so `shadow` was record-only on legacy traffic and CONSUMING on
#: `new_execute` traffic. After `1f13347` the stamp is not harmless metadata:
#: it changes durable memory ADDRESSING via `memory_key`, and therefore the
#: price. A mode named `shadow` cannot mean "consume, on some paths".
#:
#: ⭐ SO ANNOTATION IS ITS OWN STATE, and the contract is stated once, here:
#: **`shadow` may persist resolutions but may NEVER put `canonical_entity_id`
#: on a settlement-bound item, whatever `TURN_COORDINATOR_MODE` says.**
_MODES = ("off", "shadow", "consume")


def entity_resolution_mode() -> str:
    """`off` | `shadow` | `consume`. DEFAULT OFF.

    ⭐ REGISTERED IN `core.config_guard`, because this parser has exactly the
    `else <default>` shape that let `NUTRITION_RESOLVER_MODE=true` run production
    in shadow for six days while a comment recorded it as live. A third state
    makes that worse, not better: a typo'd `consume` is silently `off`, and the
    symptom is an improvement that never arrives.
    """
    import os

    mode = (os.getenv("ENTITY_RESOLUTION_MODE", "off") or "").strip().lower()
    return mode if mode in _MODES else "off"


def _consume_allowlist() -> frozenset:
    """The users for whom a canonical identity may affect PRICING.

    ⛔⛔ FAIL CLOSED, AND THIS DELIBERATELY BREAKS THE HOUSE CONVENTION.
    `lane_executes_natively` treats an empty `TURN_COORDINATOR_ALLOWLIST` as
    EVERYONE, and `render.yaml` records the same reading for
    `NUTRITION_RESOLVER_MODE` ("empty allowlist = everyone"). That default is
    survivable for a flag that chooses an execution path. It is not survivable
    for the flag that decides whether a model's identity judgement moves a
    number on a user's plate: an operator who sets the mode and forgets the
    cohort would enrol the entire fleet in price movement, and the symptom
    would be prices changing for people nobody canaried.

    So: unset or empty means NOBODY, and a turn with no user id means nobody
    either. Widening is always an explicit act.
    """
    import os

    raw = os.getenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", "") or ""
    return frozenset(int(part) for part in raw.replace(",", " ").split()
                     if part.strip().isdigit())


def identity_is_consumable(user_id=None) -> bool:
    """May an identity be stamped onto THIS USER's item — i.e. reach pricing?

    ⭐ ONE PREDICATE, ASKED BY THE ONE FUNCTION THAT ANNOTATES. A second caller
    deciding this for itself is how `shadow` came to mean two things.

    ⭐⭐ AND THE COHORT BELONGS TO THE FEATURE THAT MOVES PRICES *(Danny,
    2026-08-15)*. Before this, consumption's real condition was
    `mode == consume AND coordinator native execution AND
    TURN_COORDINATOR_ALLOWLIST` — so widening the COORDINATOR rollout would
    silently widen identity consumption. Two rollouts on one dial, and only one
    of them named after the behaviour being exposed.

        Coordinator enrollment decides which execution PATH runs.
        Identity-consume enrollment decides whether canonical identity may
        affect PRICING. Neither rollout may implicitly widen the other.
    """
    if entity_resolution_mode() != "consume":
        return False
    allowed = _consume_allowlist()
    if not allowed or user_id is None:
        return False
    try:
        return int(user_id) in allowed
    except (TypeError, ValueError):
        return False


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
    await _log_identity_states([s for s in surfaces if s], resolved, db)
    return resolved


async def _log_identity_states(surfaces, resolved, db) -> None:
    """⭐ COUNT THE STATES, NOT JUST THE WINS *(Danny, 2026-08-15)*.

    ⛔ `resolved=%d` MEANT "RETURNED A BINDING ENTITY", so four legitimate
    PRODUCT turns logged `resolved=0` — which is the ambiguous zero this whole
    session keeps paying for. A canary carrying PRODUCT and UNRESOLVED traffic
    could not distinguish "the producer ran and these foods are labels" from
    "the producer never ran", and those two readings differ by everything.

    So every outcome is named and counted:

        attempted   surfaces the producer was asked about
        recorded    surfaces that HAVE a row afterwards
        resolved / distinct / product / unresolved   the row's own verdict
        binding     rows a CONSUMER would actually bind to
        absent      asked about, and no row exists — the honest failure count

    ⚠ AND COUNTING MUST NOT BE ABLE TO FAIL THE TURN, so the whole thing is
    guarded. Telemetry that can break a food log is worse than no telemetry.
    """
    import collections

    counts = collections.Counter({"attempted": len(surfaces)})
    try:
        from skills.nutrition.entity_resolution import resolve

        for surface in surfaces:
            row = await resolve(db, surface)
            if row is None:
                counts["absent"] += 1
                continue
            counts["recorded"] += 1
            counts[getattr(row.state, "value", str(row.state))] += 1
            if resolved.get(surface):
                counts["binding"] += 1
    except Exception as e:                       # noqa: BLE001
        logger.warning(f"identity state telemetry unavailable: {e}")

    logger.info(
        "event=entity_identity_recorded " + " ".join(
            f"{name}={counts[name]}" for name in
            ("attempted", "recorded", "binding", "resolved", "distinct",
             "product", "unresolved", "absent")))


async def record_turn_identities(out, db) -> dict:
    """⭐ THE SHARED SEAM OPERATION — both entrances call THIS, and it lives here.

    ⛔ OWNERSHIP DIRECTION *(Danny, 2026-08-15)*. The first version of the seam
    put this wrapper in `core.conversation` and had `handlers.tool_executor`
    import it. That works mechanically and points the wrong way: `conversation`
    is an ORCHESTRATION layer, `tool_executor` is enormous and deeply depended
    upon, and an executor reaching back up into the orchestrator is a
    dependency cycle waiting to become real.

        conversation  ─┐
                       ├──>  core.turns.stages.food  (identity recorder)
        tool_executor ─┘

    rather than `tool_executor -> conversation -> recorder`. No new
    architecture; the shared operation simply sits at the layer that owns it.

    ⚠ A FOOD TURN MUST NOT BREAK OVER AN IDENTITY ANNOTATION NOTHING YET
    CONSUMES. The producer guards resolution failing; this guards everything
    else — the difference between a resolver that answers badly and one that is
    not importable at all.
    """
    try:
        # ⭐ "THE INTERPRETER DECLINED" AND "THE SEAM NEVER RAN" ARE DIFFERENT
        # FACTS WITH ONE SPELLING. An eight-turn proof that logged four foods
        # and recorded ONE read as "not wired" when it was wired and three
        # turns had nothing to hand it.
        if not (out or {}).get("items") and entity_resolution_mode() != "off":
            logger.info("event=entity_identity_skipped reason=no_interpretation")
        # ⭐ RETURNS THE MAPPING so a CONSUMING caller can annotate what it owns.
        # The wrapper still never annotates anything itself — persistence and
        # annotation stay different decisions, and the caller that holds the
        # settlement-bound structure is the only one that can stamp it.
        return await record_identities(out, db)
    except Exception as e:                       # noqa: BLE001
        logger.warning(f"identity recording unavailable, turn unchanged: {e}")
    return {}


async def stamp_canonical_identity(out, db, user_id=None) -> None:
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
    # ⛔⛔ THE CROSS-PRODUCT GUARD. This function is reached from
    # `FoodPlanStage.run`, which runs under `new_execute` — so without this
    # line `ENTITY_RESOLUTION_MODE=shadow` would PERSIST on legacy traffic and
    # CONSUME on coordinator traffic, from one flag, with the difference
    # invisible in the flag's name. The stamp changes `memory_key` and so the
    # price; shadow must never reach it, whatever the coordinator mode.
    if not identity_is_consumable(user_id):
        logger.info("event=entity_identity_not_consumed mode=%s user=%s "
                    "resolved=%d", entity_resolution_mode(), user_id,
                    len(resolved))
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


#: The interpreter's identity-class ambiguity fields — the ones a barcode
#: settles. Same vocabulary `core.food_turn` uses for the branded strict-mode
#: rule; not a new taxonomy.
_IDENTITY_FIELDS = frozenset({"identity", "brand", "variant", "flavor", "flavour",
                              "product_identity", "product_line", "product_variant"})


# (CF5c-B4: `_scan_is_bound` — the planner's attachment read — is GONE. The
# planner has two legitimate attachment reads, both PRE-plan hooks that
# suppress an OLDER question from shaping this turn (`suppresses_replay_and_
# prior`); every scan-specific transform of the plan itself now runs in
# `bind_plan`, after the authority's decision.)


def _lift_bound_correction_to_log(ops, message: str):
    """CF5b: the ONE implicit `update_food_entry` of a scan-bound turn, as a
    fresh `log_food` of the scanned product in the user's stated quantity — or
    None when the plan is not that shape.

    SCOPED NARROWLY *(Danny)*: exact scan binding exists (the caller checked);
    the plan contains exactly ONE food update; it is an IMPLICIT correction
    (a board row the interpreter picked), not an explicit, separately
    addressed one (a move-to-date, a delete, a mixed plan) — those are left
    alone for the executor's own guards; unbound updates are byte-identical
    in behaviour because this is never called for them.

        update_food_entry -> lift to log_food
                          -> identity from the exact scanned SNAPSHOT
                          -> quantity restored from the user's LITERAL message
                          -> existing row target DISCARDED
                          -> the existing bound predicate owns the result

    ⛔ THE QUANTITY IS "2 servings" FROM THE USER'S TEXT, NEVER THE PLANNER'S
    "4 bar" — that was the corrected TOTAL computed against the old row, not
    the statement. `_restore_user_stated_unit` reads the label's vocabulary
    (servings / g / oz) off the message; otherwise the count + the noun the
    user said ("2 bar"), which the bound predicate cannot price and so ASKS
    (BoundUnpriceable -> CF9). Nothing here guesses a mass or a noun.

    ⭐ IDENTITY: the planner is DB-free, so the item is marked `_scan_lifted`
    and carries the interpreter's name only as a placeholder; the execution
    stage's `_canonical_route` reads the snapshot's own product_name onto the
    item BEFORE the predicate runs (see `_name_from_snapshot`). The row is
    then named and priced from the same exact snapshot."""
    if len(ops or ()) != 1:
        return None
    op = ops[0] or {}
    if not isinstance(op, dict) or op.get("name") != "update_food_entry":
        return None
    inp = dict(op.get("input") or {})
    if inp.get("entry_id") is None or inp.get("date"):
        return None
    placeholder = str(inp.get("food_name") or inp.get("food_hint") or "").strip()
    if not placeholder:
        return None
    from core.food_turn import _log_call
    call = _log_call({"food": placeholder, "amount": None, "unit": ""})
    if call is None:
        return None
    call["input"]["quantity"] = ""
    _restore_user_stated_unit(call, message)
    if not call["input"].get("quantity"):
        _n = _leading_count(message)
        if _n is not None:
            call["input"]["quantity"] = f"{_n} {_unit_word(message) or 'piece'}"
    call["input"]["_scan_lifted"] = True
    call["input"]["is_packaged"] = True
    logger.info("event=scan_rejects_correction_shape entry=%s food=%r "
                "stated=%r — a scan is a fresh statement about the scanned "
                "product, not a correction of another row",
                inp.get("entry_id"), placeholder, call["input"].get("quantity"))
    return call


_COUNT_RE = __import__("re").compile(
    r"(?<![\w.])(\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|half(?: a| an)?)\s+"
    r"(?:(?:of\s+)?(?:the\s+)?[\w'\-]+\s+)?([a-z]+)", __import__("re").I)


def _leading_count(message: str):
    """The count the user stated, if the message opens with one ("2 …", "two
    …"); None otherwise. A count, not a mass — the unit is read separately."""
    m = _COUNT_RE.search(message or "")
    if not m:
        return None
    head = m.group(1).lower()
    if head.startswith("half"):
        return "0.5"
    return str(_WORDS.get(head, head))


def _unit_word(message: str):
    """The unit noun the count qualifies ("bars" in "2 barebells bars", "bar"
    in "2 bar"), singularised; None when unreadable. Only the noun the user
    said — never a label serving, never a mass — so the bound predicate sees a
    heuristic-count quantity and refuses/asks rather than pricing it."""
    text = (message or "").strip().lower()
    for noun in ("bars", "bar", "pieces", "piece", "bags", "bag", "bottles",
                 "bottle", "cans", "can", "scoops", "scoop", "packs", "pack",
                 "cups", "cup", "slices", "slice", "cookies", "cookie"):
        if __import__("re").search(rf"\b{noun}\b", text):
            return noun[:-1] if noun.endswith("s") and noun not in ("glass",) else noun
    return None


#: The label's own quantity vocabulary — the two things a manufacturer panel
#: states without a product noun: its serving, and mass.
_LABEL_UNIT_RE = __import__("re").compile(
    r"(?<![\w.])((?:\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|half(?: a| an)?)\s*"
    r"(servings?|g|grams?|oz|ounces?)|(?:half(?: a| an)?|a|an|one)\s+serving)\b",
    __import__("re").I)
_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def _restore_user_stated_unit(call: dict, message: str) -> None:
    """⛔ THE USER'S STATED UNIT OUTRANKS THE INTERPRETER'S REWRITE — for a
    scan-bound item, and only against the LABEL'S OWN vocabulary.

    P17 live canary #3 (2026-08-18): the user typed "2 servings of the
    Barebells"; the interpreter's item said unit="bar" (it treats bar and
    serving as synonyms for this product); the bound predicate saw "2 bar",
    could not price it from a label that names no bar, and asked "how many
    servings?" about a message that had SAID servings. P17 precedence puts a
    user-stated quantity FIRST; an interpreter normalisation is not the user.

    Narrow by construction: only when a scan is bound, only when the user's
    text literally states the label's units (serving(s) / grams / oz), and
    only to REPLACE the op's quantity with what they typed. "2 barebells
    bars" is untouched and still asks. Nothing here guesses a mass or a
    noun."""
    if not isinstance(call, dict) or call.get("name") != "log_food":
        return
    inp = call.get("input") or {}
    m = _LABEL_UNIT_RE.search(message or "")
    if not m:
        return
    phrase = m.group(0).strip().lower()
    stated_unit = (m.group(2) or "serving").lower()
    unit = "serving" if stated_unit.startswith("serving") else stated_unit
    current = str(inp.get("quantity") or "").lower()
    if unit == "serving" and "serving" in current:
        return
    if unit != "serving" and current.split()[-1:] == [unit]:
        return
    # the amount, as the user said it
    head = phrase.split()[0]
    if head.startswith("half"):
        amount = "0.5"
    else:
        amount = str(_WORDS.get(head, head))
    inp["quantity"] = f"{amount} {unit}"
    inp["quantity_provenance"] = "user_stated"
    logger.info("event=scan_user_unit_restored from=%r to=%r message=%r",
                current, inp["quantity"], message)


def _scan_answers_the_identity(out) -> bool:
    """True when the interpreter staged exactly ONE item and every ambiguity
    it reported is identity-class. Attachment-blind: called only from
    `bind_plan`, i.e. only once the authority has said BOUND."""
    items = [it for it in (out.get("items") or []) if isinstance(it, dict)]
    if len(items) != 1:
        return False
    fields = [str(a.get("field") or "").strip().lower()
              for a in (out.get("ambiguities") or []) if isinstance(a, dict)]
    return bool(fields) and all(f in _IDENTITY_FIELDS for f in fields)


#: The producer keys `food_subjects_of` MUST read. This is not documentation:
#: `tests/test_cf5c_one_scan_authority.py` parses the normaliser and asserts
#: every key here appears as a subscript of `out` inside it, so a key added
#: to this tuple without a reader fails the build — and a key the producer
#: grows that is NOT here is the reviewer's cue, not a silent hole *(leak d)*.
SUBJECT_SOURCES = ("tool_calls", "deferred_calls", "questions", "points",
                   "b1_material", "items", "ambiguities")


def _norm_key(name: str) -> str:
    """The dedupe key for a food name — the shared normaliser, so 'Barebells
    bar' and 'barebells bars' are one subject, exactly as dedup sees them.
    Falls back to a lowercase strip if the normaliser is unavailable, never
    to the raw string."""
    try:
        from skills.nutrition.food_dedup import normalize_food_name
        k = normalize_food_name(name)
        if k:
            return k
    except Exception:                                    # noqa: BLE001
        pass
    return " ".join(str(name or "").lower().split())


def food_subjects_of(out) -> tuple:
    """⛔ CF5c — THE COMPLETE SET OF FOODS A PLAN IS ABOUT, from the producer's
    REAL output shape, normalised once.

    `core.food_turn.run` returns an ask as

        {"action": "ask", "tool_calls": <ready writes>,
         "deferred_calls": <held writes>, "questions": [{"item": label,..}],
         "b1_material": {"staged_items": (...), "items": <interpretation>},
         "points": [{"label": ..., "qs": [...]}]}

    — no top-level `items`, no `ambiguities`. The remaining foods live in the
    DEFERRED writes and the NESTED material. With partial commit OFF every
    write is deferred, so a one-food quantity ask has ZERO ready operations;
    with it ON, a two-food ask exposes ONE ready write. A gate that reads any
    one of these views alone is wrong in both directions: it refuses the
    legitimate scanned quantity ask as "no food", or binds a two-food turn.

    ⛔⛔ OCCURRENCE, NOT NAME, IS THE UNIT *(Danny, pre-ship review)*. A first
    cut keyed every subject by normalised name, so two SEPARATE Barebells
    operations — one ready, one held — collapsed to ONE subject and the turn
    read as BOUND: the ready write went through although there were two food
    intents, contradicting "BOUND = exactly one log_food". Names normalise
    identically; occurrences do not merge because of it.

    So the rule is:
      · WITHIN a carrier, occurrences are distinct by a stable correlation id
        — the op's carrier + position (or `entry_id` for an update/delete),
        the staged item's `staged_item_id`, the interpretation's position.
        Two ops are two subjects, whatever their names.
      · ACROSS carriers, NAME is the fallback that links a LABEL (a question,
        a point — carriers that have no id) to an occurrence that already
        exists, and links the raw interpretation's positional rows to the
        writes built from them. A label matching several same-name occurrences
        attaches to all of them (it is a question about that food; it does
        not create a third).
      · a label naming a food no carrier has yet is its own subject.

    One Barebells mirrored through every carrier -> 1. Two independently
    represented Barebells -> 2 -> SKIPPED_MULTI_ITEM."""
    from core.turns.models import FoodSubject
    if not isinstance(out, dict):
        return ()
    # occurrence key -> {"name", "roles": [...], "fields": set, "nk": name key,
    #                    "consumed": bool}
    found: dict = {}
    order: list = []
    # ⛔ CF5c-B2 — the MESSAGE's consumption state, read once. A write carrier
    # asserts consumption by existing (the interpreter chose to log it); a
    # label-only carrier asserts it only if the user's words did.
    try:
        from core.food_turn import STATE_CONSUMED, consumption_state
        message_consumed = consumption_state(
            str(out.get("_message") or ""),
            thread_active=bool(out.get("_thread_active"))) == STATE_CONSUMED
    except Exception:                                    # noqa: BLE001
        message_consumed = False

    def _put(occ_key, name, role, fields=(), consumed=None):
        name = str(name or "").strip()
        rec = found.get(occ_key)
        if rec is None:
            rec = {"name": name or occ_key, "roles": [], "fields": set(),
                   "nk": _norm_key(name) if name else "",
                   "consumed": False}
            found[occ_key] = rec
            order.append(occ_key)
        elif name and not rec["nk"]:
            rec["name"], rec["nk"] = name, _norm_key(name)
        if role not in rec["roles"]:
            rec["roles"].append(role)
        rec["fields"].update(f for f in fields if f)
        if consumed is None:
            consumed = role in ("ready", "held") or message_consumed
        rec["consumed"] = rec["consumed"] or bool(consumed)
        return rec

    def _by_name(name):
        nk = _norm_key(name)
        return [k for k in order if nk and found[k]["nk"] == nk]

    label_seen: dict = {}      # (carrier, name key) -> repeat count

    def _link_or_put(name, role, fields=(), carrier="label"):
        """A LABEL carrier: attach to every same-name occurrence that a WRITE
        or a STAGED/INTERPRETED row introduced. When none exists, the label
        is its own subject.

        ⛔ REPEATS, CONSERVATIVELY *(leak c)*: the SAME label seen once in
        `questions` and once in `points` is ONE reference (the producer emits
        both views of one question); the same label seen TWICE WITHIN one
        carrier — two questions about "Barebells" with no write behind either
        — is two intents until something says otherwise, and two intents
        means the scan binds nothing rather than one of them."""
        nk = _norm_key(name)
        if not nk:
            return
        anchored = [k for k in _by_name(name) if not k.startswith("label:")]
        if anchored:
            for k in anchored:
                _put(k, name, role, fields)
            return
        # a label already introduced by the OTHER label carrier is the same
        # reference (questions and points are two views of one question)
        other = [k for k in _by_name(name) if k.startswith("label:")]
        if other and label_seen.get((carrier, nk), 0) == 0:
            for k in other:
                _put(k, name, role, fields)
            label_seen[(carrier, nk)] = 1
            return
        n = label_seen.get((carrier, nk), 0)
        label_seen[(carrier, nk)] = n + 1
        _put(f"label:{nk}" if n == 0 else f"label:{nk}:{n}", name, role, fields)

    def _write(call, carrier, index, role):
        inp = (call or {}).get("input") if isinstance(call, dict) else None
        if not isinstance(inp, dict):
            return
        kind = call.get("name")
        if kind not in ("log_food", "update_food_entry", "delete_food_entry"):
            return
        name = (inp.get("food_name") or inp.get("food_hint")
                or inp.get("food") or "")
        eid = inp.get("entry_id")
        # ⛔ A CORRECTION OR DELETE THAT NAMES NO FOOD IS STILL ABOUT ONE — the
        # board row it targets. `_update_call` emits exactly this shape when
        # the interpreter does not rename ("make it 4"). Keyed on the row so
        # two edits of the same row are one subject.
        occ = (f"entry:{eid}" if kind != "log_food" and eid is not None
               else f"op:{carrier}:{index}")
        _put(occ, name if name else (f"entry {eid}" if eid is not None else ""),
             role)

    for i, call in enumerate(out.get("tool_calls") or ()):
        _write(call, "ready", i, "ready")
    for i, call in enumerate(out.get("deferred_calls") or ()):
        _write(call, "held", i, "held")

    material = out.get("b1_material")
    if isinstance(material, dict):
        for i, it in enumerate(material.get("staged_items") or ()):
            nm = (getattr(it, "food", None) or getattr(it, "name", None)
                  or (it.get("food") if isinstance(it, dict) else None))
            sid = (getattr(it, "staged_item_id", None)
                   or (it.get("staged_item_id") if isinstance(it, dict) else None))
            ambs = getattr(it, "ambiguities", None) or (
                it.get("ambiguities") if isinstance(it, dict) else None) or ()
            fields = [str(getattr(a, "field", None) or
                          (a.get("field") if isinstance(a, dict) else "") or "")
                      .strip().lower() for a in ambs]
            if not nm:
                continue
            # a staged row that names a food a WRITE already carries is the
            # same occurrence seen through typed staging, not a second food;
            # a staged row naming something no write carries is its own
            matches = _by_name(nm)
            if matches and len(matches) == 1:
                _put(matches[0], nm, "staged", fields)
            else:
                _put(f"staged:{sid or i}", nm, "staged", fields)
        # the raw interpretation is positional and PRECEDES the writes in the
        # producer — its rows are the foods the writes were built from. A row
        # whose name matches exactly one write is that write; a row matching
        # none is a food the interpreter parsed but wrote nothing for (the
        # corn); a row matching several is ambiguous and attaches to none —
        # the writes already count it.
        for i, it in enumerate(material.get("items") or ()):
            if not isinstance(it, dict):
                continue
            nm = it.get("food") or it.get("name")
            if not nm:
                continue
            explicit = it.get("consumed")
            c = (bool(explicit) if isinstance(explicit, bool) else None)
            matches = _by_name(nm)
            if len(matches) == 1:
                _put(matches[0], nm, "interpreted", consumed=c)
            elif not matches:
                _put(f"interp:{i}", nm, "interpreted", consumed=c)

    for it in out.get("items") or ():
        if isinstance(it, dict):
            nm = it.get("food") or it.get("name")
            # typed fields are attached once, below, from `typed_fields`
            _link_or_put(nm, "interpreted")

    # ⛔ TYPED FIELD IDS FIRST *(leak a)*. The producer now carries the
    # interpreter's own `ambiguities: [{item, field}]`; a field named there
    # is authoritative for its item. Keyword inference over the question's
    # prose is the FALLBACK for a label no typed record covers, and a field
    # so inferred is recorded as such ("quantity?" — a guess the CF9 test
    # does NOT accept, so an un-typed question refuses rather than asks).
    typed_fields: dict = {}
    for a in out.get("ambiguities") or ():
        if not isinstance(a, dict):
            continue
        item = str(a.get("item") or a.get("food") or "").strip()
        field = str(a.get("field") or "").strip().lower()
        if item and field:
            typed_fields.setdefault(_norm_key(item), set()).add(_canon_field(field))

    def _fields_for(label, prose):
        """Typed wins outright: a label with a typed record contributes NO
        inferred field (the typed one is attached below). Only a label the
        interpreter did not type falls back to prose, marked '?'."""
        nk = _norm_key(label)
        if nk in typed_fields:
            return ()
        inferred = _fields_in_question(prose)
        return tuple(f"{f}?" for f in inferred)      # marked as inferred

    # LABEL carriers last: they reference foods, they do not introduce
    # occurrences unless nothing else names the food at all
    for q in out.get("questions") or ():
        if isinstance(q, dict):
            _link_or_put(q.get("item"), "asked",
                         _fields_for(q.get("item"), q.get("text")),
                         carrier="questions")
    for pt in out.get("points") or ():
        if isinstance(pt, dict):
            qs = pt.get("qs") if isinstance(pt.get("qs"), list) else [pt.get("q")]
            _link_or_put(pt.get("label"), "asked",
                         _fields_for(pt.get("label"),
                                     " ".join(str(x) for x in qs if x)),
                         carrier="points")
    # a typed record for an item that no label mentioned still names an
    # open field on that item
    for nk, fields in typed_fields.items():
        for k in [k for k in order if found[k]["nk"] == nk]:
            found[k]["fields"].update(fields)

    return tuple(FoodSubject(name=found[k]["name"], role=found[k]["roles"][0],
                             open_fields=tuple(sorted(found[k]["fields"])),
                             key=k, consumed=bool(found[k]["consumed"]))
                 for k in order)


#: The words a quantity question is made of. Read off the QUESTION TEXT because
#: the live producer's `questions[]` carry a label and a sentence, not a field
#: id — "How much…?" / "How many…?" / "…serving…" is a quantity question; a
#: flavour or brand question is not. Conservative: a question that names none
#: of these is recorded with an unnamed open field, which is "another
#: ambiguity" to the CF9 test and refuses rather than asks.
_QTY_WORDS = ("how much", "how many", "serving", "servings", "grams", "oz",
              "ounce", "portion", "amount", "quantity", "cups", "pieces",
              "slices", "how big", "size")


#: The interpreter says "prep"; the semantics say "preparation". One map, so
#: the CF9 test compares canonical ids, not spellings.
_FIELD_ALIASES = {"prep": "preparation", "amount": "quantity",
                  "portion": "quantity", "size": "quantity",
                  "flavor": "food_identity", "flavour": "food_identity",
                  "identity": "food_identity", "brand": "food_identity",
                  "variant": "product_variant"}


def _canon_field(field: str) -> str:
    f = str(field or "").strip().lower()
    return _FIELD_ALIASES.get(f, f)


def _fields_in_question(text) -> tuple:
    t = " ".join(str(text or "").lower().split())
    if not t:
        return ()
    if any(w in t for w in _QTY_WORDS):
        return ("quantity",)
    return ("unknown",)


def plan_from_interpretation(out) -> TurnPlan:
    """Lift an interpreter result into a typed plan. Pure — no model call.

    ⛔ CF5c: EVERY plan leaving here carries `food_subjects` — the producer's
    COMPLETE interpretation normalised once (see `food_subjects_of`). The
    body below decides the operations and the intent; this wrapper stamps the
    subjects on whichever plan it returns, so no branch can forget them and
    no consumer has to reach back into the interpreter's dict."""
    from dataclasses import replace as _replace
    plan = _plan_from_interpretation(out)
    subjects = food_subjects_of(out)
    open_fields = tuple(sorted({f for sub in subjects for f in sub.open_fields}))
    return _replace(plan, food_subjects=subjects, open_fields=open_fields,
                    source=out if isinstance(out, dict) else None)


def _plan_from_interpretation(out) -> TurnPlan:
    """The untyped body — see `plan_from_interpretation`.

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
    # ⛔⛔ CF5c-B4 — THIS FUNCTION IS ATTACHMENT-BLIND *(Danny, 2026-08-19)*.
    # Three scan-specific transforms used to live here, ahead of the binding
    # decision — a scan-answers-the-identity lift, the CF5b implicit-
    # correction lift, and the user's-unit restoration — each keyed on
    # ATTACHMENT. So a plan could be scan-transformed and THEN classified
    # SKIPPED_MULTI_ITEM: the authority ruled on a plan the attachment had
    # already rewritten, which is not dominance. They now live in `bind_plan`
    # and run only AFTER `decide_from_plan` says BOUND. This body sees an
    # interpreter result and types it; it does not know a scan exists.
    # ⛔⛔ CF5b — SCAN BINDING DOMINATES CORRECTION CLAIMS *(Danny, 2026-08-18,
    # P1 authority violation; production turn ios:D3B7757E)*. The user scanned
    # 70004199 and typed "2 servings of Barebells bars"; a legacy Barebells row
    # was already on the board, so the interpreter read the message as "make
    # that 4 bars" and emitted update_food_entry(3030, "4 bar"). Every
    # scan-binding check downstream keys on `log_food` — `_food_inputs` drops
    # an update op — so the bound predicate NEVER RAN (no settlement_route
    # line), `_correction_route` declined a legacy row, and the op reached the
    # legacy executor's ratio arm: heuristic bar-mass x2 = 800 kcal committed
    # against an exact label. CF4 and CF5 broken in one turn, through a shape
    # neither guarded.
    #
    #     scan acquired exact snapshot
    #     -> correction route discarded binding
    #     -> heuristic ratio mutation committed
    #     -> bound predicate never ran
    #
    # A SCAN ATTACHMENT MEANS A NEW EXACT-PRODUCT REPORT. It must not mutate an
    # old row merely because that product already appears on the board. So at
    # the correction-claim boundary — here, before the plan is typed — a bound
    # turn's implicit correction is NOT eligible: the single update op is
    # lifted to a fresh `log_food` of the same food, in the user's stated
    # quantity, and continues through bound-item planning, where the predicate
    # settles it (Supported(product)) or asks in the label's terms
    # (BoundUnpriceable -> the CF9 ask). Snapshot preserved; nothing here
    # guesses a mass or a noun. An UNBOUND update op is untouched — implicit
    # correction is legitimate when nothing outranks it. Ratio correction is
    # not weakened globally; the exclusion is exactly "implicit correction
    # cannot outrank explicit scan binding".
    # (the CF5b correction lift is applied in `bind_plan`, post-decision)
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
    ops = tuple(out.get("tool_calls") or ())
    # (the user's-unit restoration is applied in `bind_plan`, post-decision)
    return TurnPlan(
        operations=ops,
        response_intent=action or "",
        ambiguities=(),
        narration_hint=str(out.get("say") or ""),
        planner_version=FOOD_PLANNER_VERSION)


def bind_plan(plan) -> TurnPlan:
    """⛔⛔ CF5c-B4 — THE SCAN-SPECIFIC PLAN TRANSFORMS, applied ONLY once the
    authority has said BOUND. Called by `FoodValidationStage` immediately
    after `decide_from_plan`; a plan the authority classified anything else
    is returned UNTOUCHED — a hidden second subject prevents every one of
    these, which is the point.

    Three transforms, in the order the planner used to apply them:

      1. SCAN ANSWERS THE IDENTITY (P17 live canary #1): the interpreter asked
         "Salty Peanut or Caramel Cashew?" about a scan-bound bar — an
         identity question the snapshot has already answered. A single item
         whose ONLY open questions are identity-class is not ambiguous: it
         becomes a log operation and the bound predicate decides the quantity.
      2. THE IMPLICIT-CORRECTION LIFT (CF5b): a scanned turn's single
         `update_food_entry` of a board row is a fresh statement about the
         scanned product, lifted to `log_food` in the user's own words.
      3. THE USER'S UNIT (P17 live canary #3): "2 servings" typed by the user
         outranks the interpreter's rewrite to "2 bar" — restored against the
         label's own vocabulary.

    All three read the interpreter's raw output off `plan.source`; none of
    them consults the attachment. `food_subjects` are recomputed from the
    transformed operations so downstream sees one truth."""
    from dataclasses import replace as _replace
    from core.scan_authority import is_bound
    if not is_bound():
        return plan
    out = getattr(plan, "source", None)
    if not isinstance(out, dict):
        return plan
    action = out.get("action")
    message = out.get("_message") or ""

    # 1. scan answers the identity
    if action == "ask" and _scan_answers_the_identity(out):
        from core.food_turn import _log_call
        items = [it for it in (out.get("items") or []) if isinstance(it, dict)]
        call = _log_call(items[0]) if items else None
        if call is not None:
            _restore_user_stated_unit(call, message)
            logger.info("event=scan_answers_identity item=%r ambiguities=%s",
                        items[0].get("food"),
                        [a.get("field") for a in (out.get("ambiguities") or [])])
            new_plan = _replace(plan, operations=(call,), response_intent="log",
                                ambiguities=())
            return _retype(new_plan, out)

    # 2. the implicit-correction lift
    if action in ("update", "log"):
        lifted = _lift_bound_correction_to_log(
            tuple(plan.operations or ()), message)
        if lifted is not None:
            new_plan = _replace(plan, operations=(lifted,),
                                response_intent="log", ambiguities=())
            return _retype(new_plan, out)

    # 3. the user's unit, on the single log this turn settles
    ops = tuple(plan.operations or ())
    if len(ops) == 1 and isinstance(ops[0], dict):
        _restore_user_stated_unit(ops[0], message)
    return plan


def _retype(plan, out) -> TurnPlan:
    """After a bind transform the operations changed; the typed subjects are
    recomputed from the transformed shape so the two never disagree. The
    transformed plan is a single log by construction (transforms 1 and 2
    each produce exactly one), and its subject is that log."""
    from dataclasses import replace as _replace
    from core.turns.models import FoodSubject
    op = plan.operations[0] if plan.operations else None
    inp = (op or {}).get("input") if isinstance(op, dict) else None
    name = str((inp or {}).get("food_name") or "")
    subs = (FoodSubject(name=name, role="ready", open_fields=(),
                        key="op:ready:0", consumed=True),) if name else ()
    return _replace(plan, food_subjects=subs, open_fields=())


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
        # ⛔⛔ CF5c POST-PLAN GATE — THE ONE BINDING DECISION, made here because
        # this is the first place the COMPLETE plan is known: the operations
        # AND the clarification's items. Deciding from `approved_operations`
        # instead is how a two-food clarification could bind a scan — the
        # branch below approves only the READY items of an ask, so a turn
        # naming two foods can expose exactly one approved operation.
        #
        # Every downstream reader consumes this decision; none re-derives it.
        from core.scan_authority import decide_from_plan
        decide_from_plan(plan)
        # ⛔ CF5c-B4 — the scan-specific transforms run HERE, after the
        # decision and only for a BOUND plan. `bind_plan` returns any other
        # plan untouched, so a turn the authority classified
        # SKIPPED_MULTI_ITEM is validated exactly as an unscanned one.
        plan = bind_plan(plan)
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
                policy_version=self.POLICY_VERSION, plan=plan)
        if ops:
            return ValidationResult(disposition="execute",
                                    approved_operations=ops,
                                    policy_version=self.POLICY_VERSION,
                                    plan=plan)
        return ValidationResult(disposition="pass",
                                policy_version=self.POLICY_VERSION, plan=plan)
