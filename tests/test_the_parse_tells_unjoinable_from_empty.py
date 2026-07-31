"""The 6-hour turn parse — `scripts/parse_user_turns.py`.

The master audit could not compute "narrated a log without an operation"
(2026-07-30 §9): ledger `turn_id` carried three formats, none of which equaled
anything on the conversation row. D4 gave every turn one identity and stamped
every turn with its build; this is the read side, and these are the properties
that make its numbers worth quoting.

The central one is a THREE-WAY distinction the audit's own history argues for.
A turn with no `turn_id` cannot be asked whether it wrote anything; a turn that
joins and finds nothing has been asked and answered. Collapsing them is exactly
the failure the fabricated `ios_edit:update:{id}` produced — an id that "joined"
nothing while looking like an honest empty result — so a parse that reports two
buckets reproduces the defect it exists to find.

The last test runs the whole CLI over a database built from the REAL models. It
is the one that fails if a column is renamed: every other assertion here is
about logic, and logic keeps agreeing with itself after the schema has moved.
"""
import json
from datetime import datetime, timedelta

import pytest

from scripts.parse_user_turns import (
    dedupe_mirrored, find_duplicate_operations, find_quick_corrections,
    parse_receipt, parse_turn, redact, rollup, split_tools,
)

NOW = datetime(2026, 7, 31, 12, 0, 0)


def _turn(id_, *, turn_id=None, tools=None, message="had a banana",
          response="Logged it.", receipt="{}", minutes_ago=0, user_id=26,
          source_type="ios", parsed_intent=None, feedback=None):
    return {
        "id": id_, "user_id": user_id, "raw_message": message,
        "response": response, "timestamp": NOW - timedelta(minutes=minutes_ago),
        "source_type": source_type, "platform": "ios", "skills_fired": tools,
        "cards_json": None, "idempotency_key": None, "feedback": feedback,
        "reasoning_json": receipt, "superseded_by": None, "turn_id": turn_id,
        "parsed_intent": parsed_intent,
    }


def _event(id_, *, turn_id, entry_id=1, event_type="created", source="ios",
           minutes_ago=0, user_id=26, domain="food"):
    return {"id": id_, "user_id": user_id, "domain": domain, "turn_id": turn_id,
            "entry_id": entry_id, "daily_log_id": 1, "event_type": event_type,
            "source": source, "created_at": NOW - timedelta(minutes=minutes_ago)}


# ── the three-way join ────────────────────────────────────────────────────────

def test_a_turn_with_no_id_is_unjoinable_not_empty():
    """The whole point. A turn that cannot be asked the question must not be
    counted as one that answered nothing."""
    parsed = parse_turn(_turn(1, turn_id=None, tools="log_food"), {})
    assert parsed["join"] == "unjoinable"
    assert parsed["wrote_nothing"] is False, \
        "an unjoinable turn was scored as a turn that wrote nothing"


def test_a_turn_that_joins_and_finds_nothing_is_the_finding():
    parsed = parse_turn(_turn(2, turn_id="ios:A", tools="log_food"), {})
    assert parsed["join"] == "empty"
    assert parsed["wrote_nothing"] is True


def test_a_turn_that_wrote_is_joined():
    events = {"ios:B": [_event(10, turn_id="ios:B")]}
    parsed = parse_turn(_turn(3, turn_id="ios:B", tools="log_food"), events)
    assert parsed["join"] == "joined"
    assert parsed["wrote_nothing"] is False
    assert parsed["operations"][0]["entry_id"] == 1


def test_a_chat_turn_that_wrote_nothing_is_not_a_finding():
    """No tool fired and no claim was made — an empty join is correct here, and
    reporting it would bury the real ones in conversation."""
    parsed = parse_turn(_turn(4, turn_id="ios:C", tools=None,
                              message="how's my protein",
                              response="You're at 118g."), {})
    assert parsed["join"] == "empty"
    assert parsed["wrote_nothing"] is False


def test_an_empty_join_after_a_tool_error_is_kept_apart():
    """A tool that failed and said so explains its own missing row. A tool that
    reported success over nothing does not — and only the second is silent."""
    errored = parse_turn(_turn(5, turn_id="ios:D", tools="log_food:error",
                               response="Something went wrong."), {})
    silent = parse_turn(_turn(6, turn_id="ios:E", tools="log_food"), {})
    assert errored["wrote_nothing"] and errored["wrote_nothing_explained_by_error"]
    assert silent["wrote_nothing"] and not silent["wrote_nothing_explained_by_error"]

    metrics = rollup([errored, silent], [], NOW - timedelta(hours=6), NOW, 0)
    assert metrics["join"]["wrote_nothing_turns"] == [6]
    assert metrics["join"]["wrote_nothing_after_tool_error"] == [5]


def test_a_reply_claiming_a_log_with_no_tool_is_caught():
    """The phantom claim: the user reported food, the reply said it was
    recorded, nothing fired."""
    parsed = parse_turn(_turn(7, turn_id="ios:F", tools=None,
                              message="just ate two eggs and toast",
                              response="Noted — that's on the board."), {})
    assert parsed["narrated_without_tool"] is True
    assert parsed["wrote_nothing"] is True


# ── the receipt ───────────────────────────────────────────────────────────────

def test_a_turn_with_no_receipt_is_reported_as_missing_not_as_legacy():
    """core/reasoning.py omits `route` when the lane could not be read. A turn
    whose route is unknown must not read as one that routed to legacy."""
    receipt = parse_receipt(None)
    assert receipt["present"] is False
    assert receipt.get("lane") is None

    metrics = rollup([parse_turn(_turn(8, receipt=None), {})], [],
                     NOW - timedelta(hours=6), NOW, 0)
    assert metrics["build"]["turns_without_receipt"] == 1
    assert metrics["route"]["lanes"] == {"—": 1}
    assert metrics["build"]["blind_surfaces"] == {"ios": 1}


def test_an_unreadable_receipt_is_not_a_missing_one():
    receipt = parse_receipt("{not json")
    assert receipt["present"] is True and receipt["readable"] is False


def test_the_receipt_yields_lane_owner_reason_and_build():
    payload = json.dumps({
        "steps": [{"k": "brain"}], "duration_ms": 4100,
        "route": {"lane": "legacy", "owner": "gate_regex",
                  "legacy_reason": "interpreter_none"},
        "build": {"sha": "47e290d1a2b3", "flags": {"STRUCTURED_FOOD": "true",
                                                   "FOOD_GATE_OPEN": None}}})
    receipt = parse_receipt(payload)
    assert receipt["lane"] == "legacy"
    assert receipt["owner"] == "gate_regex"
    assert receipt["legacy_reason"] == "interpreter_none"
    assert receipt["sha"] == "47e290d1a2b3"
    # An unset flag is dropped rather than recorded as the string "None" — the
    # build stamp keeps unset and false distinguishable, and so must this.
    assert receipt["flags"] == {"STRUCTURED_FOOD": "true"}


def test_two_shas_in_one_window_is_named_a_mixed_deployment():
    """Three audits opened by inferring the deployed SHA from behaviour. A
    window spanning two builds mixes every rate in the report; unnamed, it
    reads as one population."""
    def with_sha(id_, sha):
        return parse_turn(_turn(id_, receipt=json.dumps(
            {"build": {"sha": sha, "flags": {}}})), {})

    one = rollup([with_sha(9, "aaa"), with_sha(10, "aaa")], [],
                 NOW - timedelta(hours=6), NOW, 0)
    two = rollup([with_sha(11, "aaa"), with_sha(12, "bbb")], [],
                 NOW - timedelta(hours=6), NOW, 0)
    assert one["build"]["mixed_deployment"] is False
    assert two["build"]["mixed_deployment"] is True


def test_a_flag_that_changed_mid_window_is_named():
    """The other confound §1–4 could not check: flags are Render-managed and
    were 'not queryable from here'. Stamped per turn, a mid-window flip is."""
    def with_flag(id_, value):
        return parse_turn(_turn(id_, receipt=json.dumps(
            {"build": {"sha": "aaa", "flags": {"FOOD_GATE_OPEN": value}}})), {})

    metrics = rollup([with_flag(13, "false"), with_flag(14, "true")], [],
                     NOW - timedelta(hours=6), NOW, 0)
    assert metrics["build"]["mixed_flags"] == ["FOOD_GATE_OPEN"]
    assert metrics["build"]["flag_values"]["FOOD_GATE_OPEN"] == {"false": 1,
                                                                "true": 1}


# ── tools ─────────────────────────────────────────────────────────────────────

def test_an_errored_tool_still_counts_as_fired():
    """`skills_fired` suffixes the failure onto the name. A turn that called
    log_food and got an error DID call log_food."""
    tools, errored = split_tools("log_food,update_food_entry:error")
    assert tools == ["log_food", "update_food_entry"]
    assert errored == ["update_food_entry"]


# ── mirrored rows ─────────────────────────────────────────────────────────────

def test_one_message_on_two_linked_accounts_is_one_turn():
    """Danny's linked accounts each store the same message. Counted twice,
    every rate in the report doubles."""
    rich = _turn(20, turn_id="ios:G", tools="log_food", receipt="{}")
    mirror = dict(_turn(21, turn_id=None, tools=None, receipt=None), user_id=2)
    kept, dropped = dedupe_mirrored([mirror, rich])
    assert dropped == 1
    assert [t["id"] for t in kept] == [20], \
        "the mirror displaced the row that actually carries the turn"


def test_two_different_messages_at_one_timestamp_both_survive():
    a = _turn(22, message="chicken", turn_id="ios:H")
    b = _turn(23, message="rice", turn_id="ios:I")
    kept, dropped = dedupe_mirrored([a, b])
    assert dropped == 0 and len(kept) == 2


# ── duplicates and corrections ────────────────────────────────────────────────

def test_a_shared_turn_id_that_joins_nothing_is_not_called_one_turn():
    """Two edits collapsed into one fabricated, entry-derived id. Reporting
    them as 'the same turn, two writers' asserts the very thing the id got
    wrong."""
    events = [_event(30, turn_id="ios_edit:update:2587", entry_id=2587,
                     event_type="updated", source="ios_edit", minutes_ago=10),
              _event(31, turn_id="ios_edit:update:2587", entry_id=2587,
                     event_type="updated", source="ios_edit",
                     minutes_ago=10) | {"created_at": NOW - timedelta(minutes=10,
                                                                     seconds=-18)}]
    duplicates = find_duplicate_operations(events, known_turn_ids=set())
    assert len(duplicates) == 1
    assert duplicates[0]["same_turn_id"] is True
    assert duplicates[0]["turn_id_joins"] is False

    corroborated = find_duplicate_operations(
        events, known_turn_ids={"ios_edit:update:2587"})
    assert corroborated[0]["turn_id_joins"] is True


def test_an_orphan_belonging_to_a_turn_outside_the_window_is_not_a_defect():
    """Where the window was cut is not a finding. An id no conversation row
    has ever held is — and inside the window the two look identical."""
    since, until = NOW - timedelta(hours=6), NOW
    boundary = _event(60, turn_id="ios:EARLIER", entry_id=5, minutes_ago=5)
    fabricated = _event(61, turn_id="ios_edit:update:2587", entry_id=2587,
                        event_type="updated", source="ios_edit", minutes_ago=5)

    metrics = rollup([], [boundary, fabricated], since, until, 0,
                     turn_ids_elsewhere={"ios:EARLIER"})
    j = metrics["join"]
    assert j["orphan_operations"] == 2
    assert j["orphans_joining_a_turn_outside_the_window"] == 1
    assert j["orphans_joining_no_turn_at_all"] == 1
    assert j["orphan_sources"] == {"ios_edit": 1}, \
        "the boundary artifact was counted against a source as a defect"


def test_a_margin_operation_can_join_its_turn_across_the_boundary():
    """Operations are pulled on a WIDER window than turns, because a turn's
    conversation row is written after its ledger events — an exact-bounds pull
    would report the turn as having written nothing."""
    margin = _event(62, turn_id="ios:R", minutes_ago=362)   # 2 min early
    turn = parse_turn(_turn(63, turn_id="ios:R", tools="log_food",
                            minutes_ago=359), {"ios:R": [margin]})
    assert turn["join"] == "joined"
    assert turn["wrote_nothing"] is False


def test_a_margin_operation_of_an_earlier_turn_is_not_scored_as_an_orphan():
    """The cost of that wider pull: operations belonging to turns BEFORE the
    window come back too. Scored as orphans they would manufacture a defect out
    of where the window was cut — and the count would grow with the margin."""
    since, until = NOW - timedelta(hours=6), NOW
    # 2 minutes before `since`, belonging to a turn that is not in the window.
    stray = _event(64, turn_id="ios:BEFORE", entry_id=7, minutes_ago=362)
    inside = _event(65, turn_id="ios:S", entry_id=8, minutes_ago=30)
    turn = parse_turn(_turn(66, turn_id="ios:S", tools="log_food",
                            minutes_ago=30), {"ios:S": [inside]})

    metrics = rollup([turn], [stray, inside], since, until, 0)
    assert metrics["join"]["orphan_operations"] == 0, \
        "an operation outside the window was counted as an orphan of it"


def test_operations_a_minute_apart_are_not_duplicates():
    events = [_event(32, turn_id="ios:J", entry_id=9, event_type="updated",
                     minutes_ago=10),
              _event(33, turn_id="ios:K", entry_id=9, event_type="updated",
                     minutes_ago=8)]
    assert find_duplicate_operations(events, set()) == []


def test_a_correction_minutes_after_a_log_is_paired_with_it():
    log = parse_turn(_turn(40, turn_id="ios:L", tools="log_food",
                           minutes_ago=20), {})
    fix = parse_turn(_turn(41, turn_id="ios:M", tools="update_food_entry",
                           minutes_ago=14), {})
    stale = parse_turn(_turn(42, turn_id="ios:N", tools="update_food_entry",
                             minutes_ago=0), {})
    corrections = find_quick_corrections([log, fix, stale])
    assert [(c["log_turn"], c["correction_turn"]) for c in corrections] \
        == [(40, 41)], "a correction 20 minutes later was paired with the log"


def test_a_correction_is_not_paired_across_users():
    log = parse_turn(_turn(43, turn_id="ios:O", tools="log_food",
                           minutes_ago=10, user_id=26), {})
    other = parse_turn(_turn(44, turn_id="ios:P", tools="update_food_entry",
                             minutes_ago=5, user_id=31), {})
    assert find_quick_corrections([log, other]) == []


# ── the snapshot ──────────────────────────────────────────────────────────────

def test_the_snapshot_carries_no_message_text():
    """The committed artifact is aggregates and shape. `logging_audit.py` set
    the rule — no message bodies leave the database — and a per-turn detail
    list is exactly where it would quietly break."""
    parsed = [parse_turn(_turn(50, turn_id="ios:Q",
                               message="had a chicken shawarma at Nadimos",
                               response="On the board — 780 cal."), {})]
    record = redact(parsed)[0]
    assert "raw_message" not in record and "response" not in record
    serialized = json.dumps(record)
    assert "shawarma" not in serialized and "Nadimos" not in serialized
    # Length survives: a two-character reply is a signal, its text is not.
    assert record["message_chars"] == 33 and record["response_chars"] == 23


# ── end to end, against the real schema ───────────────────────────────────────

async def test_the_parse_runs_against_the_real_schema(tmp_path, monkeypatch,
                                                      capsys):
    """Every column this script names must exist on the real models.

    The logic tests above pass a hand-built dict, so they keep agreeing with
    themselves after a rename. This one builds the tables from `db.models` and
    runs the CLI, which is what actually fails when the schema moves.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from db.database import Base
    from db.models import ConversationLog, LedgerEvent, User  # noqa: F401
    from scripts.parse_user_turns import main

    db_file = tmp_path / "window.db"
    engine = create_engine(f"sqlite:///{db_file}")
    Base.metadata.create_all(engine)

    recent = datetime.utcnow() - timedelta(minutes=30)
    with Session(engine) as session:
        session.add(User(id=26, name="Danny", telegram_id="t26"))
        session.commit()
        session.add(ConversationLog(
            id=901, user_id=26, raw_message="chicken and rice",
            response="On the board — 620 cal.", timestamp=recent,
            source_type="ios", platform="ios", skills_fired="log_food",
            turn_id="ios:UUID-A",
            reasoning_json=json.dumps({"route": {"lane": "structured_log"},
                                       "build": {"sha": "47e290d", "flags": {}},
                                       "duration_ms": 4100})))
        session.add(ConversationLog(
            id=902, user_id=26, raw_message="also had a banana",
            response="Logged it — 105 cal.", timestamp=recent,
            source_type="ios", platform="ios", skills_fired="log_food",
            turn_id="ios:UUID-B",
            reasoning_json=json.dumps({"build": {"sha": "47e290d",
                                                 "flags": {}}})))
        session.add(LedgerEvent(
            id=501, user_id=26, domain="food", turn_id="ios:UUID-A",
            entry_id=2601, daily_log_id=88, event_type="created",
            source="structured:v3", created_at=recent))
        session.commit()

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_file}")
    snapshot = tmp_path / "snap.json"
    assert main(["--hours", "6", "--json", str(snapshot)]) == 0

    report = capsys.readouterr().out
    assert "**2 turns**" in report
    # 901 wrote and joins; 902 fired log_food, joins, and found nothing.
    assert "WROTE NOTHING**     turns [902]" in report

    metrics = json.loads(snapshot.read_text())
    assert metrics["join"] == metrics["join"] | {"turns_joined": 1,
                                                 "turns_joined_empty": 1,
                                                 "turns_unjoinable": 0}
    assert metrics["tools"]["histogram"] == {"log_food": 2}


async def test_a_missing_database_url_says_what_to_set(monkeypatch, tmp_path):
    """A fresh checkout has no `.env` — that is the normal state, not a bug to
    be debugged through a driver stack trace."""
    from scripts import parse_user_turns

    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setattr(parse_user_turns, "REPO_ROOT", tmp_path)
    with pytest.raises(SystemExit) as raised:
        parse_user_turns.resolve_database_url()
    assert "DATABASE_URL" in str(raised.value)
