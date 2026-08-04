"""Synthetic identity cases, for the variability no authored list covers.

Production inputs are unavailable in this environment (no `DATABASE_URL`;
`/admin/audit` returns raw messages and per-day totals but no message-to-parse
mapping, so nothing in it is labelled). So the corpus is grown synthetically
and is labelled as such — a synthetic case proves the SHAPE is handled and
proves nothing about how often that shape occurs.

GENERATED FROM FAMILIES, NOT WRITTEN OUT. Each family is a rule about how real
food language varies, applied across the registry's own vocabulary. That keeps
the corpus honest in a way a hand-written list is not: it cannot quietly
contain only the cases the implementation already passes, because the inputs
are derived from the entity table rather than from memory of what was fixed.

MOST OF THIS CORPUS IS CIRCULAR, AND THAT LIMITS WHAT PASSING IT MEANS.

The plural and relation families are generated FROM `_ENTITIES` and tested
against a resolver that READS `_ENTITIES`. They therefore prove the lookup
works — that a declared alias resolves, that a declared subtype unifies and a
declared ingredient does not. They prove nothing about whether the declarations
are RIGHT: a wrong parent row produces a wrong pair and a passing test.

The non-circular families are the ones worth the most per case:

  * casing/punctuation — generated names, but tested against the NORMALISER,
    which does not read the table. A comma defeated `resolve` entirely and this
    family is what would have caught it.
  * unrelated — a control group. A corpus containing only near-misses cannot
    show that ordinary pairs still behave.

`tests/data/identity_collisions.py` remains the non-circular ground truth: its
36 pairs were labelled from the directive's families by hand, BEFORE the
registry existed, so the registry cannot have defined them into agreement.

WHAT IS DELIBERATELY NOT HERE. Misspellings, speech-to-text errors, branded
products, restaurant dishes and non-English aliases are all named by the
directive and NONE of them is generated, because a synthetic misspelling tests
a spellchecker nobody has written and would pass or fail for reasons unrelated
to identity. Those families need real inputs. They are listed in
`UNCOVERED_FAMILIES` so the gap is a value in the code rather than a note.
"""
from skills.nutrition.entities import _ENTITIES, Relation, UNIFYING

#: Families the directive requires that synthetic data CANNOT honestly cover.
#: Each needs production or curated real-world input.
UNCOVERED_FAMILIES = (
    "misspellings",
    "speech-to-text errors",
    "branded products",
    "restaurant dishes",
    "multilingual and transliterated aliases",
    "user-specific terminology",
    "mixed food lists in one message",
)


def _entities_with(relation):
    return [(e, t) for e in _ENTITIES.values()
            for r, t in e.relations if r is relation]


def _casing_and_punctuation():
    """The same food, written the way a person actually types it.

    A comma defeated `resolve` entirely until 2026-08-04 — "White rice, cooked"
    is not an edge case, it is how the interpreter names food.
    """
    out = []
    for eid, ent in list(_ENTITIES.items())[:40]:
        n = ent.canonical_name
        for variant in (n.upper(), n.title(), f"{n},", f"  {n}  ", f"{n}."):
            out.append((n, variant, True, "casing/punctuation"))
    return out


def _plurals():
    """Every registered plural against its singular. The failure that wrote a
    potato twice was exactly this, and it survived because nothing enumerated
    it."""
    out = []
    for ent in _ENTITIES.values():
        for alias in ent.aliases:
            if alias.text != ent.canonical_name:
                out.append((ent.canonical_name, alias.text, True, "plural"))
    return out


def _unifying_relations():
    """Every declared same-food edge, in both directions. `_undeferred` sees
    two readings of one message and neither is guaranteed to be the narrower,
    so both orders must agree."""
    out = []
    for rel in UNIFYING:
        for ent, target in _entities_with(rel):
            t = _ENTITIES.get(target)
            if t:
                out.append((t.canonical_name, ent.canonical_name, True,
                            rel.value))
                out.append((ent.canonical_name, t.canonical_name, True,
                            f"{rel.value} (reversed)"))
    return out


def _ingredient_edges():
    """THE DANGEROUS FAMILY. A dish made with a food is not that food, and
    every one of these shares a token with it — which is precisely the shape a
    string rule collapses. Each pair here is a row that would disappear."""
    out = []
    for ent, target in _entities_with(Relation.INGREDIENT_OF):
        t = _ENTITIES.get(target)
        if t:
            out.append((t.canonical_name, ent.canonical_name, False,
                        "ingredient_of — made with, not the same as"))
    return out


def _distinct_entities():
    """Foods declared to stand alone, against every registered food whose name
    they contain. Peanut butter against butter, generalised."""
    out = []
    names = {e.canonical_name for e in _ENTITIES.values()}
    for ent, _ in _entities_with(Relation.DISTINCT):
        for word in ent.canonical_name.split():
            if word in names and word != ent.canonical_name:
                out.append((word, ent.canonical_name, False,
                            "declared distinct — nothing may claim it"))
    return out


def _unrelated_pairs():
    """Foods with nothing in common. The control group: a corpus that only
    contains near-misses cannot show that ordinary pairs still behave."""
    names = sorted(e.canonical_name for e in _ENTITIES.values())
    out = []
    for i in range(0, min(len(names), 60), 3):
        a, b = names[i], names[(i + 17) % len(names)]
        if a != b and not set(a.split()) & set(b.split()):
            out.append((a, b, False, "unrelated"))
    return out


def synthetic_pairs():
    """(narrow, wide, same, family) for every generated case."""
    out = []
    for fn in (_casing_and_punctuation, _plurals, _unifying_relations,
               _ingredient_edges, _distinct_entities, _unrelated_pairs):
        out.extend(fn())
    # De-duplicate while keeping the first family that produced each pair.
    seen, uniq = set(), []
    for a, b, same, why in out:
        key = (a.lower(), b.lower())
        if key not in seen:
            seen.add(key)
            uniq.append((a, b, same, why))
    return uniq


SYNTHETIC_PAIRS = synthetic_pairs()
