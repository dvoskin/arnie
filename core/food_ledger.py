"""Food ledger transaction layer (Danny 2026-07-24).

Food logging is a LEDGER with an LLM interface, not a chatbot that happens to
call food tools. This module is the deterministic half of that contract — the
parts that must never depend on a model being right:

  • policy engine     — the SYSTEM decides whether reported ambiguity blocks a
                        write (the model reports uncertainty, it does not get
                        to decide that uncertainty is acceptable)
  • idempotency       — duplicate delivery of the same message+plan (client
                        retry, double webhook, cross-device race) returns the
                        prior outcome instead of writing a second meal
  • pending expiry    — a stale confirm ("yes" hours later) or ancient clarify
                        must never bind a fresh turn
  • snapshot          — ONE committed result object; card and narration both
                        read from it, so they cannot diverge
  • renderer          — narration is composed from committed numbers; the
                        interpreter's words are used only when they carry no
                        unbacked numeric or semantic claims

Layering: core/food_turn (the interpreter) imports this module; this module
imports neither food_turn nor conversation. Everything here is pure logic —
no model calls, no DB session.

The in-process idempotency registry here is the fast path; the DURABLE half
lives in the database (processed_turns claim via db.queries.claim_processed_turn,
ledger_events history via record_ledger_event) — both shipped 2026-07-24.
Calibration and the full policy inversion are the next growth steps
(docs/FOOD_LEDGER_V2.md).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

# Versions ride telemetry on every structured turn (fix: "version everything").
# Bump when the contract meaningfully changes so regressions are traceable.
INTERPRETER_VERSION = "food_interpreter_v2"
POLICY_VERSION = "food_policy_v1"
RENDERER_VERSION = "food_renderer_v1"

# ── policy engine ─────────────────────────────────────────────────────────────
# The ask thresholds live HERE, not in the model's head: the interpreter
# reports ambiguities with estimated calorie impact; this code decides whether
# any of them is worth holding the write for. (First step of inverting
# "model decides" → "system decides"; the prompt keeps a mirror of the
# threshold only as guidance for what to report.)
#: Derived, never declared. This was a fourth copy of the same decision, and a
#: copy is a place for the numbers to disagree.
def _ask_thresholds() -> dict:
    from skills.nutrition.materiality import calorie_threshold
    return {m: calorie_threshold(m) for m in ("quick", "moderate", "strict")}


ASK_THRESHOLDS = _ask_thresholds()


def material_ambiguities(ambiguities, mode: str) -> list:
    """The subset of reported ambiguities whose estimated impact crosses the
    mode's threshold — the ones the policy engine holds a write for."""
    thresh = ASK_THRESHOLDS.get(mode, ASK_THRESHOLDS["moderate"])
    out = []
    for a in ambiguities if isinstance(ambiguities, list) else []:
        if not isinstance(a, dict):
            continue
        try:
            impact = float(a.get("impact_cal") or 0)
        except (TypeError, ValueError):
            impact = 0.0
        if impact >= thresh:
            out.append(a)
    return out


_AMB_QUESTIONS = {
    "quantity": "roughly how much?",
    "identity": "which one exactly?",
    "brand": "which brand or flavor?",
    "prep": "how was it made?",
    "consumed": "did you actually eat it?",
}


def ambiguity_points(ambiguities: list) -> list:
    """Convert material ambiguities into the ask formatter's points shape —
    the system-generated question when policy overrules a write."""
    pts = []
    for a in ambiguities[:3]:
        label = str(a.get("item") or "").strip()
        q = _AMB_QUESTIONS.get(str(a.get("field") or "").lower().strip(),
                               "can you pin that down?")
        pts.append({"label": label, "q": q})
    return pts


# ── pending-state expiry ──────────────────────────────────────────────────────
def _confirm_ttl_min() -> int:
    return int(os.getenv("FOOD_CONFIRM_TTL_MIN", "20"))


def _ask_ttl_min() -> int:
    return int(os.getenv("FOOD_ASK_TTL_MIN", "240"))


def pending_expired(pq, kind: Optional[str] = None, now: Optional[datetime] = None) -> bool:
    """A confirm pending goes stale fast (a bare 'yes' twenty minutes later is
    probably about something else); a clarify pending survives until the day
    AFTER the meal it is about, so a question asked before midnight can still be
    answered the next morning and land on the right day.

    The clarify window keys on the logical meal date stashed in the pending
    payload (`log_date`), NOT on elapsed minutes. "Which bar was it?" asked at
    23:50 and answered at 07:30 is ~8 hours old but still a live answer about
    yesterday's meal. The old flat 240-minute TTL retired it overnight, so the
    answer arrived cold and was re-logged onto TODAY — the wrong-day write this
    now prevents. Falls back to the flat minute TTL when no meal date travelled
    with the row (older rows, non-food pendings)."""
    asked = getattr(pq, "last_asked_at", None) or getattr(pq, "asked_at", None)
    _kind = (kind or "").strip()
    _now = now or datetime.utcnow()

    # Clarify: prefer the stashed logical meal date. Stay open through the whole
    # meal day and the day after; retire only once we are past that.
    if _kind != "confirm":
        try:
            import json as _json
            from datetime import date as _date
            _payload = _json.loads(getattr(pq, "payload_json", "") or "{}")
            _ld = (_payload.get("log_date") or "").strip()
            if _ld:
                return _now.date() > _date.fromisoformat(_ld) + timedelta(days=1)
        except Exception:
            pass

    if asked is None:
        return False
    ttl = _confirm_ttl_min() if _kind == "confirm" else _ask_ttl_min()
    try:
        return (_now - asked) > timedelta(minutes=ttl)
    except Exception:
        return False


# ── idempotency ───────────────────────────────────────────────────────────────
_SEEN: "OrderedDict[str, float]" = OrderedDict()
_SEEN_MAX = 256


def _idem_ttl_sec() -> float:
    return float(os.getenv("FOOD_IDEM_TTL_SEC", "90"))


def turn_idempotency_key(user_id, message: str, tool_calls: list) -> str:
    """Stable key for one (user, message, plan) — the same key means the same
    turn arrived again, not a new report."""
    fingerprint = []
    for tc in tool_calls or []:
        inp = tc.get("input") or {}
        fingerprint.append([
            str(tc.get("name") or ""),
            str(inp.get("food_name") or inp.get("entry_id") or ""),
            str(inp.get("quantity") or ""),
        ])
    raw = json.dumps([str(user_id), (message or "").strip().lower(), fingerprint])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def already_processed(key: str) -> bool:
    now = time.monotonic()
    ts = _SEEN.get(key)
    return ts is not None and (now - ts) < _idem_ttl_sec()


def mark_processed(key: str) -> None:
    _SEEN[key] = time.monotonic()
    _SEEN.move_to_end(key)
    while len(_SEEN) > _SEEN_MAX:
        _SEEN.popitem(last=False)


# ── committed snapshot ────────────────────────────────────────────────────────
@dataclass(frozen=True)
class TransactionSnapshot:
    """The immutable committed result of one structured food turn. Narration
    (and, as the wiring grows, the card) reads ONLY from this — the numbers
    are the post-enrichment database state, never a model's claim."""
    batch_cal: int = 0
    batch_protein: int = 0
    day_cal: int = 0
    day_protein: int = 0
    cal_target: int = 0
    protein_target: int = 0
    logged: tuple = ()
    updated: tuple = ()
    deleted: tuple = ()

    @property
    def cal_left(self) -> int:
        return max(0, self.cal_target - self.day_cal)

    @property
    def protein_left(self) -> int:
        return max(0, self.protein_target - self.day_protein)

    def token_values(self) -> dict:
        return {
            "batch_cal": self.batch_cal, "batch_protein": self.batch_protein,
            "day_cal": self.day_cal, "day_protein": self.day_protein,
            "cal_left": self.cal_left, "protein_left": self.protein_left,
        }


# ── executor-result awareness ─────────────────────────────────────────────────
# The executor stamps each call's outcome onto its input (_result). Narration
# must read it: a refused CAS update or dedup-blocked write narrated as success
# is a lie with committed-looking numbers.
FAILURE_PREFIXES = (
    "Error:", "Skipped", "Failed to", "STALE BOARD", "COULD NOT FIND",
    "No food entry", "No exercise entry", "Missing entry_id",
    "Nothing to restore", "Already on the board",
)

#: Prefix → what to actually TELL the user, in their terms.
#:
#: Every blocked call used to be narrated as "the board changed under me",
#: which is the explanation for exactly ONE of these prefixes. In the
#: 2026-07-25 transcript a Barebells bar the user had just confirmed came back
#: as "Couldn't touch the Barebells Salty Peanut Protein Bar - the board
#: changed under me" — and STALE BOARD is only ever emitted by
#: update_food_entry's compare-and-swap, so whatever actually stopped that log
#: was not a concurrent edit. The user was handed a cause that could not apply,
#: which is a worse failure than saying nothing: it sends them to re-read a
#: board that was never the problem.
#:
#: Lives beside FAILURE_PREFIXES on purpose. A prefix added in one place and
#: explained in another drifts, and the fallback quietly absorbs the drift.
FAILURE_REASONS = (
    ("STALE BOARD", "it changed while I was writing"),
    ("Already on the board", "it was already logged"),
    ("COULD NOT FIND", "I couldn't find it"),
    ("No food entry", "I couldn't find that entry"),
    ("No exercise entry", "I couldn't find that exercise"),
    ("Nothing to restore", "there was nothing to restore"),
    ("Missing entry_id", "I lost track of which entry you meant"),
)

#: When the prefix carries no specific cause ("Error:", "Skipped", "Failed
#: to"). Says that it did not save and nothing more — inventing a reason is
#: how the stale-board line came to be attached to unrelated failures.
GENERIC_FAILURE_REASON = "it didn't save"


def failure_reason(result_text: str) -> str:
    """The honest clause for one blocked call's result text."""
    text = result_text or ""
    for prefix, reason in FAILURE_REASONS:
        if text.startswith(prefix):
            return reason
    return GENERIC_FAILURE_REASON


def _call_failed(tc: dict) -> bool:
    """Legacy shim: judge a call by its shared result text. Kept only for
    tests that build tool-call dicts by hand — production reads the typed
    ExecutionResult, which carries per-call status natively."""
    r = (tc.get("input") or {}).get("_result")
    return isinstance(r, str) and r.startswith(FAILURE_PREFIXES)


def successful_calls(tool_calls: list) -> list:
    """Legacy shim (see _call_failed)."""
    return [tc for tc in (tool_calls or []) if not _call_failed(tc)]


def failed_call_names(tool_calls: list) -> list:
    """Legacy shim (see _call_failed)."""
    out = []
    for tc in (tool_calls or []):
        if _call_failed(tc):
            inp = tc.get("input") or {}
            out.append(str(inp.get("food_name") or inp.get("food_hint")
                           or f"entry #{inp.get('entry_id')}").strip())
    return out


def compute_batch(action: str, ok_calls: list,
                  day_delta_cal: int, day_delta_protein: int) -> tuple:
    """{batch_*} semantics per plan kind, computed over SUCCESSFUL writes:
    pure log → the committed day delta (post-enrichment truth) when positive,
    else the log inputs' sum; update/delete → the entries' new absolute values
    (the update inputs); mixed commit → the LOGGED items' inputs only — never
    the day delta, which folds update deltas into numbers the say attributes
    to the named logged items ('Coke logged, 320 cal' for a 140-cal Coke).
    Never negative."""
    def _sum(calls, key):
        return int(sum((tc.get("input") or {}).get(key) or 0 for tc in calls))
    logs = [tc for tc in ok_calls
            if tc.get("name") in ("log_food", "restore_food_entry")]
    ups = [tc for tc in ok_calls if tc.get("name") == "update_food_entry"]
    if action == "log":
        c, p = int(day_delta_cal), int(day_delta_protein)
        if c <= 0 and p <= 0:
            c, p = _sum(logs, "calories"), _sum(logs, "protein")
    elif action in ("update", "delete"):
        # ABSENT IS NOT ZERO, HERE TOO. A correction to WHAT something was
        # omits the macros on purpose — the ladder re-resolves them for the new
        # identity — so summing the inputs reads the gap as nought and the say
        # line states it: "Switched that to 90/10, updated to 0 cal for the
        # beef", over a row that holds 250. The user then has to ask what was
        # zeroed, which is the opposite of a correction landing cleanly.
        #
        # Sum only what carries a number; when none does, the day delta is the
        # post-enrichment truth for what actually changed — the same source the
        # log branch already prefers.
        _priced = [tc for tc in ups
                   if isinstance((tc.get("input") or {}).get("calories"),
                                 (int, float))]
        if _priced:
            c, p = _sum(_priced, "calories"), _sum(_priced, "protein")
        else:
            c, p = int(day_delta_cal), int(day_delta_protein)
    else:
        c, p = _sum(logs, "calories"), _sum(logs, "protein")
    return max(0, c), max(0, p)


def build_snapshot(tool_calls: list, batch_cal: int, batch_protein: int,
                   day_cal: int, day_protein: int,
                   cal_target: int, protein_target: int) -> TransactionSnapshot:
    logged, updated, deleted = [], [], []
    for tc in tool_calls or []:
        inp = tc.get("input") or {}
        name = tc.get("name")
        label = str(inp.get("food_name") or inp.get("food_hint") or "").strip()
        if name in ("log_food", "restore_food_entry") and label:
            logged.append(label)
        elif name == "update_food_entry":
            updated.append(label or f"entry #{inp.get('entry_id')}")
        elif name == "delete_food_entry":
            deleted.append(label or f"entry #{inp.get('entry_id')}")
    return TransactionSnapshot(
        batch_cal=int(batch_cal or 0), batch_protein=int(batch_protein or 0),
        day_cal=int(day_cal or 0), day_protein=int(day_protein or 0),
        cal_target=int(cal_target or 0), protein_target=int(protein_target or 0),
        logged=tuple(logged), updated=tuple(updated), deleted=tuple(deleted))


# ── renderer ──────────────────────────────────────────────────────────────────
_TOKEN_RE = re.compile(
    r"\{(batch_cal|batch_protein|day_cal|cal_left|day_protein|protein_left)\}")

# Database-dependent semantic claims: any of these in interpreter prose means
# the model is characterizing the food/day from numbers it does not own —
# the "Great protein-heavy breakfast" failure the digit contract can't see.
_CLAIM_RE = re.compile(
    r"\b(?:protein[- ](?:heavy|packed|rich)|high[- ]protein|"
    r"low[- ](?:cal(?:orie)?|carb)|"
    r"(?:under|over|near(?:ly)?|almost\s+at|past)\s+(?:your\s+)?"
    r"(?:target|goal|budget)|"
    r"half\s+(?:of\s+)?your|doubled?|tripled|couple\s+hundred|"
    r"plenty\s+of\s+\w+|good\s+source|balanced\s+(?:meal|plate|day)|"
    r"fiber|sodium|sugar[- ](?:free|heavy))\b", re.I)

# Non-blocking follow-ups the renderer may append AFTER a committed write —
# a whitelist, so "a committed write never asks" relaxes into "a committed
# write only asks vetted, optional questions" (blocking clarification stays
# pre-write). Grows deliberately, one vetted key at a time.
_FOLLOW_UPS = {
    "save_as_regular": ("Want me to save that as one of your regulars so next "
                        "time it logs with exact numbers?"),
}


def fill_tokens(say: str, values: dict) -> str:
    """The interpreter writes the WORDS; the system writes the NUMBERS —
    token values come from the committed snapshot, nowhere else."""
    out = _TOKEN_RE.sub(lambda m: str(values.get(m.group(1), "")), say or "")
    # Belt: any token the model invented must never reach the user.
    out = re.sub(r"\{[a-z_]{2,24}\}", "", out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def say_semantically_safe(say: str) -> bool:
    """True when the interpreter's prose makes no database-dependent claim.
    (Digits are policed separately by enforce_say_contract in food_turn.)"""
    stripped = re.sub(r"\{[a-z_]{2,24}\}", "", say or "")
    return not _CLAIM_RE.search(stripped)


def sanitize_note(note: str) -> str:
    """The interpreter's optional forward-looking fragment: no digits, no
    claims, no questions — or it doesn't ship."""
    n = (note or "").strip().replace("~", "")
    n = re.sub(r"\s*[—–]\s*", ", ", n)
    if not n or len(n) > 160 or "?" in n:
        return ""
    if re.search(r"\d", n) or _CLAIM_RE.search(n):
        return ""
    return n


def _join_names(names) -> str:
    names = [str(n).strip() for n in names if str(n or "").strip()][:4]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def _deterministic_line(snap: TransactionSnapshot) -> str:
    """The floor: a complete, correct read composed purely from committed
    numbers. Used whenever the interpreter's prose is missing or unsafe."""
    parts = []
    if snap.logged:
        parts.append(f"{_join_names(snap.logged)} logged, {snap.batch_cal} cal "
                     f"and {snap.batch_protein}g protein.")
    if snap.updated:
        parts.append(f"Updated the {_join_names(snap.updated)}.")
    if snap.deleted:
        parts.append(f"Took the {_join_names(snap.deleted)} off the board.")
    day = (f"You're at {snap.day_cal} with {snap.cal_left} left and "
           f"{snap.protein_left}g protein to go.")
    # TWO BUBBLES, because the canonical voice ends "never one bubble alone
    # after logging food" and this floor was one. It runs when the composer
    # has already failed, which is exactly when a reply that reads like a
    # different product does the most damage — so it is held to the persona's
    # rule rather than exempted from it for being deterministic.
    #
    # What was already here is two ideas: what happened, then where the day
    # stands. They were joined with a space; a ||| is the same sentence pair
    # sent the way a person sends them.
    if not parts:
        return day
    return f"{' '.join(parts)}|||{day}"


def render_committed(say: str, note: str, follow_up: str,
                     snap: TransactionSnapshot) -> str:
    """Compose the user-facing reply for a committed transaction. The
    interpreter's say is used when it is question-free and claim-free (its
    numbers already policed to tokens); otherwise the deterministic line takes
    over, optionally carrying the sanitized note. A whitelisted non-blocking
    follow-up may ride as a second bubble — coaching, never clarification."""
    text = ""
    s = (say or "").strip()
    if s and "?" not in s and say_semantically_safe(s):
        text = fill_tokens(s, snap.token_values())
    if not text.strip():
        text = _deterministic_line(snap)
        n = sanitize_note(note)
        if n:
            text = f"{text} {n}"
    fu = _FOLLOW_UPS.get((follow_up or "").strip())
    if fu and snap.logged:
        text = f"{text}|||{fu}"
    return text.strip()


def build_failure_notice(failures: list) -> str:
    """The sentence the user reads when something did not make it onto the log.

    Groups by reason so two foods lost the same way read as one sentence rather
    than two near-identical ones, and only ever states the reason the call
    actually reported.
    """
    if not failures:
        return ""
    by_reason: dict = {}
    for name, reason in failures:
        if name:
            by_reason.setdefault(reason, []).append(name)
    if not by_reason:
        return ""
    parts = []
    for reason, names in by_reason.items():
        listed = _join_names(names)
        parts.append(f"I couldn't log the {listed} — {reason}")
    notice = "; ".join(parts)
    tail = ("Want me to try again?" if len(failures) == 1
            else "Want me to try those again?")
    return f"{notice[0].upper()}{notice[1:]}. {tail}"


def _join_names(names: list) -> str:
    """"a", "a and b", "a, b and c" — capped so a long batch cannot run away."""
    names = [n for n in names if n][:4]
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return f"{', '.join(names[:-1])} and {names[-1]}"
