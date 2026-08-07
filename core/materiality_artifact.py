"""A DERIVED FACT, COMPUTED ONCE AND READ MANY TIMES — mechanism only.

    build time   real provider evidence -> the SAME semantic resolver
                 -> the SAME projection -> versioned artifact -> fingerprint
    turn  time   identity -> lookup -> fingerprints valid? -> space or UNKNOWN

WHY THIS EXISTS, MEASURED 2026-08-07. Preparation materiality was computed per
turn: bare `chicken` returned 8 USDA rows, qualification correctly kept ONE
(refusing chicken spread, chicken FAT at 900 kcal and a frankfurter), and the
semantic classification cost 8,992 ms for 8 records and 15,813 ms for 12. The
answer it computes — which preparations exist for chicken and how they price —
does not vary by user, by turn, or by day. Recomputing a universal fact inside
an interactive request, at nine to sixteen seconds, is the defect.

NOT A CURATED LIST, and the distinction is the whole design. Nothing here is
authored. Every entry is the resolver's own output, keyed by the input that
produced it, stamped with the versions that make it meaningful. A food absent
from the artifact simply never opens its field. The prohibition this codebase
carries is on hand-written judgements about foods; a cache of a derivation is
a different thing, and it stays a different thing only while nothing may be
written here by hand.

CORE HOLDS NO DOMAIN KNOWLEDGE. This module does not know what a food is, what
a preparation is, or which providers exist. It loads a document, checks the
stamps it was given, and refuses when they disagree. The domain supplies the
path and the fingerprints — see `skills/nutrition/preparation_artifact.py`,
mirroring the `core.semantic_evidence` / `evidence_semantics` split.

⭐ BUILD BLOCKS, RUNTIME DEGRADES — the asymmetry is deliberate.

    build/release   stale or mismatched  ->  FAIL. Deploying it is impossible.
    runtime         stale or mismatched  ->  UNKNOWN. The field does not open.

An unreadable artifact means a field silently stops opening, which is the
instrument-lies-by-silence failure this codebase keeps paying for. So CI is
where staleness is made loud. What runtime must never do is turn a stale
document into a slow request or a failed one: it degrades to "no question",
never to a provider call, never to an exception reaching the user.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

#: Beyond this the artifact is refused. Providers revise their data, and a
#: document old enough to predate that is no longer the derivation it claims
#: to be. Generous, because refreshing is a deliberate act and the release
#: gate — not a silent expiry in production — is what forces it.
MAX_ARTIFACT_AGE_DAYS = 90


class Stale(Exception):
    """Why the artifact may not be read. Carried, never swallowed, so the
    release gate can print the reason a build is refused."""


@dataclass(frozen=True)
class Artifact:
    resolver_version: str
    vocabulary_fingerprint: str
    retrieval_fingerprint: str
    generated_at: datetime
    entries: dict

    def age_days(self, now: Optional[datetime] = None) -> float:
        now = now or datetime.now(timezone.utc)
        return (now - self.generated_at).total_seconds() / 86400.0


def parse(document: dict) -> Artifact:
    """A document -> an `Artifact`, or `Stale` if it is not one.

    Deliberately strict. A half-read artifact that answers for some foods and
    not others is worse than none: it would make the field open inconsistently
    with no way to tell that from a food genuinely having no material space.
    """
    try:
        stamped = str(document["generated_at"])
        generated = datetime.fromisoformat(stamped.replace("Z", "+00:00"))
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
        return Artifact(
            resolver_version=str(document["resolver_version"]),
            vocabulary_fingerprint=str(document["vocabulary_fingerprint"]),
            retrieval_fingerprint=str(document["retrieval_fingerprint"]),
            generated_at=generated,
            entries=dict(document["entries"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise Stale(f"artifact is not readable: {exc}") from exc


def verify(artifact: Artifact, *, resolver_version: str,
           vocabulary_fingerprint: str, retrieval_fingerprint: str,
           max_age_days: float = MAX_ARTIFACT_AGE_DAYS,
           now: Optional[datetime] = None) -> None:
    """Raise `Stale` unless this artifact still describes the live system.

    EVERY STAMP IS A WAY THE DERIVATION CAN STOP BEING TRUE:

      resolver_version        a different model or prompt reaches different
                              relationships, so every entry is a claim the
                              current resolver never made
      vocabulary_fingerprint  a preparation added to the registry was never
                              queried for, so the space is missing states the
                              field can now offer — silently incomplete
      retrieval_fingerprint   different queries reach different rows, and the
                              rows ARE the evidence
      age                     providers revise; a derivation has a shelf life
    """
    if artifact.resolver_version != resolver_version:
        raise Stale(f"resolver_version {artifact.resolver_version!r} != "
                    f"live {resolver_version!r}")
    if artifact.vocabulary_fingerprint != vocabulary_fingerprint:
        raise Stale("vocabulary_fingerprint disagrees with the live registry "
                    "— a field state exists that was never queried for")
    if artifact.retrieval_fingerprint != retrieval_fingerprint:
        raise Stale("retrieval_fingerprint disagrees — the queries that "
                    "produced this artifact are not the queries in the code")
    age = artifact.age_days(now)
    if age > max_age_days:
        raise Stale(f"generated {age:.0f} days ago, limit {max_age_days:.0f}")


def load(path, *, resolver_version: str, vocabulary_fingerprint: str,
         retrieval_fingerprint: str,
         max_age_days: float = MAX_ARTIFACT_AGE_DAYS,
         now: Optional[datetime] = None) -> Artifact:
    """The verified artifact at `path`, or `Stale`.

    Raises rather than returning None so the release gate gets the reason.
    Runtime callers catch it and fail closed — see the domain binding.
    """
    try:
        document = json.loads(open(path, encoding="utf-8").read())
    except FileNotFoundError as exc:
        raise Stale(f"no artifact at {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise Stale(f"artifact unreadable at {path}: {exc}") from exc
    artifact = parse(document)
    verify(artifact, resolver_version=resolver_version,
           vocabulary_fingerprint=vocabulary_fingerprint,
           retrieval_fingerprint=retrieval_fingerprint,
           max_age_days=max_age_days, now=now)
    return artifact
