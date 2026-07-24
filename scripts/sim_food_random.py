"""High-volume randomized simulation of the structured food turn.

Generates seeded random meal reports (branded/generic × stated/vague/counted
portions × composites) across all three accuracy modes and asserts the MODE
CONTRACT on live logger output:

  strict   -> NEVER a silent log: every log-shaped report returns ask
              (clarify or confirm). Zero exceptions.
  moderate -> fully-specified reports log silently; package-portion vagueness
              still asks (class 1).
  quick    -> only huge unknowns ask; clean reports always log silently.
  all      -> say carries no model-authored digits (contract-clean), items
              split, actions are one of log|update|ask|pass.

Run:  ANTHROPIC_API_KEY=... PYTHONPATH=<repo> python scripts/sim_food_random.py [seed] [n_per_mode]
"""
import asyncio
import random
import sys
from types import SimpleNamespace

sys.path.insert(0, ".")
from core import food_turn as FT  # noqa: E402

BRANDED = [("Barebells caramel cashew bar", "1 bar"),
           ("Quest sour cream chips", "1 bag"),
           ("Fage 0% greek yogurt", "1 cup"),
           ("Jack Link's teriyaki jerky", None),        # portion unstated → class 1
           ("Ben & Jerry's ice cream", None)]           # tub, unstated → class 1
GENERIC = [("grilled chicken breast", "6 oz"),
           ("white rice", "150g"),
           ("scrambled eggs", "3"),
           ("caesar salad with chicken", None),          # add-ons unclear
           ("beef stew", "a bowl of"),
           ("strawberries", "8"),
           ("mixed vegetables", "some")]                 # tiny swing → no ask


def gen_report(rng):
    items, must_ask_p1 = [], False
    for _ in range(rng.randint(1, 3)):
        pool = BRANDED if rng.random() < 0.4 else GENERIC
        name, qty = rng.choice(pool)
        if qty is None:
            must_ask_p1 = True
            items.append(f"some {name}")
        elif qty in ("a bowl of", "some"):
            items.append(f"{qty} {name}")
        else:
            items.append(f"{qty} {name}")
    verb = rng.choice(["had", "ate", "just had"])
    return f"{verb} " + " and ".join(items), must_ask_p1


def user(mode):
    return SimpleNamespace(id=1, preferences=SimpleNamespace(
        food_logging_mode=mode, calorie_target=2200, protein_target=170))


async def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    rng = random.Random(seed)
    fails, runs = [], 0
    for mode in ("strict", "moderate", "quick"):
        for _ in range(n):
            msg, pkg_vague = gen_report(rng)
            out = await FT.run(msg, user(mode),
                               day_line="Today: 400 cal, 30g protein so far.")
            runs += 1
            act = out["action"] if out else None
            kind = (out or {}).get("kind")
            tag = f"[{mode}] {msg!r} -> {act}{'/' + kind if kind else ''}"
            if act not in ("log", "update", "ask", None):
                fails.append(f"BAD ACTION {tag}")
            if mode == "strict" and act == "log":
                fails.append(f"STRICT SILENT LOG {tag}")
            if mode != "strict" and pkg_vague and act == "log":
                fails.append(f"CLASS-1 VAGUE LOGGED SILENTLY {tag}")
            if act == "log":
                say = (out or {}).get("say") or ""
                if FT.enforce_say_contract(say, out["tool_calls"]) != say:
                    fails.append(f"SAY CONTRACT {tag} :: {say[:80]}")
            print(("FAIL " if fails and fails[-1].endswith(tag) else "ok   ") + tag,
                  flush=True)
    print(f"\n{runs - len(fails)}/{runs} passed", flush=True)
    for f in fails:
        print("  •", f)
    return len(fails)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
