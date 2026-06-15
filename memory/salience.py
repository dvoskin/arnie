"""Salience scoring — pick the attributes most relevant to the current message.

Deterministic, no LLM (this runs on every turn — must be cheap). Used by
get_attributes_for_context to (1) spotlight the active facts most pertinent to
what the user just said, and (2) RECALL archived facts the default block omits
when the topic matches — so a fact Arnie filed away resurfaces exactly when it
matters, instead of being invisible forever.

The whole-picture block is unchanged; salience is purely additive on top of it.
"""
import re

# Surface words → canonical concept. Both the message and each attribute's text
# are expanded through this map so vocabulary gaps still match
# (msg "knee" ↔ attribute "ACL reconstruction" both → concept "injury").
_CONCEPT_SYNONYMS: dict[str, set[str]] = {
    "injury": {"knee", "acl", "meniscus", "joint", "shoulder", "elbow", "wrist",
               "injury", "injured", "pain", "hurt", "rehab", "tendon", "strain"},
    "cardio": {"cardio", "spin", "bike", "cycling", "walk", "incline", "zone",
               "run", "running", "treadmill", "steps", "conditioning"},
    "sleep_recovery": {"sleep", "tired", "exhausted", "rest", "recovery", "nap",
                       "insomnia", "rested", "fatigue", "fatigued", "hrv", "groggy"},
    "stress": {"stress", "stressed", "anxiety", "anxious", "overwhelmed", "burnout",
               "tense", "pressure"},
    "travel": {"travel", "traveling", "trip", "flight", "hotel", "vacation",
               "airport", "road", "away"},
    "alcohol": {"beer", "wine", "alcohol", "drink", "drinks", "cocktail", "duvel",
                "ipa", "whiskey", "tequila", "buzzed", "drinking"},
    "evening": {"late", "night", "nighttime", "evening", "bedtime", "midnight",
                "pm", "snack", "snacking"},
    "protein": {"protein", "macro", "macros", "shake", "bar", "chicken", "turkey",
                "whey", "grams"},
    "supplement": {"supplement", "supplements", "creatine", "vitamin", "vitamins",
                   "magnesium", "zinc", "omega", "fish", "oil", "ferritin"},
    "biomarker": {"bloodwork", "labs", "lab", "a1c", "glucose", "cholesterol", "tsh",
                  "testosterone", "panel", "biomarker", "egfr", "lh"},
    "dining_out": {"restaurant", "takeout", "delivery", "order", "ordered", "ubereats",
                   "doordash", "dining", "menu", "chipotle", "sushi", "shawarma"},
    "weight": {"weight", "scale", "weigh", "weighed", "lbs", "kg", "lighter", "heavier"},
    "family": {"baby", "wife", "husband", "family", "kid", "kids", "married", "son",
               "daughter"},
    "work": {"work", "job", "office", "meeting", "desk", "shift", "deadline"},
    "cut_bulk": {"cut", "cutting", "deficit", "bulk", "bulking", "surplus", "lean",
                 "maintenance", "recomp"},
}

# Reverse index: surface word → set of concepts it belongs to.
_WORD_TO_CONCEPTS: dict[str, set[str]] = {}
for _concept, _words in _CONCEPT_SYNONYMS.items():
    for _w in _words:
        _WORD_TO_CONCEPTS.setdefault(_w, set()).add(_concept)

_STOPWORDS = {
    "the", "and", "for", "you", "your", "what", "with", "this", "that", "have",
    "how", "are", "was", "should", "could", "would", "can", "did", "does", "got",
    "get", "out", "any", "but", "not", "all", "now", "today", "about", "from",
    "they", "them", "i'm", "i've", "it's", "just", "like", "want", "need", "more",
}


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
            if len(w) >= 3 and w not in _STOPWORDS}


def _expand(words: set[str]) -> set[str]:
    """Words plus the concepts they map to."""
    out = set(words)
    for w in words:
        out |= _WORD_TO_CONCEPTS.get(w, set())
    return out


def _attr_terms(attr) -> set[str]:
    """Concept-expanded term set for an attribute (key + display + value)."""
    key_words = {p for p in (attr.attribute_key or "").split("_") if len(p) >= 3}
    text_words = _tokens(f"{attr.display_name or ''} {attr.value or ''}")
    return _expand(key_words | text_words)


def score_attribute(message_text: str, attr) -> int:
    """Overlap score between the message and an attribute. 0 = unrelated."""
    msg = _expand(_tokens(message_text))
    if not msg:
        return 0
    return len(msg & _attr_terms(attr))


def select_relevant(message_text: str, rows: list, *, k: int = 4,
                    min_score: int = 1) -> list:
    """Top-k attributes most relevant to the message, score-desc then recency.
    Returns [] if the message is empty or nothing clears min_score."""
    if not message_text or not rows:
        return []
    scored = [(score_attribute(message_text, r), r) for r in rows]
    scored = [(s, r) for s, r in scored if s >= min_score]
    scored.sort(key=lambda sr: (sr[0], sr[1].updated_at or sr[1].created_at),
                reverse=True)
    return [r for _, r in scored[:k]]
