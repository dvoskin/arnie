"""ONE GATE DECIDES WHICH LANE OWNS A FOOD TURN.

Until this commit the answer had two owners. `conversation.py` decided whether
the client could render a canonical interaction and passed the verdict into
`try_take_ownership`; `try_take_ownership` separately asked the rollout gate
whether the user was in the cohort. Both answer "is this turn canonical?", so
no single place could be read to find out what the system would do — and a
predicate with two owners drifts.

It had already drifted. `client_capable` was a BOOL meaning "this client can
read the canonical payload at all", which is true of Telegram; the selection
context then read `ID_ADDRESSED if client_capable else LABEL_TEXT` and gave
Telegram — the channel with no chips, where the sentence IS the interface —
`surface=id_addressed`. Two different questions, "capable of anything" and
"capable of ids", collapsed into one bool.

These gates hold the new arrangement: one function, one moment, and nothing
else deciding the same thing somewhere else.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from core.canonical_lane import LaneReason, canonical_food_enabled

CAPABLE = "ios"
LABEL_ONLY = "telegram"
#: Not in the capability table — an old client, or one we have never shipped.
INCAPABLE = "web"


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("B1_QUANTITY_HALT", raising=False)
    monkeypatch.delenv("B1_QUANTITY_ALLOWLIST", raising=False)
    monkeypatch.delenv("B1_QUANTITY_PERCENT", raising=False)


# ── who gets which lane ──────────────────────────────────────────────────────

def test_an_allowlisted_user_on_a_capable_client_is_canonical(monkeypatch):
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "26")
    d = canonical_food_enabled(user_id=26, channel=CAPABLE)
    assert d.canonical and d.reason == LaneReason.CANONICAL
    assert d.cohort == "allowlist"


def test_everyone_else_stays_legacy(monkeypatch):
    """The whole rollout decision in one assertion: canonical development
    continues for the allowlist, and nobody else's food behaviour moves."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "26")
    d = canonical_food_enabled(user_id=999, channel=CAPABLE)
    assert d.legacy and d.reason == LaneReason.NOT_IN_COHORT


def test_the_halt_outranks_the_allowlist(monkeypatch):
    """An allowlist entry that could outrank a kill switch is not a kill
    switch."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "26")
    monkeypatch.setenv("B1_QUANTITY_HALT", "1")
    d = canonical_food_enabled(user_id=26, channel=CAPABLE)
    assert d.legacy and d.reason == LaneReason.HALTED


def test_an_incapable_client_is_excluded_not_downgraded(monkeypatch):
    """A client that cannot read the payload stays WHOLLY legacy. Rendering
    the canonical question as prose for it would keep the sentence parser
    alive inside its own replacement."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "26")
    d = canonical_food_enabled(user_id=26, channel=INCAPABLE)
    assert d.legacy and d.reason == LaneReason.CLIENT_INCAPABLE
    assert d.capability is None


def test_an_anonymous_turn_is_legacy():
    assert canonical_food_enabled(user_id=None,
                                  channel=CAPABLE).reason == LaneReason.NO_USER


def test_the_gate_fails_to_legacy_when_it_throws(monkeypatch):
    """A rollout control may never cost someone a logged meal."""
    import skills.nutrition.quantity_rollout as qr

    monkeypatch.setattr(qr, "cohort_label",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError))
    d = canonical_food_enabled(user_id=26, channel=CAPABLE)
    assert d.legacy and d.reason == LaneReason.GATE_FAILED


# ── the bug that two owners produced ─────────────────────────────────────────

def test_telegram_is_label_text_and_ios_is_id_addressed(monkeypatch):
    """THE LATENT DEFECT THIS REFACTOR FIXED.

    `ID_ADDRESSED if client_capable else LABEL_TEXT` gave Telegram
    `id_addressed`, because `client_capable` means "can read the payload at
    all" and Telegram can. It never reached production data — all eight
    recorded decisions are iOS — but it would have fired on the first Telegram
    B-1 turn after the candidate universe landed.
    """
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "26")
    assert canonical_food_enabled(
        user_id=26, channel=LABEL_ONLY).capability == "label_text"
    assert canonical_food_enabled(
        user_id=26, channel=CAPABLE).capability == "id_addressed"


def test_a_capable_channel_that_is_not_id_addressed_is_still_canonical(
        monkeypatch):
    """Telegram is canonical-eligible. "Cannot answer by id" is not "cannot
    participate" — it answers by the exact offered label instead."""
    monkeypatch.setenv("B1_QUANTITY_ALLOWLIST", "26")
    assert canonical_food_enabled(user_id=26, channel=LABEL_ONLY).canonical


# ── the ratchet: nothing else may decide the lane ───────────────────────────

#: The modules allowed to name the rollout primitives. Everything else must
#: ask `canonical_food_enabled`, which is the entire point of it existing.
_LANE_PRIMITIVES = ("may_take_ownership", "client_renders_interactions")
_MAY_NAME_THEM = {
    "skills/nutrition/quantity_rollout.py",   # defines may_take_ownership
    "core/canonical_lane.py",                 # the one gate
    "core/b1_quantity_operation.py",          # defines client_renders_interactions
    "api/diagnostics.py",                     # publishes state, decides nothing
}


def _source_files():
    root = pathlib.Path(__file__).resolve().parent.parent
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith(("tests/", ".venv/", "alembic/", "scripts/")):
            continue
        yield rel, path


def test_no_second_module_decides_lane_ownership():
    """A ratchet, not a style rule.

    The two-owner problem is not that the old code was ugly — it is that
    `conversation.py` and `try_take_ownership` could disagree, and the only
    durable fix is that there is nowhere else to ask. If a module needs to
    know which lane owns a turn, it calls the gate.
    """
    offenders = []
    for rel, path in _source_files():
        if rel in _MAY_NAME_THEM:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in _LANE_PRIMITIVES:
            if name in text:
                offenders.append(f"{rel} names {name}")
    assert not offenders, (
        "these decide lane ownership outside the one gate: "
        + "; ".join(offenders)
        + " — call core.canonical_lane.canonical_food_enabled instead")


def test_the_ownership_entry_point_asks_the_gate_and_asks_it_once():
    """`try_take_ownership` must consult the gate exactly once.

    Asked twice it is two decisions; asked zero times the signature lies. The
    cohort check used to live here as well as in the caller, and this is what
    keeps it from coming back.
    """
    from core import b1_quantity_operation as b1

    tree = ast.parse(inspect.getsource(b1.try_take_ownership))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "canonical_food_enabled"]
    assert len(calls) == 1, f"{len(calls)} calls to the lane gate, want 1"


def test_the_gate_is_asked_before_any_material_is_examined():
    """ORDER IS THE CONTRACT. Nothing about the user's food may be looked at
    before we know whose lane this is — examining material first is how a
    legacy user's turn ends up half-processed by canonical code."""
    from core import b1_quantity_operation as b1

    src = inspect.getsource(b1.try_take_ownership)
    assert src.index("canonical_food_enabled(") < src.index("is_eligible("), (
        "the material predicate runs before the lane gate")


def test_lane_reasons_are_closed():
    """Pinned so a new reason is a deliberate addition — these are grouped by
    in dashboards, and a silently added value splits a series in two."""
    reasons = {v for k, v in vars(LaneReason).items()
               if not k.startswith("_") and isinstance(v, str)}
    assert reasons == {"canonical", "no_user", "halted", "not_in_cohort",
                       "client_incapable", "gate_failed"}
