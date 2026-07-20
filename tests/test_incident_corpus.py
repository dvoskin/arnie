"""The incident corpus, executable — every corpus case whose expectations the
write-set validator can check runs as CI. Model-level expectations (reply
wording, tool ordering) wait for the full replay harness; the JUSTIFICATION
layer is checkable today, so it gates today.

Contract: for each corpus case with `setup.board` + `user_msg`:
  • every item in expected.writes  → validator says justified/repeat_cue
    when the model proposes it,
  • every item in expected.blocked → validator flags it as suspicious
    when the model proposes it anyway.
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.write_set import validate_write_set
from skills.logging_intent import effective_intent_message

CORPUS = Path(__file__).parent / "corpus" / "incident_cases.jsonl"


def _cases():
    for line in CORPUS.read_text().splitlines():
        if line.strip():
            yield json.loads(line)


def _board(case):
    out = []
    for i, e in enumerate(case.get("setup", {}).get("board", [])):
        out.append(SimpleNamespace(
            id=e.get("entry_id", 900 + i),
            parsed_food_name=e.get("name", ""),
            timestamp=datetime.utcnow() - timedelta(minutes=e.get("logged_min_ago", 10)),
        ))
    return out


def _gate_msg(case):
    return effective_intent_message(case["user_msg"], case.get("prior_user_msg"),
                                    case.get("prior_assistant_msg"))


_CHECKABLE = [c for c in _cases()
              if (c.get("expected", {}).get("writes") or c.get("expected", {}).get("blocked"))
              and not c["user_msg"].startswith("[")]   # sentinel turns need the pipeline


@pytest.mark.parametrize("case", _CHECKABLE, ids=lambda c: c["id"])
def test_corpus_case_justification(case):
    exp = case["expected"]
    board = _board(case)
    msg = _gate_msg(case)

    for spec in exp.get("writes") or []:
        frag = spec.get("name_contains", "")
        v = validate_write_set(
            [{"name": "log_food", "input": {"food_name": frag}}], msg, board)
        assert v[0].verdict in ("justified", "repeat_cue"), (
            f"{case['id']}: expected write '{frag}' judged {v[0].verdict} — {v[0].reason}")

    for spec in exp.get("blocked") or []:
        frag = spec.get("name_contains", "")
        # The FULL on-board name is what a carried-over re-fire proposes.
        full = next(
            (getattr(e, "parsed_food_name") for e in board
             if frag.lower() in getattr(e, "parsed_food_name", "").lower()),
            frag)
        v = validate_write_set(
            [{"name": "log_food", "input": {"food_name": full}}], msg, board)
        assert v[0].verdict.startswith("suspicious"), (
            f"{case['id']}: expected block '{full}' judged {v[0].verdict} — {v[0].reason}")
