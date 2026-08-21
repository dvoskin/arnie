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
