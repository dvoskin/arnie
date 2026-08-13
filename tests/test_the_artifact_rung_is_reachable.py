"""EVERY IDENTITY THE ARTIFACT COMMITS MUST BE PRICEABLE FROM IT.

Building evidence and being unable to reach it is worse than not having it:
the retrieval ran, the model judged, a person reviewed, the rows were
committed — and then the turn prices from a lower rung anyway, silently,
because `_from_artifact` returns None when the ranker matches nothing and
`price()` simply falls through.

⭐ THE DEFECT THIS FILE PINS DOWN. `_ranker_query` composes the identity
correctly — "mackerel, roasted" — and hands it to `best_candidate`, which
cannot match it against "Fish, mackerel, Atlantic, cooked, dry heat". Bare
"mackerel" matches the same row. So the composed query is the thing that
breaks it, and committed identities price from nothing:

    banana|            'banana' misses "Bananas, raw"      (singular/plural)
    potato|            'potato' misses "Potatoes, ..."     (singular/plural)
    oats|              'oats'   misses "Cereals, oats, ..."(category prefix)
    mackerel|roasted   the preparation term breaks a match that works bare
    tilapia|roasted    the preparation term breaks a match that works bare

This is the identity-boundary lesson at one more consumer: A CANONICALISATION
IS ONLY AS GOOD AS ITS LEAST CAREFUL CONSUMER. Fixing the query without
fixing the ranker built a system that can FIND evidence it cannot USE.

⭐⭐ AND IT FAILS CLOSED AND SILENT, which is why nothing caught it. There is
no error, no log, no metric — the rung yields None and the next rung answers.
`mackerel|roasted` is the identity this entire migration started from.

⭐⭐⭐ HOW MANY DEPENDS ON A PER-USER FEATURE FLAG, WHICH IS WHY THE FIRST
MEASUREMENT WAS WRONG. `best_candidate` branches on `NUTRITION_ACCURACY_V2`,
and V2 strips preparation tokens before measuring coverage. Measured locally
with the flag unset, five identities are unreachable; with it set, three of
those five recover. Production runs `effective: allowlist`, so BOTH modes are
live at once and reachability differs BY USER. Only the two singular/plural
misses fail in every mode — so those are the unconditional defect and the
other three are conditional on a flag nobody would think to check.

The reachability gates are `xfail(strict=True)`: they encode the defect
without reddening the board, and they will FAIL the moment the ranker is
fixed, which is the signal to delete the marker.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager

import pytest

from core.canonical_pricing import _ranker_query
from core.food_intelligence import best_candidate
from skills.nutrition import pricing_artifact as art

#: Measured 2026-08-13 against the committed artifact, per flag mode. Never
#: guessed, and never stated without its mode — the mode IS the finding.
UNREACHABLE_V2_OFF = {"banana|", "potato|", "oats|", "mackerel|roasted",
                      "tilapia|roasted"}
UNREACHABLE_V2_ON = {"banana|", "potato|"}

#: Fails in EVERY mode. A plain noun cannot reach USDA's plural heading.
UNREACHABLE_ALWAYS = UNREACHABLE_V2_OFF & UNREACHABLE_V2_ON


@contextmanager
def _v2(active: bool):
    """⭐ THE INSTRUMENT CHECK. A reachability number measured in one flag
    mode and reported as "the" number is a wrong number."""
    previous = os.environ.get("NUTRITION_ACCURACY_V2")
    os.environ["NUTRITION_ACCURACY_V2"] = "1" if active else ""
    try:
        from core.food_intelligence import _nutrition_accuracy_v2
        assert _nutrition_accuracy_v2() is active, (
            "the flag did not take effect — this measurement would be of the "
            "wrong mode, which is exactly the error this wrapper prevents")
        yield
    finally:
        if previous is None:
            os.environ.pop("NUTRITION_ACCURACY_V2", None)
        else:
            os.environ["NUTRITION_ACCURACY_V2"] = previous


def _entries():
    if not art.ARTIFACT_PATH.exists():
        pytest.skip("no committed artifact")
    doc = json.loads(art.ARTIFACT_PATH.read_text())
    return {k: v for k, v in (doc.get("entries") or {}).items()
            if (v.get("candidates") or ())}


def _winner(key, entry):
    entity, _, preparation = key.partition("|")
    return best_candidate(_ranker_query(entity, preparation),
                          list(entry.get("candidates") or ()))[0]


@pytest.mark.parametrize("v2_on, known", [(False, UNREACHABLE_V2_OFF),
                                          (True, UNREACHABLE_V2_ON)])
def test_the_committed_identities_that_can_be_priced_still_can(v2_on, known):
    """A REGRESSION FLOOR PER MODE, so the reachable set cannot quietly shrink
    in one flag state while the other stays green."""
    entries = _entries()
    with _v2(v2_on):
        broken = sorted(k for k, v in entries.items()
                        if k not in known and _winner(k, v) is None)
    assert broken == [], (
        f"with V2 {'on' if v2_on else 'off'}, {len(broken)} identities became "
        f"unreachable: {broken}. Evidence was retrieved, judged and "
        f"committed, and the turn will price from a lower rung without "
        f"saying so")


def test_reachability_depends_on_a_per_user_flag(worksheet=None):
    """⭐ THE FINDING ITSELF, pinned so it cannot be forgotten: the same
    artifact yields DIFFERENT reachable sets under the two flag modes, and
    production runs both at once via the allowlist."""
    entries = _entries()
    with _v2(False):
        off = {k for k, v in entries.items() if _winner(k, v) is None}
    with _v2(True):
        on = {k for k, v in entries.items() if _winner(k, v) is None}
    assert off == UNREACHABLE_V2_OFF, off
    assert on == UNREACHABLE_V2_ON, on
    assert on < off, "V2 no longer changes reachability — re-measure both"
    assert UNREACHABLE_ALWAYS == on, (
        "the mode-independent failures changed; the singular/plural defect is "
        "the one that reaches every user")


@pytest.mark.xfail(strict=True, reason="the ranker cannot match a composed "
                                       "identity against USDA naming — "
                                       "delete this marker when it is fixed")
@pytest.mark.parametrize("v2_on", [False, True])
def test_every_committed_identity_is_reachable(v2_on):
    entries = _entries()
    with _v2(v2_on):
        unreachable = sorted(k for k, v in entries.items()
                             if _winner(k, v) is None)
    assert unreachable == [], (
        f"{len(unreachable)} of {len(entries)} committed identities price "
        f"from NOTHING with V2 {'on' if v2_on else 'off'}: {unreachable}")


@pytest.mark.xfail(strict=True, reason="singular/plural and the USDA category "
                                       "prefix defeat the ranker")
@pytest.mark.parametrize("v2_on", [False, True])
@pytest.mark.parametrize("query, expected_fragment", [
    ("banana", "Bananas"),
    ("potato", "Potatoes"),
])
def test_a_singular_request_matches_the_plural_record(query, expected_fragment,
                                                      v2_on):
    """⭐ THE MODE-INDEPENDENT DEFECT. Both flag states fail this, so it
    reaches every user rather than only the ones outside the allowlist."""
    entry = _entries().get(f"{query}|")
    if entry is None:
        pytest.skip(f"{query} not committed")
    with _v2(v2_on):
        winner, _ = best_candidate(query, list(entry.get("candidates") or ()))
    assert winner is not None and expected_fragment.lower() in str(
        winner.get("description", "")).lower()


@pytest.mark.xfail(strict=True, reason="with V2 OFF a preparation term in the "
                                       "query breaks a match that works "
                                       "without it; V2 ON strips prep tokens "
                                       "and recovers these")
@pytest.mark.parametrize("key", ["mackerel|roasted", "tilapia|roasted"])
def test_naming_the_preparation_does_not_lose_the_food(key):
    """⭐ THE SHARPEST FORM OF THE DEFECT. Bare `mackerel` matches the very
    row that `mackerel, roasted` cannot — so ASKING FOR MORE finds LESS."""
    entries = _entries()
    if key not in entries:
        pytest.skip(f"{key} not committed")
    entity, _, preparation = key.partition("|")
    candidates = list(entries[key].get("candidates") or ())

    with _v2(False):
        bare, _ = best_candidate(entity, candidates)
        assert bare is not None, "the bare food does not match either"
        composed, _ = best_candidate(_ranker_query(entity, preparation),
                                     candidates)
    assert composed is not None, (
        f"{entity!r} matches {bare.get('description')!r} but "
        f"{_ranker_query(entity, preparation)!r} matches nothing")
