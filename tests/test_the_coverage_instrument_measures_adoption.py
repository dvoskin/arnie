"""⭐ THE INSTRUMENT THAT RE-SEQUENCED THE ROADMAP, GATED.

`scripts/measure_identity_coverage.py` produced the number the whole plan now
turns on — the committed artifact DECIDES 1.9% of real logged food — and a
measurement that carries that much weight has to be unable to drift quietly.

⛔ THE FAILURE THESE GATES EXIST FOR IS SPECIFIC AND I MADE IT ONCE. Measuring
artifact reachability in isolation says 28 of 691 entries are priceable. Asking
the LADDER, in the ladder's own order, says 13 — because `Rung.MEMORY` outranks
`Rung.ARTIFACT` and had already claimed 15 of them. Both numbers are true. Only
one of them is the artifact's contribution, and the difference decided whether
the five oils were the next tranche or the last one.

So the load-bearing gate here is a NEGATIVE one: reordering the ladder inside
the instrument must not be possible without a test going red.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

from scripts import measure_identity_coverage as mic


def test_memory_is_asked_before_the_artifact_because_the_ladder_does():
    """⭐ THE ONE THAT PROTECTS THE HEADLINE.

    `price()` tries memory, product, artifact, estimate — first rung that can
    produce numbers wins. An instrument that checks the artifact first reports
    a CAPABILITY as an ADOPTION, inflating `artifact_decides` from 13 to 28 and
    deleting the reason the roadmap was re-sequenced.
    """
    # ⚠ AST, NOT GREP. Both names appear all over this function; what matters
    # is WHICH BRANCH each decides, and only the tree carries that. A textual
    # check would pass on a reordered ladder because the same two words are
    # still present — grep checks spelling, AST checks structure.
    tree = ast.parse(inspect.getsource(mic.measure))
    branch = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.If)
                  and any(isinstance(inner, ast.If) for inner in node.orelse))

    tested_first = {node.id for node in ast.walk(branch.test)
                    if isinstance(node, ast.Name)}
    assert "memory" in tested_first and "has_artifact" not in tested_first, (
        "the instrument now asks the artifact before memory — that measures "
        "what the artifact COULD price, not what it DECIDES, and the two "
        "differ by a factor of two on real production data")


def test_it_calls_the_production_identity_functions_not_a_copy():
    """An instrument that re-derives the predicate it measures can disagree
    with the runtime — exactly what `/health` did for two canary runs."""
    source = pathlib.Path(mic.__file__).read_text()

    for required in ("split_identity", "evidence_for", "normalize_name"):
        assert required in source, (
            f"the instrument no longer calls {required} — a local "
            f"reimplementation would measure a pricer that does not exist")
    assert "def split_identity" not in source and "def evidence_for" not in source, (
        "the instrument has grown its OWN copy of an identity function; it "
        "must ask production's, or its numbers describe nothing shipped")


def test_a_non_ascii_brand_is_an_interpretation_problem_first():
    """⚠ BUCKET ORDER IS LOAD-BEARING. `Барбеллс` is unreachable because the
    key is built from the surface string, not because the PRODUCT rung has no
    producer — fixing the product rung would leave it exactly as unreachable."""
    assert mic.classify("Барбеллс шоколад") == mic.NON_ENGLISH
    assert mic.classify("Помидор") == mic.NON_ENGLISH


def test_the_buckets_separate_the_four_fixes():
    """Each bucket names a DIFFERENT piece of work, which is the only reason
    the breakdown is worth having."""
    assert mic.classify("Barebells Salty Peanut Protein Bar") == mic.BRANDED
    assert mic.classify("Ground turkey, 96% lean") == mic.QUALIFIED
    assert mic.classify("Eggplant") == mic.UNCOVERED


def test_a_bare_uncovered_food_is_not_reported_as_a_modifier_problem():
    """NEGATIVE INVARIANT. `Eggplant` is a genuine artifact gap — the 5.6%
    bucket the oils live in. Misfiling it as QUALIFIED would inflate the
    modifier bucket and make the interpretation boundary look larger than it
    is, which is the direction this instrument must NOT be wrong in, because
    it is the direction that flatters its own conclusion."""
    for bare in ("Eggplant", "Almonds", "Chicken wings"):
        assert mic.classify(bare) != mic.QUALIFIED


def test_the_report_carries_its_own_limits():
    """A number this load-bearing must travel with what it cannot say. The
    limits live in the OUTPUT, not only in a docstring, so a reader who sees
    the JSON and never opens the script still gets them."""
    limits = " ".join(mic.measure.__doc__ or "") if mic.measure.__doc__ else ""
    source = pathlib.Path(mic.__file__).read_text()

    assert '"instrument_limits"' in source or "instrument_limits" in source
    for claim in ("ENTRIES, not turns", "HEURISTIC", "REACHED"):
        assert claim in source, (
            f"the report no longer states the limit {claim!r}; a measurement "
            f"that has lost its caveats reads as stronger than it is")


def test_the_headline_field_is_named_for_adoption_not_capability():
    """⭐ THE NAME IS THE ARGUMENT. `artifact_reachable` and
    `artifact_decides` differ by 15 entries and by an entire roadmap; a field
    called the first would be read as the second."""
    source = pathlib.Path(mic.__file__).read_text()

    assert '"artifact_decides"' in source
    assert '"artifact_reachable"' not in source, (
        "the headline field was renamed to a capability measure — the "
        "distinction between what a producer CAN do and what it IS DOING is "
        "the finding this instrument exists to preserve")
