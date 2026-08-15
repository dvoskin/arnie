"""⭐ THE PRODUCER — interpreted meaning, once, at interpretation time.

⛔ A SEPARATE MODULE FROM `entity_resolution`, AND THE SPLIT IS ARCHITECTURE
RATHER THAN TIDINESS. `entity_resolution` is asserted by gate to contain no
model call at all, because settlement reads it and `price()` is synchronous by
design (Gate B). Putting the producer beside the reader would make that gate a
lint rule about spelling; keeping them apart makes it a statement about which
code can reach a network.

WHERE THIS RUNS. The interpretation stage, where a model call is already being
made for the turn and its latency already paid. Not the settle path — and not
the interpreter's prompt either, which is FROZEN: this is a separate call in
code, which is where enhancements have belonged since 2026-08-01.

⭐⭐ THE MODEL IS ASKED A SEMANTIC QUESTION, NEVER GIVEN A CATALOGUE. There is
no list of 27 entities here and there must never be one — handing over a
catalogue would make every food outside it DISTINCT by construction, which is
the doorway-shaped mistake of asserting an answer the data never supported. The
question is whether a faithful, standard English food term EXISTS for this food,
which is a fact about language rather than about our coverage.

⭐⭐⭐ AND `UNRESOLVED` IS ALWAYS AVAILABLE TO IT. Every failure — an outage, a
truncated reply, an unparseable payload, a food the model will not commit on —
produces no row, and no row reproduces today's behaviour exactly. That is the
monotonicity guarantee: this can raise reachability and cannot lower it.

⚠ THE TRUNCATION TRAP, PAID FOR ONCE ALREADY. `resolve()` in the pricing lane
once received a reply cut mid-string and the whole batch abstained silently; the
bound was OUTPUT LENGTH, not record count. So a `max_tokens` stop reason
abstains the WHOLE batch here, loudly, rather than trusting the prefix that
happened to arrive.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from typing import Iterable, Optional

from skills.nutrition.entity_resolution import (EntityResolution,
                                                ResolutionState, record,
                                                resolve, surface_key)

logger = logging.getLogger(__name__)

#: Identity across languages is a judgement, not a lookup, so this is not the
#: cheap model. `temperature` is deliberately not set — it is REJECTED on this
#: model, and determinism here comes from storing the answer once, not from
#: configuring the sampler.
RESOLVER_MODEL = "claude-sonnet-5"

#: Generous per food, because the failure this bound causes is not a slow
#: answer — it is a truncated one, which the guard below then turns into a
#: whole-batch abstention.
_TOKENS_PER_FOOD = 220
_MAX_BATCH = 12

_SYSTEM = (
    "You map a food NAME, written in any language, to a canonical food "
    "identity. You are not looking anything up and you are not being given a "
    "catalogue: decide from what the words mean.\n\n"
    "For each food return exactly one state.\n\n"
    '"resolved" — a standard English food term names THIS SAME food faithfully. '
    'Give that term, lowercase, as the entity: "Помидор" -> "tomato", '
    '"Куриная грудка" -> "chicken breast". A translation is faithful only when '
    "someone shopping for the English term would come home with this food.\n\n"
    '"distinct" — this is a real food with NO faithful English equivalent, so '
    "it keeps its own identity. Give a stable lowercase identifier for the food "
    "ITSELF. Do this whenever the nearest English word would change what the "
    "food is, how it is made, or what grade of it is standard — even slightly. "
    "Choosing this is never a failure; it is the correct answer for most "
    "regional and traditional foods.\n\n"
    '"product" — this names a BRANDED or packaged product rather than a food: '
    "a manufacturer's item, a restaurant menu item, a labelled package. Give the "
    "product identity as the entity. Do not describe it as a distinct food — a "
    "product is identified by its label, not by what kind of food it is.\n\n"
    '"unresolved" — you cannot tell what food this is, or you are not '
    "confident. Prefer this over a guess. An absent answer costs us nothing; a "
    "wrong one prices somebody's meal from the wrong food.\n\n"
    "MODIFIERS STAY WITH THE FOOD. A stated fat percentage, cut, grade or "
    "cooking method is part of what the food IS, so keep it in the entity when "
    "it changes the food.\n\n"
    'Return JSON only: {"foods": [{"surface": "<the name given>", '
    '"state": "resolved|distinct|product|unresolved", '
    '"entity": "<term or id or empty>", '
    '"meaning": "<one short clause: what this food is>", '
    '"language": "<BCP-47 tag or empty>"}]}'
)


def _get_client():
    """The shared Anthropic client.

    ⚠ `core.llm`, NOT `core.micro_estimator`. The first version imported
    `_get_anthropic` from the estimator — which imports it from here — and the
    name does not exist there. Every unit gate passed anyway, because they all
    stub THIS function: the one line they could not exercise was the one that
    was wrong. Only the live smoke run found it, and
    `test_the_client_factory_actually_resolves` now covers the gap.
    """
    from core.llm import _get_anthropic

    return _get_anthropic()


def _parse(text: str, asked: dict) -> list:
    """Model payload -> resolutions, for the foods that were ACTUALLY ASKED.

    ⭐ A RESOLUTION FOR A FOOD NOBODY ASKED ABOUT IS DISCARDED. The model can
    echo, invent or merge a surface form, and a row keyed on a string the user
    never typed would be unreachable at best and wrong at worst.
    """
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in the reply")
    payload = json.loads(text[start:end + 1])

    out = []
    for entry in payload.get("foods") or ():
        if not isinstance(entry, dict):
            continue
        surface = asked.get(surface_key(str(entry.get("surface") or "")))
        if surface is None:
            logger.info("event=entity_resolution_unasked surface=%r",
                        entry.get("surface"))
            continue
        try:
            state = ResolutionState(str(entry.get("state") or "").strip().lower())
        except ValueError:
            continue
        entity = str(entry.get("entity") or "").strip().lower()
        if state in (ResolutionState.RESOLVED, ResolutionState.DISTINCT) \
                and not entity:
            # A binding state with no entity is not a decision. Recording it as
            # UNRESOLVED would be inventing a judgement the model did not make,
            # so it is dropped and the food simply stays unresolved by absence.
            continue
        out.append(EntityResolution(
            surface_form=surface, surface_key=surface_key(surface),
            state=state,
            canonical_entity_id=(entity if state is not ResolutionState.UNRESOLVED
                                 else ""),
            interpreted_meaning=str(entry.get("meaning") or "")[:400],
            source_language=str(entry.get("language") or "")[:16],
            model_id=RESOLVER_MODEL))
    return out


async def interpret(surfaces: Iterable[str]) -> list:
    """One batch, one call. `[]` on ANY failure — never a partial verdict."""
    asked = {}
    for surface in surfaces:
        key = surface_key(surface)
        if key and key not in asked:
            asked[key] = str(surface).strip()
    if not asked:
        return []
    names = list(asked.values())[:_MAX_BATCH]

    try:
        reply = await _get_client().messages.create(
            model=RESOLVER_MODEL, max_tokens=_TOKENS_PER_FOOD * len(names),
            system=_SYSTEM,
            messages=[{"role": "user",
                       "content": json.dumps({"foods": names},
                                             ensure_ascii=False)}])
    except Exception as exc:
        logger.warning("event=entity_resolution_unavailable foods=%d err=%s — "
                       "no resolution recorded, identity keeps today's "
                       "behaviour", len(names), exc)
        return []

    # ⚠ TRUNCATION ABSTAINS THE WHOLE BATCH. The prefix that arrived is not a
    # smaller correct answer; it is an answer about some foods and silence
    # about the rest, and the silence is indistinguishable from a verdict once
    # it has been written down.
    if getattr(reply, "stop_reason", None) == "max_tokens":
        logger.warning("event=entity_resolution_truncated foods=%d — the whole "
                       "batch abstains; a cut reply is not a shorter answer",
                       len(names))
        return []

    text = "".join(block.text for block in (getattr(reply, "content", []) or ())
                   if getattr(block, "type", None) == "text")
    try:
        return _parse(text, asked)
    except Exception as exc:
        logger.warning("event=entity_resolution_unparseable err=%s", exc)
        return []


_REUSE_SYSTEM = (
    "You are given one food and a list of canonical food identities already "
    "established. Decide whether the food IS one of them.\n\n"
    "Answer with the existing identity ONLY when they are the same food — the "
    "same thing, prepared and sold the same way, with the same nutrition. A "
    "difference in fat percentage, cut, grade or preparation makes it a "
    "DIFFERENT identity, not the same one described loosely.\n\n"
    "If none is the same food, say so. Creating a new identity is cheap and "
    "correct; merging two foods that differ is a permanent error that prices "
    "one of them from the other.\n\n"
    'Return JSON only: {"match": "<an identity from the list, or empty>"}')


async def _reuse_existing_distinct(db, resolution):
    """A DISTINCT food re-uses an established identity when it IS that food.

    ⛔ WHY THIS EXISTS. Measured 2026-08-14: one live batch produced `tvorog`,
    `tvorog_5%` and `tvorog 5% fat` for one family. `normalize_entity_id`
    settles the typography; only a semantic judgement can settle the rest, and
    without it the boundary would fix fragmentation at the surface layer and
    reintroduce it one layer down — a canonical identity that is per-surface is
    not canonical.

    ⭐ THE LIST IS A GROWING STORE, NOT A CATALOGUE. Every candidate offered
    here was resolved once already, so this asks "is this one of the identities
    we have met" rather than "pick from these blessed foods". The prompt is
    biased AGAINST merging, because a wrong merge is permanent and prices one
    food from another, while a redundant identity is merely untidy.

    ⚠ ANY FAILURE KEEPS THE PRODUCER'S OWN ID. Reuse is an improvement, never a
    precondition.
    """
    from skills.nutrition.entity_resolution import (distinct_entities,
                                                    normalize_entity_id)

    known = await distinct_entities(db)
    proposed = normalize_entity_id(resolution.canonical_entity_id)
    if not known or proposed in known:
        return resolution
    try:
        reply = await _get_client().messages.create(
            model=RESOLVER_MODEL, max_tokens=200, system=_REUSE_SYSTEM,
            messages=[{"role": "user", "content": json.dumps(
                {"food": {"name": resolution.surface_form,
                          "meaning": resolution.interpreted_meaning},
                 "established": [{"identity": k, "meaning": v}
                                 for k, v in sorted(known.items())][:60]},
                ensure_ascii=False)}])
        if getattr(reply, "stop_reason", None) == "max_tokens":
            return resolution
        text = "".join(b.text for b in (getattr(reply, "content", []) or ())
                       if getattr(b, "type", None) == "text")
        start, end = text.find("{"), text.rfind("}")
        match = normalize_entity_id(
            str(json.loads(text[start:end + 1]).get("match") or ""))
    except Exception as exc:
        logger.info("event=distinct_reuse_unavailable err=%s", exc)
        return resolution
    # ⚠ ONLY AN IDENTITY THAT ALREADY EXISTS. A model naming something outside
    # the list is proposing a NEW id under the guise of reuse, which would
    # bypass the very judgement this step exists to make.
    if match and match in known:
        logger.info("event=distinct_reused surface=%r proposed=%r reused=%r",
                    resolution.surface_form, proposed, match)
        return replace(resolution, canonical_entity_id=match)
    return resolution


async def ensure_resolved(db, surfaces: Iterable[str]) -> dict:
    """`{surface: canonical_entity_id}` for these foods, resolving what is new.

    ⭐ STORE FIRST, AND THE MODEL ONLY FOR WHAT IS MISSING OR EXPIRED. A food
    the user logs every week is interpreted once, ever — which is what makes
    this affordable and what makes it deterministic afterwards.

    ⚠ A FOOD ABSENT FROM THE RESULT IS NOT AN ERROR. It resolved to nothing,
    and nothing is the fallback: `entity_id_for_surface` returns `""` and the
    caller keeps `food:<surface>`.
    """
    from skills.nutrition.entity_resolution import canonical_entity_id_for

    known, missing = {}, []
    for surface in surfaces:
        if not surface_key(surface):
            continue
        existing = await resolve(db, surface)
        if existing is not None and existing.is_current():
            known[surface] = canonical_entity_id_for(existing)
        else:
            missing.append(surface)

    for resolution in await interpret(missing):
        if resolution.state is ResolutionState.DISTINCT:
            resolution = await _reuse_existing_distinct(db, resolution)
        stored = await record(db, resolution)
        known[resolution.surface_form] = canonical_entity_id_for(stored)
    return {k: v for k, v in known.items() if v}
