"""Open Food Facts (OFF) name-search enrichment for TYPED branded foods.

The iOS app already uses OFF for BARCODE scans; this is the backend counterpart
for text logs ("a Barebells bar", "Fairlife core power") where there's no
barcode — it searches OFF by name and returns a per-100g candidate in the SAME
shape the USDA path returns, so core.food_intelligence.analyze() can rank it.

Public API, NO key required:
  https://world.openfoodfacts.org/cgi/search.pl?search_terms=...&json=1

CONSERVATIVE BY DESIGN — a fuzzy name search over a crowd-sourced DB will happily
return the wrong flavor. A wrong match is WORSE than the LLM's own estimate, so
this returns None unless the best product's name overlaps the query strongly
(>=0.6 token overlap) AND its macros are present and plausible. Never raises;
any error/timeout/miss -> None and the caller falls through unchanged.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_asleep = asyncio.sleep

_SEARCH_URL = "https://world.openfoodfacts.org/cgi/search.pl"
# Search-a-licious — OFF's newer search service. The legacy cgi/search.pl above
# returns HTTP 503 intermittently even at a low request rate (measured
# 2026-07-22: bare "Barebells"/"David protein bar" resolved only 1-2 of 3 tries),
# which surfaces as a silent enrichment miss. This is the fallback when the
# legacy endpoint is down; it returns the SAME per-100g nutriment keys, so the
# scorer/gate below are shared — only the hit envelope differs (hits[] + brands
# as a list). Kept as FALLBACK (not primary) so the legacy ranking that already
# resolves Core Power/David correctly is preserved.
_SAL_URL = "https://search.openfoodfacts.org/search"
# `code` is the barcode — THE ANCHOR. Everything else in this envelope
# describes the product in words, and words are what a later turn has to
# re-search. The barcode is what makes a stored resolution a claim about one
# product, so a correction, an answer or a memory row can point at it instead
# of at a string that has since been edited.
_FIELDS = "code,product_name,brands,nutriments,serving_size,quantity"
# OFF asks for a descriptive UA so they can contact abusers instead of blocking.
_UA = "Arnie/1.0 (nutrition coach; contact: support@tryarnie.com)"
# Transient statuses worth retrying: 503 (the observed flake), 502, 429 (rate cap).
_RETRY_STATUS = frozenset((502, 503, 429))

_http: Optional[httpx.AsyncClient] = None


def off_enabled() -> bool:
    """Kill switch. Default ON (public API, no key). OFF_ENRICH=false disables."""
    return os.getenv("OFF_ENRICH", "true").lower() in ("true", "1", "yes")


def off_fallback_enabled() -> bool:
    """Whether to fall back to Search-a-licious when the legacy endpoint fails.
    Default ON. OFF_FALLBACK_SEARCH=false pins behavior to the legacy endpoint."""
    return os.getenv("OFF_FALLBACK_SEARCH", "true").lower() in ("true", "1", "yes")


def _client() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=6.0, headers={"User-Agent": _UA})
    return _http


_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Connectors carry no brand/flavor identity, but a crowd-sourced `brands` field
# stuffed with flavor text ("Breyers Cookies and Cream") can match them and
# inflate overlap — enough to tie a real brand hit and win on list order (the
# Breyers-vs-Barebells collision, 2026-07-22). Drop them from the overlap math.
_STOPWORDS = frozenset((
    "and", "with", "the", "of", "for", "in", "to", "an", "on", "or",
))


def _tokens(s: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall((s or "").lower())
            if len(t) > 1 and t not in _STOPWORDS}


def _overlap(query: str, product: str, brands: str) -> float:
    """Fraction of the QUERY's tokens found in the product name + brands. Query-
    anchored (not Jaccard) so a long product title doesn't dilute a good match."""
    q = _tokens(query)
    if not q:
        return 0.0
    p = _tokens(product) | _tokens(brands)
    return len(q & p) / len(q)


def _anchor(query: str) -> Optional[str]:
    """The query's brand-ish anchor: the first significant token in order. OFF is
    only searched for branded items, so this is almost always the brand name
    ("barebells", "fairlife", "david"). Used on the fallback path to reject
    wrong-brand entries whose generic flavor words alone clear the overlap gate."""
    for t in _TOKEN_RE.findall((query or "").lower()):
        if len(t) >= 3 and t not in _STOPWORDS:
            return t
    return None


def _num(v) -> Optional[float]:
    try:
        f = float(v)
        return f if f == f else None   # reject NaN
    except (TypeError, ValueError):
        return None


def _per100g(nutriments: dict) -> Optional[dict]:
    """Map OFF nutriments -> the per-100g shape analyze() expects. Requires the
    four macros to be present and calories plausible, else None (noise/empty)."""
    if not isinstance(nutriments, dict):
        return None
    cal = _num(nutriments.get("energy-kcal_100g"))
    if cal is None:
        kj = _num(nutriments.get("energy_100g")) or _num(nutriments.get("energy-kj_100g"))
        cal = round(kj / 4.184, 1) if kj else None
    protein = _num(nutriments.get("proteins_100g"))
    carbs = _num(nutriments.get("carbohydrates_100g"))
    fat = _num(nutriments.get("fat_100g"))
    # All four macros must be present — a product missing them is unusable noise.
    if None in (cal, protein, carbs, fat):
        return None
    # Plausibility: 100g of real food is ~10-900 kcal. Reject sentinels (0, 9999).
    if not (10 <= cal <= 900):
        return None
    out = {"calories": round(cal, 1), "protein": round(protein, 1),
           "carbs": round(carbs, 1), "fat": round(fat, 1)}
    fiber = _num(nutriments.get("fiber_100g"))
    sugar = _num(nutriments.get("sugars_100g"))
    if fiber is not None:
        out["fiber"] = round(fiber, 1)
    if sugar is not None:
        out["sugar"] = round(sugar, 1)
    # Sodium: OFF gives grams. Prefer sodium_100g; else salt/2.5. Store mg.
    sodium_g = _num(nutriments.get("sodium_100g"))
    if sodium_g is None:
        salt_g = _num(nutriments.get("salt_100g"))
        sodium_g = salt_g / 2.5 if salt_g is not None else None
    if sodium_g is not None:
        out["sodium"] = round(sodium_g * 1000)
    return out


def _per_serving(nutriments: dict) -> Optional[dict]:
    """THE LABEL'S OWN SERVING, which is the answer for most branded logging.

    Only `*_100g` was ever read here, so a portion the label already answers —
    "1 bar", "1 bagel", "1 set" — had to be resolved by DERIVING a mass, and
    with no serving size to derive it from the mass came out of the model's
    calorie guess. The label was then scaled to fit the guess. That is the
    anchor problem, and this field makes most of it unnecessary: N servings of
    a product whose per-serving panel is published needs no mass at all.

    Same shape and the same four-macro requirement as `_per100g`, minus the
    100 g plausibility window — a serving is legitimately anything from a
    5-calorie pickle to a 900-calorie meal, so bounding it by that range would
    reject real labels.
    """
    if not isinstance(nutriments, dict):
        return None
    cal = _num(nutriments.get("energy-kcal_serving"))
    if cal is None:
        kj = (_num(nutriments.get("energy_serving"))
              or _num(nutriments.get("energy-kj_serving")))
        cal = round(kj / 4.184, 1) if kj else None
    protein = _num(nutriments.get("proteins_serving"))
    carbs = _num(nutriments.get("carbohydrates_serving"))
    fat = _num(nutriments.get("fat_serving"))
    if None in (cal, protein, carbs, fat):
        return None
    if not (1 <= cal <= 2000):
        return None
    out = {"calories": round(cal, 1), "protein": round(protein, 1),
           "carbs": round(carbs, 1), "fat": round(fat, 1)}
    fiber = _num(nutriments.get("fiber_serving"))
    sugar = _num(nutriments.get("sugars_serving"))
    if fiber is not None:
        out["fiber"] = round(fiber, 1)
    if sugar is not None:
        out["sugar"] = round(sugar, 1)
    sodium_g = _num(nutriments.get("sodium_serving"))
    if sodium_g is None:
        salt_g = _num(nutriments.get("salt_serving"))
        sodium_g = salt_g / 2.5 if salt_g is not None else None
    if sodium_g is not None:
        out["sodium"] = round(sodium_g * 1000)
    return out


#: LEGACY-ENDPOINT CIRCUIT BREAKER.
#:
#: `search()` tries cgi/search.pl first and falls back to Search-a-licious,
#: and its own docstring puts the legacy 503 rate at ~1/3 of calls. Measured on
#: prod 2026-08-03 (the Cali Roll turn), one lookup against a degraded legacy
#: endpoint cost:
#:
#:     22:11:14,700  cgi/search.pl -> 503
#:     22:11:15,155  cgi/search.pl -> 503     (+0.455s)
#:     22:11:16,314  cgi/search.pl -> 503     (+1.159s)
#:     22:11:16,828  search/       -> 200     (+0.514s)
#:
#: — 2.1 s, of which ~1.0 s is pure backoff sleep, to learn a thing the
#: PREVIOUS lookup in the same process already knew. When legacy is down it is
#: down for minutes, not milliseconds, so every food in a multi-item paste pays
#: the full toll independently.
#:
#: So remember it. After `_BREAKER_TRIP` consecutive HARD failures, skip legacy
#: entirely for `_BREAKER_COOLDOWN_S` and go straight to the endpoint that
#: works. One success closes it. This changes no result — legacy is only ever
#: consulted first for its ranking, and a hard failure yields no ranking at all.
#:
#: TRIP IS 1, AND THAT IS NOT TWITCHY: `_search_legacy` returns None only once
#: `_get_json` has exhausted all three attempts WITH the backoff between them,
#: so a single hard failure already means three refused requests over ~1 s. A
#: trip threshold of 2 would mean the second food in a paste still pays the
#: full toll before anything is learned — which is the exact cost this exists
#: to remove.
#:
#: A dict rather than two module floats so tests can `.clear()` it like the
#: other process-global caches conftest isolates.
_BREAKER: dict = {}
_BREAKER_TRIP = 1
_BREAKER_COOLDOWN_S = 120.0


def _legacy_is_down() -> bool:
    until = _BREAKER.get("until") or 0.0
    if not until:
        return False
    if time.monotonic() >= until:
        _BREAKER.clear()
        logger.info("event=off_breaker state=closed reason=cooldown_elapsed")
        return False
    return True


def _note_legacy(ok: bool) -> None:
    if ok:
        if _BREAKER:
            logger.info("event=off_breaker state=closed reason=success")
        _BREAKER.clear()
        return
    fails = int(_BREAKER.get("fails") or 0) + 1
    _BREAKER["fails"] = fails
    if fails >= _BREAKER_TRIP and not _BREAKER.get("until"):
        _BREAKER["until"] = time.monotonic() + _BREAKER_COOLDOWN_S
        logger.warning(
            "event=off_breaker state=open fails=%d cooldown_s=%.0f "
            "url=%s — skipping straight to the fallback",
            fails, _BREAKER_COOLDOWN_S, _SEARCH_URL)


async def _get_json(url: str, params: dict, *, attempts: int = 3,
                    timeout: float = 5.0,
                    health: Optional[dict] = None) -> Optional[dict]:
    """GET url?params and return parsed JSON, retrying transient failures.

    The legacy OFF search endpoint 503s intermittently (and instantly), so one
    shot silently drops the enrichment. Retry on _RETRY_STATUS and on network
    blips/timeouts with a short backoff. Timeouts are retried at most once (they
    already cost `timeout` seconds — piling on more would balloon a multi-item
    paste's latency). Returns None when every attempt fails. Never raises.

    `health`, when a dict is passed, is filled with what this call learned
    about the HOST as distinct from the ANSWER — `{"refused": bool}`, set only
    when the host was actually asked and actually refused. The circuit breaker
    reads that instead of `body is None`, because "no answer" has causes that
    say nothing about the host: an exhausted turn budget (no request is made at
    all), a 404, a 200 that will not parse. Counting those as outages tripped a
    process-global 120s breaker on zero HTTP requests."""
    from core import deadline

    if health is not None:
        health["refused"] = False

    backoff = (0.3, 0.7, 1.2)
    timeout_used = False
    for i in range(attempts):
        # Per-call timeouts do not bound a TURN. A four-item meal against a
        # degraded API spends four times this budget, each attempt behaving
        # exactly as configured. Clamping to what the turn has left is what
        # makes the turn's own limit a guarantee rather than a suggestion.
        call_timeout = deadline.cap(timeout)
        if call_timeout <= 0:
            # Nothing useful left. Making the call anyway would spend the
            # remainder on connection setup and still return nothing — worse
            # than the miss we return here, because it costs the time too.
            logger.info("event=off_skipped reason=turn_budget url=%s", url)
            return None          # never asked — says nothing about the host
        try:
            r = await _client().get(url, params=params, timeout=call_timeout)
        except (httpx.TimeoutException, httpx.TransportError) as e:
            if isinstance(e, httpx.TimeoutException):
                if timeout_used:
                    return None
                timeout_used = True
            if i == attempts - 1:
                logger.warning("OFF GET %s failed (transport): %s", url, e)
                if health is not None:
                    health["refused"] = True     # asked, and could not reach it
                return None
            await _asleep(backoff[min(i, len(backoff) - 1)])
            continue
        except Exception as e:
            logger.warning("OFF GET %s errored: %s: %s", url, type(e).__name__, e)
            return None
        if r.status_code == 200:
            try:
                return r.json() or {}
            except Exception:
                return None
        if r.status_code in _RETRY_STATUS and i == attempts - 1:
            # Retries exhausted against 502/503/429 — the host is refusing, and
            # this is the one signal the breaker exists for.
            if health is not None:
                health["refused"] = True
        if r.status_code in _RETRY_STATUS and i < attempts - 1:
            # Honor Retry-After when present, but cap it — a multi-second stall
            # here would serialize behind the concurrent USDA lookup for nothing.
            ra = _num(r.headers.get("retry-after"))
            await _asleep(min(ra, 1.5) if ra else backoff[min(i, len(backoff) - 1)])
            continue
        return None
    return None


def _best_candidate(name: str, products: list,
                    require_anchor: bool = False) -> Optional[tuple]:
    """Pick the best strongly-matching product from a normalized products list
    (each: {product_name, brands(str), nutriments}). Returns (product, per100g,
    overlap) or None. Shared by the legacy and Search-a-licious paths.

    require_anchor (fallback path only): skip any candidate that does NOT contain
    the query's brand anchor unless its overlap is near-exact (>=0.85). This kills
    wrong-brand entries ("Breyers Cookies and Cream" for a Barebells query) that
    only clear the gate on shared generic flavor words. The legacy path leaves
    this off so its memory-validated selection is untouched."""
    anchor = _anchor(name) if require_anchor else None
    best = None
    best_ov = 0.0
    for p in products:
        pname = (p.get("product_name") or "").strip()
        if not pname:
            continue
        ov = _overlap(name, pname, p.get("brands") or "")
        if anchor is not None and ov < 0.85:
            ptoks = _tokens(pname) | _tokens(p.get("brands") or "")
            if anchor not in ptoks:
                continue   # wrong brand riding on generic flavor words — skip
        if ov > best_ov:
            per100 = _per100g(p.get("nutriments") or {})
            if per100 is not None:
                best, best_ov = (p, per100), ov
    # Conservative gate: only trust a strong name match (else the LLM estimate wins).
    if best is None or best_ov < 0.6:
        return None
    p, per100 = best
    return p, per100, best_ov


async def _search_legacy(name: str, page_size: int) -> Optional[list]:
    """Query the legacy cgi/search.pl endpoint. Products already carry `brands`
    as a comma string. Returns the products list (possibly empty) or None on a
    hard failure (so the caller knows to try the fallback)."""
    params = {
        "search_terms": name, "search_simple": 1, "action": "process",
        "json": 1, "page_size": page_size, "fields": _FIELDS,
    }
    _health: dict = {}
    body = await _get_json(_SEARCH_URL, params, health=_health)
    # THE HOST'S HEALTH, NOT THE QUERY'S LUCK. `body is None` also covers an
    # exhausted turn budget (no request made), a 404 and an unparseable 200 —
    # none of which mean legacy is down, and all of which used to open a
    # process-global 120s breaker for every concurrent user.
    if _health.get("refused"):
        _note_legacy(False)
    elif body is not None:
        _note_legacy(True)
    if body is None:
        return None
    return body.get("products") or []


async def _search_sal(name: str, page_size: int) -> Optional[list]:
    """Query Search-a-licious. Its hits carry `brands` as a LIST — normalize to
    the comma string the scorer/`brand` extraction expect. Returns products or
    None on hard failure."""
    params = {"q": name, "page_size": page_size, "fields": _FIELDS}
    body = await _get_json(_SAL_URL, params)
    if body is None:
        return None
    hits = body.get("hits") or []
    out = []
    for h in hits:
        b = h.get("brands")
        if isinstance(b, (list, tuple)):
            b = ", ".join(str(x) for x in b if x)
        out.append({
            "product_name": h.get("product_name"),
            "brands": b or "",
            "nutriments": h.get("nutriments") or {},
        })
    return out


async def search(name: str, page_size: int = 8) -> Optional[dict]:
    """Search OFF by name; return a candidate {per100g, _match, name, brand} for
    the best strongly-matching product, or None. Never raises.

    Tries the legacy endpoint (retried) first; only if it fails hard or yields
    no gated match does it fall back to Search-a-licious. Keeping legacy primary
    preserves the ranking that already resolves Core Power/David correctly, while
    the fallback rescues the ~1/3 of calls the legacy endpoint 503s away."""
    if not off_enabled() or not (name or "").strip():
        return None

    # Skip a host we already know is down (see _BREAKER). The fallback below is
    # not a lesser answer here — when legacy fails hard it returns no ranking at
    # all, so the only thing the attempt buys is its own latency.
    if _legacy_is_down():
        products = None
        logger.info("event=off_breaker state=open action=skipped_legacy food=%r",
                    name)
    else:
        products = await _search_legacy(name, page_size)
    picked = _best_candidate(name, products) if products else None
    used = "legacy"

    if picked is None and off_fallback_enabled():
        sal = await _search_sal(name, page_size)
        alt = _best_candidate(name, sal, require_anchor=True) if sal else None
        if alt is not None:
            picked, used = alt, "sal"

    if picked is None:
        return None
    p, per100, best_ov = picked
    logger.info("OFF hit via %s for %r: %r (ov=%.2f)",
                used, name, (p.get("product_name") or "").strip(), best_ov)
    return {
        "per100g": per100,
        "_match": "exact" if best_ov >= 0.85 else "likely",
        "name": (p.get("product_name") or "").strip(),
        "brand": (p.get("brands") or "").split(",")[0].strip() or None,
        # The product's own id, carried so a resolution can be anchored to it.
        "code": str(p.get("code") or "").strip() or None,
        # The serving panel was already in _FIELDS and was thrown away here.
        # It is the only thing that knows one Peanut M&M weighs ~2.9 g, and
        # without it a "15 pieces" portion of a per-100g row cannot be scaled
        # at all — so the resolution came back empty and a guess was committed
        # under this source's name (2026-07-25).
        "serving_text": (p.get("serving_size") or "").strip(),
        # THE PACKAGE NET WEIGHT. Already in _FIELDS, already fetched, and
        # discarded here — while the resolver had no mass to scale by and fell
        # back to trusting the model's calorie guess. Many single-serve
        # products (bars, bottles, pouches) publish no serving panel at all
        # because the package IS the serving, so this is the only mass their
        # label carries. Without it an exact branded match still lost its
        # calories to a guess, and the same product came out at three
        # different numbers depending on the logging mode.
        "package_text": (p.get("quantity") or "").strip(),
        # The label's own per-serving panel. When the portion is N of the
        # product's own units this answers it outright — no mass to derive and
        # so nothing for the model's calorie guess to anchor.
        "per_serving": _per_serving(p.get("nutriments") or {}),
        "source": "off",
    }

async def search_variants(name: str, limit: int = 5) -> list:
    """The product's SIBLINGS — the other variants the same search returned.

    `search()` fetches a page and returns the single best match, discarding the
    rest. For a brand whose flavours differ, those discards are the answer to
    "which one was it?": they are the real options, with real numbers, instead
    of a plausible-sounding pair the model invented.

    They also make the doubt MEASURABLE. Barebells across its line runs 353-395
    cal/100g but 29-37 g protein — so the variant question is material because
    of protein, not calories, and only a spread computed from the actual
    candidates can know that. An estimated span cannot.

    Deduped on name, best first, never raises. Returns [] when the lane is off
    or nothing came back — the caller then asks whatever it would have asked.
    """
    if not off_enabled() or not (name or "").strip():
        return []
    # THE SAME FALLBACK `search()` HAS. Its own note: the fallback "rescues the
    # ~1/3 of calls the legacy endpoint 503s away". This path never got it, so
    # roughly a third of variant lookups came back empty and the turn quietly
    # degraded — options vanished, the spread went unmeasured, and the same
    # query returned 5 variants, then 0, then 5 again. Nondeterminism that
    # reads as the mode changing its mind about a food.
    page = max(limit * 2, 8)
    try:
        products = await _search_legacy(name, page)
    except Exception:
        products = None
    if not products and off_fallback_enabled():
        try:
            products = await _search_sal(name, page)
        except Exception:
            products = None
    # THE SAME GATE THE PRIMARY SEARCH USES. `search()` filters on overlap and
    # a brand anchor; this took whatever the text search returned, so a query
    # for a plain 2% milk came back led by that brand's chocolate protein
    # shake, and a chocolate-chip energy bar query dragged in the kids' line.
    # Those are not variants of the thing asked about — they are other products
    # that share words. Offering them as "which one was it?" is wrong, and the
    # spread computed across them says the shelf disagrees when what actually
    # disagrees is the search.
    anchor = _anchor(name)
    out, seen = [], set()
    for product in (products or []):
        label = (product.get("product_name") or "").strip()
        key = label.lower()
        if not label or key in seen:
            continue
        overlap = _overlap(name, label, product.get("brands") or "")
        if overlap < 0.6:
            continue
        if anchor is not None and overlap < 0.85:
            tokens = _tokens(label) | _tokens(product.get("brands") or "")
            if anchor not in tokens:
                continue
        nutriments = product.get("nutriments") or {}
        calories = nutriments.get("energy-kcal_100g")
        if not calories:
            continue
        # PHYSICALLY IMPOSSIBLE ROWS. Open Food Facts is crowd-entered and
        # carries unit mistakes — a Muscle Milk row reads 17000 cal/100g, which
        # is a kilojoule field pasted into a kcal one, or a per-container value
        # in a per-100g slot. Pure fat is 9 cal/g, so nothing edible exceeds
        # 900 cal/100g; anything above it is a data error, and left in it
        # dominates every spread it appears in and turns "how far apart is this
        # shelf?" into "always ask".
        try:
            if not (0 < float(calories) <= 900):
                continue
        except (TypeError, ValueError):
            continue
        seen.add(key)
        out.append({
            "name": label,
            "brand": (product.get("brands") or "").split(",")[0].strip(),
            # Each sibling is a product in its own right, and the one the user
            # picks becomes the anchored resolution — so it carries its id for
            # the same reason the primary hit does.
            "code": str(product.get("code") or "").strip() or None,
            # HOW BIG THE PACK IS, kept because the question needs it.
            #
            # `_FIELDS` has always asked for `serving_size` and `quantity`, and
            # `search()` maps both — this builder was throwing them away, so a
            # clarification about which product could name the flavours and not
            # the sizes. "a small bag or the share size?" is a question someone
            # can answer in one word; "was that a single small…" is not.
            #
            # Carried raw. Whether a 24 oz share bag is a plausible SITTING is
            # judgement about the food and the occasion, not something this
            # layer can decide — it supplies the shelf and the reader weighs it.
            "serving_text": (product.get("serving_size") or "").strip(),
            "package_text": (product.get("quantity") or "").strip(),
            "per100g": {
                "calories": calories,
                "protein": nutriments.get("proteins_100g"),
                "carbs": nutriments.get("carbohydrates_100g"),
                "fat": nutriments.get("fat_100g"),
            },
        })
        if len(out) >= limit:
            break
    return out


def variant_spread(variants: list) -> dict:
    """`{nutrient: span}` across the variants — what choosing wrong would cost.

    Per nutrient, because the deciding one is not always calories, and the
    materiality scorer reads whichever is worst against its own target.
    """
    spread = {}
    for key in ("calories", "protein", "carbs", "fat"):
        values = [float(v["per100g"][key]) for v in (variants or [])
                  if (v.get("per100g") or {}).get(key) is not None]
        if len(values) >= 2:
            spread[key] = round(max(values) - min(values), 1)
    return spread
