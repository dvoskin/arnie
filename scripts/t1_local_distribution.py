"""T1 LOCAL ASK-TYPE DISTRIBUTION — ⚠ NON-PRODUCTION, HYPOTHESIS-FORMING ONLY.

⛔⛔⛔ THIS NUMBER CANNOT SIZE A TRANCHE. The corpus is CURATED: 25 meals chosen
by hand. A distribution over meals we selected says what we asked about, not
what users ask about. The evidence hierarchy is explicit:

    local corpus distribution   -> hypothesis-forming ONLY
    production ask distribution -> tranche-sizing AUTHORITY

Its one legitimate use is NEGATIVE: if `menu_size` is tiny even in a corpus
selected without regard to ask type, T1 dies cheaply. If it is large, the only
conclusion permitted is *"T1 survives local screening and earns a production
measurement"* — never *"menu_size is a large production lever."*

⭐ THE HEADLINE IS NEVER menu_size / classified. That denominator hides the
coverage hole. Every rate is over ALL asks:

    known lower bound   =  M / N
    missingness ceiling = (M + U) / N
"""
import collections, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from skills.nutrition.ask_type import ALL, UNCLASSIFIED

lines = [json.loads(x) for x in pathlib.Path(sys.argv[1]).read_text().splitlines()]
cfg = next((l["_config"] for l in lines if "_config" in l), None)
recs = [l for l in lines if "_config" not in l]
asks = [r for r in recs if r["verdict"] == "ASK"]

print("⚠  NON-PRODUCTION — curated 25-meal corpus. Hypothesis-forming only.\n")
if cfg:
    print(f"config: gate={cfg.get('FOOD_GATE_MODEL')!r} "
          f"resolver={cfg.get('NUTRITION_RESOLVER_MODE')!r} "
          f"model={cfg.get('DEFAULT_MODEL')!r}\n")

N = len(asks)
typed = [r for r in asks if r.get("ask_types")]
U = sum(1 for r in asks if not r.get("ask_types")
        or set(r["ask_types"]) == {UNCLASSIFIED})
C = N - U
counts = collections.Counter(t for r in asks for t in set(r.get("ask_types") or ()))

print(f"turns={len(recs)}   ASK turns (N) = {N}")
print(f"classified (C) = {C}   unclassified (U) = {U}\n")
print(f"{'ask type':<24}{'turns':<8}{'lower bound M/N':<18}{'ceiling (M+U)/N'}")
print("-" * 74)
for t in ALL:
    if t == UNCLASSIFIED:
        continue
    M = counts.get(t, 0)
    lo = M / N if N else 0
    hi = (M + U) / N if N else 0
    print(f"{t:<24}{M:<8}{lo:>7.1%}          {hi:>7.1%}")
print(f"{'(unclassified)':<24}{U:<8}{U/N if N else 0:>7.1%}")

M = counts.get("menu_size", 0)
print(f"\n=== T1 HEADLINE ===")
print(f"  menu_size known lower bound   = {M}/{N} = {M/N if N else 0:.1%}")
print(f"  menu_size missingness ceiling = ({M}+{U})/{N} = {(M+U)/N if N else 0:.1%}")
print(f"  ⛔ NOT {M}/{C} = {M/C if C else 0:.1%} — that denominator hides the "
      f"coverage hole.")
print(f"\n  compound asks (2+ types): "
      f"{sum(1 for r in asks if len(set(r.get('ask_types') or ())) > 1)}/{N}")
