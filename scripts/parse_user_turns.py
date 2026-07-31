"""Parse every user turn in a recent window — READ-ONLY, one command.

    python scripts/parse_user_turns.py                  # last 6 hours
    python scripts/parse_user_turns.py --hours 18
    python scripts/parse_user_turns.py --user 26 --rollup

Every audit in `audits/` opens the same way: pull the window, parse each turn
into route / build / tools / operations, then count. That opening has been
hand-written three times, and each rewrite recovered a slightly different set
of fields — which is why the 07-29 and 07-30 audits disagree about how many
turns carry a receipt. This is that opening, once.

WHAT THE PARSE IS FOR. Three of the master audit's findings were **not
computable** when it ran (`audits/MASTER_AUDIT_2026-07-30.md` §9, §1–4):

  * "narrated a log without an operation" — no reliable turn⋈operation join
    existed; ledger `turn_id` carried three formats, none equal to anything on
    the conversation row.
  * the deployed SHA — inferred from behavioural markers ("does this pending
    carry `log_date`?") because nothing recorded it.
  * turns with no receipt at all — read as a sampling gap; D4 later measured
    them as three whole surfaces, each 100% blank.

D4 closed all three at the write site (`conversation_logs.turn_id`, and the
build stamped on every turn whether or not it has a receipt). This script is
the read side: the questions those commits made answerable, asked.

So the join is reported in THREE buckets, never two. A turn with no `turn_id`
is *unjoinable*, which is not the same as a turn that joined and found nothing
— collapsing them is how a fabricated id reads as an honest empty result
(`tests/test_a_dashboard_edit_joins_its_turn.py`). Anything this script cannot
establish it prints as unknown rather than as zero.

NOTHING IS WRITTEN. No UPDATE/INSERT/DELETE is issued and no ORM session is
opened (the async engine hangs against prod — see `scripts/logging_audit.py`).
The per-turn parse prints message bodies to your terminal because reading them
is the point; the JSON snapshot is aggregates plus redacted per-turn records,
so the committed artifact carries no message text. `--rollup` skips the bodies
entirely.

Postgres needs `psycopg`; a local SQLite `DATABASE_URL` works with the stdlib
and no extra install, which is what makes the parse testable off prod.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: Tools whose firing means the turn tried to WRITE something. A turn that
#: fired one of these and produced no operation is the §9 question.
LOG_TOOLS = ("log_food", "log_exercise", "log_water", "log_body_weight")
MUTATING_TOOLS = LOG_TOOLS + (
    "update_food_entry", "delete_food_entry",
    "update_exercise_entry", "delete_exercise_entry",
)
CORRECTION_TOOLS = ("update_food_entry", "delete_food_entry",
                    "update_exercise_entry", "delete_exercise_entry")

#: A correction that lands within this long of a log is the user fixing what
#: Arnie just wrote. Same window `scripts/logging_audit.py` scores.
CORRECTION_WINDOW = timedelta(minutes=15)
#: Two operations on one entry closer together than this are one intent
#: recorded twice (master audit §10 scores duplicates at 60s).
DUPLICATE_WINDOW = timedelta(seconds=60)


# ── connection ───────────────────────────────────────────────────────────────

def resolve_database_url() -> str:
    """DATABASE_URL from the environment, else the repo `.env`.

    Raises with the actual fix rather than a driver error three frames down: a
    missing URL is the normal state of a fresh checkout (`.env` is gitignored),
    and it is not a bug to be debugged.
    """
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        env_file = REPO_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.strip().startswith("DATABASE_URL="):
                    url = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not url:
        raise SystemExit(
            "No DATABASE_URL.\n"
            "  prod:  export DATABASE_URL='<Render external connection string>'\n"
            "  local: export DATABASE_URL='sqlite:///arnie.db'\n"
            f"or put DATABASE_URL= in {REPO_ROOT / '.env'} (gitignored).\n"
            "This script only reads; a read-only role is enough.")
    return url


class Cursor:
    """One cursor over either driver, with `%s` placeholders throughout.

    SQLite wants `?`; translating here keeps every query in this file written
    one way, so the two backends cannot drift apart query by query.
    """

    def __init__(self, cur, is_sqlite: bool):
        self._cur = cur
        self._sqlite = is_sqlite

    def rows(self, sql: str, params: Iterable = ()) -> list[dict]:
        params = tuple(params)
        if self._sqlite:
            sql = sql.replace("%s", "?")
        self._cur.execute(sql, params)
        if self._cur.description is None:
            return []
        cols = [d[0] for d in self._cur.description]
        return [dict(zip(cols, r)) for r in self._cur.fetchall()]


def connect(url: str):
    """(Cursor, closer, backend-name). Postgres via psycopg, SQLite via stdlib."""
    if url.startswith("sqlite"):
        import sqlite3
        path = url.split("///")[-1] or ":memory:"
        conn = sqlite3.connect(path)
        return Cursor(conn.cursor(), True), conn.close, f"sqlite:{path}"

    normalized = re.sub(r"^[a-z]+\+[a-z0-9]+://", "postgresql://", url)
    normalized = re.sub(r"^postgres://", "postgresql://", normalized)
    try:
        import psycopg
    except ImportError:
        raise SystemExit(
            "psycopg is not installed — needed for a Postgres DATABASE_URL.\n"
            "  pip install 'psycopg[binary]'")
    conn = psycopg.connect(normalized)
    return Cursor(conn.cursor(), False), conn.close, "postgres"


# ── loading the window ───────────────────────────────────────────────────────

def _as_dt(value) -> datetime | None:
    """SQLite hands back strings, Postgres hands back datetimes. Naive UTC out."""
    if value is None or isinstance(value, datetime):
        return value.replace(tzinfo=None) if isinstance(value, datetime) \
            and value.tzinfo else value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")
                                      ).replace(tzinfo=None)
    except ValueError:
        return None


def load_window(cur: Cursor, since: datetime, until: datetime,
                user_id: int | None = None) -> dict:
    """Turns in the window, plus every ledger operation that could belong to one.

    Operations are pulled on a WIDER window than the turns. An operation
    recorded a second after its turn's timestamp is the same turn's work, and
    an exact-bounds pull would drop it and report the turn as having written
    nothing — inventing the very defect this looks for.
    """
    where = ["timestamp >= %s", "timestamp < %s"]
    params: list[Any] = [since, until]
    if user_id is not None:
        where.append("user_id = %s")
        params.append(user_id)
    turns = cur.rows(
        "SELECT id, user_id, raw_message, parsed_intent, response, timestamp, "
        "source_type, platform, skills_fired, cards_json, idempotency_key, "
        "feedback, reasoning_json, superseded_by, turn_id "
        f"FROM conversation_logs WHERE {' AND '.join(where)} "
        "ORDER BY timestamp ASC, id ASC", params)
    for t in turns:
        t["timestamp"] = _as_dt(t["timestamp"])

    slack = timedelta(minutes=5)
    ev_where = ["created_at >= %s", "created_at < %s"]
    ev_params: list[Any] = [since - slack, until + slack]
    if user_id is not None:
        ev_where.append("user_id = %s")
        ev_params.append(user_id)
    events = cur.rows(
        "SELECT id, user_id, domain, turn_id, entry_id, daily_log_id, "
        "event_type, source, created_at "
        f"FROM ledger_events WHERE {' AND '.join(ev_where)} "
        "ORDER BY created_at ASC, id ASC", ev_params)
    for e in events:
        e["created_at"] = _as_dt(e["created_at"])

    return {"turns": turns, "events": events}


def turn_ids_existing_anywhere(cur: Cursor, wanted: set) -> set:
    """Which of these turn ids exist on ANY conversation row, in any window.

    An operation whose turn sits a minute outside the window is a boundary
    artifact; an operation whose id belongs to no turn that has ever existed is
    the fabricated-identity defect. Both look identical inside the window, and
    reporting them as one number would put the dashboard's 28 unjoinable edits
    in the same bucket as ordinary edge effects.
    """
    wanted = {w for w in wanted if w}
    if not wanted:
        return set()
    found: set = set()
    ids = sorted(wanted)
    for start in range(0, len(ids), 200):       # bounded IN() lists
        chunk = ids[start:start + 200]
        placeholders = ",".join(["%s"] * len(chunk))
        rows = cur.rows(
            f"SELECT DISTINCT turn_id FROM conversation_logs "
            f"WHERE turn_id IN ({placeholders})", chunk)
        found.update(r["turn_id"] for r in rows)
    return found


def dedupe_mirrored(turns: list[dict]) -> tuple[list[dict], int]:
    """Linked accounts mirror one real turn onto two rows; count it once.

    Danny's iOS and Telegram ids both carry the same message (the reason
    `scripts/audit_history_query_turns.py` dedupes on the same key). Keeping
    both would double every rate in this report. The survivor is the row that
    knows more: a turn_id first, then tool telemetry — a mirror written by a
    surface that never joined must not displace the one that did.
    """
    best: dict[tuple, dict] = {}
    dropped = 0

    def rank(t: dict) -> tuple:
        return (bool(t.get("turn_id")), bool(t.get("skills_fired")),
                bool(t.get("reasoning_json")))

    for t in turns:
        key = (t["timestamp"], (t.get("raw_message") or "")[:120])
        incumbent = best.get(key)
        if incumbent is None:
            best[key] = t
        else:
            dropped += 1
            if rank(t) > rank(incumbent):
                best[key] = t
    return sorted(best.values(),
                  key=lambda t: (t["timestamp"] or datetime.min, t["id"])), dropped


# ── parsing one turn ─────────────────────────────────────────────────────────

def split_tools(skills_fired: str | None) -> tuple[list[str], list[str]]:
    """(tools, errored) — `skills_fired` is comma-separated, errors suffixed
    `:error` (core/conversation.py)."""
    tools, errored = [], []
    for part in (skills_fired or "").split(","):
        name = part.strip()
        if not name:
            continue
        if name.endswith(":error"):
            base = name[: -len(":error")]
            tools.append(base)
            errored.append(base)
        else:
            tools.append(name)
    return tools, errored


def parse_receipt(reasoning_json: str | None) -> dict:
    """The receipt's diagnostic half: lane, owner, legacy_reason, build, flags.

    A row with no receipt at all is `present: False` — since D4 that means the
    write did not come through `log_conversation`, which is a finding, not a
    blank. Unparseable JSON is reported as its own state for the same reason.
    """
    if not reasoning_json:
        return {"present": False, "readable": False}
    try:
        payload = json.loads(reasoning_json)
    except (ValueError, TypeError):
        return {"present": True, "readable": False}
    if not isinstance(payload, dict):
        return {"present": True, "readable": False}
    route = payload.get("route") if isinstance(payload.get("route"), dict) else {}
    build = payload.get("build") if isinstance(payload.get("build"), dict) else {}
    flags = build.get("flags") if isinstance(build.get("flags"), dict) else {}
    return {
        "present": True,
        "readable": True,
        # Absent rather than "legacy": core/reasoning.py omits `route` when the
        # lane could not be read, and a turn whose route is unknown must not be
        # indistinguishable from one that routed to legacy.
        "lane": route.get("lane"),
        "owner": route.get("owner"),
        "legacy_reason": route.get("legacy_reason"),
        "sha": build.get("sha"),
        "flags": {k: v for k, v in flags.items() if v is not None},
        "steps": len(payload.get("steps") or []),
        "duration_ms": payload.get("duration_ms"),
    }


def narrates_a_write(user_text: str, response: str, has_tools: bool) -> bool:
    """Does the reply claim something was recorded?

    Reuses `core.turn_health` — the same detectors that flag the turn live, so
    this report and the flag on the row cannot disagree about what a claim is.
    Pure regex functions, no DB, no app state.
    """
    try:
        from core.turn_health import looks_like_phantom_log_claim
    except ImportError:      # pragma: no cover — repo layout changed
        return False
    return looks_like_phantom_log_claim(user_text or "", response or "",
                                        has_tools)


def parse_turn(turn: dict, events_by_turn: dict[str, list[dict]]) -> dict:
    """One turn, parsed into the fields every audit re-derives by hand."""
    tools, errored = split_tools(turn.get("skills_fired"))
    receipt = parse_receipt(turn.get("reasoning_json"))
    turn_id = turn.get("turn_id")
    operations = events_by_turn.get(turn_id, []) if turn_id else []

    # THREE states, never two. "unjoinable" is a turn that cannot be asked the
    # question; "empty" is a turn that was asked and answered nothing.
    if not turn_id:
        join = "unjoinable"
    elif operations:
        join = "joined"
    else:
        join = "empty"

    mutating = [t for t in tools if t in MUTATING_TOOLS]
    claimed = narrates_a_write(turn.get("raw_message"), turn.get("response"),
                               bool(tools))
    # An empty join whose tools ALL errored is explained: the write failed and
    # said so. An empty join with no error is the unexplained kind — a tool
    # that reported success over nothing, or a reply that claimed a write with
    # no tool behind it. Scoring them together buries the second in the first.
    explained = bool(mutating and all(t in errored for t in mutating)
                     and not claimed)

    return {
        "id": turn["id"],
        "user_id": turn.get("user_id"),
        "timestamp": turn["timestamp"],
        "platform": turn.get("platform") or "?",
        "source_type": turn.get("source_type") or "text",
        "turn_id": turn_id,
        "tools": tools,
        "tool_errors": errored,
        "mutating_tools": mutating,
        "health_flags": [f for f in (turn.get("parsed_intent") or "").split(",")
                         if f.strip()],
        "feedback": turn.get("feedback"),
        "superseded": turn.get("superseded_by") is not None,
        "receipt": receipt,
        "join": join,
        "operations": [
            {"id": e["id"], "domain": e.get("domain"), "entry_id": e.get("entry_id"),
             "event_type": e.get("event_type"), "source": e.get("source"),
             "created_at": e.get("created_at")}
            for e in operations
        ],
        # The §9 question, now askable: a write was attempted or claimed, the
        # turn CAN be joined, and the join is empty. A turn with no turn_id is
        # excluded — it is unjoinable, which is a different defect.
        "wrote_nothing": bool(join == "empty" and (mutating or claimed)),
        "wrote_nothing_explained_by_error": explained,
        "narrated_without_tool": bool(claimed),
        "raw_message": turn.get("raw_message") or "",
        "response": turn.get("response") or "",
    }


# ── cross-turn passes ────────────────────────────────────────────────────────

def find_duplicate_operations(events: list[dict],
                              known_turn_ids: set) -> list[dict]:
    """Operations recorded twice for one entry inside a minute.

    Reports the two `source` labels because that is what identified the
    quick-log double-write: same turn, 0s apart, two writers (`ios`,
    `legacy:ios`) — a second writer, not a race.

    Every event type is scanned, but note what the schema already rules out:
    invariant I3's partial unique index makes a second `created` for one entry
    impossible at the database. So a duplicate found here is a repeated
    UPDATE or DELETE — which is the shape the dashboard's double-edit takes,
    and the one still live.

    A shared `turn_id` is only reported as one turn when that id actually
    joins a turn. Two operations agreeing on an id no conversation row holds
    is the fabricated-id defect, not evidence of a shared turn — treating it
    as the latter is the same mistake the id itself made.
    """
    by_entry: dict[tuple, list[dict]] = defaultdict(list)
    for e in events:
        if e.get("entry_id") is None:
            continue
        by_entry[(e.get("user_id"), e.get("domain"), e["entry_id"],
                  e.get("event_type"))].append(e)

    duplicates = []
    for key, group in by_entry.items():
        group.sort(key=lambda e: (e["created_at"] or datetime.min, e["id"]))
        for prev, cur in zip(group, group[1:]):
            if not (prev["created_at"] and cur["created_at"]):
                continue
            gap = cur["created_at"] - prev["created_at"]
            if gap <= DUPLICATE_WINDOW:
                shared = (prev.get("turn_id") == cur.get("turn_id")
                          and bool(prev.get("turn_id")))
                duplicates.append({
                    "user_id": key[0], "domain": key[1], "entry_id": key[2],
                    "event_type": key[3], "gap_seconds": gap.total_seconds(),
                    "event_ids": [prev["id"], cur["id"]],
                    "sources": [prev.get("source"), cur.get("source")],
                    "same_turn_id": shared,
                    "turn_id_joins": bool(shared and prev["turn_id"]
                                          in known_turn_ids),
                    "turn_ids": [prev.get("turn_id"), cur.get("turn_id")],
                })
    return duplicates


def find_quick_corrections(parsed: list[dict]) -> list[dict]:
    """A correction the user made within 15 minutes of a log — the cheapest
    proxy for "the write was wrong", and the rate the baseline tracks."""
    corrections = []
    by_user: dict[Any, list[dict]] = defaultdict(list)
    for p in parsed:
        by_user[p["user_id"]].append(p)
    for turns in by_user.values():
        logs = [t for t in turns if any(x in LOG_TOOLS for x in t["tools"])]
        for t in turns:
            if not any(x in CORRECTION_TOOLS for x in t["tools"]):
                continue
            for earlier in logs:
                if earlier["timestamp"] and t["timestamp"] \
                        and earlier["timestamp"] < t["timestamp"] \
                        <= earlier["timestamp"] + CORRECTION_WINDOW:
                    corrections.append({
                        "log_turn": earlier["id"], "correction_turn": t["id"],
                        "user_id": t["user_id"],
                        "gap_seconds": (t["timestamp"]
                                        - earlier["timestamp"]).total_seconds(),
                        "tools": t["tools"],
                    })
                    break
    return corrections


def rollup(parsed: list[dict], events: list[dict], since: datetime,
           until: datetime, mirrored_dropped: int,
           turn_ids_elsewhere: set = frozenset()) -> dict:
    """Every count the audits open with, from one pass over the parsed turns."""
    joinable_ops = {e.get("turn_id") for e in events if e.get("turn_id")}
    turn_ids = {p["turn_id"] for p in parsed if p["turn_id"]}
    # Orphans are counted only over operations recorded INSIDE the window. The
    # margins are pulled so a turn's own operation can join it across the
    # boundary — counting those as orphans would manufacture a defect out of
    # where the window happens to be cut.
    in_window = [e for e in events
                 if e["created_at"] and since <= e["created_at"] < until]
    orphan_ops = [e for e in in_window
                  if not e.get("turn_id") or e["turn_id"] not in turn_ids]
    orphan_boundary = [e for e in orphan_ops
                       if e.get("turn_id") in turn_ids_elsewhere]
    orphan_no_turn = [e for e in orphan_ops if e not in orphan_boundary]

    shas = Counter(p["receipt"].get("sha") or "—" for p in parsed)
    blind_by_surface = Counter(p["source_type"] for p in parsed
                               if not p["receipt"]["present"])
    surfaces = Counter(p["source_type"] for p in parsed)

    tools = Counter(t for p in parsed for t in p["tools"])
    lanes = Counter(p["receipt"].get("lane") or "—" for p in parsed)
    owners = Counter(p["receipt"].get("owner") or "—" for p in parsed)
    legacy_reasons = Counter(p["receipt"]["legacy_reason"] for p in parsed
                             if p["receipt"].get("legacy_reason"))
    flags = Counter(f for p in parsed for f in p["health_flags"])
    joins = Counter(p["join"] for p in parsed)

    # Flags observed across the window, each with the raw value it held. A
    # flag that changed value mid-window is a mixed-flag period — the same
    # class of confound as a mixed-deploy one, and previously unaskable.
    flag_values: dict[str, Counter] = defaultdict(Counter)
    for p in parsed:
        for name, value in (p["receipt"].get("flags") or {}).items():
            flag_values[name][str(value)] += 1

    wrote_nothing = [p for p in parsed if p["wrote_nothing"]]
    durations = sorted(p["receipt"]["duration_ms"] for p in parsed
                       if isinstance(p["receipt"].get("duration_ms"), int))

    def percentile(pct: float):
        """Nearest-rank, so p95 of 20 samples is the 19th, not the largest."""
        if not durations:
            return None
        import math
        rank = max(1, math.ceil(pct * len(durations)))
        return durations[rank - 1]

    return {
        "window": {"since_utc": since.isoformat(), "until_utc": until.isoformat(),
                   "hours": round((until - since).total_seconds() / 3600, 2)},
        "generated_utc": datetime.now(timezone.utc).replace(
            tzinfo=None).isoformat(timespec="seconds"),
        "turns": len(parsed),
        "mirrored_rows_dropped": mirrored_dropped,
        "users": len({p["user_id"] for p in parsed}),
        "by_platform": dict(Counter(p["platform"] for p in parsed)),
        "by_source_type": dict(surfaces),
        "superseded_turns": sum(1 for p in parsed if p["superseded"]),
        "feedback": dict(Counter(p["feedback"] for p in parsed if p["feedback"])),

        "build": {
            "sha_distribution": dict(shas),
            # More than one SHA means the window spans a deploy and every
            # per-lane rate below mixes two builds. Naming it is the point.
            "mixed_deployment": len([s for s in shas if s != "—"]) > 1,
            "turns_without_receipt": sum(1 for p in parsed
                                         if not p["receipt"]["present"]),
            "unreadable_receipts": sum(1 for p in parsed
                                       if p["receipt"]["present"]
                                       and not p["receipt"]["readable"]),
            "blind_surfaces": dict(blind_by_surface),
            "flag_values": {k: dict(v) for k, v in flag_values.items()},
            "mixed_flags": sorted(k for k, v in flag_values.items()
                                  if len(v) > 1),
        },

        "route": {"lanes": dict(lanes), "owners": dict(owners),
                  "legacy_reasons": dict(legacy_reasons)},

        "tools": {
            "histogram": dict(tools),
            "turns_with_tools": sum(1 for p in parsed if p["tools"]),
            "turns_with_tool_error": sum(1 for p in parsed if p["tool_errors"]),
            "log_turns": sum(1 for p in parsed
                             if any(t in LOG_TOOLS for t in p["tools"])),
        },

        "join": {
            "operations": len(events),
            "turns_joined": joins.get("joined", 0),
            "turns_joined_empty": joins.get("empty", 0),
            "turns_unjoinable": joins.get("unjoinable", 0),
            "operations_with_turn_id": len([e for e in events if e.get("turn_id")]),
            "orphan_operations": len(orphan_ops),
            # A turn just outside the window is an artifact of where the window
            # was cut. An id no conversation row has ever held is the defect.
            "orphans_joining_a_turn_outside_the_window": len(orphan_boundary),
            "orphans_joining_no_turn_at_all": len(orphan_no_turn),
            "orphan_sources": dict(Counter(e.get("source") or "—"
                                           for e in orphan_no_turn)),
            "distinct_operation_turn_ids": len(joinable_ops),
            # §9, computable: a write attempted or claimed, joinable, empty.
            # Split, because a tool that ERRORED explains its own missing row
            # and a tool that reported success does not.
            "wrote_nothing_turns": [p["id"] for p in wrote_nothing
                                    if not p["wrote_nothing_explained_by_error"]],
            "wrote_nothing_after_tool_error": [
                p["id"] for p in wrote_nothing
                if p["wrote_nothing_explained_by_error"]],
            "narrated_without_tool_turns": [p["id"] for p in parsed
                                            if p["narrated_without_tool"]],
        },

        "health_flags": dict(flags),
        "duplicate_operations": find_duplicate_operations(events, turn_ids),
        "quick_corrections": find_quick_corrections(parsed),
        "latency_ms": {
            "n": len(durations),
            "p50": percentile(0.50),
            "p95": percentile(0.95),
            "max": durations[-1] if durations else None,
        },
    }


def redact(parsed: list[dict]) -> list[dict]:
    """Per-turn records with the bodies removed — what a committed snapshot may
    carry. Lengths are kept: "a 2-character reply" is a signal, its text is not."""
    return [{k: v for k, v in dict(
        p, timestamp=p["timestamp"].isoformat() if p["timestamp"] else None,
        message_chars=len(p["raw_message"]), response_chars=len(p["response"]),
        operations=[dict(o, created_at=o["created_at"].isoformat()
                         if o["created_at"] else None) for o in p["operations"]],
    ).items() if k not in ("raw_message", "response")} for p in parsed]


# ── rendering ────────────────────────────────────────────────────────────────

def _bar(counter: dict, total: int, indent: str = "  ") -> list[str]:
    lines = []
    for name, n in sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0]))):
        share = f" ({n / total:.0%})" if total else ""
        lines.append(f"{indent}{str(name):<28} {n}{share}")
    return lines


def render_rollup(m: dict) -> str:
    w, n = m["window"], m["turns"]
    out = [
        f"# Turn parse — {w['hours']}h window "
        f"({w['since_utc'][:16]}Z → {w['until_utc'][:16]}Z)",
        "",
        f"**{n} turns** · {m['users']} user{'' if m['users'] == 1 else 's'} · "
        f"{m['join']['operations']} ledger operations · generated "
        f"{m['generated_utc'][:16]}Z",
    ]
    if not n:
        out += ["", "No turns in this window."]
        return "\n".join(out)
    if m["mirrored_rows_dropped"]:
        out.append(f"_{m['mirrored_rows_dropped']} mirrored row(s) from linked "
                   f"accounts collapsed into their real turn._")

    b = m["build"]
    out += ["", "## Build", ""]
    out += _bar(b["sha_distribution"], n)
    if b["mixed_deployment"]:
        out.append("  **MIXED DEPLOYMENT — this window spans a deploy; every "
                   "rate below mixes two builds.**")
    if b["turns_without_receipt"]:
        out.append(f"  turns with NO receipt: {b['turns_without_receipt']} "
                   f"— {b['blind_surfaces']} (invisible to every audit query; I1)")
    if b["unreadable_receipts"]:
        out.append(f"  unreadable receipts: {b['unreadable_receipts']}")
    if b["flag_values"]:
        out += ["", "  flags as the turns saw them:"]
        for name, values in sorted(b["flag_values"].items()):
            mark = "  ← CHANGED MID-WINDOW" if name in b["mixed_flags"] else ""
            out.append(f"    {name:<26} {values}{mark}")

    out += ["", "## Route", ""] + _bar(m["route"]["lanes"], n)
    if m["route"]["owners"]:
        out += ["", "  owner:"] + _bar(m["route"]["owners"], n, "    ")
    if m["route"]["legacy_reasons"]:
        out += ["", "  legacy_reason:"] + _bar(m["route"]["legacy_reasons"], n, "    ")

    t = m["tools"]
    out += ["", "## Tools", "",
            f"  turns firing a tool: {t['turns_with_tools']}/{n} · "
            f"log turns: {t['log_turns']} · tool errors: "
            f"{t['turns_with_tool_error']}", ""]
    out += _bar(t["histogram"], n) or ["  (no tools fired)"]

    j = m["join"]
    out += ["", "## Turn ⋈ operation", "",
            f"  joined                {j['turns_joined']}",
            f"  joined, no operations {j['turns_joined_empty']} "
            f"(includes chat turns, which correctly write nothing)",
            f"  UNJOINABLE (no id)    {j['turns_unjoinable']}",
            f"  operations            {j['operations']} "
            f"({j['operations_with_turn_id']} carry a turn_id, "
            f"{j['orphan_operations']} join no turn in this window)"]
    if j["orphan_operations"]:
        out += [f"    …of a turn outside the window  "
                f"{j['orphans_joining_a_turn_outside_the_window']} "
                f"(boundary, not a defect)",
                f"    …of NO turn that has ever existed  "
                f"{j['orphans_joining_no_turn_at_all']}  {j['orphan_sources']}"]
    if j["wrote_nothing_turns"]:
        out.append(f"  **WROTE NOTHING**     turns {j['wrote_nothing_turns']} "
                   f"— a write was attempted or claimed, the turn joins, the "
                   f"join is empty, and nothing errored")
    if j["wrote_nothing_after_tool_error"]:
        out.append(f"  empty after an error  turns "
                   f"{j['wrote_nothing_after_tool_error']} (the tool failed "
                   f"and said so — a different defect)")
    if j["narrated_without_tool_turns"]:
        out.append(f"  narrated, no tool     turns "
                   f"{j['narrated_without_tool_turns']}")

    if m["duplicate_operations"]:
        out += ["", "## Duplicate operations", ""]
        for d in m["duplicate_operations"]:
            if d["same_turn_id"] and d["turn_id_joins"]:
                whose = "SAME turn — two writers on one path"
            elif d["same_turn_id"]:
                whose = (f"same turn_id ({d['turn_ids'][0]}) but it joins NO "
                         f"turn — the id is fabricated, so these may be two "
                         f"separate edits collapsed into one identity")
            else:
                whose = "different turns"
            out.append(
                f"  {d['domain']} entry {d['entry_id']} {d['event_type']} ×2 "
                f"in {d['gap_seconds']:.0f}s · sources {d['sources']} · {whose}")

    if m["quick_corrections"]:
        out += ["", "## Corrections within 15 min of a log", ""]
        for c in m["quick_corrections"]:
            out.append(f"  turn {c['log_turn']} → {c['correction_turn']} "
                       f"after {c['gap_seconds']:.0f}s ({','.join(c['tools'])})")

    if m["health_flags"]:
        out += ["", "## Health flags", ""] + _bar(m["health_flags"], n)
    if m["feedback"]:
        out += ["", f"## Feedback  {m['feedback']}"]

    lat = m["latency_ms"]
    if lat["n"]:
        out += ["", f"## Latency  p50 {lat['p50']}ms · p95 {lat['p95']}ms · "
                    f"max {lat['max']}ms  (n={lat['n']})"]

    out += ["", "## Shape", "",
            f"  platform     {m['by_platform']}",
            f"  source_type  {m['by_source_type']}"]
    if m["superseded_turns"]:
        out.append(f"  superseded   {m['superseded_turns']} (regenerated)")
    return "\n".join(out)


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_turns(parsed: list[dict], width: int) -> str:
    """The turns themselves, one block each — the part that is actually read."""
    out = ["", "=" * 78, "PER-TURN PARSE", "=" * 78]
    for p in parsed:
        stamp = p["timestamp"].strftime("%m-%d %H:%M:%S") if p["timestamp"] else "?"
        r = p["receipt"]
        lane = r.get("lane") or "—"
        if r.get("legacy_reason"):
            lane += f"/{r['legacy_reason']}"
        if r.get("owner"):
            lane += f" owner={r['owner']}"
        marks = []
        if p["wrote_nothing"]:
            marks.append("WROTE-NOTHING-AFTER-ERROR"
                         if p["wrote_nothing_explained_by_error"]
                         else "WROTE-NOTHING")
        if p["join"] == "unjoinable":
            marks.append("unjoinable")
        if p["tool_errors"]:
            marks.append("tool-error:" + ",".join(p["tool_errors"]))
        if p["health_flags"]:
            marks.append("flags:" + ",".join(p["health_flags"]))
        if p["feedback"]:
            marks.append(f"thumbs-{p['feedback']}")
        if p["superseded"]:
            marks.append("superseded")

        out += ["",
                f"#{p['id']} {stamp}  {p['platform']}/{p['source_type']}  "
                f"user={p['user_id']}  build={r.get('sha') or '—'}",
                f"   route  {lane}",
                f"   tools  {','.join(p['tools']) or '—'}"
                + (f"   {' · '.join(marks)}" if marks else ""),
                f"   USER   {_clip(p['raw_message'], width)}",
                f"   ARNIE  {_clip(p['response'], width)}"]
        if p["operations"]:
            for o in p["operations"]:
                out.append(f"   WROTE  {o['event_type']} {o['domain']} "
                           f"entry={o['entry_id']} src={o['source']}")
        elif p["mutating_tools"]:
            out.append(f"   WROTE  — nothing joined "
                       f"({'unjoinable: no turn_id' if p['join'] == 'unjoinable' else 'join empty'})")
    return "\n".join(out)


# ── entry point ──────────────────────────────────────────────────────────────

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Parse every user turn in a recent window (read-only).")
    ap.add_argument("--hours", type=float, default=6.0,
                    help="window size, default 6")
    ap.add_argument("--until", default=None,
                    help="ISO end of window (default: now UTC)")
    ap.add_argument("--user", type=int, default=None, help="one user id only")
    ap.add_argument("--rollup", action="store_true",
                    help="aggregates only — no message bodies printed")
    ap.add_argument("--width", type=int, default=200,
                    help="per-turn body clip width")
    ap.add_argument("--json", dest="json_out", default=None,
                    help="write the snapshot here (redacted; no message text)")
    args = ap.parse_args(argv)

    until = (datetime.fromisoformat(args.until) if args.until
             else datetime.now(timezone.utc).replace(tzinfo=None))
    since = until - timedelta(hours=args.hours)

    cur, close, backend = connect(resolve_database_url())
    try:
        window = load_window(cur, since, until, args.user)
        turns, mirrored = dedupe_mirrored(window["turns"])
        in_window_ids = {t["turn_id"] for t in turns if t["turn_id"]}
        elsewhere = turn_ids_existing_anywhere(
            cur, {e.get("turn_id") for e in window["events"]} - in_window_ids)
    finally:
        close()

    events_by_turn: dict[str, list[dict]] = defaultdict(list)
    for e in window["events"]:
        if e.get("turn_id"):
            events_by_turn[e["turn_id"]].append(e)

    parsed = [parse_turn(t, events_by_turn) for t in turns]
    metrics = rollup(parsed, window["events"], since, until, mirrored,
                     elsewhere)

    print(f"# source: {backend}", file=sys.stderr)
    print(render_rollup(metrics))
    if not args.rollup and parsed:
        print(render_turns(parsed, args.width))

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**metrics, "turns_detail": redact(parsed)},
                                   indent=2, default=str))
        print(f"\nsnapshot: {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
