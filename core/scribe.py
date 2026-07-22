"""The scribe — deterministic multi-item completeness, independent of pass-1.

The model (even opus) sometimes emits ONE log_food for a message that names two or
three foods — the egg-whites drop (Chaya 2026-07-21), turkey+rice, the burrito. No
heuristic on the MESSAGE text scales to every food pair. The scribe instead does what
a human scribe does: read the message, list what was ordered, and check every item
made it onto the board.

Flow (wired in core/conversation.run_turn):
  1. cheap gate — only a multi-item food turn that logged FEWER items than it named
     runs the scribe (single foods, fully-logged meals pay nothing).
  2. extract_food_items() — a Haiku call returns the canonical item list, RESPECTING
     groupings (one combined total = one item, so 'lettuce, tomato, onion + mustard,
     20 cal' is NOT split into four).
  3. missing_items() — reconcile the list against what actually logged (token overlap,
     reusing write_set._named_in), returning only the genuinely-unlogged items.
  4. the caller feeds those exact names into the existing self-heal nudge.

Pure + small: the only side effect is one Haiku call, and it's skipped unless a drop
is already plausible. Kill switch: SCRIBE_ENABLED=false.
"""
from __future__ import annotations

import os
import re
from typing import List

from core.llm import chat
from core.write_set import _named_in, _tokens

# Extraction model. Tested Haiku vs Sonnet (2026-07-21) on the composite/distinct
# set: with the tightened prompt below they're EQUIVALENT (both keep a poke bowl
# whole, both split a per-portioned bowl, both catch distinct drops), so Haiku is
# the default — 10x cheaper and faster for the same result, and it runs in
# PARALLEL with pass-1 so it's off the latency path anyway. Set SCRIBE_MODEL=
# claude-sonnet-5 to upgrade if a future ambiguous case ever needs it.
def _scribe_model() -> str:
    return os.getenv("SCRIBE_MODEL", "claude-haiku-4-5-20251001")


# Cheap multi-item signal — a conjunction/separator between plausible foods. Broad on
# purpose: it only DECIDES WHETHER TO LOOK; the extraction is the precise part.
_MULTI_SEP_RE = re.compile(r",|;|\n|\+|\band\b|\bplus\b|\bwith\b|\balso\b|\bи\b|\bс\b|\bплюс\b",
                           re.IGNORECASE)
# Pure ack / lookup-question — no consumed food to extract, so the scribe skips it.
_ACK_RE = re.compile(
    r"^(ok(ay)?|k+|thx|thanks|thank\s+you|ty|cool|nice|great|sweet|got\s+it|gotcha|"
    r"yes|yeah|yep|yup|sure|no+|nope|word|bet|perfect|awesome|good|alright|lol|haha)"
    r"[.!,\s]*$", re.I)
_Q_RE = re.compile(
    r"^\s*(how|what|why|when|where|which|who|whose|is|are|am|was|were|do|does|did|"
    r"can|could|should|would|will|has|have)\b|\?", re.I)


def scribe_enabled() -> bool:
    return os.getenv("SCRIBE_ENABLED", "true").lower() in ("true", "1", "yes")


def looks_multi_item(message: str) -> bool:
    """True when the message plausibly names >1 food — worth a completeness check.
    Cheap and broad; false positives cost only the reconcile (no model call unless a
    shortfall is also present)."""
    m = (message or "").strip()
    if len(m) < 6:
        return False
    return bool(_MULTI_SEP_RE.search(m))


def should_run_scribe(message: str) -> bool:
    """Launch the scribe for ANY substantive message that could name food(s) —
    broadened 2026-07-21 from looks_multi_item so a SPACE-separated list ('eggs
    bacon toast', no comma/and) is covered too, making completeness deterministic
    on every food turn rather than only separator-lists. Skips pure acks and
    lookup questions (no consumed food to extract). The scribe runs in PARALLEL
    with pass-1, so a non-food false positive costs only a cancelled call — never
    latency. ≥2 content words = worth a look."""
    m = (message or "").strip()
    if len(m) < 3 or _ACK_RE.match(m) or _Q_RE.search(m):
        return False
    words = re.findall(r"[A-Za-zА-Яа-яЁё'][A-Za-zА-Яа-яЁё']+", m)
    return len(words) >= 2


_EXTRACT_SYSTEM = (
    "You are a meticulous food-logging scribe. List each food/drink the user should "
    "have as its OWN log entry, one per line: '<quantity> | <food name>'. Think about "
    "how a person tracks a meal, not every ingredient. Rules:\n"
    "- A NAMED SINGLE DISH is ONE entry, even when its fillings/toppings/components are "
    "listed WITHOUT their own amounts. This INCLUDES a sandwich, club, burger, wrap, "
    "taco, burrito, roll, sushi roll, omelette, smoothie, shake, parfait, AND ANY "
    "bowl/plate/platter/salad (poke bowl, grain bowl, burrito bowl, Buddha bowl, grain "
    "salad). 'poke bowl with salmon, tuna, rice, edamame, avocado' → ONE line (poke "
    "bowl) — NOT five. 'turkey club with turkey, bacon, cheddar, lettuce, tomato' → ONE "
    "line (turkey club) — NOT six.\n"
    "- SPLIT a bowl/plate into its components ONLY when the user gave EACH component its "
    "OWN explicit amount ('bowl with 5oz chicken, 3/4 cup rice, 1/2 cup beans' → "
    "chicken, rice, beans). No per-component amount = ONE dish, never split it.\n"
    "- SEPARATE FOODS are separate lines: distinct dishes/sides/drinks ('a burger AND "
    "fries AND a coffee' → three), and clearly distinct foods each with their own amount "
    "('175g turkey and 100g rice' → two; '1 egg plus 3/4 cup egg whites' → two).\n"
    "- Several things sharing ONE combined amount/calorie total are ONE line ('lettuce, "
    "tomato, onion and mustard, 20 cal').\n"
    "- Keep the user's wording and brand (Royo bagel, Barebells). Quantity if stated, "
    "else 'some'.\n"
    "- ONLY foods actually consumed. Ignore plans ('gonna have'), questions, chit-chat. "
    "If nothing was consumed, output NOTHING.\n"
    "Output ONLY the lines."
)


async def extract_food_items(message: str) -> List[dict]:
    """Haiku → the canonical list of consumed items as [{'name','quantity','raw'}].
    Empty list on nothing-consumed or any failure (fail-open: the scribe never breaks
    a turn)."""
    try:
        res = await chat(
            messages=[{"role": "user", "content": (message or "").strip()}],
            system=_EXTRACT_SYSTEM, tools=False, max_tokens=200, model=_scribe_model(),
        )
    except Exception:
        return []
    out: List[dict] = []
    for line in (res.get("text") or "").splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if not line or line.startswith("("):
            continue
        if "|" in line:
            qty, _, name = line.partition("|")
            qty, name = qty.strip(), name.strip()
        else:
            qty, name = "", line
        # The model emits NOTHING when there's no consumed food — but it sometimes
        # EXPLAINS instead ("I don't see any foods… please tell me what you ate"),
        # which must NOT be parsed as a food. Reject those + any over-long "name"
        # (a real food name is short; a sentence is a non-answer).
        low = name.lower()
        if (not name or low in ("nothing", "none")
                or "nothing to" in low or "not consumed" in low
                or "don't see" in low or "do not see" in low or "dont see" in low
                or "please tell" in low or "tell me" in low or "no food" in low
                or "no drink" in low or "didn't mention" in low
                or "did not mention" in low or "let me know" in low
                or low.startswith(("if you", "if there", "i don't", "i do not",
                                   "i'll log", "i can log", "there's no", "there is no",
                                   "no specific", "it looks like", "you haven't"))
                or len(name) > 90):
            continue
        out.append({"name": name, "quantity": qty, "raw": line})
    return out


def _covered_by(name: str, logged_names: List[str]) -> bool:
    """True when SOME logged entry covers EVERY content token of `name` (prefix-
    tolerant). Stricter than write_set._named_in on purpose: for the reconcile we ask
    'is this whole item logged?', so 'egg whites' must NOT count as covered by a plain
    'egg (whole)' — the shared 'egg' token isn't enough; 'whites' must be present too."""
    nt = _tokens(name)
    if not nt:
        return True  # vacuous (units-only) — never a drop
    for ln in logged_names:
        lt = _tokens(ln)
        if lt and all(any(t == l or t.startswith(l) or l.startswith(t) for l in lt)
                      for t in nt):
            return True
    return False


def missing_items(extracted: List[dict], logged_names: List[str]) -> List[dict]:
    """The extracted items with NO logged entry covering all their tokens — the genuine
    drops. 'egg whites' stays missing when only 'Egg (whole)' logged."""
    return [it for it in extracted
            if _tokens(it.get("name") or "")
            and not _covered_by(it.get("name") or "", logged_names)]


_MISSING_STOP = {"with", "and", "the", "of", "a", "in", "on", "plus", "some"}


def distinct_missing_items(extracted: List[dict], logged_names: List[str]) -> List[str]:
    """The missing items that are DISTINCT foods worth an automatic rescue — a
    SHORT name (rice, turkey, sweet potato fries), NOT a composite the scribe
    described with all its fillings ('poke bowl with salmon, tuna, rice, edamame…').

    Why the cap: a composite logs as ONE row, and its scribe-name (full phrasing)
    vs the model's log-name ('Poke bowl (…)') token-mismatch would FALSE-flag it as
    missing → a wasteful/duplicating rescue. A genuine dropped distinct dish has a
    short name, so ≤3 content tokens catches every real drop (turkey, rice, fries)
    while never firing on a composite. Returns bare name strings, drop order."""
    out: List[str] = []
    for it in missing_items(extracted, logged_names):
        nm = (it.get("name") or "").strip()
        if nm and len([t for t in _tokens(nm) if t not in _MISSING_STOP]) <= 3:
            out.append(nm)
    return out
