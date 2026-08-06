"""WHICH candidates become offers. A versioned, pure policy.

    CandidateSet + CandidateSelectionContext + policy version
        -> selected candidates, and a typed reason for every other one

That is the whole contract. The selector reads PERSISTED FEATURES of
candidates it is given and nothing else: it retrieves no evidence, mutates no
candidate, converts no quantity and renders no label. Anything it needed to go
and fetch would be a feature the decision record could not explain afterwards,
which defeats the point of persisting the universe at all.

WHY LABELS ARE NOT HERE. Collapsing two options because they READ the same is
a real rule — `5 oz` and `6 oz` are two chips and one choice — but it is a
judgement about wording, under one renderer, in one locale. Selection decides
what a candidate MEANS; presentation decides what it SAYS. Keeping them
separate is what lets `RENDER_COLLISION` be attributed to a renderer version
rather than blamed on the policy, and what stops a locale that words two
candidates differently from silently getting a different selection.

POLICIES ARE REGISTERED, NOT REPLACED. A new policy is a new entry with a new
version, so decisions taken under the old one keep meaning what they meant.
`b1_quantity_select_v1` is the baseline: it reproduces the behaviour shipped
before this module existed, to the option.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from fractions import Fraction
from typing import Callable, Dict

logger = logging.getLogger(__name__)

#: The policy production uses. Bumped only when the RULE changes — never for a
#: refactor that selects the same candidates, because two versions that decide
#: identically would split one population for no reason.
SELECTION_POLICY_VERSION = "b1_quantity_select_v1"

#: Two masses closer than this say the same thing. Kept at the shipped value:
#: v1 exists to reproduce current behaviour, and a policy that also retunes a
#: constant could not be compared with what it replaced.
#:
#: EXACT RATIONAL. Neither `hi / lo < ratio` NOR `hi < lo * ratio` is safe in
#: `Decimal`: both are arithmetic, and every Decimal operation is governed by
#: the ambient context's precision and rounding. Measured:
#:
#:     lo=100.1  hi=125.1  ratio=1.25   exact product 125.125, so hi < it
#:     prec=3 ROUND_DOWN -> 125  ->  False
#:     prec=3 ROUND_UP   -> 126  ->  True
#:
#: The same comparison, two answers, decided by process-wide state no caller
#: set. `Fraction` has no context and no rounding — the arithmetic is exact or
#: it does not happen.
NEAR_DUPLICATE_RATIO = Fraction(Decimal("1.25"))

_POLICIES: Dict[str, Callable] = {}


def register(version: str):
    """Add a policy. Registration is how a version becomes selectable."""
    def _register(fn):
        if version in _POLICIES:
            raise ValueError(
                f"{version} is already registered — a policy version names "
                f"one rule forever, so redefining it would silently change "
                f"what past decisions claimed to be")
        _POLICIES[version] = fn
        return fn
    return _register


def registered() -> frozenset:
    return frozenset(_POLICIES)


def select(universe, *, context, policy_version: str = SELECTION_POLICY_VERSION):
    """Run a registered policy. Returns `(selected, exclusions)`.

    `selected` is ordered as the row will be read; `exclusions` are
    `(candidate_id, ExclusionReason)` pairs. Every generated candidate appears
    in exactly one of them — the aggregate proves that on construction, and
    this returns the material for it.
    """
    try:
        policy = _POLICIES[policy_version]
    except KeyError:
        raise ValueError(
            f"{policy_version!r} is not a registered selection policy; "
            f"known: {sorted(_POLICIES)}") from None
    selected, exclusions = policy(universe, context)
    _assert_partition(universe, selected, exclusions, policy_version)
    return selected, exclusions


def _assert_partition(universe, selected, exclusions, policy_version):
    """A POLICY THAT LOSES A CANDIDATE IS A BUG IN THE POLICY.

    The aggregate catches it later, but by then the message is about a record
    rather than about the rule that produced it — and a new policy is exactly
    where this mistake gets made.
    """
    decided = ([c.candidate_id for c in selected]
               + [cid for cid, _r in exclusions])
    if len(decided) != len(set(decided)):
        raise ValueError(
            f"{policy_version} decided a candidate twice: {sorted(decided)}")
    if set(decided) != set(universe.candidate_ids):
        missing = sorted(set(universe.candidate_ids) - set(decided))
        invented = sorted(set(decided) - set(universe.candidate_ids))
        raise ValueError(
            f"{policy_version} did not account for every candidate — "
            f"missing {missing}, invented {invented}")


def rank_of(candidate) -> Fraction:
    """`prior x best evidence confidence`, both read off the candidate.

    THE PERSISTED FEATURES AND NOTHING ELSE. Recomputing either from its
    source would make the ranking unexplainable from the record, which is the
    property the whole universe exists to provide.

    It also gives the authority ladder for free rather than by a special case:
    a user-history candidate carries prior 0.55 at confidence 0.9, an ontology
    median 0.5 at 0.6 — so someone's own logged portion outranks the
    population's typical one without the rule ever naming a source.

EXACT RATIONAL, NOT FLOAT AND NOT DECIMAL.

    `float()` was the first hole: two Decimal scores differing in the 18th
    place collapse to one binary float, and generation order silently becomes
    the tie-breaker.

    `Decimal` was the second, and subtler. `prior * best` is arithmetic, and
    every Decimal operation is governed by the ambient context — so at a
    reduced precision two distinguishable candidates round to one score and
    the tie-break fires again, decided by process-wide state no caller set.
    `Fraction` has no context: the product of two exact rationals is exact.
    """
    best = max((Fraction(Decimal(str(e.confidence)))
                for e in candidate.evidence if e.confidence is not None),
               default=Fraction(0))
    prior = (Fraction(Decimal(str(candidate.prior)))
             if candidate.prior is not None else Fraction(0))
    return prior * best


def _near(a, b) -> bool:
    """Within `NEAR_DUPLICATE_RATIO`, decided in EXACT RATIONAL ARITHMETIC.

    Avoiding division was not enough. `hi < lo * ratio` is still a Decimal
    multiplication, and Decimal multiplication rounds to the ambient
    context — so the same pair of masses answers differently under
    ROUND_DOWN and ROUND_UP at a reduced precision, which is precisely the
    nondeterminism this was meant to remove. `Fraction` has neither precision
    nor rounding.
    """
    lo, hi = min(a, b), max(a, b)
    if lo <= 0:
        return False
    return Fraction(Decimal(str(hi))) < Fraction(Decimal(str(lo))) * (
        NEAR_DUPLICATE_RATIO)


def _says_the_same_thing(a, b) -> bool:
    """Quantity-equivalent AND on the same basis.

    THE BASIS CHECK IS NOT DECORATION. `1 piece` and `1 g` can be numerically
    adjacent and mean nothing like each other; collapsing them because the
    numbers are close would delete a genuinely distinct option and record it
    as a duplicate. Distinct bases are distinct choices.
    """
    from core.semantics import measure_on

    if a.serving_basis is not b.serving_basis:
        return False
    lhs = measure_on(a.quantity, a.serving_basis)
    rhs = measure_on(b.quantity, b.serving_basis)
    return lhs is not None and rhs is not None and _near(lhs, rhs)


@register(SELECTION_POLICY_VERSION)
def _v1(universe, context):
    """THE BASELINE. Reproduces the behaviour shipped before this module.

    NOT top-N by probability — that returns near-duplicates, which is how
    `4.8 / 5.0 / 5.2` reached a screen. Rank by `prior x confidence`, then
    accept a candidate only if it says something the already-accepted ones do
    not: information gain, expressed as distance.

    The cap comes from the CONTEXT, not from a constant here, because how many
    options fit is a property of the surface — three in a sentence, more in a
    chip row — and a policy that hardcoded it could not be reused across
    channels.
    """
    from core.semantics import ExclusionReason

    selected, exclusions = [], []
    for cand in _by_rank(universe):
        if len(selected) >= context.maximum_options:
            exclusions.append((cand.candidate_id,
                               ExclusionReason.SELECTION_CAP))
            continue
        if any(_says_the_same_thing(cand, kept) for kept in selected):
            exclusions.append((cand.candidate_id,
                               ExclusionReason.SEMANTIC_DUPLICATE))
            continue
        selected.append(cand)

    # ASCENDING, because a row of portions that does not climb reads as
    # unordered. Presentation order, decided here because it is part of the
    # decision the user sees.
    selected.sort(key=_ascending_key)
    return tuple(selected), tuple(exclusions)


def _by_rank(universe):
    """Highest rank first, with an EXPLICIT tie-break.

    Equal ranks used to be resolved by `sorted`'s stability, i.e. by whatever
    order the generator happened to emit — a real rule, written nowhere. It is
    stated here instead: ties go to the earlier-generated candidate, which is
    the authority ladder's own order.
    """
    ordered = list(enumerate(universe.candidates))
    ordered.sort(key=lambda pair: (-rank_of(pair[1]), pair[0]))
    return [cand for _position, cand in ordered]


def _ascending_key(candidate):
    from core.semantics import measure_on

    amount = measure_on(candidate.quantity, candidate.serving_basis)
    # Bases are grouped so a mixed row stays coherent; within a basis, by
    # amount. Sorting across bases by raw number would interleave `2 pieces`
    # between `85 g` and `226 g`. Decimal, so two amounts that differ below
    # float precision keep their order rather than tying arbitrarily.
    return (candidate.serving_basis.value,
            amount if amount is not None else Decimal(0))
