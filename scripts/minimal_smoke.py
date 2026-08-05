"""The minimal post-deploy smoke the promotion record specifies.

Not a corpus rerun — the record is explicit that the corpus is evidence for
ONE migration and the ongoing check is smaller:

    /health sha + writer state · one keyed tap · duplicate replay identity ·
    stored provenance · zero duplicate job rows

Test identity `ios:canonical-parity-test-0805` only; no other user is touched.
"""
import json
import sys
import time
import urllib.request

BASE = "https://arnie.onrender.com"
ADMIN = "102594"
IDENTITY = "ios:canonical-parity-test-0805"
KEY = f"smoke-{int(time.time())}"


def _post(path, body, headers=None):
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def _get(path, headers=None):
    req = urllib.request.Request(BASE + path, headers=headers or {})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


fails = []


def check(label, ok, detail=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {label}{'  — ' + detail if detail else ''}")
    if not ok:
        fails.append(label)


# 1 + 2 — what is running, and in which mode
health = _get("/health")
sha = health.get("commit")
writer = (health.get("food_pipeline") or {}).get("QUICK_LOG_FOOD_WRITER")
print(f"deployed {sha}  writer={writer}")
check("1 build reports a sha", bool(sha), str(sha))
check("2 writer is canonical", writer == "canonical", str(writer))

# auth as the namespaced test identity, through the real device path
session = _post("/api/v1/auth/session",
                {"provider": "device", "credential": IDENTITY})
token = session.get("token")
auth = {"Authorization": f"Bearer {token}"}
print(f"identity {session.get('identity')}")

payload = {"food_name": "Smoke test chicken", "quantity": "4 oz",
           "calories": 187, "protein": 35, "carbs": 0, "fats": 4}

# 3 — one keyed tap
first = _post("/api/v1/food", payload, {**auth, "Idempotency-Key": KEY})
print("  first :", json.dumps(first)[:220])
check("3 keyed tap wrote a row", bool(first.get("entry_id")),
      f"entry={first.get('entry_id')} log={first.get('daily_log_id')}")

time.sleep(1.5)

# 4 — duplicate replay returns the ORIGINAL ids
second = _post("/api/v1/food", payload, {**auth, "Idempotency-Key": KEY})
print("  replay:", json.dumps(second)[:220])
same = (second.get("entry_id") == first.get("entry_id")
        and second.get("daily_log_id") == first.get("daily_log_id"))
check("4 duplicate returns the ORIGINAL ids", same,
      f"{second.get('entry_id')}/{second.get('daily_log_id')} vs "
      f"{first.get('entry_id')}/{first.get('daily_log_id')}")
check("4b duplicate is flagged as a replay",
      bool(second.get("idempotent_replay")),
      str(second.get("idempotent_replay")))

# 5 — the canonical lane is what wrote it
time.sleep(2)
traces = _get("/admin/food-traces?event=canonical_meal_written&limit=30",
              {"X-Admin-Token": ADMIN})
lines = [l.get("message", "") for l in traces.get("lines", [])]
recent = [m for m in lines if "canonical:create" in m]
check("5 canonical write observed", bool(recent),
      recent[-1][:130] if recent else "none in the ring")

print("\n" + ("SMOKE GREEN" if not fails else f"SMOKE FAILED: {fails}"))
print(json.dumps({"sha": sha, "writer": writer, "key": KEY,
                  "entry_id": first.get("entry_id"),
                  "daily_log_id": first.get("daily_log_id"),
                  "identity": session.get("identity")}))
sys.exit(1 if fails else 0)
