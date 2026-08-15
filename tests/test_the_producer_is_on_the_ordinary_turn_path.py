"""⛔ THE ADOPTION SEAM — ordinary food traffic must reach the identity producer.

Measured on the real turn path 2026-08-15: `stamp_canonical_identity` called
DIRECTLY wrote four resolutions, and the SAME foods driven through
`run_chat_turn` wrote ZERO. Its only call site was `FoodPlanStage.run`,
reachable under `TURN_COORDINATOR_MODE=new_execute`, or `new_observe` with
`TURN_COORDINATOR_OBSERVE_DEEP=1` — while production runs `legacy_only`, where
`observing()` is False and no stage runs at all.

⛔⛔ SO A SHADOW CANARY WOULD HAVE PASSED FOR THE WORST REASON. §0 step 5 asks
it to prove "resolution writes · NO turn behaviour change"; the second half is
satisfied perfectly by a feature that never runs. That is what these gates are
against, and it is why the reachability gate below is written as a MUTATION:
restoring coordinator-only reachability must turn it red.

WHAT IS PROVEN HERE vs WHAT IS PROVEN BY EVIDENCE
-------------------------------------------------
These are CONTRACT gates. They stub the resolver, so they prove what the seam
DOES with an answer — that it is invoked on the legacy path, that it records
without annotating, that it cannot fail a turn. They cannot prove a real model
resolves `Помидор` to `tomato`; a stub is a statement about the contract, never
evidence the stubbed thing exists. That half is
`scripts/prove_the_seam_is_reachable.py`, which makes real calls.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest


def _conversation_source() -> str:
    return (pathlib.Path(__file__).resolve().parents[1]
            / "core" / "conversation.py").read_text(encoding="utf-8")


def test_the_legacy_path_calls_the_producer_after_every_interpreter_run():
    """⭐ AST, NOT GREP. The question is STRUCTURAL — "is the producer awaited in
    the same block as the interpreter" — and a substring search answers a
    different one. This project has already paid for that confusion once: a
    frozen enum member was present in `main` and its producer was not, and the
    grep said shipped.

    EVERY `_sft_run` call site must be followed by a recording call. One
    covered entrance and one uncovered one is how a producer comes to look
    adopted while a whole class of turns silently skips it.
    """
    tree = ast.parse(_conversation_source())

    interpreter_calls, recorder_calls = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        if name == "_sft_run":
            interpreter_calls.append(node.lineno)
        elif name == "_record_turn_identities":
            recorder_calls.append(node.lineno)

    assert interpreter_calls, (
        "no `_sft_run` call found — this gate has stopped measuring its subject")
    assert len(recorder_calls) >= len(interpreter_calls), (
        f"{len(interpreter_calls)} interpreter call site(s) at "
        f"{interpreter_calls} but only {len(recorder_calls)} recording call(s) "
        f"at {recorder_calls}. An uncovered entrance means those turns never "
        f"reach the producer.")

    # Each recorder must FOLLOW an interpreter call closely — a recording call
    # somewhere else in the file would satisfy a bare count while covering
    # nothing.
    for line in interpreter_calls:
        assert any(0 < recorded - line < 40 for recorded in recorder_calls), (
            f"the `_sft_run` at line {line} is not followed by a recording "
            f"call; recorders are at {recorder_calls}")


def test_the_recorder_is_not_behind_a_condition_the_interpreter_is_not():
    """⛔ THE MUTATION GATE — and the FIRST version of it was hollow.

    It scanned a text window above the call for `observing(`,
    `coordinator_mode(` and friends. Reintroducing the exact original defect
    left it GREEN, because the mutation imported the flag under an alias:

        from core.turns.observe import observing as _obs_mut
        if _obs_mut():
            await _record_turn_identities(_sft, db)

    No substring matched. That is the grep trap in an AST costume — grep checks
    SPELLING, and the question here is STRUCTURE.

    ⭐ SO THE PROPERTY IS STATED STRUCTURALLY AND NAMES NO FLAG AT ALL:
    **whenever the interpreter runs, the recorder runs.** The recorder may not
    sit inside any conditional the interpreter is not also inside. Any guard —
    a coordinator mode, a cohort check, a flag invented next year, under any
    name — puts it inside an extra `If` and turns this red.
    """
    tree = ast.parse(_conversation_source())

    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node

    def guards(node):
        """The conditionals this call is nested inside, innermost first."""
        chain, cursor = [], node
        while cursor in parents:
            cursor = parents[cursor]
            if isinstance(cursor, (ast.If, ast.While)):
                chain.append(cursor)
            elif isinstance(cursor, ast.ExceptHandler):
                chain.append(cursor)
        return chain

    def calls_named(name):
        return [n for n in ast.walk(tree)
                if isinstance(n, ast.Call)
                and (getattr(n.func, "id", None)
                     or getattr(n.func, "attr", None)) == name]

    interpreters = calls_named("_sft_run")
    recorders = calls_named("_record_turn_identities")
    assert interpreters and recorders, (
        "the gate cannot find its subject any more — it has stopped measuring")

    for recorder in recorders:
        # The interpreter this recorder follows: the nearest one above it.
        above = [i for i in interpreters if i.lineno < recorder.lineno]
        assert above, f"recorder at line {recorder.lineno} follows no interpreter"
        interpreter = max(above, key=lambda n: n.lineno)

        extra = [g for g in guards(recorder) if g not in guards(interpreter)]
        assert not extra, (
            f"the recorder at line {recorder.lineno} is nested inside "
            f"{len(extra)} condition(s) the interpreter at line "
            f"{interpreter.lineno} is not (first at line {extra[0].lineno}). "
            f"Whatever that condition tests, there are now turns that "
            f"interpret food and never reach the producer — which is the exact "
            f"defect this slice closes.")


@pytest.mark.asyncio
async def test_recording_persists_without_annotating_the_items():
    """⭐ THE ANNOTATION-ONLY CONTRACT, asserted on the RETURNED items.

    Stamping `canonical_entity_id` is not cosmetic: it travels through
    `_log_call` into `_analyze_food`, where `memory_key(food, entity)` addresses
    a DIFFERENT memory row and therefore changes the PRICE. Shadow must add
    durable evidence and nothing else, so the item must come back untouched.
    """
    import core.turns.stages.food as food_stage

    out = {"action": "log",
           "items": [{"food": "Помидор", "amount": 1, "unit": "шт"},
                     {"food": "Barebells Salty Peanut Protein Bar",
                      "amount": 1, "unit": "bar"}]}
    calls = {}

    async def _fake_ensure_resolved(db, surfaces):
        calls["surfaces"] = list(surfaces)
        return {"Помидор": "tomato"}

    import skills.nutrition.entity_resolver as resolver
    original_mode = food_stage.entity_resolution_mode
    original_ensure = resolver.ensure_resolved
    food_stage.entity_resolution_mode = lambda: "shadow"
    resolver.ensure_resolved = _fake_ensure_resolved
    try:
        resolved = await food_stage.record_identities(out, db=object())
    finally:
        food_stage.entity_resolution_mode = original_mode
        resolver.ensure_resolved = original_ensure

    # The producer ran and returned an answer — without this the assertions
    # below pass vacuously on an empty dict.
    assert calls.get("surfaces") == ["Помидор",
                                     "Barebells Salty Peanut Protein Bar"]
    assert resolved == {"Помидор": "tomato"}
    for item in out["items"]:
        assert "canonical_entity_id" not in item, (
            f"{item['food']!r} was annotated by a RECORDING call — that stamp "
            f"reaches memory_key and changes the price, which makes shadow a "
            f"behaviour change rather than annotation-only")


@pytest.mark.parametrize("coordinator_mode",
                         ["legacy_only", "new_observe", "new_execute"])
@pytest.mark.asyncio
async def test_shadow_never_annotates_under_any_coordinator_mode(
        coordinator_mode, monkeypatch):
    """⛔⛔ THE CROSS-PRODUCT GATE — the one that was missing *(Danny, 2026-08-15)*.

    `shadow` used to mean two different things depending on
    `TURN_COORDINATOR_MODE`: the legacy seams call `record_identities` (persist
    only), while `FoodPlanStage.run` calls `stamp_canonical_identity`
    (annotate). So one flag named `shadow` was record-only on legacy traffic
    and CONSUMING on `new_execute` traffic.

    ⭐ AND AFTER `1f13347` THAT IS NOT COSMETIC. The stamp rides `_log_call`
    into `_analyze_food`, where `memory_key(food, entity)` addresses a
    DIFFERENT durable memory row — so `shadow` could move a PRICE on one
    coordinator path and not the other, invisibly, from a flag whose name
    promises neither.

    The property, across the whole cross product: **shadow leaves the item and
    therefore `memory_key` byte-identical to off.**
    """
    import core.turns.stages.food as food_stage
    import skills.nutrition.entity_resolver as resolver
    from core.food_intelligence import memory_key

    monkeypatch.setenv("TURN_COORDINATOR_MODE", coordinator_mode)
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "shadow")

    async def _fake_ensure_resolved(db, surfaces):
        # A VALID, BINDING resolution — anything weaker and the gate passes
        # because there was nothing to stamp, which proves nothing at all.
        return {"Помидор": "tomato"}

    monkeypatch.setattr(resolver, "ensure_resolved", _fake_ensure_resolved)
    monkeypatch.setattr(food_stage, "_log_identity_states",
                        lambda *a, **k: _noop())

    out = {"action": "log", "items": [{"food": "Помидор", "amount": 1}]}
    await food_stage.stamp_canonical_identity(out, db=object())

    item = out["items"][0]
    assert "canonical_entity_id" not in item, (
        f"under TURN_COORDINATOR_MODE={coordinator_mode}, shadow STAMPED "
        f"{item.get('canonical_entity_id')!r} onto a settlement-bound item. "
        f"That reaches memory_key and moves the price — shadow would mean "
        f"'consume' on this coordinator path and 'record' on the others.")
    assert memory_key("Помидор", item.get("canonical_entity_id", "")) == \
        memory_key("Помидор", ""), (
        "the memory key under shadow differs from the key under off — the "
        "identity reached durable addressing")


async def _noop():
    return None


@pytest.mark.asyncio
async def test_consume_is_the_state_that_annotates(monkeypatch):
    """The other half of the contract: `consume` MUST stamp, or the split has
    quietly deleted consumption's doorway while every recording gate stays
    green."""
    import core.turns.stages.food as food_stage
    import skills.nutrition.entity_resolver as resolver

    async def _fake_ensure_resolved(db, surfaces):
        return {"Помидор": "tomato"}

    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "consume")
    # ⚠ CONSUMPTION NOW HAS TWO CONDITIONS: the mode AND the cohort. This test
    # asserted the mode alone and correctly went red when the cohort landed.
    monkeypatch.setenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", "26")
    monkeypatch.setattr(resolver, "ensure_resolved", _fake_ensure_resolved)
    monkeypatch.setattr(food_stage, "_log_identity_states",
                        lambda *a, **k: _noop())

    out = {"action": "log", "items": [{"food": "Помидор", "amount": 1}]}
    await food_stage.stamp_canonical_identity(out, db=object(), user_id=26)
    assert out["items"][0].get("canonical_entity_id") == "tomato"


def test_the_mode_is_registered_with_the_config_guard():
    """⚠ THE PARSER HAS AN `else <default>` BRANCH, AND THAT BRANCH IS THE
    SILENT FAILURE. `NUTRITION_RESOLVER_MODE=true` ran production in shadow for
    six days while a comment recorded it as live. A third state makes it worse:
    a typo'd `consume` is silently `off`, and the symptom is an improvement
    that never arrives."""
    from core.config_guard import ENUM_FLAGS

    flag = ENUM_FLAGS.get("ENTITY_RESOLUTION_MODE")
    assert flag is not None, (
        "ENTITY_RESOLUTION_MODE is not registered — its typos are invisible")
    assert set(flag.allowed) == {"off", "shadow", "consume"}
    assert flag.falls_back_to == "off"


@pytest.mark.asyncio
async def test_off_records_nothing_at_all():
    """`off` must reproduce today's behaviour exactly — no resolver call, so
    not even a lookup's worth of latency or a row's worth of evidence."""
    import core.turns.stages.food as food_stage
    import skills.nutrition.entity_resolver as resolver

    called = []

    async def _fake_ensure_resolved(db, surfaces):
        called.append(surfaces)
        return {}

    original_mode = food_stage.entity_resolution_mode
    original_ensure = resolver.ensure_resolved
    food_stage.entity_resolution_mode = lambda: "off"
    resolver.ensure_resolved = _fake_ensure_resolved
    try:
        resolved = await food_stage.record_identities(
            {"items": [{"food": "Помидор"}]}, db=object())
    finally:
        food_stage.entity_resolution_mode = original_mode
        resolver.ensure_resolved = original_ensure

    assert resolved == {}
    assert not called, "the resolver was consulted with the mode off"


@pytest.mark.asyncio
async def test_a_resolver_failure_cannot_fail_the_food_turn():
    """⚠ THE FOOD TURN OUTRANKS THE ANNOTATION. Nothing consumes the identity
    yet, so a resolver that raises must cost the turn nothing at all."""
    import core.turns.stages.food as food_stage
    import skills.nutrition.entity_resolver as resolver

    async def _exploding(db, surfaces):
        raise RuntimeError("resolver is down")

    original_mode = food_stage.entity_resolution_mode
    original_ensure = resolver.ensure_resolved
    food_stage.entity_resolution_mode = lambda: "shadow"
    resolver.ensure_resolved = _exploding
    try:
        out = {"items": [{"food": "Помидор"}]}
        assert await food_stage.record_identities(out, db=object()) == {}
        assert "canonical_entity_id" not in out["items"][0]
    finally:
        food_stage.entity_resolution_mode = original_mode
        resolver.ensure_resolved = original_ensure


@pytest.mark.asyncio
async def test_the_shared_wrapper_survives_a_missing_producer():
    """The wrapper's own guard, which the producer's internal one cannot give:
    an ImportError is the difference between a resolver that answers badly and
    one that is not there.

    ⚠ IT LIVES IN `core.turns.stages.food`, NOT IN `core.conversation`. Both
    seams import it from the layer that OWNS it, so `handlers.tool_executor`
    never reaches upward into the orchestration layer — a cycle waiting to
    become real."""
    import core.turns.stages.food as food_stage

    # A `db` of None makes the real producer return immediately, so this
    # exercises the wrapper without a database.
    await food_stage.record_turn_identities({"items": [{"food": "x"}]}, None)


def test_the_legacy_tool_path_records_identities_too():
    """⛔⛔ THE SECOND ENTRANCE, AND IT CARRIES MOST OF THE TRAFFIC.

    Wiring the producer to the structured interpreter's output covered ONE food
    turn in FOUR. Measured through `run_chat_turn` on 2026-08-15: three of four
    ordinary food turns logged `entity_identity_skipped
    reason=no_interpretation` — the structured lane declined and the food was
    logged by `execute_tool_calls`, where no interpreter `items` dict exists at
    all. Adding the conversation seam alone took the store from 0 rows to 1;
    adding this one took it to 4.

    ⭐ SO THE COVERAGE OF A SEAM IS NOT THE SAME QUESTION AS ITS EXISTENCE, and
    a gate that only proves the first entrance is exactly how a producer comes
    to look adopted while three quarters of turns walk past it.
    """
    source = (pathlib.Path(__file__).resolve().parents[1]
              / "handlers" / "tool_executor.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    # ⚠ THE PUBLIC NAME IS A WRAPPER; the body lives in `_execute_tool_calls`.
    # The first version of this gate asserted on `execute_tool_calls` alone and
    # went red against correct code — which is the good failure, but it is also
    # the reminder that a structural gate must name the structure that exists
    # rather than the one its author assumed.
    executors = [n for n in ast.walk(tree)
                 if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                 and n.name.lstrip("_") == "execute_tool_calls"]
    assert executors, (
        "no execute_tool_calls definition — this gate has stopped measuring")

    recorders = [n for executor in executors for n in ast.walk(executor)
                 if isinstance(n, ast.Call)
                 and (getattr(n.func, "id", None)
                      or getattr(n.func, "attr", None))
                 in ("record_turn_identities", "_record_turn_identities")]
    assert recorders, (
        "`execute_tool_calls` never records identities. Every food logged by "
        "the legacy tool path — three of four ordinary food turns, measured — "
        "would resolve to nothing, and the store would fill from the minority "
        "of turns the structured lane happens to accept.")

    # It must read the LOG_FOOD input, not some other tool's — a recorder wired
    # to the wrong key records an empty list forever and stays green.
    body = "\n".join(ast.get_source_segment(source, e) or ""
                     for e in executors)
    assert "log_food" in body and "food_name" in body, (
        "the recording block does not reference log_food/food_name, so it "
        "cannot be collecting the foods this turn is about to write")


def test_the_recorder_does_not_import_the_settlement_layer():
    """⭐ SCOPE, ENFORCED. This slice makes the producer REACHABLE. It does not
    move settlement ownership, and the way that promise gets broken is an
    import creeping in — so the promise is a gate rather than a sentence in a
    commit message."""
    import core.turns.stages.food as food_stage

    source = inspect.getsource(food_stage.record_identities)
    for forbidden in ("tool_executor", "assemble", "commit_or_load_existing",
                      "write_canonical_meal", "price("):
        assert forbidden not in source, (
            f"`record_identities` reaches into {forbidden!r} — that is the "
            f"general settlement migration, not the adoption seam")


@pytest.mark.asyncio
async def test_the_adoption_diagnostic_answers_both_canary_questions():
    """⭐ STEP 7 AND STEP 8, ANSWERABLE FROM OUTSIDE THE CONTAINER.

    A shadow canary must prove non-zero resolution ACTIVITY and ZERO
    consumption, and until this endpoint both required reading container logs.

    ⚠ THE TWO NUMBERS ONLY MEAN ANYTHING TOGETHER. A store with nothing in it
    reports zero identity-keyed rows too, so `recorded` and
    `memory_rows_not_keyed_by_their_own_name` are returned side by side — "no
    price moved" and "nothing ran" have one spelling otherwise, which is the
    ambiguous zero this whole tranche kept paying for.

    ⚠⚠ AND IT MUST NEVER RAISE. A diagnostic that 500s has turned an
    observability gap into an outage, so a failure is reported as an `error`
    KEY rather than an exception — asserted here against a database this test
    does not configure.
    """
    from api.diagnostics import identity_adoption_summary

    summary = await identity_adoption_summary()
    assert isinstance(summary, dict)
    for field in ("resolutions", "memory_rows_not_keyed_by_their_own_name"):
        assert field in summary, f"{field} missing — the canary cannot ask its question"
    # Either it answered, or it said why. Never both absent, never an exception.
    assert "error" in summary or "mode" in summary


def test_the_diagnostic_never_echoes_food_names_or_user_ids():
    """⚠ COUNTS AND STATES ONLY. This sits beside endpoints that already refuse
    to echo `env_raw`; a debug surface that leaks what a user ate is a
    different kind of bug from the one it was added to catch."""
    import inspect

    from api import diagnostics

    source = inspect.getsource(diagnostics.identity_adoption_summary)
    for leak in ("surface_form", "parsed_food_name", "display_name)",
                 "user_id"):
        assert f'out["{leak}' not in source, f"{leak} is being returned"


def test_every_seam_import_actually_resolves():
    """⛔⛔ THE GATE THAT WAS MISSING, AND IT COST A BROKEN PUSH.

    `f43b2d5` shipped `from core.conversation import _record_turn_identities`
    after that function had moved to `core.turns.stages.food`. The seam's own
    guard catches ImportError and logs a warning, so the failure mode is
    SILENT: every legacy-tool-path food turn stops recording and the turn looks
    perfectly healthy.

    ⭐ AND EVERY OTHER GATE STAYED GREEN, because they assert the CALL exists.
    An AST gate proves a name is written down; it cannot prove the name
    resolves to anything. Same family as "a stub is a statement about the
    contract, never evidence the stubbed thing exists" — one level up, about
    imports rather than about behaviour.

    So this IMPORTS what the seams import, by name, and fails if it is not
    there.
    """
    import ast
    import importlib
    import pathlib

    for module_path in ("handlers/tool_executor.py", "core/conversation.py"):
        source = (pathlib.Path(__file__).resolve().parents[1]
                  / module_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module:
                continue
            names = [a.name for a in node.names]
            if not any("record_turn_identities" in n or
                       "record_identities" in n for n in names):
                continue
            module = importlib.import_module(node.module)
            for name in names:
                assert hasattr(module, name), (
                    f"{module_path}:{node.lineno} imports {name!r} from "
                    f"{node.module!r}, which does not define it. The seam's "
                    f"guard swallows the ImportError, so this fails SILENTLY "
                    f"and every affected food turn stops recording.")


# ── stage-time recording: the ask path ────────────────────────────────────────

def test_a_pending_canonical_operation_records_before_it_asks():
    """⛔⛔ ANY FOOD ENTERING A PENDING CANONICAL OPERATION MUST HAVE HAD
    IDENTITY RECORDING ATTEMPTED BEFORE THE TURN RETURNS ASK *(Danny,
    2026-08-15)*.

    An ask return carries `text`/`questions`/`options`/`points` and NO `items`
    (core/food_turn.py:5468, :5547), so the post-interpreter seam sees nothing
    and logs `no_interpretation`. The food is then staged into a pending
    operation and settled by B-1 WITHOUT re-interpretation — through neither
    seam, ever. Measured live on `chat_quantity:26:telegram:9340`: the
    interpreter named "Chicken breast", the row committed at 287 kcal from
    `rung=memory`, and no resolution existed for it.

    ⭐ THE INVARIANT IS *ATTEMPTED*, NOT *RESOLVED*. Truncation and abstention
    may legitimately leave no row; never asking is the defect.

    ⚠ STRUCTURAL, because the behavioural version would need a full B-1 turn.
    The recording call must sit inside the block that takes B-1 ownership and
    BEFORE `b1_material` is popped — the pop is what destroys the surface, so
    ordering is the whole property.
    """
    import ast

    source = _conversation_source()
    tree = ast.parse(source)

    recorders, pops = [], []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (getattr(node.func, "id", None)
                    or getattr(node.func, "attr", None))
            if name in ("record_turn_identities", "_record_turn_identities"):
                recorders.append(node.lineno)
            elif name == "pop":
                segment = ast.get_source_segment(source, node) or ""
                if "b1_material" in segment:
                    pops.append(node.lineno)

    assert pops, ("the `b1_material` pop is gone — this gate has stopped "
                  "measuring its subject")
    for pop_line in pops:
        before = [r for r in recorders if r < pop_line and pop_line - r < 25]
        assert before, (
            f"`b1_material` is popped at line {pop_line} with no identity "
            f"recording in the 25 lines before it. That pop destroys the only "
            f"copy of the staged food surface, so every food that enters a "
            f"pending canonical operation would reach settlement with no "
            f"identity ever attempted.")


def test_the_stage_time_recorder_reads_the_interpreter_items():
    """It must record the food the interpreter actually named, not a label
    reconstructed from the question text. `_b1_material` carries
    `data.get("items")` verbatim, which is why option 2 needed no interpreter
    contract change — the surface is already at the staging site."""
    source = _conversation_source()
    assert 'b1_material") or {}).get("items")' in source, (
        "the stage-time recorder is not reading `b1_material['items']`; a food "
        "surface recovered from question copy is a different string from the "
        "one settlement will use")


def test_stage_time_recording_adds_no_pricing_or_settlement_dependency():
    """⭐ SCOPE, ENFORCED. Option 2 was chosen over option 3 precisely because
    semantic resolution must not move into settlement — Gate B. If this block
    ever grows a pricing or commit call, that choice has been undone."""
    source = _conversation_source()
    start = source.index("STAGE-TIME RECORDING")
    block = source[start:start + 2200]
    for forbidden in ("assemble(", "price(", "commit_or_load_existing",
                      "write_canonical_meal"):
        assert forbidden not in block, (
            f"the stage-time recording block reaches {forbidden!r} — that is "
            f"settlement, and moving model-dependent work there is what Gate B "
            f"forbids")


# ── consume is scoped by its OWN cohort ───────────────────────────────────────

@pytest.mark.parametrize("coordinator_mode",
                         ["legacy_only", "new_observe", "new_execute"])
@pytest.mark.parametrize("coordinator_allowlist", ["", "26", "26,27,28"])
def test_coordinator_rollout_cannot_widen_identity_consumption(
        coordinator_mode, coordinator_allowlist, monkeypatch):
    """⛔⛔ THE COUPLING THIS SLICE EXISTS TO BREAK *(Danny, 2026-08-15)*.

    Consumption's real condition used to be `mode == consume` AND coordinator
    native execution AND `TURN_COORDINATOR_ALLOWLIST` — because the only
    caller of the stamp is `FoodPlanStage.run`, which only the native lane
    reaches. So widening the COORDINATOR rollout silently widened PRICE
    MOVEMENT, from a dial named after neither.

        Coordinator enrollment decides which execution PATH runs.
        Identity-consume enrollment decides whether canonical identity may
        affect PRICING. Neither rollout may implicitly widen the other.

    Across the whole cross product of coordinator mode x coordinator allowlist,
    with the consume cohort EMPTY, nobody may consume.
    """
    from core.turns.stages.food import identity_is_consumable

    monkeypatch.setenv("TURN_COORDINATOR_MODE", coordinator_mode)
    monkeypatch.setenv("TURN_COORDINATOR_ALLOWLIST", coordinator_allowlist)
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "consume")
    monkeypatch.delenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", raising=False)

    for user_id in (26, 27, 28, None):
        assert identity_is_consumable(user_id) is False, (
            f"user {user_id} consumes with an EMPTY consume cohort under "
            f"coordinator {coordinator_mode}/{coordinator_allowlist} — the "
            f"coordinator rollout is still deciding price movement")


def test_the_consume_cohort_admits_only_who_it_names(monkeypatch):
    """User 26 consumes; user 27 does not. The canary is one user by
    construction, not by accident of another flag."""
    from core.turns.stages.food import identity_is_consumable

    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "consume")
    monkeypatch.setenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", "26")

    assert identity_is_consumable(26) is True
    assert identity_is_consumable(27) is False
    assert identity_is_consumable(None) is False, (
        "a turn with no user id consumed — the cohort cannot have been checked")


def test_an_empty_cohort_means_nobody_not_everybody(monkeypatch):
    """⛔ FAIL CLOSED, DELIBERATELY AGAINST THE HOUSE CONVENTION.
    `lane_executes_natively` reads an empty allowlist as EVERYONE, and
    render.yaml records the same for NUTRITION_RESOLVER_MODE. Survivable for a
    flag that picks an execution path; not for the one that moves a number on a
    user's plate. An operator who sets the mode and forgets the cohort must
    enrol nobody."""
    from core.turns.stages.food import identity_is_consumable

    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "consume")
    for empty in ("", "   ", ","):
        monkeypatch.setenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", empty)
        assert identity_is_consumable(26) is False, (
            f"an empty cohort {empty!r} enrolled the fleet in price movement")


def test_shadow_is_unchanged_by_the_cohort(monkeypatch):
    """The cohort gates CONSUMPTION only. A user inside it must still not
    consume while the mode is shadow — otherwise the cohort has quietly become
    a second way to turn the feature on."""
    from core.turns.stages.food import identity_is_consumable

    monkeypatch.setenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", "26")
    for mode in ("off", "shadow"):
        monkeypatch.setenv("ENTITY_RESOLUTION_MODE", mode)
        assert identity_is_consumable(26) is False, (
            f"user 26 consumes under mode={mode} because they are in the "
            f"cohort — the cohort is not a mode")


@pytest.mark.asyncio
async def test_the_stamp_asks_the_cohort_not_just_the_mode(monkeypatch):
    """End of the chain: the annotating producer must refuse a user outside the
    cohort even in consume mode, and stamp one inside it."""
    import core.turns.stages.food as food_stage
    import skills.nutrition.entity_resolver as resolver

    async def _fake(db, surfaces):
        return {"Помидор": "tomato"}

    monkeypatch.setattr(resolver, "ensure_resolved", _fake)
    monkeypatch.setattr(food_stage, "_log_identity_states",
                        lambda *a, **k: _noop())
    monkeypatch.setenv("ENTITY_RESOLUTION_MODE", "consume")
    monkeypatch.setenv("ENTITY_RESOLUTION_CONSUME_ALLOWLIST", "26")

    outside = {"action": "log", "items": [{"food": "Помидор", "amount": 1}]}
    await food_stage.stamp_canonical_identity(outside, db=object(), user_id=27)
    assert "canonical_entity_id" not in outside["items"][0], (
        "a user outside the consume cohort was stamped")

    inside = {"action": "log", "items": [{"food": "Помидор", "amount": 1}]}
    await food_stage.stamp_canonical_identity(inside, db=object(), user_id=26)
    assert inside["items"][0].get("canonical_entity_id") == "tomato", (
        "the cohort member was not stamped — consumption is unreachable")
