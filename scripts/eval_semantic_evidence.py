"""Layer C: the REAL resolver over the CAPTURED corpus, scored against human
ground truth.

Run manually (network + model cost — not part of CI):

    ../arnie/.venv/bin/python scripts/eval_semantic_evidence.py [model]

Prints per-record classifications and the §19 metrics. FALSE-COMPATIBLE is the
expensive error: predicted identity-bearing where the truth is not. Rejecting
a useful candidate costs another lookup; accepting chicken fat as chicken
costs a wrong meal.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The human-reviewed expectations from tests/evidence_corpus/GROUND_TRUTH.md,
# keyed by (intent, record title). Kept HERE, beside the eval, so the fixtures
# stay raw.
TRUTH_USDA = {
    "chicken": {
        "Chicken spread": "COMPOSITE_CONTAINING_IDENTITY",
        "Chicken, meatless": "SUBSTITUTE_OR_ANALOGUE",
        "Fat, chicken": "DERIVED_OR_EXTRACTED_FORM",
        "Frankfurter, chicken": "DIFFERENT_IDENTITY",
        "Fast foods, chicken tenders": "COMPOSITE_CONTAINING_IDENTITY",
        "Bologna, chicken, pork": "DIFFERENT_IDENTITY",
        "Bratwurst, chicken, cooked": "DIFFERENT_IDENTITY",
        "Chicken, canned, no broth": "COMPATIBLE_SPECIALIZATION",
    },
    "papaya": {
        "Papayas, raw": "SAME_IDENTITY",
        "Papaya nectar, canned": "DERIVED_OR_EXTRACTED_FORM",
        "Papaya, canned, heavy syrup, drained": "DERIVED_OR_EXTRACTED_FORM",
        "Babyfood, fruit, guava and papaya with tapioca, strained":
            "COMPOSITE_CONTAINING_IDENTITY",
        "Babyfood, fruit, papaya and applesauce with tapioca, strained":
            "COMPOSITE_CONTAINING_IDENTITY",
        "Fruit salad, (pineapple and papaya and banana and guava), tropical, "
        "canned, in heavy syrup, solids and liquids":
            "COMPOSITE_CONTAINING_IDENTITY",
    },
    "salmon": {
        "Fish oil, salmon": "DERIVED_OR_EXTRACTED_FORM",
        "Fish, salmon, chinook, raw": "COMPATIBLE_SPECIALIZATION",
        "Fish, salmon, chinook, smoked": "COMPATIBLE_SPECIALIZATION",
        "Fish, salmon, chum, raw": "COMPATIBLE_SPECIALIZATION",
        "Fish, salmon, pink, raw": "COMPATIBLE_SPECIALIZATION",
        "Fish, salmon, sockeye, raw": "COMPATIBLE_SPECIALIZATION",
        "Fish, salmon, Atlantic, farmed, raw": "COMPATIBLE_SPECIALIZATION",
        "Fish, salmon, Atlantic, wild, raw": "COMPATIBLE_SPECIALIZATION",
    },
    "potato": {
        "Bread, potato": "DIFFERENT_IDENTITY",
        "Potato flour": "DERIVED_OR_EXTRACTED_FORM",
        "Potato pancakes": "COMPOSITE_CONTAINING_IDENTITY",
        "Babyfood, potatoes, toddler": "COMPATIBLE_SPECIALIZATION",
        "Potato salad with egg": "COMPOSITE_CONTAINING_IDENTITY",
        "Potatoes, raw, skin": "COMPATIBLE_SPECIALIZATION",
        "Snacks, potato sticks": "DERIVED_OR_EXTRACTED_FORM",
    },
}

TRUTH_OFF = {  # by intent -> substring of title -> truth
    "chicken": {"PIZZA": "COMPOSITE_CONTAINING_IDENTITY"},
    "papaya": {"Mango Papaya Passion Fruit": "COMPOSITE_CONTAINING_IDENTITY"},
    "salmon": {"Salmon ahumado": "COMPATIBLE_SPECIALIZATION"},
    "Barebells salty peanut protein bar":
        {"Salty Peanut": "SAME_IDENTITY"},
}

IDENTITY_BEARING = {"SAME_IDENTITY", "COMPATIBLE_SPECIALIZATION"}


async def main():
    model = sys.argv[1] if len(sys.argv) > 1 else "claude-haiku-4-5-20251001"
    for line in (ROOT.parent / "arnie" / ".env").read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            os.environ.setdefault("ANTHROPIC_API_KEY",
                                  line.split("=", 1)[1].strip().strip('"'))

    from anthropic import AsyncAnthropic

    from core import semantic_evidence as se
    from skills.nutrition import evidence_semantics as food

    client = AsyncAnthropic()

    async def complete(prompt):
        reply = await client.messages.create(
            model=model, max_tokens=3000,
            messages=[{"role": "user", "content": prompt}])
        # Thinking-enabled models emit a ThinkingBlock before the text block;
        # `content[0].text` raised on Sonnet 5 — and the boundary abstained
        # the whole batch rather than crashing, which is §33 demonstrating
        # itself. Take the text block wherever it sits.
        return next(b.text for b in reply.content if hasattr(b, "text"))

    usda = json.loads((ROOT / "tests/evidence_corpus/usda_2026_08_07.json")
                      .read_text())["queries"]
    off = json.loads((ROOT / "tests/evidence_corpus/off_2026_08_07.json")
                     .read_text())

    scored = []           # (intent, title, truth, predicted, confidence)
    for intent_name, truth in TRUTH_USDA.items():
        records = food.from_usda(usda[intent_name])
        out = await se.resolve(food.DOMAIN, food.FoodIntent(intent_name),
                               records, complete)
        for record, a in zip(records, out):
            expected = truth.get(record.title)
            if expected:
                scored.append((intent_name, record.title, expected,
                               a.relationship, a.confidence))

    for intent_name, truths in TRUTH_OFF.items():
        best = off["best_match"].get(intent_name)
        records = food.from_off(best, off["variants"].get(intent_name) or ())
        if not records:
            continue
        out = await se.resolve(food.DOMAIN, food.FoodIntent(intent_name),
                               records, complete)
        for record, a in zip(records, out):
            for needle, expected in truths.items():
                if needle.lower() in record.title.lower():
                    scored.append((intent_name, record.title, expected,
                                   a.relationship, a.confidence))

    exact = false_compatible = false_incompatible = abstained = 0
    print(f"\nmodel={model}  version={food.VERSION}\n")
    for intent_name, title, expected, predicted, confidence in scored:
        t_id, p_id = expected in IDENTITY_BEARING, predicted in IDENTITY_BEARING
        if predicted == se.ABSTAIN:
            abstained += 1
            flag = "ABSTAIN"
        elif predicted == expected:
            exact += 1
            flag = "ok"
        elif p_id and not t_id:
            false_compatible += 1
            flag = "FALSE-COMPATIBLE  <<<< expensive"
        elif t_id and not p_id:
            false_incompatible += 1
            flag = "false-incompatible"
        else:
            flag = "class-miss (both non-identity)"
        print(f"  [{intent_name:8}] {title[:52]:53} truth={expected[:28]:29} "
              f"got={predicted[:28]:29} {confidence:.2f}  {flag}")

    n = len(scored)
    print(f"\n  n={n}  exact={exact} ({exact/n:.0%})  "
          f"false-compatible={false_compatible} ({false_compatible/n:.1%})  "
          f"false-incompatible={false_incompatible}  abstained={abstained}")


if __name__ == "__main__":
    asyncio.run(main())
