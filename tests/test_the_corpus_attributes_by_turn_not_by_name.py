"""⛔⛔ THE CORPUS INSTRUMENT MAY NOT ATTRIBUTE A ROW BY WHAT THE FOOD IS CALLED.

P1 of the 2026-08-16 correction. The 2026-08-15 reconciler matched written rows
to corpus items through `normalize_name`, which strips non-Latin script — 28 of
the 30 Russian items shared the key `''` — and its substring fallback made that
key a WILDCARD, because `'' in anything` is True. Measured on the recorded
artifacts: **29 of 29 attributed `ru` rows in run_shadow.json, and 26 of 27 in
run_off.json, name a different food than the one that produced them.**

⭐ THE FAILURE IS NOT "CYRILLIC IS HARD". It is that a name is the wrong key.
Interpretation TRANSLATES (`Куриная грудка` -> `Chicken breast`), so even a
script-preserving `surface_key()` would still be matching two different strings
for one food. These tests hold the contract that replaced it: the join is
`ledger_events.turn_id` on `entry_id`, the driver stamps a unique
`client_msg_id` per turn, and a flush turn DECLARES the turn it settles.

⚠ THE SCRIPT ITSELF NEVER JOINS THE SUITE — it makes real model calls and writes
real rows. `_attribute` is pure, takes ids, and is the part that decides, which
is exactly why it can be gated here at zero cost.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from scripts.corpus_through_the_real_turn import (ATTRIBUTION_VERSION,
                                                  _attribute,
                                                  _position_for_row)


def _item(position, user, food, text=None, declared="NON-ENGLISH",
          role="establish"):
    return {"user": user, "food": food, "text": text or f"I ate {food}",
            "declared": declared, "role": role}


def _turn(seq, turn_id, user, *, index=None, kind="item", flushes=None):
    return {"seq": seq, "kind": kind, "turn_id": turn_id, "user": user,
            "index": index, "flushes": flushes, "text": "t"}


def _row(entry_id, committed_by, name, *, user="ru", rung="ESTIMATE_OR_REFUSE"):
    return {"entry_id": entry_id, "committed_by": committed_by,
            "observed_in_turn": committed_by, "user": user,
            "parsed_food_name": name, "canonical_entity_id": "", "rung": rung,
            "bucket": None, "calories": 100.0, "quantity": "100 g",
            "latency_ms": 1000}


def _ran(*turn_ids):
    return set(turn_ids)


# ── the historical failure, reproduced and refused ────────────────────────────

def test_a_translated_name_cannot_move_a_row_to_another_item():
    """⛔ THE 2026-08-15 DEFECT ITSELF. Two Russian foods, both normalizing to
    the empty string, both TRANSLATED by interpretation. Under name matching the
    first row took the first slot and every later row shifted with it. Under id
    matching each row lands on the turn that wrote it, and the names are not
    consulted at all."""
    body = [_item(0, "ru", "Куриная грудка"), _item(1, "ru", "Сметана 5%")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0),
              _turn(1, "ios:corpus:1", "ru", index=1)]
    rows = [_row(10, "ios:corpus:0", "Chicken breast"),
            _row(11, "ios:corpus:1", "Sour cream 5%")]

    got = _attribute(driven, rows, body, _ran("ios:corpus:0", "ios:corpus:1"))

    assert got["complete"] is True
    by_position = {o["position"]: o for o in got["observations"]}
    assert by_position[0]["entry_id"] == 10
    assert by_position[1]["entry_id"] == 11
    # And the shape that made the old bug invisible: the predicted food and the
    # written name DISAGREE, legitimately, on every one of these rows.
    assert by_position[0]["predicted_food"] == "Куриная грудка"
    assert by_position[0]["parsed_food_name"] == "Chicken breast"


def test_two_items_whose_names_are_identical_are_still_told_apart():
    """⭐ THE CONTROL FOR THE ENGLISH POPULATION. `establish` and `repeat` share
    a name, which is why name matching looked correct for English and hid the
    ordering defect underneath it. Ids separate them with nothing to hide
    behind."""
    body = [_item(0, "en", "Chicken breast", declared="BARE+UNCOVERED"),
            _item(1, "en", "Chicken breast", declared="BARE+UNCOVERED",
                  role="repeat")]
    driven = [_turn(0, "ios:corpus:0", "en", index=0),
              _turn(1, "ios:corpus:1", "en", index=1)]
    # Deliberately out of order: the second turn's row is seen first.
    rows = [_row(21, "ios:corpus:1", "Chicken breast", user="en", rung="MEMORY"),
            _row(20, "ios:corpus:0", "Chicken breast", user="en")]

    got = _attribute(driven, rows, body, _ran("ios:corpus:0", "ios:corpus:1"))

    by_position = {o["position"]: o for o in got["observations"]}
    assert by_position[0]["entry_id"] == 20
    assert by_position[1]["entry_id"] == 21
    assert by_position[1]["rung"] == "MEMORY"


# ── delayed settlement ────────────────────────────────────────────────────────

def test_a_flush_turn_maps_its_rows_back_to_the_turn_it_settles():
    """⭐ DELAYED SETTLEMENT IS DECLARED, NOT DEDUCED. Held food rides
    `deferred_calls` and commits on a LATER turn, so the ledger stamps the FLUSH
    turn's id on the row. The flush record carries the turn it was driven to
    drain — written down before it ran — so the row goes home."""
    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0),
              _turn(1, "ios:corpus:flush:1", "ru", index=0, kind="flush",
                    flushes="ios:corpus:0")]
    rows = [_row(30, "ios:corpus:flush:1", "Borscht")]

    got = _attribute(driven, rows, body,
                     _ran("ios:corpus:0", "ios:corpus:flush:1"))

    assert got["complete"] is True
    assert got["observations"][0]["position"] == 0
    assert got["observations"][0]["entry_id"] == 30


def test_a_flush_for_an_undriven_origin_does_not_invent_a_home():
    """⛔ AND IT REFUSES RATHER THAN GUESSING. A flush whose declared origin is
    not a driven item turn resolves to nothing, so its rows are UNATTRIBUTED —
    never assigned to whichever item happens to be nearby."""
    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0),
              _turn(1, "ios:corpus:flush:1", "ru", kind="flush",
                    flushes="ios:corpus:NOT-DRIVEN")]
    rows = [_row(31, "ios:corpus:flush:1", "Borscht")]

    got = _attribute(driven, rows, body,
                     _ran("ios:corpus:0", "ios:corpus:flush:1"))

    assert got["complete"] is False
    assert len(got["rows_unattributed"]) == 1
    assert (got["rows_unattributed"][0]["reason"]
            == "committing_turn_not_driven_by_this_run")
    assert got["observations"][0]["rung"] == "NO_ROW_WRITTEN"


# ── the gates: every leftover is typed, and none of them is silent ────────────

def test_an_item_that_produced_no_row_is_typed_not_dropped():
    body = [_item(0, "ru", "Кефир 1%")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0)]

    got = _attribute(driven, [], body, _ran("ios:corpus:0"))

    assert got["items_with_no_row"] == 1
    assert got["observations"][0]["rung"] == "NO_ROW_WRITTEN"
    # ⭐ A typed no-row is NOT an attribution failure — the item was driven and
    # observed. What it must never be is missing.
    assert got["complete"] is True


def test_a_row_with_no_ledger_turn_id_fails_rather_than_joining_a_total():
    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0)]
    rows = [_row(40, "", "Borscht")]

    got = _attribute(driven, rows, body, _ran("ios:corpus:0"))

    assert got["complete"] is False
    assert got["rows_unattributed"][0]["reason"] == "no_ledger_turn_id"


def test_an_unattributable_row_is_not_rescued_by_an_identical_name():
    """⛔⛔ THE EXACT SHAPE OF THE ORIGINAL DEFECT, AS A BEHAVIOURAL GATE.

    Version 1's second pass existed to rescue rows the first pass could not
    place, and that rescue is what turned a missing key into a wildcard. Here
    the row's name is IDENTICAL to the one item's predicted food and exactly one
    slot is free — every condition a fallback would want. It must still be
    reported as unattributed, because the ledger cannot say which turn wrote it.

    ⭐ A NAME THAT MATCHES IS NOT PROVENANCE. Same lesson as banana 210 = 2x105.
    """
    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0)]
    rows = [_row(70, "", "Борщ")]              # same name, no correlation id

    got = _attribute(driven, rows, body, _ran("ios:corpus:0"))

    assert got["complete"] is False
    assert len(got["rows_unattributed"]) == 1
    assert got["observations"][0]["rung"] == "NO_ROW_WRITTEN"
    assert got["rows_attributed"] == 0


def test_a_row_seen_twice_is_a_problem_not_a_double_count():
    """⛔ ONE ROW, ONE TURN. A row observed in two windows would inflate every
    count under it, and the inflation would be invisible in the totals."""
    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0)]
    rows = [_row(50, "ios:corpus:0", "Borscht"),
            _row(50, "ios:corpus:0", "Borscht")]

    got = _attribute(driven, rows, body, _ran("ios:corpus:0"))

    assert got["complete"] is False
    assert any(p["kind"] == "row_observed_more_than_once"
               for p in got["problems"])


def test_two_driven_turns_sharing_an_id_is_a_problem():
    """⛔ THE COLLISION THE CLIENT ID EXISTS TO PREVENT. `make_turn_id` falls
    back to sha1 over (channel, user, text, HOUR), so two identical utterances
    inside one hour share an id — measured live as 810 metric rows over 740
    distinct ids. Unasserted, a silent fallback would restore the ambiguity."""
    body = [_item(0, "en", "Almonds"), _item(1, "en", "Almonds", role="repeat")]
    driven = [_turn(0, "ios:h:same", "en", index=0),
              _turn(1, "ios:h:same", "en", index=1)]

    got = _attribute(driven, [], body, _ran("ios:h:same"))

    assert got["complete"] is False
    assert any(p["kind"] == "duplicate_turn_id" for p in got["problems"])


def test_a_driven_turn_that_never_ran_is_a_problem():
    """⛔ A FLUSH THAT DID NOT RUN DRAINS NOTHING AND LOOKS LIKE A FLUSH THAT
    FOUND NOTHING. `turn_metrics` is the only place the difference is visible,
    so a driven id missing from it fails the run."""
    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0),
              _turn(1, "ios:corpus:flush:1", "ru", kind="flush",
                    flushes="ios:corpus:0")]

    got = _attribute(driven, [], body, _ran("ios:corpus:0"))   # flush absent

    assert got["complete"] is False
    problems = [p for p in got["problems"]
                if p["kind"] == "driven_turn_never_ran"]
    assert [p["turn_id"] for p in problems] == ["ios:corpus:flush:1"]


# ── the structural contract ───────────────────────────────────────────────────

def test_the_decision_function_reads_one_key_and_calls_nothing():
    """⭐ STRUCTURE, NOT SPELLING. The gate that a mutation defeated on
    2026-08-15 was a substring scan; this one walks the AST of the function that
    DECIDES and asserts what it may touch. The only literal it may name is the
    correlation key, and the only call it may make is a dict lookup — so there
    is nowhere for a name comparison, a fuzzy pass or a fallback to live."""
    tree = ast.parse(inspect.getsource(_position_for_row))
    function = tree.body[0]
    assert isinstance(function, ast.FunctionDef)

    literals = {node.value for node in ast.walk(function)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node is not function.body[0].value}
    assert literals <= {"committed_by", ""}, (
        f"the decision function names {literals} — the only string it may "
        f"reference is the correlation key")

    called = {node.func.attr for node in ast.walk(function)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert called <= {"get"}, f"the decision function calls {called}"
    assert not [node for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)], (
        "the decision function calls a bare function — attribution must not "
        "reach a normalizer, a matcher or a comparison")


def test_the_attribution_pass_never_reaches_a_name_normalizer():
    """⛔ AND THE SURROUNDING PASS MAY NOT SMUGGLE ONE BACK IN. `_attribute`
    copies food names into its OUTPUT — that is a label, and labels are fine.
    What it may not do is import or call anything that compares them."""
    source = inspect.getsource(_attribute)
    tree = ast.parse(source)

    banned = {"normalize_name", "surface_key", "memory_key", "classify",
              "difflib", "SequenceMatcher", "fuzz"}
    named = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree)
                  if isinstance(node, ast.Attribute)}
    assert not (banned & (named | attributes)), (
        f"attribution reaches {banned & (named | attributes)}")
    assert not [node for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom))], (
        "attribution imports something — it needs ids and nothing else")


def test_the_recorded_2026_08_15_artifacts_are_below_the_version_floor():
    """⛔ THE ARTIFACTS ARE EVIDENCE, NEVER RESULTS. They are preserved byte for
    byte and carry no `attribution` block, which is what puts them below the
    floor `--compare` enforces. If this ever passes trivially because the files
    were replaced, the preservation contract has already been broken."""
    corpus_dir = pathlib.Path(__file__).resolve().parents[1] / "data" / "corpus"
    assert ATTRIBUTION_VERSION >= 2
    for name in ("run_shadow.json", "run_off.json"):
        path = corpus_dir / name
        if not path.exists():          # a fresh checkout may not carry them
            continue
        import json

        report = json.loads(path.read_text())
        version = (report.get("attribution") or {}).get("version", 1)
        assert version < ATTRIBUTION_VERSION, (
            f"{name} claims attribution v{version} — the 2026-08-15 artifacts "
            f"must stay below the floor so `--compare` keeps refusing them")


@pytest.mark.parametrize("field", ["realized_mix_pct", "drift_pts",
                                   "memory_at_settle_pct"])
def test_a_percentage_may_not_publish_while_attribution_is_incomplete(field):
    """⛔⛔ THE RULE THE WHOLE CORRECTION EXISTS FOR. The 2026-08-15 numbers were
    internally consistent, well formed and confident — and computed over rows
    attached to the wrong items. A missing number is recoverable; a wrong one
    gets quoted."""
    from scripts.corpus_through_the_real_turn import _report

    body = [_item(0, "ru", "Борщ")]
    driven = [_turn(0, "ios:corpus:0", "ru", index=0)]
    rows = [_row(60, "", "Borscht")]                # unattributable
    attribution = _attribute(driven, rows, body, _ran("ios:corpus:0"))
    assert attribution["complete"] is False

    corpus = {"corpus_version": "test", "target_mix_pct": {"MEMORY": 43.7},
              "body": body}
    report = _report(corpus, attribution, [1000.0], [], [], [],
                     mode="off", turns=1, items=1)

    assert report[field] is None
    assert report["percentages_withheld_because"]
    assert report["anti_vacuity"]["checks"]["attribution_was_complete"] is False
