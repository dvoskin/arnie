"""CLARIFICATION SIM — what does Arnie actually ASK, and what does it drop?

The accuracy sims measure whether the number lands. None of them show the
SENTENCE. This one does, because the sentence is what the user answers and it
is where the defects live: a compound question, a card title dropped
mid-sentence, an estimate asserted for the very thing being asked about, and —
the expensive one — four material portion unknowns collapsed into whichever
facet the interpreter happened to emit first.

Drives the REAL interpreter (live LLM, production system prompt, per-mode ask
threshold) and then the REAL composer, for each mode. Prints:

  budget    how much room the mode gives the coach to ask
  UNKNOWNS  what the composer is handed, grouped and ranked by what it is worth
  SHIPPED   the sentence the user would actually see
  floor     the deterministic fallback, for comparison only — it ships on a
            composer outage and nowhere else
  pending   what the plan claims is being held

The floor is printed LAST and dimmed on purpose. An earlier version of this sim
printed only the floor, which is identical across modes, and so appeared to
prove that mode-scaling did nothing while the thing that ships was never run.

Run from arnie/ (needs .venv + ANTHROPIC_API_KEY in .env):
    .venv/bin/python scripts/sim_clarify.py
    .venv/bin/python scripts/sim_clarify.py --modes strict
    .venv/bin/python scripts/sim_clarify.py --case 0
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_env() -> None:
    """The key lives in .env; nothing here should require it to be exported.

    Walks UP from this file rather than assuming the repo root: a git worktree
    has no .env of its own, and the checkout it belongs to is several levels
    above. ARNIE_ENV overrides when the file lives somewhere else entirely.
    """
    candidates = []
    if os.environ.get("ARNIE_ENV"):
        candidates.append(os.environ["ARNIE_ENV"])
    directory = os.path.dirname(os.path.abspath(__file__))
    for _ in range(8):
        candidates.append(os.path.join(directory, ".env"))
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    for candidate in candidates:
        if not candidate or not os.path.exists(candidate):
            continue
        for line in open(candidate):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        return


_load_env()

from dataclasses import replace                                        # noqa: E402
from core.food_turn import (_SYSTEM, _THRESH, _parse, _logger_model,   # noqa: E402
                            clarify_plan_from_points)
from core.food_response import apply_policy, compose_async             # noqa: E402
from core.llm import chat                                              # noqa: E402

B, DIM, X = "\033[1m", "\033[2m", "\033[0m"
RED, GRN, YEL = "\033[31m", "\033[32m", "\033[33m"

#: Real shapes, not toy ones. Each is a message a user actually sent or would.
CASES = [
    # The production turn this sim was written for (7948, 2026-07-27).
    "Had some pasta some yellowtail crudo some ceased salad and some beef tartare",
    # One item, one genuinely material portion unknown.
    "Just had a piece of toast with cheese",
    # Brand casing: the brand must survive, the generic must not be title-cased.
    "I had a Barebells bar and some toast with philadelphia cream cheese",
    # Multi-item where only one is ambiguous — the rest should commit clean.
    "Two eggs, a banana, and some of that leftover lasagna",
    # Restaurant meal, every portion vague.
    "Had a bit of the ribeye, some mashed potato and a few bites of cheesecake",
]


async def interpret(message: str, mode: str):
    sys_prompt = (_SYSTEM.replace("{thresh}", str(_THRESH[mode]))
                         .replace("{mode}", mode))
    res = await chat([{"role": "user", "content": message}], sys_prompt,
                     tools=False, max_tokens=700, model=_logger_model())
    return _parse(res.get("text") or "")


async def report(message: str, mode: str, data) -> None:
    """SHOW WHAT SHIPS.

    The first version of this printed `plan.clarification_question` — the
    DETERMINISTIC FLOOR — and so displayed one identical sentence for all three
    modes while reporting mode-scaling as working. The floor only ships when the
    composer errors out. Everything the mode actually changes (how much room to
    ask, how thorough to be) reaches the composer and nothing else, so a sim
    that stops at the floor cannot see any of it.
    """
    print(f"\n  {B}{mode.upper():9}{X} ask-threshold {_THRESH[mode]} cal")
    if not data:
        print(f"    {RED}<interpreter returned nothing>{X}")
        return
    action = data.get("action")
    points = data.get("points") or []
    ready = data.get("ready") or []
    if action != "ask" or not points:
        print(f"    action={action!r} — no question raised"
              f"{'' if action != 'log' else ' (logged straight through)'}")
        return

    plan = clarify_plan_from_points(points, ready, user_message=message)
    if plan is None:
        print(f"    {RED}<no plan>{X}")
        return
    plan = apply_policy(replace(plan, user_mode=mode))

    print(f"    {DIM}budget {X} {plan.max_sentences} sentence(s), "
          f"{plan.max_words} words")
    from core.food_response import pursued_unknowns
    pursued = pursued_unknowns(plan.clarification_unknowns, mode)
    skipped = [u for u in plan.clarification_unknowns if u not in pursued]
    print(f"    {YEL}PURSUED {X} ({len(pursued)} of "
          f"{len(plan.clarification_unknowns)} unknowns, at this mode's granularity):")
    for unknown in pursued:
        stakes = unknown.get("stakes") or 0
        print(f"             - {unknown.get('phrase')} "
              f"— {', '.join(unknown.get('items') or ())}"
              + (f"  [~{int(stakes)} cal]" if stakes else ""))

    for unknown in skipped:
        print(f"    {DIM}skipped {X} {unknown.get('phrase')} "
              f"— {', '.join(unknown.get('items') or ())} "
              f"[~{int(unknown.get('weight') or 0)} cal, below threshold]")
    composed, reason = "", ""
    try:
        composed, reason = await compose_async(plan)
        composed = composed or ""
    except Exception as e:
        print(f"    {RED}composer failed{X}: {type(e).__name__}: {e}")
    if composed:
        tag = GRN if reason == "ok" else YEL
        print(f"    {tag}SHIPPED {X} {composed!r}")
        if reason != "ok":
            print(f"    {DIM}        {X} (composer rejected: {reason})")
    print(f"    {DIM}floor   {X} {plan.clarification_question!r}")
    print(f"    {DIM}pending {X} {[i.name for i in (plan.pending_items or ())]}")


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="quick,moderate,strict")
    ap.add_argument("--case", type=int, default=None,
                    help="run a single case by index")
    args = ap.parse_args()
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    cases = [CASES[args.case]] if args.case is not None else CASES

    print(f"{B}CLARIFICATION SIM{X} — real interpreter, real renderer, "
          f"model={_logger_model()}")
    for i, message in enumerate(cases):
        print(f"\n{'=' * 78}\n{B}[{i}]{X} {message!r}\n{'=' * 78}")
        for mode in modes:
            try:
                data = await interpret(message, mode)
                await report(message, mode, data)
            except Exception as e:
                print(f"\n  {mode.upper():9} {RED}failed{X}: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
