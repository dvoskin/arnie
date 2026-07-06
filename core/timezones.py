"""
Offline city/region -> IANA timezone resolution. No network calls, no deps
beyond the stdlib (zoneinfo for validation via pytz already in the project).

resolve_timezone(text) takes a free-form location string ("austin", "NYC",
"London, UK", "i'm in the bay area") and returns a valid IANA tz string
(e.g. "America/Chicago") or None if it can't confidently map it.

Strategy: normalize -> direct city hit -> US state hit -> country hit ->
substring scan. Conservative: returns None rather than guessing wildly, so
the caller can ask a follow-up instead of setting the wrong zone.
"""
import re

# ── Major cities -> IANA tz. Keys are lowercase, punctuation-stripped. ──────────
_CITY_TZ = {
    # US
    "new york": "America/New_York", "nyc": "America/New_York", "manhattan": "America/New_York",
    "brooklyn": "America/New_York", "boston": "America/New_York", "philadelphia": "America/New_York",
    "philly": "America/New_York", "washington": "America/New_York", "washington dc": "America/New_York",
    "dc": "America/New_York", "atlanta": "America/New_York", "miami": "America/New_York",
    "orlando": "America/New_York", "tampa": "America/New_York", "charlotte": "America/New_York",
    "pittsburgh": "America/New_York", "baltimore": "America/New_York", "newark": "America/New_York",
    "jersey city": "America/New_York", "detroit": "America/Detroit", "cleveland": "America/New_York",
    "columbus": "America/New_York", "cincinnati": "America/New_York", "buffalo": "America/New_York",
    "chicago": "America/Chicago", "houston": "America/Chicago", "dallas": "America/Chicago",
    "austin": "America/Chicago", "san antonio": "America/Chicago", "fort worth": "America/Chicago",
    "minneapolis": "America/Chicago", "kansas city": "America/Chicago", "st louis": "America/Chicago",
    "saint louis": "America/Chicago", "milwaukee": "America/Chicago", "nashville": "America/Chicago",
    "memphis": "America/Chicago", "new orleans": "America/Chicago", "oklahoma city": "America/Chicago",
    "omaha": "America/Chicago", "madison": "America/Chicago", "denver": "America/Denver",
    "boulder": "America/Denver", "salt lake city": "America/Denver", "albuquerque": "America/Denver",
    "santa fe": "America/Denver", "phoenix": "America/Phoenix", "tucson": "America/Phoenix",
    "scottsdale": "America/Phoenix", "mesa": "America/Phoenix", "los angeles": "America/Los_Angeles",
    "la": "America/Los_Angeles", "san francisco": "America/Los_Angeles", "sf": "America/Los_Angeles",
    "san diego": "America/Los_Angeles", "san jose": "America/Los_Angeles", "sacramento": "America/Los_Angeles",
    "oakland": "America/Los_Angeles", "bay area": "America/Los_Angeles", "silicon valley": "America/Los_Angeles",
    "seattle": "America/Los_Angeles", "portland": "America/Los_Angeles", "las vegas": "America/Los_Angeles",
    "vegas": "America/Los_Angeles", "fresno": "America/Los_Angeles", "long beach": "America/Los_Angeles",
    "anchorage": "America/Anchorage", "honolulu": "Pacific/Honolulu", "hawaii": "Pacific/Honolulu",
    # Canada
    "toronto": "America/Toronto", "ottawa": "America/Toronto", "montreal": "America/Toronto",
    "quebec": "America/Toronto", "vancouver": "America/Vancouver", "calgary": "America/Edmonton",
    "edmonton": "America/Edmonton", "winnipeg": "America/Winnipeg",
    # UK / Ireland
    "london": "Europe/London", "manchester": "Europe/London", "birmingham": "Europe/London",
    "liverpool": "Europe/London", "leeds": "Europe/London", "glasgow": "Europe/London",
    "edinburgh": "Europe/London", "bristol": "Europe/London", "cardiff": "Europe/London",
    "belfast": "Europe/London", "dublin": "Europe/Dublin",
    # Europe
    "paris": "Europe/Paris", "marseille": "Europe/Paris", "lyon": "Europe/Paris",
    "madrid": "Europe/Madrid", "barcelona": "Europe/Madrid", "valencia": "Europe/Madrid",
    "lisbon": "Europe/Lisbon", "porto": "Europe/Lisbon", "berlin": "Europe/Berlin",
    "munich": "Europe/Berlin", "hamburg": "Europe/Berlin", "frankfurt": "Europe/Berlin",
    "cologne": "Europe/Berlin", "amsterdam": "Europe/Amsterdam", "rotterdam": "Europe/Amsterdam",
    "brussels": "Europe/Brussels", "rome": "Europe/Rome", "milan": "Europe/Rome",
    "venice": "Europe/Rome", "zurich": "Europe/Zurich",
    # "naples" alone: our user base is US-centric and Naples FL is a major US
    # city — a bare "naples" (or "Naples, USA") is far more likely Florida than
    # Italy. Qualified Italian forms still map to Rome.
    "naples": "America/New_York", "naples fl": "America/New_York",
    "naples florida": "America/New_York", "naples usa": "America/New_York",
    "naples italy": "Europe/Rome",
    "geneva": "Europe/Zurich", "vienna": "Europe/Vienna", "prague": "Europe/Prague",
    "warsaw": "Europe/Warsaw", "stockholm": "Europe/Stockholm", "oslo": "Europe/Oslo",
    "copenhagen": "Europe/Copenhagen", "helsinki": "Europe/Helsinki", "athens": "Europe/Athens",
    "istanbul": "Europe/Istanbul", "moscow": "Europe/Moscow", "kyiv": "Europe/Kyiv",
    "kiev": "Europe/Kyiv", "budapest": "Europe/Budapest", "bucharest": "Europe/Bucharest",
    # Middle East
    "dubai": "Asia/Dubai", "abu dhabi": "Asia/Dubai", "doha": "Asia/Qatar",
    "riyadh": "Asia/Riyadh", "tel aviv": "Asia/Jerusalem", "jerusalem": "Asia/Jerusalem",
    # Asia
    "tokyo": "Asia/Tokyo", "osaka": "Asia/Tokyo", "kyoto": "Asia/Tokyo",
    "seoul": "Asia/Seoul", "beijing": "Asia/Shanghai", "shanghai": "Asia/Shanghai",
    "shenzhen": "Asia/Shanghai", "guangzhou": "Asia/Shanghai", "hong kong": "Asia/Hong_Kong",
    "taipei": "Asia/Taipei", "singapore": "Asia/Singapore", "bangkok": "Asia/Bangkok",
    "jakarta": "Asia/Jakarta", "manila": "Asia/Manila", "kuala lumpur": "Asia/Kuala_Lumpur",
    "ho chi minh city": "Asia/Ho_Chi_Minh", "saigon": "Asia/Ho_Chi_Minh", "hanoi": "Asia/Ho_Chi_Minh",
    "mumbai": "Asia/Kolkata", "delhi": "Asia/Kolkata", "new delhi": "Asia/Kolkata",
    "bangalore": "Asia/Kolkata", "bengaluru": "Asia/Kolkata", "hyderabad": "Asia/Kolkata",
    "chennai": "Asia/Kolkata", "kolkata": "Asia/Kolkata", "pune": "Asia/Kolkata",
    "karachi": "Asia/Karachi", "lahore": "Asia/Karachi", "islamabad": "Asia/Karachi",
    "dhaka": "Asia/Dhaka",
    # Oceania
    "sydney": "Australia/Sydney", "melbourne": "Australia/Melbourne", "brisbane": "Australia/Brisbane",
    "perth": "Australia/Perth", "adelaide": "Australia/Adelaide", "canberra": "Australia/Sydney",
    "auckland": "Pacific/Auckland", "wellington": "Pacific/Auckland",
    # Latin America / Africa
    "mexico city": "America/Mexico_City", "guadalajara": "America/Mexico_City",
    "monterrey": "America/Monterrey", "sao paulo": "America/Sao_Paulo", "rio de janeiro": "America/Sao_Paulo",
    "rio": "America/Sao_Paulo", "buenos aires": "America/Argentina/Buenos_Aires",
    "santiago": "America/Santiago", "lima": "America/Lima", "bogota": "America/Bogota",
    "cairo": "Africa/Cairo", "lagos": "Africa/Lagos", "nairobi": "Africa/Nairobi",
    "johannesburg": "Africa/Johannesburg", "cape town": "Africa/Johannesburg",
}

# ── US state names/abbreviations -> tz (best single zone for the populous part) ─
_US_STATE_TZ = {
    "alabama": "America/Chicago", "al": "America/Chicago",
    "alaska": "America/Anchorage", "ak": "America/Anchorage",
    "arizona": "America/Phoenix", "az": "America/Phoenix",
    "arkansas": "America/Chicago", "ar": "America/Chicago",
    "california": "America/Los_Angeles", "ca": "America/Los_Angeles", "cali": "America/Los_Angeles",
    "colorado": "America/Denver", "co": "America/Denver",
    "connecticut": "America/New_York", "ct": "America/New_York",
    "delaware": "America/New_York", "de": "America/New_York",
    "florida": "America/New_York", "fl": "America/New_York",
    "georgia": "America/New_York", "ga": "America/New_York",
    "hawaii": "Pacific/Honolulu", "hi": "Pacific/Honolulu",
    "idaho": "America/Boise", "id": "America/Boise",
    "illinois": "America/Chicago", "il": "America/Chicago",
    "indiana": "America/Indiana/Indianapolis", "in": "America/Indiana/Indianapolis",
    "iowa": "America/Chicago", "ia": "America/Chicago",
    "kansas": "America/Chicago", "ks": "America/Chicago",
    "kentucky": "America/New_York", "ky": "America/New_York",
    "louisiana": "America/Chicago", "la state": "America/Chicago",
    "maine": "America/New_York", "me": "America/New_York",
    "maryland": "America/New_York", "md": "America/New_York",
    "massachusetts": "America/New_York", "ma": "America/New_York", "mass": "America/New_York",
    "michigan": "America/Detroit", "mi": "America/Detroit",
    "minnesota": "America/Chicago", "mn": "America/Chicago",
    "mississippi": "America/Chicago", "ms": "America/Chicago",
    "missouri": "America/Chicago", "mo": "America/Chicago",
    "montana": "America/Denver", "mt": "America/Denver",
    "nebraska": "America/Chicago", "ne": "America/Chicago",
    "nevada": "America/Los_Angeles", "nv": "America/Los_Angeles",
    "new hampshire": "America/New_York", "nh": "America/New_York",
    "new jersey": "America/New_York", "nj": "America/New_York",
    "new mexico": "America/Denver", "nm": "America/Denver",
    "new york state": "America/New_York", "ny": "America/New_York",
    "north carolina": "America/New_York", "nc": "America/New_York",
    "north dakota": "America/Chicago", "nd": "America/Chicago",
    "ohio": "America/New_York", "oh": "America/New_York",
    "oklahoma": "America/Chicago", "ok": "America/Chicago",
    "oregon": "America/Los_Angeles", "or": "America/Los_Angeles",
    "pennsylvania": "America/New_York", "pa": "America/New_York",
    "rhode island": "America/New_York", "ri": "America/New_York",
    "south carolina": "America/New_York", "sc": "America/New_York",
    "south dakota": "America/Chicago", "sd": "America/Chicago",
    "tennessee": "America/Chicago", "tn": "America/Chicago",
    "texas": "America/Chicago", "tx": "America/Chicago",
    "utah": "America/Denver", "ut": "America/Denver",
    "vermont": "America/New_York", "vt": "America/New_York",
    "virginia": "America/New_York", "va": "America/New_York",
    "washington state": "America/Los_Angeles", "wa": "America/Los_Angeles",
    "west virginia": "America/New_York", "wv": "America/New_York",
    "wisconsin": "America/Chicago", "wi": "America/Chicago",
    "wyoming": "America/Denver", "wy": "America/Denver",
}

# ── Country names -> single representative tz (used as a last resort) ───────────
_COUNTRY_TZ = {
    "usa": "America/New_York", "us": "America/New_York", "united states": "America/New_York",
    "america": "America/New_York", "uk": "Europe/London", "england": "Europe/London",
    "scotland": "Europe/London", "wales": "Europe/London", "britain": "Europe/London",
    "united kingdom": "Europe/London", "ireland": "Europe/Dublin", "france": "Europe/Paris",
    "spain": "Europe/Madrid", "portugal": "Europe/Lisbon", "germany": "Europe/Berlin",
    "netherlands": "Europe/Amsterdam", "belgium": "Europe/Brussels", "italy": "Europe/Rome",
    "switzerland": "Europe/Zurich", "austria": "Europe/Vienna", "poland": "Europe/Warsaw",
    "sweden": "Europe/Stockholm", "norway": "Europe/Oslo", "denmark": "Europe/Copenhagen",
    "finland": "Europe/Helsinki", "greece": "Europe/Athens", "turkey": "Europe/Istanbul",
    "russia": "Europe/Moscow", "ukraine": "Europe/Kyiv", "uae": "Asia/Dubai",
    "japan": "Asia/Tokyo", "korea": "Asia/Seoul", "south korea": "Asia/Seoul",
    "china": "Asia/Shanghai", "singapore": "Asia/Singapore", "thailand": "Asia/Bangkok",
    "india": "Asia/Kolkata", "pakistan": "Asia/Karachi", "australia": "Australia/Sydney",
    "new zealand": "Pacific/Auckland", "mexico": "America/Mexico_City", "brazil": "America/Sao_Paulo",
    "argentina": "America/Argentina/Buenos_Aires", "chile": "America/Santiago",
    "canada": "America/Toronto", "egypt": "Africa/Cairo", "nigeria": "Africa/Lagos",
    "kenya": "Africa/Nairobi", "south africa": "Africa/Johannesburg",
}


def _normalize(text: str) -> str:
    t = (text or "").strip().lower()
    t = t.replace("&", " and ")
    t = re.sub(r"[.,/]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # strip common filler so "i'm in austin texas" -> "austin texas"
    for filler in ("i live in ", "i'm in ", "im in ", "i am in ", "based in ",
                   "i'm from ", "im from ", "from ", "currently in ", "live in ",
                   "located in ", "spend most of my time in ", "mostly in "):
        if t.startswith(filler):
            t = t[len(filler):].strip()
    return t


def resolve_timezone(text: str) -> str | None:
    """
    Map a free-form location string to an IANA timezone, or None if unsure.
    """
    t = _normalize(text)
    if not t:
        return None

    # 1) direct full-string city hit
    if t in _CITY_TZ:
        return _CITY_TZ[t]

    # 2) "city, state/country" — try the first token group as a city
    parts = [p.strip() for p in re.split(r"[ ]+", t)]
    # try progressively shorter prefixes as a city name (handles "san francisco ca")
    for n in range(min(3, len(parts)), 0, -1):
        cand = " ".join(parts[:n])
        if cand in _CITY_TZ:
            return _CITY_TZ[cand]

    # 3) US state (often the last token, e.g. "austin tx")
    for token in reversed(parts):
        if token in _US_STATE_TZ:
            return _US_STATE_TZ[token]
    # multi-word states ("new york state", "south carolina")
    for n in (2, 3):
        for i in range(len(parts) - n + 1):
            cand = " ".join(parts[i:i + n])
            if cand in _US_STATE_TZ:
                return _US_STATE_TZ[cand]

    # 4) country
    if t in _COUNTRY_TZ:
        return _COUNTRY_TZ[t]
    for token in reversed(parts):
        if token in _COUNTRY_TZ:
            return _COUNTRY_TZ[token]

    # 5) substring scan — any known city name appearing anywhere, on WORD
    # boundaries. A raw `in` check made every string containing "la"/"dc"/"sf"
    # resolve ("Planet Xyzzy" → Los Angeles via p-LA-net), which mattered once
    # normalize_timezone started routing junk timezone-field input through here.
    for city, tz in _CITY_TZ.items():
        if re.search(rf"\b{re.escape(city)}\b", t):
            return tz

    return None


# ── Intake gate for the users.timezone column ─────────────────────────────────
# users.timezone feeds pytz.timezone() on the chat turn path
# (db/queries._user_today), the proactive scheduler, and the context builder.
# A junk value in the column (a real user typed "Naples, USA" into the
# onboarding timezone field) used to 500 every message that user sent. The
# rule: only a real IANA zone name ever lands in the column. Free-form input
# gets one confident salvage pass through resolve_timezone; anything else
# normalizes to None ("unknown" — everything falls back to UTC and the
# proactive city-ask recovers the real zone conversationally).

import pytz as _pytz

# Case-corrected lookup of every IANA zone ("america/new_york" → "America/New_York").
_IANA_CANONICAL = {z.lower(): z for z in _pytz.all_timezones}


def normalize_timezone(value) -> str | None:
    """The valid IANA zone for `value` — exact (case-corrected) IANA names pass
    through, free-form locations go through resolve_timezone — or None for
    anything unrecognizable. Never raises."""
    if not value or not isinstance(value, str):
        return None
    v = value.strip()
    if not v:
        return None
    canon = _IANA_CANONICAL.get(v.lower())
    if canon:
        return canon
    return resolve_timezone(v)


def safe_timezone(name):
    """pytz tzinfo for `name`, falling back to UTC instead of raising — legacy
    rows written before intake validation may still hold junk values, and a bad
    timezone must never crash a chat turn or a scheduler tick."""
    try:
        return _pytz.timezone(name or "UTC")
    except _pytz.exceptions.UnknownTimeZoneError:
        return _pytz.utc
