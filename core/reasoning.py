"""The reasoning receipt — Arnie's expandable "How I got this" trace.

Assembled DETERMINISTICALLY from what the turn actually did: the context it
read, each tool it fired (humanized from name + input + result), and the
checks that ran. Never model-narrated — a receipt can't hallucinate, which is
the entire point (see the phantom-claim history). Pure functions, no DB.
"""
from typing import Optional


def _shorten(text: str, n: int = 60) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _step(icon: str, label: str, detail: str = "") -> dict:
    out = {"icon": icon, "label": _shorten(label, 70)}
    if detail:
        out["detail"] = _shorten(detail, 90)
    return out


# How each enrichment source reads in the trace: (icon, "found" line) for the
# detailed single-item trace, and a one-word source detail for the condensed
# multi-item line. Keyed by FoodAnalysis.source (see core/food_intelligence).
_SOURCE_LABELS = {
    "history":   ("checkmark.seal", "Found it in your own earlier log"),
    "memory":    ("checkmark.seal", "Found it in your saved foods"),
    # OFF HAD NO ENTRY HERE. `FoodAnalysis.source` has carried "off" since Open
    # Food Facts was added, and an unknown key falls through to the "estimate"
    # row — so a product answered by its OFF label read back as "No exact
    # match — estimated from the description". The lane was working and the
    # receipt was calling it a guess, which is why it looked like OFF never ran.
    "off":       ("barcode", "Found the product in Open Food Facts"),
    "web_label": ("globe", "Found the product label online"),
    "usda":      ("magnifyingglass", "Matched the USDA food database"),
    "estimate":  ("wand.and.stars", "No exact match — estimated from the description"),
}
_SOURCE_DETAIL = {
    "history":   "From your own earlier log",
    "memory":    "From your saved foods",
    "off":       "From the Open Food Facts label",
    "web_label": "From the product label",
    "usda":      "From the USDA database",
    "estimate":  "Best estimate from the description",
}

#: Which lookup lanes ran, in the order they run, for the "what I checked"
#: section of a detailed trace. A receipt that names only the WINNER cannot
#: answer "did you even look?" — and that is the question actually being asked
#: when a named product comes back estimated.
_LANE_LABELS = {
    "usda": ("magnifyingglass", "USDA food database"),
    "off":  ("barcode", "Open Food Facts"),
    "web":  ("globe", "the product label on the web"),
    # Not a lane — the reason no lane ran. A receipt whose lane section is
    # simply absent reads as a pipeline that never fired.
    "lookup": ("arrow.triangle.branch", "Skipped the database lookup"),
}
_LANE_OUTCOMES = {
    "hit": "found a match",
    # FOUND IS NOT USED. A branded index only earns a branded rung on an
    # exact-or-likely name match; a weaker hit is seated nowhere and cannot set
    # the calories. Reporting that as "found a match" above a line that says
    # "Portion estimated" is how a deliberate refusal reads as a broken lane.
    "weak": "match too loose to trust — not used",
    "miss": "no match",
    "skipped": "not a named product — skipped",
}


def _food_line(inp: dict, result: str) -> dict:
    """The CONDENSED one-line food step — used when several foods logged this
    turn (a full trace per item would blow the step budget). Prefers the stashed
    sourcing detail; falls back to sniffing the tool-result string."""
    name = inp.get("food_name") or "food"
    r = result or ""
    if r.startswith("Already on the board:"):
        return _step("checkmark.circle", f"Duplicate check — {name} already logged",
                     "Skipped the re-log; totals unchanged")
    src = inp.get("_sourcing") or {}
    cal = src.get("calories") if src else inp.get("calories")
    # The executor precomputes this from the SPLIT provenance. Preferred over
    # the coarse `source` because that field answered "who filled this row",
    # while the line under an item claims "who determined these calories" —
    # which is how "From the USDA database" appeared beneath numbers whose only
    # USDA contribution was the sodium.
    detail = src.get("detail") or (
        _SOURCE_DETAIL.get(src.get("source")) if src else "")
    if not detail:
        if "usda" in r.lower():
            detail = "Matched against the USDA database"
        elif "label" in r.lower() or "web" in r.lower():
            detail = "Verified against the product label"
    label = f"Logged {name}" + (f" — {round(cal)} cal" if cal else "")
    return _step("plus.circle", label, detail or "")


def _food_detailed(inp: dict, result: str) -> list:
    """The FULL sourcing trace for a single-item log — what Danny asked to see:
    searched → matched source → serving checked → logged totals. Only when the
    executor stashed `_sourcing` (the real enrichment path); otherwise one line.
    A dedup no-op collapses to the duplicate-check line."""
    r = result or ""
    if r.startswith("Already on the board:"):
        return [_food_line(inp, result)]
    src = inp.get("_sourcing") or {}
    if not src:
        return [_food_line(inp, result)]
    name = inp.get("food_name") or "food"
    source = src.get("source") or "estimate"
    icon, found = _SOURCE_LABELS.get(source, _SOURCE_LABELS["estimate"])
    # When a source only supplemented the panel, the "found it" line says what
    # was found — not that the answer came from there.
    _detail = src.get("detail") or ""
    if _detail and _detail != _SOURCE_DETAIL.get(source):
        found = _detail
        if "supplemented" in _detail:
            icon = "wand.and.stars"
    steps = [_step("magnifyingglass", f"Searched for {name}")]
    # EVERY LANE THAT RAN, not just the one that won. "Consistently estimating
    # against USDA, I don't see Open Food Facts or web search" (Danny
    # 2026-07-26) is unanswerable from a trace that reports a single winner: an
    # OFF miss and an OFF that never ran look identical, and both look like
    # nothing happened.
    for lane, outcome in (src.get("lanes") or []):
        label = _LANE_LABELS.get(lane)
        if not label:
            continue
        lane_icon, lane_name = label
        # The skip row carries its own reason verbatim and is not a "Checked".
        prefix = "" if lane == "lookup" else "Checked "
        steps.append(_step(lane_icon, f"{prefix}{lane_name}",
                           _LANE_OUTCOMES.get(outcome, outcome)))
    steps.append(_step(icon, found))
    qty = (src.get("quantity") or "").strip()
    if qty:
        steps.append(_step("ruler", f"Serving checked — {qty}"))
    cal, pro = src.get("calories"), src.get("protein")
    tail = []
    if cal:
        tail.append(f"{cal} cal")
    if pro:
        tail.append(f"{pro}g protein")
    steps.append(_step("plus.circle",
                       f"Logged {name}" + (f" — {', '.join(tail)}" if tail else "")))
    return steps


def _meal_lookup_summary(sourcings: list) -> Optional[dict]:
    """One line covering the lookups a MULTI-ITEM meal ran.

    A composite meal is the case where "did you actually check anything?" is
    hardest to answer and most often asked — and it was the one case that could
    not answer it. The full per-item trace is only affordable when a single food
    is logged, so a four-item restaurant meal rendered four bare `Logged X`
    lines and no lanes at all, which reads exactly like a pipeline that never
    ran. It did run: the same meal's items carry USDA supplementation in their
    own sourcing.

    So the lanes are aggregated instead of dropped. One line, naming each lane
    that ran across the meal and how many items it answered, which is the
    question being asked.
    """
    ran, hit, weak = {}, {}, {}
    for src in sourcings:
        for lane, outcome in (src.get("lanes") or []):
            if lane not in _LANE_LABELS or lane == "lookup":
                continue
            if outcome == "skipped":
                # NOT A CHECK. Counting a skip in the denominator printed
                # "product label 0/2" for a lane that never ran, which reads as
                # "the web has nothing" — the opposite of the truth, and it
                # sent this investigation looking at the lookup instead of the
                # gate that suppressed it.
                continue
            ran[lane] = ran.get(lane, 0) + 1
            if outcome == "hit":
                hit[lane] = hit.get(lane, 0) + 1
            elif outcome == "weak":
                # FOUND, BUT NOT SEATED. Counting this with the misses is the
                # same error the per-item trace was written to avoid: "0/2"
                # reads as "that database has nothing", when what happened is
                # the lane answered and the ladder declined its answer. Those
                # need different fixes and must not look alike.
                weak[lane] = weak.get(lane, 0) + 1
    if not ran:
        return None
    # Short names here, not `_LANE_LABELS`' prose ones. Three lanes written out
    # in full runs past the 70-character step budget and truncates mid-lane —
    # "…, the product …" — which loses the very lane the line exists to report.
    parts, notes = [], []
    for lane, short in (("usda", "USDA"), ("off", "Open Food Facts"),
                        ("web", "product label")):
        if lane not in ran:
            continue
        parts.append(f"{short} {hit.get(lane, 0)}/{ran[lane]}")
        if weak.get(lane):
            notes.append(f"{weak[lane]} {short} match"
                         f"{'es' if weak[lane] > 1 else ''} too loose to use")
    detail = "; ".join(notes) if notes else "matched / checked, across the meal"
    return _step("magnifyingglass", "Looked up " + ", ".join(parts), detail)


def _exercise_step(inp: dict, result: str) -> dict:
    name = inp.get("exercise_name") or "exercise"
    r = result or ""
    if r.startswith("Already on the board:"):
        return _step("checkmark.circle", f"Duplicate check — {name} already logged",
                     "Skipped the re-log")
    sets_, reps = inp.get("sets"), inp.get("reps")
    scheme = f" — {sets_}×{reps}" if sets_ and reps else ""
    return _step("figure.strengthtraining.traditional", f"Logged {name}{scheme}")


def _correction_step(inp: dict, result: str):
    """What a correction actually changed — read from the call, not asserted.

    This was the fixed string "Macros rescaled to the new serving", returned
    whatever the user corrected. On a turn that changed the PRODUCT ("it was
    actually a filled Twizzler") the entry was re-identified and re-looked-up,
    and the receipt explained it as a rescale. A made-up reason on the one turn
    where the user is checking our work is worse than no reason.

    When the correction re-resolved the food, the full lookup trace is rendered
    the way a fresh log's is — the executor now carries the sourcing across.
    """
    inp = inp or {}
    renamed = str(inp.get("_reresolved") or "").strip()
    if renamed and inp.get("_sourcing"):
        # An update carries entry_id and the changed fields, not `food_name` —
        # so the shared trace builder would render "Searched for food". The
        # resolved name is what it searched for; give it that.
        steps = _food_detailed({**inp, "food_name": renamed}, result or "")
        head = _step("pencil", f"Re-identified as {renamed}",
                     "Looked it up again from scratch")
        return [head] + steps
    if renamed:
        return _step("pencil", f"Re-identified as {renamed}")
    if any(k in inp for k in ("amount", "quantity", "unit")):
        return _step("pencil", "Corrected the serving",
                     "Macros rescaled to the new amount")
    if any(k in inp for k in ("calories", "protein", "carbs", "fats")):
        return _step("pencil", "Corrected the macros", "Used the numbers you gave")
    if inp.get("date"):
        return _step("calendar", "Moved the entry to another day")
    return _step("pencil", "Corrected a logged food")


_TOOL_STEPS = {
    "log_water": lambda i, r: _step("drop", "Logged water"),
    "log_body_weight": lambda i, r: _step(
        "scalemass", f"Logged weigh-in — {i.get('weight')} {i.get('unit', '')}".strip()),
    "update_food_entry": lambda i, r: _correction_step(i, r),
    "update_exercise_entry": lambda i, r: _step("pencil", "Corrected a logged set"),
    "delete_food_entry": lambda i, r: _step("minus.circle", "Removed a food entry"),
    "delete_exercise_entry": lambda i, r: _step("minus.circle", "Removed a set"),
    "search_food_database": lambda i, r: _step(
        "magnifyingglass", f"Checked the nutrition database — {i.get('query', '')}".strip(" —")),
    "web_search": lambda i, r: _step(
        "globe", f"Searched the web — {_shorten(i.get('query', ''), 40)}".strip(" —")),
    "query_history": lambda i, r: _step("clock.arrow.circlepath", "Read your history"),
    "set_program_day": lambda i, r: _step(
        "calendar", f"Set today's program day — {i.get('day_name', '')}".strip(" —")),
    "set_program_target": lambda i, r: _step("target", "Updated a program target"),
    "add_program_exercise": lambda i, r: _step(
        "plus.circle", f"Added {i.get('exercise_name', 'an exercise')} to your program"),
    "remove_program_exercise": lambda i, r: _step(
        "minus.circle", f"Removed {i.get('exercise_name', 'an exercise')} from your program"),
    "refresh_coach_brief": lambda i, r: _step(
        "arrow.clockwise", "Marked your coach brief for a rewrite",
        "What you said changed its premise"),
    "update_profile": lambda i, r: _step("person", "Updated your profile"),
    "set_macro_targets": lambda i, r: _step("target", "Recalculated your targets"),
    "generate_image": lambda i, r: _step("photo", "Generated an image"),
    "find_nearby_places": lambda i, r: _step("mappin.and.ellipse", "Looked up places near you"),
    "deep_research": lambda i, r: _step("book", "Ran deep research",
                                        "Multiple sources read and compared"),
}


def build_reasoning(tool_calls: list, tool_results: dict,
                    context_stats: Optional[dict] = None,
                    duration_ms: Optional[int] = None,
                    execution=None) -> Optional[dict]:
    """The receipt for one turn, or None when there's nothing worth showing
    (pure-chat turns with no context read and no tools stay clean).

    `execution` is the typed ExecutionResult (P0.3c): per-call result text and
    sourcing come from it, so the receipt reports what the executor actually
    did. Falls back to the executor's legacy input stash when absent."""
    steps: list = []

    ctx = context_stats or {}
    ctx_bits = []
    if ctx.get("log_days"):
        ctx_bits.append(f"{ctx['log_days']} days of logs")
    if ctx.get("has_program"):
        ctx_bits.append("your program")
    if ctx.get("has_wearable"):
        ctx_bits.append("wearable data")
    if ctx.get("weighins"):
        ctx_bits.append(f"{ctx['weighins']} weigh-ins")
    if ctx_bits:
        steps.append(_step("doc.text", "Read your data — " + ", ".join(ctx_bits)))

    # A single food log gets the FULL sourcing trace (searched → source →
    # serving → totals); several foods share the step budget, so each gets one
    # condensed line instead.
    _n_food = sum(1 for tc in (tool_calls or []) if (tc.get("name") == "log_food"))
    _detailed_food = _n_food == 1
    # Typed per-call view (P0.3c), keyed by executed input identity.
    _by_input = {}
    try:
        for _c in (execution.calls if execution is not None else ()):
            _by_input[id(_c.raw_input)] = _c
    except Exception:
        _by_input = {}
    # The meal-level lookup line, for the multi-item case that could not
    # otherwise show its lanes. Collected first so it sits ABOVE the item lines
    # it summarises.
    if not _detailed_food and _n_food > 1:
        _srcs = []
        for _tc in (tool_calls or []):
            if (_tc.get("name") or "") != "log_food":
                continue
            _c = _by_input.get(id(_tc.get("input") or {}))
            if _c is not None and _c.sourcing:
                _srcs.append(_c.sourcing)
        _summary = _meal_lookup_summary(_srcs)
        if _summary:
            steps.append(_summary)

    for tc in tool_calls or []:
        name = tc.get("name") or ""
        inp = tc.get("input") or {}
        # THIS call's own result — the shared dict is keyed by tool NAME, so a
        # multi-item batch collapses to the last result and a dedup-BLOCKED item
        # would show as "Logged" (2026-07-23). The typed view carries per-call
        # truth; the legacy stash is the fallback.
        _cr = _by_input.get(id(inp))
        result = (_cr.result_text if _cr is not None and _cr.result_text
                  else str((tool_results or {}).get(name, "")))
        if _cr is not None and _cr.sourcing:
            # Sourcing rides the typed call; the step helpers take it via a
            # DERIVED view — the caller's command is never mutated.
            inp = {**inp, "_sourcing": _cr.sourcing}
        if name == "log_food":
            if _detailed_food:
                steps.extend(_food_detailed(inp, result))
            else:
                steps.append(_food_line(inp, result))
        elif name == "log_exercise":
            steps.append(_exercise_step(inp, result))
        elif name in _TOOL_STEPS:
            # A correction that re-resolved renders a full trace, so an entry
            # may return several steps rather than one.
            _made = _TOOL_STEPS[name](inp, result)
            steps.extend(_made if isinstance(_made, list) else [_made])
        # unmapped/silent tools: no step — the receipt only shows what it
        # can state truthfully and readably.

    if not steps:
        # Every reply carries a receipt (Danny: thoughts on every reply), so
        # this stays — but it is the LAST resort, not the usual one.
        #
        # It had become the usual one: 182 of the last 400 receipts were this
        # pair and nothing else. Not because those turns did nothing, but
        # because `conversation.py` passed `context_stats=None`, so the
        # specific line above — "Read your data — 14 days of logs, 3 weigh-ins"
        # — could never render and every coaching turn fell through to here.
        # The fix is upstream, in what the caller supplies; this is what shows
        # when a turn genuinely has nothing more particular to say.
        steps = [_step("doc.text", "Read your logs, targets, and recent history"),
                 _step("brain", "Weighed the reply against your goals")]
    out = {"steps": steps[:8]}
    if duration_ms is not None:
        out["duration_ms"] = int(duration_ms)
    return out
