"""⛔⛔⛔ CF20 — A STATED SIZE MUST BIND TO A MEASURE ABOUT THAT SIZE.

Found while attributing what actually blocks the P17h count positives
(2026-08-21, after P17g merged at `a3b6b9c`). Measured against the real
committed artifact, not constructed:

    "1 large banana"  ->  matched 'extra large (9" or longer)'  ->  152 g
                          the artifact ALSO holds
                          'large (8" to 8-7/8" long)'           =   136 g

⛔ **+11.8% ON A LOG, REPORTED `authoritative=True`, CITING THE WRONG RECORD.**
This is the failure `_matching_measure`'s own docstring forbids — "a citation
that does not match the number it justifies" — and P17g makes it WORSE, not
better: before P17g a sourced conversion merely priced, now it is the thing
that lets canonical OWN the meal. An authoritative path that commits a mass
from the wrong record is the exact class P17g exists to make trustworthy.

⭐ AND "1 extra large banana" AND "1 large banana" WERE INDISTINGUISHABLE. Both
landed on extra-large, so the system could not represent the difference at all.

TWO DEFECTS, ONE SYMPTOM — and either alone still mis-prices:

  a  PRODUCER. `_size_descriptor` scans the text ONE WORD AT A TIME against
     `_SIZE_WORDS`, which contains the two-word entry "extra large". A phrase
     that the reader cannot express is not in the vocabulary no matter what the
     set literal says — the grep-trap shape, again. "extra large banana"
     therefore reported size "large".
  b  CONSUMER. The guard asked `stated_size not in measure_sizes` — token
     MEMBERSHIP. `'extra large (9" or longer)'` has size tokens
     {extra, large}, so a stated "large" was IN it and bound. Worse, that
     record sits EARLIER in the USDA list than the real "large" one, so the
     correct measure was never reached.

The rule is IDENTITY, not containment: `extra large` is a different size from
`large`, exactly as `medium` is.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from skills.nutrition.normalize import normalize_quantity
from skills.nutrition.scaling import (Per100g, SourcedMeasure, _matching_measure,
                                      resolve_scaling)


def _measure(unit_text: str, grams: float) -> SourcedMeasure:
    """A fully-provenanced measure, so `as_basis_conversion()` is real.

    ⚠ A measure missing `dataset_version` yields NO conversion and would be
    non-authoritative for a reason that has nothing to do with this test —
    the vacuity that would make every assertion below pass by accident."""
    return SourcedMeasure(
        unit_text=unit_text, grams_per_unit=grams, source_id=f"usda:{grams}",
        dataset_id="usda_fdc", dataset_version="15.3",
        record_key="banana", record_version="1", immutable_within_version=True,
        data_type="sr_legacy_food", source_fingerprint="fp")


#: THE REAL USDA BANANA PORTIONS, in the artifact's own order — extra-large
#: BEFORE large, which is what turns a containment match into a wrong answer.
BANANA = (_measure("nlea serving", 126.0),
          _measure('extra large (9" or longer)', 152.0),
          _measure('large (8" to 8-7/8" long)', 136.0),
          _measure('medium (7" to 7-7/8" long)', 118.0),
          _measure('small (6" to 6-7/8" long)', 101.0))


@pytest.mark.parametrize("text,unit_text,grams", [
    ("1 large banana", 'large (8" to 8-7/8" long)', 136.0),
    ("2 large bananas", 'large (8" to 8-7/8" long)', 136.0),
    ("1 extra large banana", 'extra large (9" or longer)', 152.0),
    ("1 medium banana", 'medium (7" to 7-7/8" long)', 118.0),
    ("1 small banana", 'small (6" to 6-7/8" long)', 101.0),
])
def test_each_stated_size_binds_to_the_record_about_that_size(text, unit_text,
                                                              grams):
    """⛔ THE WHOLE SIZE LADDER, not just the case that failed. A fix that
    repaired "large" while breaking "extra large" would pass a one-case test
    and still commit the wrong mass — and "extra large" is the case the
    producer defect makes easiest to get wrong."""
    consumed = normalize_quantity(text, "Banana")
    measure = _matching_measure(
        replace(consumed, grams=None, milliliters=None), BANANA)

    assert measure is not None, f"{text!r} matched no sourced measure at all"
    assert measure.unit_text == unit_text, (
        f"{text!r} bound to {measure.unit_text!r} ({measure.grams_per_unit} g) "
        f"— the record describes a different size, so the number and its "
        f"citation disagree; expected {unit_text!r} ({grams} g)")
    assert measure.grams_per_unit == grams


def test_large_and_extra_large_are_not_the_same_log():
    """⛔⛔ THE SYMPTOM THAT MAKES THIS MORE THAN AN OFF-BY-ONE. Both phrases
    resolved to the SAME record, so the system could not represent the
    difference between them — a user who took the trouble to say "extra large"
    got the identical row either way."""
    large = _matching_measure(
        replace(normalize_quantity("1 large banana", "Banana"),
                grams=None, milliliters=None), BANANA)
    xl = _matching_measure(
        replace(normalize_quantity("1 extra large banana", "Banana"),
                grams=None, milliliters=None), BANANA)
    assert large.grams_per_unit != xl.grams_per_unit, (
        "'large' and 'extra large' resolved to the same mass "
        f"({large.grams_per_unit} g) — the stated size is not being read")


def test_the_producer_can_express_every_size_it_claims_to_know():
    """⛔⛔⛔ A VOCABULARY ENTRY THE READER CANNOT EXPRESS IS NOT COVERAGE.

    `_SIZE_WORDS` holds "extra large"; `_size_descriptor` split on whitespace
    and compared WORDS, so that entry could never be returned by any input.
    The set literal read as support for a size the function could not produce
    — and the only reason anyone noticed is that a downstream match went to
    the wrong record.

    So the vocabulary is asserted against the reader, for every multi-word
    entry, rather than for the one that happened to bite."""
    from skills.nutrition.normalize import _SIZE_WORDS, _size_descriptor

    multiword = sorted(w for w in _SIZE_WORDS if " " in w)
    assert multiword, "no multi-word size in the vocabulary — test is stale"
    for phrase in multiword:
        got = _size_descriptor(f"1 {phrase} banana")
        assert got == phrase, (
            f"the vocabulary claims {phrase!r} but the reader returned {got!r} "
            f"— an entry no input can produce")


def test_an_unstated_size_still_binds_to_the_records_own_portion():
    """⭐ THE NEGATIVE INVARIANT. Tightening a stated size must not stop an
    UNSTATED one from binding: "1 banana" has no size claim, so the record's
    own reference portion is the honest answer and refusing it would trade a
    wrong mass for a lost log."""
    eggs = (_measure("large egg", 61.0),)
    measure = _matching_measure(
        replace(normalize_quantity("2 eggs", "Egg"), grams=None,
                milliliters=None), eggs)
    assert measure is not None and measure.grams_per_unit == 61.0, (
        "an unstated size stopped binding to the record's own portion")


def test_a_conflicting_stated_size_still_refuses():
    """⭐ AND THE GUARD THAT ALREADY EXISTED KEEPS WORKING. "2 medium eggs"
    against a large-egg-only measure set must not bind — the case the original
    guard was written for."""
    eggs = (_measure("large egg", 61.0),)
    assert _matching_measure(
        replace(normalize_quantity("2 medium eggs", "Egg"), grams=None,
                milliliters=None), eggs) is None


# ══════════════════════════════════════════════════════════════════════════
# ROUND 2 — THE THREE UNCOVERED HOLES *(Danny, review of `c9e417b`)*
#
# The first round fixed the case it found and left the guard FAIL-OPEN in two
# directions, both reachable, both realistic. A guard that only fires when it
# happens to have vocabulary for both sides is not a guard.
# ══════════════════════════════════════════════════════════════════════════

#: A bare-noun panel measure — what `measure_from_panel` builds from a product
#: label ("1 bar", "1 bottle", "1 cookie") and what USDA states for some generic
#: foods. It carries NO size, which is the whole point: it is a claim about a
#: piece, silent about which piece.
def _bare(noun: str, grams: float) -> SourcedMeasure:
    return _measure(noun, grams)


@pytest.mark.parametrize("word", ["mini", "tiny", "regular", "standard",
                                  "double", "king", "personal"])
def test_a_size_the_matcher_cannot_REPRESENT_refuses(word):
    """⛔⛔⛔ FAIL-OPEN #1 — A SIZE THE USER CAN STATE AND THE MATCHER CANNOT SEE.

    `_SIZE_WORDS` (the producer) and `_SIZE_TOKENS` (the matcher) are two
    vocabularies, and TEN entries live in the first and not the second:
    mini, tiny, regular, standard, double, king, personal, grande, tall, venti.

    For those the guard computes an EMPTY stated-size set, so it never fires,
    and `1 mini bar` binds a full-size `bar` panel — 60 g of protein bar for a
    mini one, reported authoritative. The size was read, understood, and then
    silently discarded by the layer that had to act on it.

    ⭐ REFUSING IS THE ONLY HONEST ANSWER. We cannot evaluate "is this measure
    about a mini bar?" without a token for `mini`, and a question we cannot
    evaluate must not be answered YES. Refusing costs the heuristic path, which
    is non-authoritative and therefore declines canonically — a lost admission,
    never a wrong number."""
    consumed = normalize_quantity(f"1 {word} bar", "Protein bar")
    assert getattr(consumed, "size_descriptor", "") == word, (
        f"the producer stopped reading {word!r} — this test now proves nothing")

    matched = _matching_measure(
        replace(consumed, grams=None, milliliters=None), (_bare("bar", 60.0),))
    assert matched is None, (
        f"'1 {word} bar' bound a size-less `bar` measure ({matched.grams_per_unit} "
        f"g) — the matcher has no token for {word!r}, so it answered a question "
        f"it could not evaluate")


def test_a_sized_claim_refuses_an_UNSIZED_compatible_measure():
    """⛔⛔⛔ FAIL-OPEN #2 — THE GUARD RAN ONLY WHEN BOTH SIDES HAD A SIZE.

    `if stated_sizes and measure_sizes and ...` — so a measure that states NO
    size skipped the comparison entirely. "2 large eggs" against a bare `egg`
    = 50 g panel bound at 50 g: the user named a size, the record is silent
    about size, and silence was read as agreement.

    ⭐ SILENCE IS NOT AGREEMENT. An UNSTATED size may bind to a record's own
    reference portion — the user made no size claim, so the record's default is
    the honest answer. The converse does not hold: once a size IS claimed, a
    record that cannot speak to it cannot satisfy it."""
    consumed = replace(normalize_quantity("2 large eggs", "Egg"),
                       grams=None, milliliters=None)

    matched = _matching_measure(consumed, (_bare("egg", 50.0),))
    assert matched is None, (
        f"a stated 'large' bound a size-less `egg` measure "
        f"({matched.grams_per_unit} g) — the record says nothing about size")


def test_a_sized_claim_still_finds_the_sized_record_past_the_unsized_one():
    """⭐ AND THE NEGATIVE INVARIANT THAT KEEPS #2 FROM BEING A BLUNT REFUSAL.

    Refusing the unsized measure must not stop the ladder: the real `large egg`
    record sits AFTER the bare one, and it is the right answer. A fix that
    returned None here would trade a wrong mass for a lost log."""
    consumed = replace(normalize_quantity("2 large eggs", "Egg"),
                       grams=None, milliliters=None)
    matched = _matching_measure(
        consumed, (_bare("egg", 50.0), _measure("large egg", 61.0)))
    assert matched is not None and matched.grams_per_unit == 61.0, (
        "the sized record after the unsized one was never reached")


# ══════════════════════════════════════════════════════════════════════════
# THE COMMITTED ARTIFACT ITSELF — not measures this test built
#
# ⛔⛔ EVERY ASSERTION ABOVE USES CONSTRUCTED `SourcedMeasure`s, which proves
# the matcher and proves NOTHING about the data production actually hydrates.
# The defect was found against the real artifact and must be pinned there: a
# rebuild that reorders portions, renames a unit, or drops `portion_id` would
# leave every constructed test green.
# ══════════════════════════════════════════════════════════════════════════


def _banana_rung():
    from core.canonical_pricing import _from_artifact, _ranker_query
    from skills.nutrition.pricing_artifact import evidence_for, split_identity

    entity, prep = split_identity("Banana")
    evidence = evidence_for(entity, prep)
    assert evidence is not None, (
        "the committed artifact holds no evidence for `banana` — this suite is "
        "measuring nothing")
    built = _from_artifact(evidence, query=_ranker_query(entity, prep))
    assert built is not None, "the artifact rung produced no candidate"
    return built[4], built[5]                         # source_basis, measures


@pytest.mark.parametrize("text,grams,portion_id", [
    ("1 large banana", 136.0, "93516"),
    ("1 extra large banana", 152.0, "93517"),
    ("1 medium banana", 118.0, "93515"),
    ("1 small banana", 101.0, "93514"),
])
def test_the_REAL_artifact_prices_each_size_from_its_own_record(text, grams,
                                                                portion_id):
    """⛔⛔⛔ AGAINST `data/pricing_evidence_v1.json`, THE FILE PRODUCTION LOADS.

    USDA 173944 states eight portions for a banana, and the two that matter sit
    in the order that made containment matching wrong: `extra large` (152 g)
    BEFORE `large` (136 g).

    ⭐ AND THE CITATION IS ASSERTED, NOT JUST THE NUMBER. `evidence_ids` names
    the FOOD (`usda:173944`) and is identical for all four sizes, so it cannot
    distinguish them; the per-portion identity lives in the conversion's
    `record_key` (`173944#portion:93516`). A number that is right while its
    provenance points at a different portion is the same defect wearing a
    correct answer — so the record ID is pinned per size."""
    basis, measures = _banana_rung()
    resolution = resolve_scaling(basis, normalize_quantity(text, "Banana"),
                                 measures)

    assert resolution.authoritative is True, (
        f"{text!r} is not authoritative against the committed artifact")
    assert resolution.resolved_grams == grams, (
        f"{text!r} resolved to {resolution.resolved_grams} g against the real "
        f"artifact; USDA 173944 states {grams} g")

    source = getattr(resolution.conversion, "source", None)
    assert source is not None, f"{text!r} produced no sourced conversion"
    assert source.record_key == f"173944#portion:{portion_id}", (
        f"{text!r} cites {source.record_key!r} — the conversion must name the "
        f"PORTION it used, not merely the food; expected portion {portion_id}")


def test_the_real_artifact_still_refuses_a_size_it_does_not_hold():
    """⭐ THE ARTIFACT'S OWN NEGATIVE. USDA 173944 states no `jumbo` banana, so
    a jumbo claim must fall to the heuristic path rather than borrow the
    nearest record — the failure direction that costs an admission instead of
    committing a wrong mass."""
    basis, measures = _banana_rung()
    resolution = resolve_scaling(basis,
                                 normalize_quantity("1 jumbo banana", "Banana"),
                                 measures)
    assert resolution.authoritative is False, (
        "a size the artifact does not state was answered authoritatively")


def test_every_compound_size_the_artifact_NAMES_can_be_STATED():
    """⛔⛔ THE TWO VOCABULARIES MUST NOT DRIFT FROM THE EVIDENCE.

    CF20's producer half was "the vocabulary holds a phrase the reader cannot
    express". The mirror is "the EVIDENCE holds a phrase the vocabulary does
    not" — and the artifact carries `extra small (less than 6" long)` = 81 g,
    which no user could state: `_size_descriptor` reads "small" and prices it
    at 101 g, a 24.7% overcount, authoritative, citing the small record.

    So the vocabulary is asserted against the ARTIFACT rather than against
    itself. Single-token phrases are already covered; this pins the compound
    ones, which are the ones a word-at-a-time reader loses.

    ⚠ `x` IS EXCLUDED, AND IT IS NOT A SIZE. It appears only as a DIMENSION
    separator — `can (300 x 407)`, `piece (5-1/2" x 1-1/2" x 1/2")` — and lives
    in `_SIZE_TOKENS` to keep `x-large` distinguishable from `large`. Treating
    those as size claims would be inventing a size from punctuation."""
    import json
    import pathlib
    import re

    from skills.nutrition.normalize import _SIZE_WORDS
    from skills.nutrition.scaling import _SIZE_TOKENS, _unit_tokens

    artifact = json.loads(
        (pathlib.Path(__file__).resolve().parents[1]
         / "data" / "pricing_evidence_v1.json").read_text())

    phrases: set = set()

    def walk(node):
        if isinstance(node, dict):
            for measure in (node.get("measures") or ()):
                text = str(measure.get("unit_text") or "").lower()
                words = re.findall(r"[^\W\d_]+", text)
                run = [w for w in words
                       if (w[:-1] if len(w) > 3 and w.endswith("s") else w)
                       in _SIZE_TOKENS]
                run = [w for w in run if w != "x"]
                if len(run) > 1:
                    phrases.add(" ".join(run))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(artifact)
    assert phrases, "no compound size phrase in the artifact — test is stale"
    missing = sorted(p for p in phrases if p not in _SIZE_WORDS)
    assert not missing, (
        f"the committed artifact names {missing} but no user can state them — "
        f"`_size_descriptor` will read a DIFFERENT size and price from the "
        f"wrong record")


def test_the_resolver_reports_the_size_it_actually_used():
    """⛔ END TO END, THROUGH THE ONE RESOLVER — because `_matching_measure` is
    an internal and the thing that reaches a row is `resolve_scaling`: the
    conversion it cites and the factor it returns must describe the same
    record."""
    resolution = resolve_scaling(
        Per100g(), normalize_quantity("1 large banana", "Banana"), BANANA)
    assert resolution.authoritative is True
    assert resolution.resolved_grams == 136.0, (
        f"the resolver committed {resolution.resolved_grams} g for one large "
        f"banana; the artifact's large record says 136 g")
    assert resolution.evidence_ids == ("usda:136.0",), (
        f"the citation names {resolution.evidence_ids} — a provenance that "
        f"does not describe the number it justifies")
