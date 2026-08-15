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


@pytest.mark.asyncio
async def test_the_annotating_producer_still_stamps():
    """The native lane's contract is unchanged by the split — otherwise this
    refactor would have quietly removed consumption's doorway while every gate
    about recording stayed green."""
    import core.turns.stages.food as food_stage
    import skills.nutrition.entity_resolver as resolver

    out = {"action": "log", "items": [{"food": "Помидор", "amount": 1}]}

    async def _fake_ensure_resolved(db, surfaces):
        return {"Помидор": "tomato"}

    original_mode = food_stage.entity_resolution_mode
    original_ensure = resolver.ensure_resolved
    food_stage.entity_resolution_mode = lambda: "shadow"
    resolver.ensure_resolved = _fake_ensure_resolved
    try:
        await food_stage.stamp_canonical_identity(out, db=object())
    finally:
        food_stage.entity_resolution_mode = original_mode
        resolver.ensure_resolved = original_ensure

    assert out["items"][0].get("canonical_entity_id") == "tomato"


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
async def test_the_conversation_wrapper_survives_a_missing_producer():
    """The wrapper's own guard, which the producer's internal one cannot give:
    an ImportError is the difference between a resolver that answers badly and
    one that is not there."""
    import core.conversation as conversation

    # A `db` of None makes the real producer return immediately, so this
    # exercises the wrapper without a database.
    await conversation._record_turn_identities({"items": [{"food": "x"}]}, None)


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
                 == "_record_turn_identities"]
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
