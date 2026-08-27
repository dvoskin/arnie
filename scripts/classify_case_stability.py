"""Bucket the sweep. Four buckets, authorized 2026-08-27.

⭐ A case PASSES a rep only if the TERMINAL matches the frozen label AND, on a
LOG, the row count sits inside expected_component_range. Case 11 is why:
1050-1170 kcal is inside its frozen range on every LOG while the row count
alternates 1 / 5 / 6. Terminal-only stability calls that healthy.

⚠ n=4 CANNOT CERTIFY STABILITY. A true 50/50 case shows 4/4 one way 12.5% of
the time. "Stable" here means "did not flip in 4", which is a SHORTLIST
criterion, not a proof. Case 23 alone carries n=8 from the prior run.
"""
import json, pathlib, collections, sys

_lines = [json.loads(l) for l in pathlib.Path(sys.argv[1]).read_text().splitlines()]
# ⭐ THE FIRST LINE IS THE RESOLVED CONFIGURATION. A run can no longer be read
# without it — the 2026-08-27 sweep was frozen as a baseline while every
# declared production flag was unset in its shell.
CONFIG = next((l["_config"] for l in _lines if "_config" in l), None)
recs = [l for l in _lines if "_config" not in l]
if CONFIG is None:
    print("⚠ NO CONFIG HEADER — this run predates config pinning. Its flag\n"
          "  environment is unknown and it must not be treated as a baseline.\n")
else:
    _k = ("FOOD_GATE_MODEL", "NUTRITION_RESOLVER_MODE", "DEFAULT_MODEL",
          "TURN_COORDINATOR_MODE", "FOOD_COMPOSER")
    print("config: " + "  ".join(f"{k}={CONFIG.get(k)!r}" for k in _k) + "\n")
corpus = json.load(open("data/corpus/real_meal_expectations_v1.json"))
CASES = {c["id"]: c for c in (corpus["cases"] if isinstance(corpus, dict) else corpus)}
WANT = {"LOG_COMPLETE": "LOG", "ASK_CORRECT": "ASK"}

def passes(r):
    if r["verdict"] != WANT[r["label"]]:
        return False
    if r["verdict"] == "LOG":
        return bool(r.get("components_ok") and r.get("cal_ok") and r.get("protein_ok"))
    return True

by = collections.defaultdict(list)
for r in recs:
    by[r["case"]].append(r)

buckets = collections.defaultdict(list)
rows = []
for cid in sorted(by, key=lambda x: int(x)):
    rs = sorted(by[cid], key=lambda r: r["rep"])
    m = [r for r in rs if r["verdict"] != "UNMEASURED"]
    if not m:
        buckets["UNMEASURED"].append(cid); continue
    case = CASES[cid]
    terms = [r["verdict"] for r in m]
    ok = [passes(r) for r in m]
    comps = [len(r["rows"]) for r in m if r["verdict"] == "LOG"]
    prose = sum(1 for r in m if r.get("prose_question"))
    nothing = sum(1 for t in terms if t == "NOTHING")
    struct_flip = bool(comps) and (max(comps) - min(comps) >= 1)
    term_flip = len(set(terms)) > 1

    if all(ok):
        b = "STABLE PASS"
    elif nothing == len(m):
        b = "SILENT/BROKEN"
    elif term_flip or struct_flip:
        b = "UNSTABLE"
    else:
        b = "STABLE FAILURE"
    buckets[b].append(cid)
    rows.append({
        "id": cid, "label": case["expected_terminal"], "bucket": b,
        "seq": "".join({"LOG": "L", "ASK": "A", "NOTHING": "·",
                        "UNMEASURED": "?"}[t] for t in terms),
        "pass": f"{sum(ok)}/{len(m)}", "comps": comps,
        "exp_comp": case["expected_component_range"],
        "prose": prose, "struct_flip": struct_flip, "term_flip": term_flip,
        "msg": case["message"][:44],
    })

print(f"n turns = {len(recs)}   UNMEASURED = "
      f"{sum(1 for r in recs if r['verdict']=='UNMEASURED')}\n")
print(f"{'id':<4}{'frozen':<14}{'seq':<7}{'pass':<7}{'rows seen':<13}"
      f"{'exp':<8}{'bucket':<15}{'meal'}")
print("-" * 118)
for r in sorted(rows, key=lambda x: (x["bucket"], int(x["id"]))):
    cs = ",".join(str(c) for c in r["comps"]) or "-"
    print(f"{r['id']:<4}{r['label']:<14}{r['seq']:<7}{r['pass']:<7}{cs:<13}"
          f"{str(r['exp_comp']):<8}{r['bucket']:<15}{r['msg']}")

print("\n" + "=" * 60)
for b in ("STABLE PASS", "STABLE FAILURE", "UNSTABLE", "SILENT/BROKEN"):
    ids = buckets.get(b, [])
    print(f"{b:<16} {len(ids):>2} cases   {sorted(ids, key=int)}")

print("\n" + "=" * 60)
print("⭐ DEFAULTABILITY CANDIDATES — frozen LOG_COMPLETE + observed STABLE ASK")
cand = [r for r in rows if r["label"] == "LOG_COMPLETE"
        and set(r["seq"]) == {"A"}]
if not cand:
    print("   NONE.")
for r in sorted(cand, key=lambda x: int(x["id"])):
    print(f"   c{r['id']:<4} {r['seq']:<7} {r['msg']}")
print(f"   -> population = {len(cand)}")

print("\n⛔ DEFECT POPULATION 1 — REPRESENTATION INSTABILITY "
      "(same utterance, different decomposition)")
rep_inst = [r for r in rows if r["struct_flip"]]
for r in sorted(rep_inst, key=lambda x: int(x["id"])):
    print(f"   c{r['id']:<4} rows={r['comps']} expected={r['exp_comp']}  {r['msg']}")
print(f"   -> population = {len(rep_inst)}")

print("\n⛔ DEFECT POPULATION 2 — NON-DURABLE CLARIFICATION "
      "(prose question, no answerable state)")
tot = sum(r["prose"] for r in rows)
for r in sorted([r for r in rows if r["prose"]], key=lambda x: int(x["id"])):
    print(f"   c{r['id']:<4} {r['prose']} of 4 reps   {r['msg']}")
print(f"   -> {tot} turns across {sum(1 for r in rows if r['prose'])} cases")

print("\n⛔ STRUCTURAL FAILURES ON LOG TURNS (row count outside frozen range)")
bad = [r for r in rows if r["comps"] and not all(
    r["exp_comp"][0] <= c <= r["exp_comp"][1] for c in r["comps"])]
for r in sorted(bad, key=lambda x: int(x["id"])):
    print(f"   c{r['id']:<4} rows={r['comps']} expected={r['exp_comp']}  {r['msg']}")
print(f"   -> {len(bad)} cases log the wrong number of rows at least once")
