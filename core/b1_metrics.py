"""B-1's product measurement. One owner, one event name per signal.

CORRECTNESS IS NOT SUCCESS. The directive is explicit about this and names the
failure it is guarding against: a technically correct option system that
frequently forces "Other" has failed, and only measurement can tell you. Every
test in this slice can be green while the chips are useless.

The eleven signals, and what each one would tell you:

    shown                what we asked, from which evidence
    selected             a chip carried the answer
    free_text            the offered options did not fit  <- the "Other" rate
    estimate             "I don't know" — the options did not help either
    repair               we could not read the answer
    abandoned            no answer ever came
    answer_latency_ms    how long the question cost them
    committed            the meal landed
    corrected_within_10m the number was wrong in a way they noticed
    candidate_source     history vs ontology vs fallback
    other_rate           derived: free_text / (selected + free_text)

Emitted as structured log lines with a stable `event=` prefix, because that is
what `/admin/food-traces` can already count and it is how the quick-log
promotion was verified. A metrics backend can consume the same lines later; a
turn may never fail because measurement did.

WHY THE ASK'S TIMESTAMP IS READ BACK RATHER THAN PASSED. Latency and
abandonment are both properties of the GAP between two turns, and only the
stored row spans it. Deriving them from anything the answer turn holds would
measure the answer turn.

THE KEY IS `b1_cohort`, NOT `cohort`. These lines share a log stream with
`event=food_trace`, which carries `skills/nutrition/canary.cohort_label` — the
NUTRITION RESOLVER's rollout, vocabulary `off·shadow·allowlist·canary·control·
live`. What these events carry is `skills/nutrition/quantity_rollout.cohort_label`
— the B-1 QUANTITY rollout, vocabulary `allowlist·cohort·control·off`. Different
env vars, different allowlists, different questions, and on 2026-08-08 they
printed `live` and `allowlist` for one turn under the same key. Both were right.
A reader filtering one name got a population neither of them describes.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: A correction arriving inside this window is evidence the committed number
#: was wrong, not that the user changed their mind about lunch.
CORRECTION_WINDOW_MINUTES = 10


def _ms_since(started) -> Optional[int]:
    if started is None:
        return None
    from core.clock import now as _now

    try:
        return max(0, int((_now() - started).total_seconds() * 1000))
    except Exception:
        return None


def shown(*, operation_id: str, user_id, cohort: str, locale: str,
          field, eligible_reason: str = "eligible") -> None:
    """A canonical question reached a user."""
    sources = sorted({(o.source.value if o.source else "none")
                      for o in field.options})
    # THE DENOMINATOR. `sources` is a SET — it answers "was ontology involved?"
    # and cannot answer "how often is an ontology option accepted when one is
    # offered?", which is the D4 question. Acceptance is selected/offered, so
    # the offer has to be counted per source, not merely witnessed.
    counts = Counter((o.source.value if o.source else "none")
                     for o in field.options)
    offered = ",".join(f"{s}:{n}" for s, n in sorted(counts.items()))
    logger.info(
        "event=b1_shown operation=%s user=%s b1_cohort=%s locale=%s "
        "options=%d sources=%s offered=%s free_text=%s attribute=%s reason=%s",
        operation_id, user_id, cohort or "-", locale, len(field.options),
        ",".join(sources) or "none", offered or "none", True,
        field.attribute.value, eligible_reason)


def declined(*, user_id, reason: str, cohort: str = "") -> None:
    """A turn B-1 did not take, and why.

    The MIX is the measurement: it sizes B-1.5 and B-2 directly. "How often is
    the only unresolved thing a mass?" is not answerable from anywhere else.
    """
    logger.info("event=b1_declined user=%s reason=%s b1_cohort=%s",
                user_id, reason, cohort or "-")


def answered(*, operation_id: str, user_id, outcome: str, modality: str,
             cohort: str = "", asked_at=None, reason: str = "",
             provenance: str = "", grams=None,
             selected_source: str = "") -> None:
    """An answer arrived. `modality` is the signal the "Other" rate reads.

    `chip`   an option id — a real structured tap
    `label`  the exact text of an offered option (Telegram/iMessage)
    `text`   something we were not offering  <- Other
    `command` cancel / skip / estimate
    """
    # `selected_source` IS THE FUNNEL'S JOIN KEY. modality says HOW they
    # answered (tap / label / free text); this says WHERE the value they chose
    # came from. Without it "ontology options are accepted 55% of the time and
    # then corrected 9% of the time" is unanswerable, and that comparison is
    # the whole reason D4 runs before the chips are built.
    logger.info(
        "event=b1_answered operation=%s user=%s outcome=%s modality=%s "
        "selected_source=%s b1_cohort=%s latency_ms=%s provenance=%s grams=%s "
        "reason=%s",
        operation_id, user_id, outcome, modality, selected_source or "-",
        cohort or "-", _ms_since(asked_at), provenance or "-",
        grams if grams is not None else "-", reason or "-")


def committed(*, operation_id: str, user_id, entry_id, calories,
              cohort: str = "", asked_at=None, rounds: int = 1,
              selected_source: str = "", repairs: int = 0) -> None:
    """The terminal event, carrying the whole path so the funnel needs one join.

    `entry_id` is what a correction lands on later, and `selected_source` is
    what that correction is then attributed to — so a correction 9 minutes
    later can be charged to the ontology option that produced it without
    re-reading the operation.
    """
    logger.info(
        "event=b1_committed operation=%s user=%s entry=%s cal=%s "
        "selected_source=%s repairs=%d b1_cohort=%s "
        "latency_ms=%s rounds=%d",
        operation_id, user_id, entry_id, calories, selected_source or "-",
        repairs, cohort or "-", _ms_since(asked_at), rounds)


def abandoned(*, operation_id: str, user_id, cohort: str = "",
              asked_at=None) -> None:
    """The question expired unanswered.

    Emitted by the expiry sweep, not by a turn — nobody is having a turn when
    a user abandons one, which is exactly why this signal is the one most
    likely to be missing from a dashboard that looks complete.
    """
    logger.info(
        "event=b1_abandoned operation=%s user=%s b1_cohort=%s open_ms=%s",
        operation_id, user_id, cohort or "-", _ms_since(asked_at))


def corrected(*, operation_id: str, user_id, entry_id, minutes: float,
              cohort: str = "") -> None:
    """A committed B-1 row was corrected soon after landing.

    The sharpest quality signal in the set: the user saw the number, and it
    was wrong enough to fix. A rising rate here invalidates a green corpus.
    """
    logger.info(
        "event=b1_corrected operation=%s user=%s entry=%s within_min=%.1f "
        "b1_cohort=%s", operation_id, user_id, entry_id, minutes, cohort or "-")


def modality_of(*, option_id: str, reason: str) -> str:
    """Which route carried the answer — the input to the "Other" rate.

    Derived HERE rather than at each call site so the rate cannot quietly come
    to mean different things in different branches.
    """
    # THE LEADING TOKEN, NOT THE WHOLE STRING. This matched `reason` by exact
    # equality, so the moment a reason carried any detail — "estimate: no
    # evidence supports this one" — the route was silently reclassified as
    # `text` and counted as free-text usage. That is the "Other" rate, the
    # single number the observation window exists to read, corrupted by an
    # improved error message. Reasons are allowed to explain themselves; what
    # they NAME is the part before the colon.
    head = str(reason or "").split(":", 1)[0].strip()
    if option_id:
        return "chip"
    if head == "label_selection":
        return "label"
    if head in ("estimate", "keep_as_read", "commit_ready", "cancel_meal",
                "skip_item", "restart"):
        return "command"
    return "text"


def partial(*, operation_id: str, user_id, field_id: str,
            answered_count: int, open_count: int,
            modality: str = "") -> None:
    """A field was answered and the question is still open (B-1.5).

    ITS OWN SIGNAL, not a variant of `answered`. The question this exists to
    answer is "how many multi-field questions get abandoned half-answered" —
    a number no join over commits can produce, because the abandoned ones
    never reach a commit at all.
    """
    logger.info("event=b1_partial operation=%s user=%s field=%s "
                "answered=%d open=%d modality=%s",
                operation_id, user_id, field_id, answered_count, open_count,
                modality or "-")
