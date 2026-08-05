"""Drive the production quick-log endpoint as a test user; collect parity.

Phase 1 / Step 1 of the migration directive: meaningful shadow traffic against
the LIVE environment, as a user, through the real endpoint — not a simulation
of it. The test identity is namespaced and obvious
(`ios:canonical-parity-test-0805`), and nothing here touches another user.

Each case is one tap. The corpus is chosen for what a CLIENT-PRICED tap can
actually get wrong across the boundary: name fidelity (unicode, quotes),
macro passthrough (decimals, zeros, large values), day-total accumulation
across taps, duplicate delivery, and the absent-vs-present quantity split.

Usage:
    python scripts/parity_corpus.py            # shadow mode: needs the flag on
    python scripts/parity_corpus.py --promoted # post-promotion verification:
                                               # sends the same corpus at the
                                               # CANONICAL endpoint and reads
                                               # event=canonical_meal_written
    python scripts/parity_corpus.py --traces   # pull traces only
"""
import json
import sys
import time
import urllib.request

BASE = "https://arnie.onrender.com"
ADMIN = "102594"
TOKEN_FILE = ("/private/tmp/claude-501/-Users-danielvoskin-Code-Learn/"
              "2f42fee2-1f7d-4fbc-82e3-cb39dcccb248/scratchpad/parity_token.txt")

#: (label, payload, idempotency_key or None, expect_replay)
CORPUS = [
    ("plain",        {"food_name": "Chicken breast", "calories": 320,
                      "protein": 43, "carbs": 0, "fats": 15}, "cp-01", False),
    ("quantity+meal", {"food_name": "White rice", "quantity": "1 cup",
                      "calories": 205, "protein": 4.3, "carbs": 45,
                      "fats": 0.4, "meal_type": "lunch"}, "cp-02", False),
    ("DUPLICATE of cp-02", {"food_name": "White rice", "quantity": "1 cup",
                      "calories": 205, "protein": 4.3, "carbs": 45,
                      "fats": 0.4, "meal_type": "lunch"}, "cp-02", True),
    ("second helping", {"food_name": "White rice", "quantity": "1 cup",
                      "calories": 205, "protein": 4.3, "carbs": 45,
                      "fats": 0.4, "meal_type": "lunch"}, "cp-03", False),
    ("zero calories", {"food_name": "Black coffee", "calories": 0,
                      "protein": 0, "carbs": 0, "fats": 0}, "cp-04", False),
    ("decimals",     {"food_name": "Greek yogurt", "quantity": "150g",
                      "calories": 137.5, "protein": 11.3, "carbs": 9.1,
                      "fats": 6.2}, "cp-05", False),
    ("unicode",      {"food_name": "Гречка с курицей", "quantity": "1 порция",
                      "calories": 410, "protein": 32, "carbs": 48,
                      "fats": 9}, "cp-06", False),
    ("apostrophe",   {"food_name": "Trader Joe's Yogurt", "calories": 140,
                      "protein": 12, "carbs": 16, "fats": 3}, "cp-07", False),
    ("large meal",   {"food_name": "Cheat day burger platter",
                      "quantity": "1 platter", "calories": 1850,
                      "protein": 78, "carbs": 145, "fats": 98,
                      "meal_type": "dinner"}, "cp-08", False),
    ("unkeyed",      {"food_name": "Almonds", "quantity": "small handful",
                      "calories": 165, "protein": 6, "carbs": 6,
                      "fats": 14}, None, False),
]


def _post(path, body, headers):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def _get(path, headers):
    req = urllib.request.Request(BASE + path, headers=headers)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read())


def send_corpus(token):
    """Send the corpus and CHECK each response, rather than printing it.

    The duplicate case is the one that matters most: a replay must return the
    ORIGINAL entry_id and daily_log_id, not merely a 200 with the replay flag
    set. A replay pointing at a different row would satisfy a flag check and
    still be a duplicate write.
    """
    results, by_key, problems = [], {}, []
    for label, payload, key, expect_replay in CORPUS:
        headers = {"Authorization": f"Bearer {token}"}
        if key:
            headers["Idempotency-Key"] = key
        try:
            out = _post("/api/v1/food", payload, headers)
        except Exception as exc:
            print(f"  {label:<22} -> FAILED {exc}")
            problems.append(f"{label}: request failed: {exc}")
            results.append((label, {"error": str(exc)}))
            time.sleep(1.2)
            continue

        replay = bool(out.get("idempotent_replay"))
        note = ""
        if replay != expect_replay:
            note = f"  <-- expected replay={expect_replay}"
            problems.append(f"{label}: replay={replay}, expected {expect_replay}")

        if key and expect_replay and key in by_key:
            original = by_key[key]
            for field in ("entry_id", "daily_log_id"):
                if out.get(field) != original.get(field):
                    note += f"  <-- {field} {out.get(field)} != original {original.get(field)}"
                    problems.append(
                        f"{label}: replay returned {field}={out.get(field)}, "
                        f"original was {original.get(field)}")
        elif key and not replay:
            by_key[key] = out

        print(f"  {label:<22} -> {'REPLAY' if replay else 'ok':<7} "
              f"entry={out.get('entry_id')} log={out.get('daily_log_id')}{note}")
        results.append((label, out))
        time.sleep(1.2)      # keep the ring's ordering readable

    if problems:
        print("\nPROBLEMS:")
        for p in problems:
            print("  ", p)
    else:
        print("\nall responses as expected, including duplicate identity")
    return results, problems


def pull_traces():
    d = _get("/admin/food-traces?event=canonical_shadow&limit=100",
             {"X-Admin-Token": ADMIN})
    print(f"\ncanonical_shadow lines: {d.get('matched')} "
          f"(dropped_from_ring={d.get('dropped_from_ring')})")
    agreed = diverged = errored = 0
    for l in d.get("lines", []):
        msg = l.get("message", "")
        if "outcome=agreed" in msg:
            agreed += 1
        elif "outcome=diverged" in msg:
            diverged += 1
            print("  DIVERGED:", msg[:220])
        elif "outcome=error" in msg:
            errored += 1
            print("  ERROR   :", msg[:220])
    print(f"\nagreed={agreed} diverged={diverged} errored={errored}")
    return agreed, diverged, errored


if __name__ == "__main__":
    token = open(TOKEN_FILE).read().strip()
    promoted = "--promoted" in sys.argv
    if "--traces" not in sys.argv:
        health = _get("/health", {})
        flag = (health.get("food_pipeline", {})
                .get("CANONICAL_WRITER_SHADOW", {}))
        print(f"deployed={health.get('commit')} shadow={flag}")
        if not promoted and not flag.get("effective"):
            sys.exit("REFUSING to send the corpus: the shadow is OFF, and an "
                     "empty window would read as perfect parity. (After the "
                     "promotion deploys, run with --promoted instead — there "
                     "is no shadow on a canonical endpoint.)")
        print(f"sending {len(CORPUS)} taps as ios:canonical-parity-test-0805:")
        _, problems = send_corpus(token)
        time.sleep(2)
    if promoted:
        d = _get("/admin/food-traces?event=canonical_meal_written&limit=50",
                 {"X-Admin-Token": ADMIN})
        print(f"\ncanonical_meal_written lines: {d.get('matched')} "
              f"(one per non-replayed tap; a replay writes nothing, which is "
              f"the point)")
        for l in d.get("lines", [])[-12:]:
            print("  ", l.get("message", "")[:150])
        if d.get("matched", 0) == 0:
            sys.exit("NO canonical writes observed — either the promoted build "
                     "is not deployed, or taps are not reaching this worker.")
    else:
        pull_traces()
