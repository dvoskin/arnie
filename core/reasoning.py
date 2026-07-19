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


def _food_step(inp: dict, result: str) -> dict:
    name = inp.get("food_name") or "food"
    r = result or ""
    if r.startswith("Already on the board:"):
        return _step("checkmark.circle", f"Duplicate check — {name} already logged",
                     "Skipped the re-log; totals unchanged")
    cal = inp.get("calories")
    detail = ""
    if "usda" in r.lower():
        detail = "Matched against the USDA database"
    elif "label" in r.lower() or "web" in r.lower():
        detail = "Verified against the product label"
    label = f"Logged {name}" + (f" — {round(cal)} cal" if cal else "")
    return _step("plus.circle", label, detail)


def _exercise_step(inp: dict, result: str) -> dict:
    name = inp.get("exercise_name") or "exercise"
    r = result or ""
    if r.startswith("Already on the board:"):
        return _step("checkmark.circle", f"Duplicate check — {name} already logged",
                     "Skipped the re-log")
    sets_, reps = inp.get("sets"), inp.get("reps")
    scheme = f" — {sets_}×{reps}" if sets_ and reps else ""
    return _step("figure.strengthtraining.traditional", f"Logged {name}{scheme}")


_TOOL_STEPS = {
    "log_water": lambda i, r: _step("drop", "Logged water"),
    "log_body_weight": lambda i, r: _step(
        "scalemass", f"Logged weigh-in — {i.get('weight')} {i.get('unit', '')}".strip()),
    "update_food_entry": lambda i, r: _step("pencil", "Corrected a logged food",
                                            "Macros rescaled to the new serving"),
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
                    duration_ms: Optional[int] = None) -> Optional[dict]:
    """The receipt for one turn, or None when there's nothing worth showing
    (pure-chat turns with no context read and no tools stay clean)."""
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

    for tc in tool_calls or []:
        name = tc.get("name") or ""
        inp = tc.get("input") or {}
        result = str((tool_results or {}).get(name, ""))
        if name == "log_food":
            steps.append(_food_step(inp, result))
        elif name == "log_exercise":
            steps.append(_exercise_step(inp, result))
        elif name in _TOOL_STEPS:
            steps.append(_TOOL_STEPS[name](inp, result))
        # unmapped/silent tools: no step — the receipt only shows what it
        # can state truthfully and readably.

    if not steps:
        return None
    out = {"steps": steps[:8]}
    if duration_ms is not None:
        out["duration_ms"] = int(duration_ms)
    return out
