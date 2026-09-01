"""ACQUIRE — establishing a food Arnie has never seen, on first encounter.

⭐⭐⭐ THE ONE SENTENCE THIS MODULE EXISTS FOR *(Danny, sequencing directive
2026-08-31)*: "The corpus tells us whether Arnie improved. It does not tell us
what foods to build Arnie for."

The 9.0% ownership number has ONE root cause, measured three ways: canonical
holds authoritative evidence for 27 foods, and that catalog was hand-seeded
from a list whose own generator admits `"seems likely someone will log this" is
NOT a criterion`. Every attempt to raise ownership by ADDING to that list is
memorising the evaluation set. The 68 exact-mass meals contain 54 identities,
46 of which appear exactly ONCE — a long tail is not a backlog, it is the
argument for a MECHANISM.

    look()  = do I already hold admissible local evidence?   →  miss  →  legacy
    ACQUIRE = can I ESTABLISH admissible evidence right now?  →  hit   →  canonical

⛔⛔⛔ ACQUISITION RETURNS FACTS, NEVER A DECISION. This is the entire safety
contract and it is enforced structurally, not by review:

  * `AcquiredEvidence` has NO boolean field, and `__post_init__` refuses any
    field whose NAME is a decision (`supported`, `authoritative`, `has_*`,
    `priced`, `settled`, `owned`). The counterfactual experiment already made
    this mistake once, in a script, and reported "evidence recovers 0 meals"
    followed by "scaling is the lever" — BOTH artifacts of flipping the
    booleans that `decide()` is supposed to DERIVE. `selected_rung_authoritative
    = False` does not mean "cannot scale", it means NO RUNG WAS SELECTED.
    A producer that sets outcomes cannot discover that its subject is broken.

  * There is no channel from here to settlement except PERSISTED EVIDENCE.
    `acquire()` cannot hand a verdict to anybody. What it can do is write a
    canonical evidence record, which `assemble()` then reads by the same local
    read it already performs, feeding the SAME artifact rung under the SAME
    `select_priced_rung` → `resolve_scaling` → `decide()` ladder. Acquisition
    is structurally incapable of bypassing the gates because it never touches
    them.

⛔⛔ AND IT MAY NEVER LAUNDER A GUESS INTO AUTHORITY. The failure mode that
would quietly destroy the metric is:

    legacy estimated 487 calories  →  write artifact  →  now "canonical"

Ownership would climb, authority would be gone, and the number would be
measuring its own contamination. So `authority_grade` is a CLOSED vocabulary of
source classes, `ESTIMATE`/`WEB`/`MODEL` are not members of it, and there is no
code path that constructs `AcquiredEvidence` from interpreter numbers.

⭐ THE CAPABILITY ALREADY EXISTS — AS A BATCH SCRIPT. `build_pricing_artifact`
retrieves from `api.usda`, qualifies identity through `qualify_usda_rows`, and
writes candidates keyed by `pricing_artifact.key`. That is acquisition, run
offline against a guessed seed list. This module does not reinvent any of it;
it reuses those exact producers and changes only WHEN they run (at first
encounter, driven by demand) and WHERE the result lands (a durable store, not a
committed JSON file that production cannot write and Render's ephemeral
per-instance filesystem could not keep).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, fields
from typing import Mapping, Optional

logger = logging.getLogger(__name__)


# ⛔⛔ A CLOSED VOCABULARY OF SOURCE CLASSES, AND ESTIMATE IS NOT IN IT.
# `authority_grade` answers "what KIND of authority is this", which is the
# question the rung ladder already asks. It deliberately does NOT answer
# "is this good enough" — `select_priced_rung` owns that, as it always has.
SOURCED_COMPOSITION = "sourced_composition"   # USDA Foundation / SR Legacy / Survey
PACKAGE_DECLARED = "package_declared"          # OFF / manufacturer panel, barcode-bound

#: The grades that may become durable canonical evidence. Membership is checked
#: at construction: a grade not listed here cannot be represented at all, so
#: "we accidentally admitted web text" is not a bug that can be written.
ADMISSIBLE_GRADES = frozenset({SOURCED_COMPOSITION, PACKAGE_DECLARED})

#: ⛔ NAMES THAT WOULD MAKE THIS A DECISION. Checked over the dataclass fields
#: themselves so the refusal survives someone ADDING a field in good faith.
_DECISION_NAMES = ("supported", "authoritative", "priced", "settled", "owned",
                   "covered", "eligible", "admissible", "approved")


class AcquisitionRefused(Exception):
    """Acquisition declined, with a NAMED reason.

    ⭐ NAMED, because `PRICEABILITY_*` already proved the value: a refusal that
    logs a reason string is a refusal you can COUNT, and the count is how the
    next tranche learns which adapter to build. An anonymous `return None`
    produces a coverage miss indistinguishable from "we never tried".
    """

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}: {detail}" if detail else reason)


# Reasons. Every one of these is a MEASURABLE outcome, not an error.
NO_IDENTITY = "ACQUIRE_NO_IDENTITY"                 # nothing to look up
NO_SOURCE_RECORD = "ACQUIRE_NO_SOURCE_RECORD"       # provider returned nothing
IDENTITY_UNQUALIFIED = "ACQUIRE_IDENTITY_UNQUALIFIED"   # rows found, none IS this food
GRADE_INADMISSIBLE = "ACQUIRE_GRADE_INADMISSIBLE"   # source is not an authority class
BASIS_UNUSABLE = "ACQUIRE_BASIS_UNUSABLE"           # numbers exist on no stateable basis
PROVIDER_UNAVAILABLE = "ACQUIRE_PROVIDER_UNAVAILABLE"   # network/quota — NOT an absence


@dataclass(frozen=True)
class AcquiredEvidence:
    """What was ESTABLISHED about one food. Ten facts, zero decisions.

    ⛔ Every field answers "what is true about the source record", and none
    answers "what should the pipeline do". If you find yourself wanting to add
    a field that settlement would branch on, that branch belongs in `decide()`
    where it can be tested against its negative case.
    """

    #: The artifact key — `pricing_artifact.key(entity, preparation)`. THE SAME
    #: keying the file artifact uses, so acquired and seeded evidence are
    #: indistinguishable downstream and there is exactly one identity vocabulary.
    canonical_identity: str

    #: WHY this provider record is this food: the qualification trace, verbatim
    #: from `qualify_usda_rows`/`qualify_off_product`. Kept because "how did a
    #: wrong food become canonical" must be answerable from the durable row —
    #: the Barebells false positive (SAME_IDENTITY 0.85 on a different product
    #: line) is exactly the case that needs it.
    identity_evidence: Mapping

    #: Qualified candidates in the artifact's own candidate shape. NOT a chosen
    #: winner: `best_candidate` still picks, deterministically, downstream.
    #: Storing the winner would move ranking authority into a model.
    nutrition_evidence: tuple

    source_type: str            # "usda" | "off" | "manufacturer"
    source_identifier: str      # fdc_id | barcode | SKU — the record's own key
    authority_grade: str        # a member of ADMISSIBLE_GRADES

    #: "per_100g" | "per_serving". STATED, never inferred: the OFF probe found
    #: `nutrition_data_per='100ml'` poisoning the `_100g` keys, and a basis that
    #: is assumed rather than read is how per-bar numbers became per-100g.
    nutrition_basis: str

    #: `SourcedMeasure`-shaped conversions this record licenses, if any. Empty
    #: is normal and is NOT a defect — most generic composition records carry no
    #: serving basis, which is precisely why the exact-mass slice comes first.
    serving_basis: tuple

    #: Which quantity EXPRESSIONS this evidence can price without guessing.
    #: A fact about the record, not a permission: `resolve_scaling` still
    #: decides, and it remains the only thing that may call a scaling
    #: authoritative.
    quantity_compatibility: frozenset

    #: Dataset id/version, record version, retrieval fingerprint, acquired_at.
    #: `dataset_version` may NEVER be derived from today's date — USDA publishes
    #: explicit releases and a placeholder would be baked into durable records
    #: as the thing a correction cites.
    provenance: Mapping

    def __post_init__(self):
        for f in fields(self):
            low = f.name.lower()
            if low.startswith("has_") or low.startswith("is_") or \
                    any(d in low for d in _DECISION_NAMES):
                raise TypeError(
                    f"AcquiredEvidence.{f.name} names a DECISION. Acquisition "
                    "reports facts; decide() derives verdicts. See the module "
                    "docstring — this refusal is the safety contract.")
        if self.authority_grade not in ADMISSIBLE_GRADES:
            raise AcquisitionRefused(
                GRADE_INADMISSIBLE,
                f"{self.authority_grade!r} is not an authority class")
        if not self.canonical_identity:
            raise AcquisitionRefused(NO_IDENTITY, "empty canonical identity")
        if not self.nutrition_evidence:
            # ⭐ ZERO CANDIDATES IS A REFUSAL, NOT AN EMPTY SUCCESS. An artifact
            # entry with no candidates reads as a HIT at the rung and then
            # prices nothing — `evidence_for` already guards this on the read
            # side; guarding the write side too means the bad row never exists.
            raise AcquisitionRefused(IDENTITY_UNQUALIFIED, "no qualified candidate")
