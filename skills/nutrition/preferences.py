"""User-specific resolution memory and correction learning (directive 14, 15).

Two halves of the same idea: stop asking a question that has been answered, and
stop making a mistake that has been corrected.

**Preferences.** After the third consistent answer, "my Fairlife" should resolve
to Core Power Elite 14 oz without asking. The guard is that a preference is
never created from ONE occurrence — a single answer is a fact about one bottle,
not a standing default, and promoting on first sight makes the system
confidently wrong for everyone who drank something unusual once.

The promotion rule:

    3 consistent confirmations, and no contradiction in the recent window

A contradiction does not merely decrement. It DEMOTES: the standing default was
wrong at least once, and continuing to apply it silently is worse than asking
again. Confirmations are kept so a re-promotion is fast, but the default stops
applying immediately.

Strict mode still confirms a promoted preference for the first few uses, because
strict users have opted into being asked and a learned default is still an
assumption.

**Corrections.** A correction currently fixes the entry and the signal is
discarded. Keeping it — with the candidate ranking as it stood — is what turns
"the resolver keeps picking the wrong bagel" from an anecdote into a query, and
what lets alias maps and scoring improve from evidence.

Neither half stores nutrition. A cached number goes stale when a product is
reformulated; a cached identity does not.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

#: Consistent answers required before a preference applies on its own.
PROMOTION_CONFIRMATIONS = 3

#: A contradiction inside this window blocks the default outright. Beyond it,
#: an old disagreement should not hold a good default hostage forever.
CONTRADICTION_WINDOW = timedelta(days=45)

#: How many times strict mode confirms an already-promoted preference. A learned
#: default is still an assumption, and strict users opted into being asked.
STRICT_CONFIRMATIONS = 2

PREFERENCE_VERSION = "user_food_pref_v1"

#: Phrases that mark a possessive reference — the shape a learned default is
#: most useful for. "my usual bagel", "the usual", "my shake".
_POSSESSIVE = re.compile(r"\b(?:my|our|the)\s+(?:usual\s+)?|\busual\b", re.I)

_NOISE = {"a", "an", "the", "some", "of", "my", "our", "please", "one"}


def normalize_term(text: str) -> str:
    """The key a preference is stored under.

    Deliberately lossy: "my Fairlife", "a fairlife", "Fairlife" all collapse, so
    a default learned from one phrasing applies to the others. Quantities are
    stripped — "2 Fairlifes" is the same product as one.
    """
    t = (text or "").lower()
    t = re.sub(r"\b\d+(?:\.\d+)?\s*(?:g|kg|oz|ml|l|cups?|bottles?|cans?|"
               r"servings?|slices?|scoops?)?\b", " ", t)
    words = [w for w in re.findall(r"[a-z']+", t) if w not in _NOISE]
    return " ".join(words).strip()


def is_possessive_reference(text: str) -> bool:
    """Whether the phrasing suggests a standing personal default rather than a
    one-off. Not required for learning, but it is the strongest signal."""
    return bool(_POSSESSIVE.search(text or ""))


@dataclass(frozen=True)
class UserFoodPreference:
    """A learned default. `promoted_at` is the gate — an unpromoted row is
    evidence being gathered, not a default in force."""
    trigger_term: str
    canonical_name: Optional[str] = None
    brand: Optional[str] = None
    product_line: Optional[str] = None
    variant: Optional[str] = None
    package_amount: Optional[float] = None
    package_unit: Optional[str] = None
    default_consumed_fraction: Optional[float] = None
    default_unit_mass_g: Optional[float] = None
    confirmations: int = 0
    contradictions: int = 0
    confidence: float = 0.0
    promoted_at: Optional[datetime] = None
    last_confirmed_at: Optional[datetime] = None
    last_contradicted_at: Optional[datetime] = None

    @property
    def is_promoted(self) -> bool:
        return self.promoted_at is not None

    def identity_fields(self) -> dict:
        """The fields this preference can fill on a FoodIdentity."""
        out = {}
        for name in ("canonical_name", "brand", "product_line", "variant"):
            value = getattr(self, name)
            if value:
                out[name] = value
        return out

    def quantity_fields(self) -> dict:
        out = {}
        if self.default_consumed_fraction is not None:
            out["consumed_fraction"] = self.default_consumed_fraction
        return out

    def blocked_by_contradiction(self, now: datetime) -> bool:
        """A recent contradiction stops the default applying.

        Not a decrement — a demotion. The standing default was wrong at least
        once, and continuing to apply it silently is worse than asking again.
        """
        if self.last_contradicted_at is None:
            return False
        return (now - self.last_contradicted_at) <= CONTRADICTION_WINDOW

    def applies(self, now: datetime, mode: str = "moderate") -> bool:
        """Whether this default may be used WITHOUT asking."""
        if not self.is_promoted or self.blocked_by_contradiction(now):
            return False
        if (mode or "").lower() == "strict":
            # Strict confirms a learned default for its first few uses.
            return self.confirmations >= (PROMOTION_CONFIRMATIONS
                                          + STRICT_CONFIRMATIONS)
        return True

    def describe(self) -> str:
        parts = [p for p in (self.brand, self.product_line, self.variant) if p]
        if self.package_amount and self.package_unit:
            parts.append(f"{_trim(self.package_amount)} {self.package_unit}")
        return " ".join(parts) or (self.canonical_name or self.trigger_term)


# ── promotion ─────────────────────────────────────────────────────────────────
def confirm(pref: UserFoodPreference, now: datetime,
            *, matches: bool = True) -> UserFoodPreference:
    """Record one more consistent answer, promoting when the rule is met.

    `matches=False` is a contradiction: the user answered differently from the
    stored default. It demotes rather than decrementing, because a default that
    has been wrong once should stop applying now, not after it has been wrong
    three times.
    """
    from dataclasses import replace
    if not matches:
        return replace(pref, contradictions=pref.contradictions + 1,
                       last_contradicted_at=now, promoted_at=None,
                       confidence=round(max(0.0, pref.confidence - 0.35), 3))
    confirmations = pref.confirmations + 1
    promoted = pref.promoted_at
    if promoted is None and confirmations >= PROMOTION_CONFIRMATIONS:
        # Only promote if no recent contradiction — three confirmations after a
        # disagreement last week is not yet a settled default.
        if not pref.blocked_by_contradiction(now):
            promoted = now
    return replace(
        pref, confirmations=confirmations, last_confirmed_at=now,
        promoted_at=promoted,
        confidence=round(min(0.98, 0.3 + 0.2 * confirmations), 3))


def observe_answer(existing: Optional[UserFoodPreference], *, term: str,
                   now: datetime, identity: Mapping[str, Any] = None,
                   consumed_fraction: Optional[float] = None
                   ) -> UserFoodPreference:
    """Fold one answered clarification into the preference for this phrase.

    A brand-new phrase starts at one confirmation and unpromoted — which is the
    whole guard. It takes two more consistent answers before it changes anything
    the user sees.
    """
    identity = dict(identity or {})
    term = normalize_term(term)
    if existing is None:
        fresh = UserFoodPreference(
            trigger_term=term,
            canonical_name=identity.get("canonical_name"),
            brand=identity.get("brand"),
            product_line=identity.get("product_line"),
            variant=identity.get("variant"),
            package_amount=identity.get("package_amount"),
            package_unit=identity.get("package_unit"),
            default_consumed_fraction=consumed_fraction)
        return confirm(fresh, now)

    return confirm(existing, now, matches=_same_identity(existing, identity))


def _same_identity(pref: UserFoodPreference, identity: Mapping[str, Any]) -> bool:
    """Whether an answer agrees with the stored default.

    Only fields the ANSWER supplied are compared — an answer that named the
    product line without the size neither confirms nor contradicts the size, and
    treating a silence as a contradiction would demote a good default for being
    incompletely restated.
    """
    for name in ("canonical_name", "brand", "product_line", "variant"):
        answered = identity.get(name)
        if not answered:
            continue
        stored = getattr(pref, name)
        if stored and normalize_term(str(stored)) != normalize_term(str(answered)):
            return False
    return True


def resolve_from_preference(pref: Optional[UserFoodPreference], *,
                            now: datetime, mode: str = "moderate") -> dict:
    """The fields a promoted preference contributes, or {} when it must not
    apply. Returned as data so the caller records it as an ASSUMPTION — a
    learned default is still an assumption, and silently applying it is how a
    user discovers the system has been guessing."""
    if pref is None or not pref.applies(now, mode):
        return {}
    out = dict(pref.identity_fields())
    out.update(pref.quantity_fields())
    return out


# ── corrections ───────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class CorrectionRecord:
    """One correction, with enough context to learn from later."""
    user_id: int
    field_name: str
    chosen_value: Optional[str] = None
    corrected_value: Optional[str] = None
    original_text: str = ""
    ambiguity_type: str = ""
    turn_id: str = ""
    staged_item_id: str = ""
    entry_id: Optional[int] = None
    chosen_candidate_id: Optional[str] = None
    corrected_candidate_id: Optional[str] = None
    candidate_ranking: tuple = ()
    mode: str = ""
    via_alias: Optional[str] = None
    meal_group_id: str = ""
    #: Whether the corrected field was something WE assumed rather than
    #: something the user stated. The correction funnel is meaningless without
    #: it: a correction to an assumption is a failure of the default and is
    #: teachable, while a correction to a stated value is a failure of the
    #: parse and teaches nothing about defaults. Counting them together
    #: produces a number no decision can be made from.
    was_assumed: bool = False

    def ranking_json(self) -> str:
        return json.dumps(list(self.candidate_ranking))

    def log_line(self) -> str:
        return (f"event=food_correction user={self.user_id} "
                f"turn={self.turn_id or '-'} field={self.field_name} "
                f"type={self.ambiguity_type or '-'} "
                f"meal={self.meal_group_id or '-'} "
                f"assumed={str(bool(self.was_assumed)).lower()} "
                f"text={self.original_text!r} "
                f"chose={self.chosen_value!r} meant={self.corrected_value!r} "
                f"alias={self.via_alias or '-'} mode={self.mode or '-'} "
                f"ranked={len(self.candidate_ranking)}")


def build_correction(*, user_id: int, field_name: str, chosen, corrected,
                     item=None, candidates=(), mode: str = "",
                     turn_id: str = "", entry_id=None) -> CorrectionRecord:
    """Capture a correction from the objects that produced it.

    The candidate ranking is snapshotted here rather than referenced, because
    the ranking is a function of the scoring code AT THAT MOMENT — a later
    replay would produce a different order and hide the bug being investigated.
    """
    ranking = [{"candidate_id": getattr(c, "candidate_id", ""),
                "name": getattr(c, "canonical_name", ""),
                "score": round(float(getattr(c, "overall_score", 0.0)), 4),
                "tier": int(getattr(c, "tier", 6)),
                "via_alias": getattr(c, "via_alias", None)}
               for c in (candidates or ())]
    chosen_id = next((r["candidate_id"] for r in ranking
                      if r["name"] == str(chosen)), None)
    corrected_id = next((r["candidate_id"] for r in ranking
                         if r["name"] == str(corrected)), None)
    return CorrectionRecord(
        user_id=user_id, field_name=field_name,
        chosen_value=(None if chosen is None else str(chosen)),
        corrected_value=(None if corrected is None else str(corrected)),
        original_text=getattr(item, "original_text", "") if item else "",
        ambiguity_type=_ambiguity_type_for(item, field_name),
        turn_id=turn_id,
        staged_item_id=getattr(item, "staged_item_id", "") if item else "",
        entry_id=entry_id, chosen_candidate_id=chosen_id,
        corrected_candidate_id=corrected_id,
        candidate_ranking=tuple(ranking), mode=mode,
        meal_group_id=getattr(item, "meal_group_id", "") if item else "",
        was_assumed=_was_assumed(item, field_name),
        via_alias=next((r["via_alias"] for r in ranking
                        if r["candidate_id"] == chosen_id and r["via_alias"]),
                       None))


def _was_assumed(item, field_name: str) -> bool:
    """Whether this field carried an assumption of ours at correction time."""
    return any(getattr(a, "field_name", "") == field_name
               for a in (getattr(item, "assumptions", ()) or ()))


def _ambiguity_type_for(item, field_name: str) -> str:
    for amb in (getattr(item, "ambiguities", ()) or ()):
        if amb.field_name == field_name:
            return getattr(amb.ambiguity_type, "value", str(amb.ambiguity_type))
    return ""


def confused_pairs(corrections, *, min_count: int = 2) -> list:
    """Product pairs this user (or the corpus) keeps mixing up, commonest first.

    This is the actionable output: a pair appearing repeatedly is either an
    alias that needs adding or a scoring weight that is wrong, and it names
    which one to look at rather than leaving it to intuition.
    """
    counts = {}
    for c in corrections or []:
        chosen = (c.chosen_value or "").strip()
        meant = (c.corrected_value or "").strip()
        if not chosen or not meant or chosen == meant:
            continue
        counts[(chosen, meant)] = counts.get((chosen, meant), 0) + 1
    return sorted(((pair, n) for pair, n in counts.items() if n >= min_count),
                  key=lambda kv: -kv[1])


def _trim(n) -> str:
    try:
        f = float(n)
    except (TypeError, ValueError):
        return str(n)
    return str(int(f)) if f == int(f) else f"{f:g}"
