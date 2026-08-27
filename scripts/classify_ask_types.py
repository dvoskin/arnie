"""Count ask types across recorded stability runs.

⚠ A COUNTING AID, NOT THE TAXONOMY. The seven types were derived by READING
all 105 asks; these patterns only tally them. It reads `questions[0]` only and
leaves ~23% unclassified, so every count here is a LOWER BOUND -- including the
compound-ask rate, which reading shows is higher than this reports.

⛔ 103 of 105 asks carry no `kind` field: the structured lane records no ask
type, so this analysis is only possible offline. See
docs/ASK_TYPE_TAXONOMY_2026-08-27.md.
"""
import collections, json, pathlib, re, sys

TYPES = {
 "T1 menu size option":     r"small,? medium,? or large|regular or large|regular size or large|small, medium, or big|snack bag or something bigger|which size",
 "T2 continuous portion":   r"how much|how big|roughly a cup|small cup or|a cup or closer|\d+ ?oz\b|small bowl|full portion|how many|light scoop|hearty|small side portion",
 "T3 consumption complete": r"did you finish|leave some|whole container|split it|closer to half|half of each|eat the whole",
 "T4 preparation / fat":    r"grilled or|pan-sear|fried in butter|scrambled or|oven-baked or fried|butter on it|cooked in butter|water or milk|grilled dry|how it was cooked|how they were cooked|how they were made",
 "T5 unstated extras":      r"anything on top|any extras|toppings|extra everything|how much mayo|how loaded|stack anything|add(ed)? something|plain, or",
 "T6 portion multiplier":   r"double it up|did you double|single scoop|double protein|regular entree portion|full entree|regular single scoop|go bigger with",
 "T7 identity / variant":   r"little or regular|one-patty|whole or half|restaurant or homemade|restaurant/deli or homemade|which bag|what kind",
}
COMP = [(k, re.compile(v, re.I)) for k, v in TYPES.items()]

recs = []
for f in sys.argv[1:]:
    recs += [l for l in (json.loads(x) for x in pathlib.Path(f).read_text().splitlines())
             if "_config" not in l]
asks = [r for r in recs if r["verdict"] == "ASK"]
per_turn, per_case, uncl = collections.Counter(), collections.defaultdict(set), 0
for r in asks:
    q = " ".join((r["questions"][0] if r["questions"] else "").split())
    hit = [k for k, rx in COMP if rx.search(q)]
    if not hit:
        uncl += 1
    for k in hit:
        per_turn[k] += 1
        per_case[k].add(r["case"])
typed = sum(1 for r in asks for c in r["calls"]
            if c["tool"] == "note_food_clarification" and c["input"].get("kind"))
print(f"turns={len(recs)}  asks={len(asks)}  asks carrying a `kind` field={typed}")
print(f"unclassified={uncl}/{len(asks)} ({100*uncl/max(1,len(asks)):.0f}%) -- counts are LOWER BOUNDS\n")
for k, _ in COMP:
    print(f"{k:<26}{per_turn[k]:<7}{len(per_case[k]):<7}{sorted(per_case[k], key=int)}")
