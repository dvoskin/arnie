"""Entity-bound clarifications (review 2026-07-25, work order step 2).

Two pending shapes exist, and conflating them is what produces answers landing
on the wrong row:

  PLAN CONFIRMATION      "Log these three?" — a yes replays staged operations.
                         Owned by core.turns.stages.deterministic.
  NUTRITION CLARIFICATION "What are the Royo bagel calories and protein?" — the
                         question is about ONE already-identified thing.

This module owns the second. Its defining property: the answer cannot
re-resolve the board target. The pending row binds the entry (or staged item)
at ask time, and the answer applies to THAT entity even if the user's reply
mentions a food name, a quantity, or a different meal entirely. Re-running
identification on an answer turn is how "the label is 80 calories" ends up
rewriting yesterday's bagel.

Two further rules, both about not inventing facts:

  • a value the user states is TIER 1 — ground truth for that entry, marked
    so later enrichment cannot overwrite it;
  • a field the user does NOT state is left alone. Unknown is not zero, and
    zero sodium and unknown sodium are different product facts.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

#: Its own pending kind, so it can never be picked up by the confirm-replay
#: path — which would treat "yes" as approval to log a staged plan.
CLARIFY_KIND = "food_nutrition_clarification"

#: Provenance for a value the user read off a label. The authority tier above
#: every database: we asked, they answered, that is the product.
USER_LABEL_SOURCE = "user_label"

CLARIFICATION_VERSION = "pending_clarification_v1"


@dataclass(frozen=True)
class BoundTarget:
    """What the question is about. Exactly one of entry_id / staged_item_id is
    meaningful: a committed row, or an item held pre-write."""
    entry_id: Optional[int] = None
    staged_item_id: Optional[str] = None
    label: str = ""

    @property
    def is_committed(self) -> bool:
        return self.entry_id is not None


@dataclass(frozen=True)
class NutritionClarification:
    """One open question about one entity's nutrients."""
    target: BoundTarget
    fields: tuple = ()                    # what we asked for, in asking order
    current: Mapping[str, Any] = field(default_factory=dict)
    source: str = ""                      # where `current` came from
    operation: Mapping[str, Any] = field(default_factory=dict)
    turn_id: str = ""
    version: str = CLARIFICATION_VERSION

    def to_payload(self) -> str:
        return json.dumps({
            "kind": "nutrition",
            "version": self.version,
            "target": {"entry_id": self.target.entry_id,
                       "staged_item_id": self.target.staged_item_id,
                       "label": self.target.label},
            "fields": list(self.fields),
            "current": dict(self.current or {}),
            "source": self.source,
            "operation": dict(self.operation or {}),
            "turn_id": self.turn_id,
        })


def from_payload(raw) -> Optional[NutritionClarification]:
    """Parse a stored payload. Returns None for anything that is not a
    nutrition clarification, so a plan confirmation can never be mistaken for
    one."""
    try:
        data = raw if isinstance(raw, dict) else json.loads(raw or "{}")
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("kind") != "nutrition":
        return None
    t = data.get("target") or {}
    if t.get("entry_id") is None and not t.get("staged_item_id"):
        return None                       # unbound: not usable, by definition
    return NutritionClarification(
        target=BoundTarget(entry_id=t.get("entry_id"),
                           staged_item_id=t.get("staged_item_id"),
                           label=str(t.get("label") or "")),
        fields=tuple(data.get("fields") or ()),
        current=dict(data.get("current") or {}),
        source=str(data.get("source") or ""),
        operation=dict(data.get("operation") or {}),
        turn_id=str(data.get("turn_id") or ""),
        version=str(data.get("version") or CLARIFICATION_VERSION))


# ── parsing an answer ─────────────────────────────────────────────────────────
#: Nutrients we accept from a spoken label reading, with the units that make
#: sense for each. Anything else is left to the interpreter.
_FIELD_WORDS = {
    "calories": r"(?:cal(?:orie)?s?|kcal)",
    "protein": r"protein",
    "carbs": r"(?:carb(?:ohydrate)?s?)",
    "fat": r"(?:fats?)",
    "fiber": r"(?:fibre|fiber)",
    "sugar": r"(?:sugars?)",
    "sodium": r"(?:sodium|salt)",
}

_NUM = r"(\d+(?:\.\d+)?)"

# "80 calories" and "calories: 80" / "calories are 80" both occur in speech.
_PATTERNS = {
    fname: (re.compile(rf"{_NUM}\s*(?:g|mg)?\s*(?:of\s+)?{word}\b", re.I),
            re.compile(rf"{word}\b\s*(?:is|are|:|=)?\s*{_NUM}\s*(?:g|mg)?", re.I))
    for fname, word in _FIELD_WORDS.items()
}

#: A refusal is an answer too — it closes the question without writing.
_UNKNOWN_RE = re.compile(
    r"\b(?:i\s+)?(?:don'?t\s+know|no\s+idea|not\s+sure|dunno|no\s+label|"
    r"can'?t\s+tell|unsure|skip\s+it|never\s?mind)\b", re.I)


def answer_is_refusal(text: str) -> bool:
    return bool(_UNKNOWN_RE.search(text or ""))


def parse_nutrient_answer(text: str, fields: tuple = ()) -> dict:
    """Nutrients the user actually stated. Silent about everything else —
    a field absent from the reply stays absent from the result.

    Bare numbers ("80 and 8") are accepted ONLY when the count matches the
    fields we asked for, in asking order. That is the one context where the
    mapping is unambiguous, because we chose the order.
    """
    text = (text or "").strip()
    if not text:
        return {}
    out: dict = {}
    for fname, (after, before) in _PATTERNS.items():
        m = after.search(text) or before.search(text)
        if m:
            try:
                out[fname] = float(m.group(1))
            except (TypeError, ValueError):
                continue
    if out:
        return out
    fields = tuple(f for f in (fields or ()) if f in _FIELD_WORDS)
    if not fields:
        return {}
    bare = re.findall(_NUM, text)
    if len(bare) != len(fields):
        return {}
    for fname, raw in zip(fields, bare):
        try:
            out[fname] = float(raw)
        except (TypeError, ValueError):
            return {}
    return out


# ── turning an answer into operations ─────────────────────────────────────────
def answer_operations(pending: NutritionClarification, text: str) -> Optional[list]:
    """The bound entity's update, or None when the reply carries no values.

    The target comes from the pending row, never from the reply — a reply
    naming a different food is still an answer about the entity we asked
    about. Fields the user did not state are not written.
    """
    if pending is None:
        return None
    values = parse_nutrient_answer(text, pending.fields)
    if not values:
        return None

    if pending.target.is_committed:
        inp = {"entry_id": pending.target.entry_id,
               "source": USER_LABEL_SOURCE,
               # Tier 1: these values are the product. Enrichment must not
               # replace them on this entry.
               "user_label": True}
        # CAS seed: the update is refused if the row moved since we asked.
        expected = (pending.current or {}).get("calories")
        if expected is not None:
            inp["expected_calories"] = expected
        inp.update(values)
        return [{"name": "update_food_entry", "input": inp}]

    # Held item: commit the original operation with the user's numbers.
    op = dict(pending.operation or {})
    if not op.get("name"):
        return None
    inp = dict(op.get("input") or {})
    inp.update(values)
    inp["source"] = USER_LABEL_SOURCE
    inp["user_label"] = True
    return [{"name": op["name"], "input": inp}]


def build_ask(target: BoundTarget, fields: tuple, current: Mapping = None,
              source: str = "", operation: Mapping = None,
              turn_id: str = "") -> NutritionClarification:
    return NutritionClarification(
        target=target, fields=tuple(fields or ()), current=dict(current or {}),
        source=source, operation=dict(operation or {}), turn_id=turn_id)
