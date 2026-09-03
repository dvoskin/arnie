#!/usr/bin/env python
"""Would a CONFLICT rule contain the measured consumed-form errors — and ONLY them?

The 3-of-20 finding: among the identities query expansion recovered, three
animal proteins price from a RAW row (`Рыба` -> bluefish raw, `Кальмар`,
`Гребешок`) while six fruits/vegetables price from `raw` CORRECTLY — in USDA,
`raw` is the fresh form blueberries are actually eaten in.

So any containment has to separate those two groups without a food ontology.
The candidate signal is a property of the POOL, not the food: the winner is a
precursor form AND a cooked row for the same identity is present AND the user
named no form. This script measures that rule's precision and recall against
the 20 recovered identities. Nothing is persisted.
"""
from __future__ import annotations

import asyncio
import collections
import json
import logging
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

RECOVERED = ["Pan-fried pork", "Сыр моцарелла", "Перец сладкий", "Рыба",
             "Вареные яйца", "Чай", "Черника", "Сыр пармезан", "Lettuce and tomato",
             "Помидор", "Соевый соус", "Салями", "Кальмар", "Гребешок",
             "Миндальное молоко", "Манго", "Яйца пашот", "Smoke test chicken",
             "Редис", "Шоколад"]
KNOWN_WRONG = {"Рыба", "Кальмар", "Гребешок"}
_PRECURSOR = {"raw", "dry", "dried", "uncooked", "unprepared"}


async def main():
    from core.food_intelligence import best_candidate, _COOKED_MARKERS, normalize_name
    from scripts.build_pricing_artifact import build_one
    from skills.nutrition import pricing_artifact as art

    flagged, rows_out = [], []
    from core.food_intelligence import cooked_preference_state, COOKED_PREFERRED
    from skills.nutrition.retrieval_intent import expand
    FORM_WORDS = set(_COOKED_MARKERS) | {"raw", "fresh", "dry", "dried", "canned", "smoked",
                                         "frozen", "brewed", "uncooked", "cured", "hard", "or"}

    def _tokens(text):
        return set(normalize_name(text or "", split_separators=True).split())

    def _neutral(q):
        """The expansion's RETRIEVAL query with its form segments removed. Ranking
        with 'Fish, raw' lets recall-expansion dictate the consumed form — the
        user said fish. 'Fish, raw, mixed species' -> 'Fish, mixed species'."""
        keep = [seg for seg in q.split(", ") if not _tokens(seg) <= FORM_WORDS]
        return ", ".join(keep) or q

    def _conflict(w, cands, prep):
        if not w:
            return False, 0
        wd = _tokens(w.get("description"))
        cooked_alt = [c for c in cands if c is not w and (_tokens(c.get("description")) & _COOKED_MARKERS)]
        precursor = "raw" in wd and not prep
        return bool(precursor and cooked_alt), len(cooked_alt)

    rows_out, naive, neutral_flag, sharp = [], [], [], []
    for name in RECOVERED:
        ent, prep = art.split_identity(name)
        try:
            r = await build_one(ent, prep, identity_key=art.key(ent, prep))
        except Exception as exc:                          # noqa: BLE001
            rows_out.append({"name": name, "error": type(exc).__name__}); continue
        cands = list(r.get("candidates") or ())
        rec = {"name": name, "status": r.get("status"), "failure_class": r.get("failure_class"),
               "reason": str(r.get("reason") or "")[:80], "known_wrong": name in KNOWN_WRONG,
               "candidates": [(c.get("evidence_id"), c.get("description")) for c in cands],
               "queries_tried": [], "per_query": {}}
        w, _ = best_candidate(ent, cands) if cands else (None, None)
        via = "original" if w else None
        english_q = None
        if not w and cands:
            intent = await expand(name)
            rec["expansion"] = list(intent.queries)
            for q in list(intent.queries)[1:]:
                cw, _ = best_candidate(q, cands)
                rec["queries_tried"].append(q); rec["per_query"][q] = cw and cw.get("description")
                if cw and not w:
                    w, via, english_q = cw, f"english:{q}", q
        if not w:
            rows_out.append(rec | {"winner": None})
            print(f"   --   {name[:24]:26} NO WINNER  status={r.get('status')} "
                  f"{r.get('failure_class') or ''} {str(r.get('reason') or '')[:40]}")
            continue
        # column 2: rank with the form-NEUTRAL identity, as a turn would
        nq = _neutral(english_q) if english_q else ent
        nw, _ = best_candidate(nq, cands)
        state = cooked_preference_state(nq)
        c_naive, alt = _conflict(w, cands, prep)
        c_neutral, _ = _conflict(nw, cands, prep)
        c_sharp = c_neutral and state == COOKED_PREFERRED
        for flag, bucket in ((c_naive, naive), (c_neutral, neutral_flag), (c_sharp, sharp)):
            if flag: bucket.append(name)
        rec |= {"winner": w.get("description"), "priced_via": via, "cooked_alternatives": alt,
                "conflict_naive": c_naive, "neutral_query": nq,
                "neutral_winner": nw and nw.get("description"), "conflict_neutral": c_neutral,
                "cooked_pref_state": state, "conflict_sharp": c_sharp}
        rows_out.append(rec)
        mark = "HIT" if (c_sharp and name in KNOWN_WRONG) else "FP " if c_sharp else "ok "
        print(f"   {mark} {name[:18]:20} via={str(w.get('description'))[:30]:32} "
              f"neutral[{nq[:22]:24}]={str(nw and nw.get('description'))[:30]:32} "
              f"state={state[:16]:17} naive={int(c_naive)} neut={int(c_neutral)} sharp={int(c_sharp)}")

    def tally(label, flagged):
        tp = len([n for n in flagged if n in KNOWN_WRONG]); fp = len([n for n in flagged if n not in KNOWN_WRONG])
        fn = len([n for n in KNOWN_WRONG if n not in flagged])
        print(f"{label:44} hit={tp}  false_positive={fp}  missed={fn}" + ("   <- 0 FP" if not fp else ""))
        return fp
    blanks = collections.Counter((x.get("status"), x.get("failure_class")) for x in rows_out if x.get("winner") is None)
    print(f"\nno-winner rows by (status, class): {dict(blanks)}")
    tally("NAIVE (ranked with the retrieval query):", naive)
    tally("NEUTRAL (form words stripped before ranking):", neutral_flag)
    tally("SHARP (neutral AND cooked-preferred food):", sharp)
    pathlib.Path("/tmp/runtime_form_conflicts.json").write_text(json.dumps(rows_out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
