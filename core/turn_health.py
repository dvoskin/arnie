"""
Turn-health detectors — cheap, deterministic signals that a turn went wrong.

These are PURE functions with no side effects. They are used for telemetry and
flagging only — never to alter the reply the user gets. The point: make every
deviation (a truncated dump, a narration stall, a frustrated user, a tool error)
self-evident in logs and the admin audit view, instead of relying on someone
eyeballing a screenshot.

The flags persist on ConversationLog.parsed_intent (an existing, unused column —
no schema migration) and surface in /admin/audit's "intent" field.
"""
import re

# Action-commitment phrases that signal a STALL when they appear with NO tool calls:
# the model promised to do something ("let me delete...", "deleting all of today's…")
# but emitted nothing, so a broken promise ships and nothing happens. High precision —
# a normal conversational reply doesn't use these first-person DB-action verbs.
# ("let me know" / "let me think" are deliberately absent.)
_STALL_MARKERS = (
    "let me do that", "let me do this", "let me handle this", "let me handle that",
    "let me delete", "let me clear", "let me log", "let me move", "let me relog",
    "let me reopen", "let me sort", "let me get that logged",
    "i need to delete", "i need to log", "i need to clear", "i need to move",
    "i need to relog", "i need to reopen", "i need to update that",
    "i'll delete", "i'll clear", "i'll relog", "i'll move that", "i'll handle that",
    "deleting all", "clearing today", "relogging", "logging everything",
    "logging it all", "logging all of that", "logging all of it",
    "i'll log all", "let me get all",
    "adding it all", "adding all of that", "gonna log", "going to log",
    # Update/correction promises — "fixing it now", "updating that", "adjusting it"
    # said with no update_food_entry (the Royo bagel "Fixing it now" that never wrote).
    "fixing it", "fixing that", "fixing now", "updating it", "updating that",
    "adjusting it", "adjusting that", "let me fix", "let me update", "let me adjust",
    "i'll fix", "i'll update", "i'll adjust",
    # Lookup-promise stalls (the screenshot pattern — "Checking the label on
    # that one" / "Let me grab the exact macros" without ever firing the tool).
    # These read as substantive replies but strand the user when paired with
    # no tool_calls.
    "checking the label", "checking exact macros", "checking the macros",
    "let me grab the exact macros", "let me grab the macros",
    "let me check the label", "let me look up", "let me pull up",
    "grabbing the exact macros", "grabbing the macros",
    "looking up the macros", "looking it up real quick",
    # Russian stall phrases
    "исправляю прямо сейчас", "исправляю сейчас", "сейчас всё занесу",
    "сейчас занесу", "сейчас залогирую", "сейчас всё залогирую",
    "сейчас исправлю", "давай занесу", "давай залогирую",
    "сейчас всё внесу", "сейчас внесу", "внесу прямо сейчас",
    "залогирую прямо сейчас", "логирую прямо сейчас",
    "мне нужно залогировать", "мне нужно внести",
    "я залогирую", "я внесу", "я занесу",
)

# Frustration / "you got it wrong" markers — a very high-precision proxy for "Arnie
# screwed up." Whole-word / phrase matching to avoid false hits ("scunthorpe" etc.).
_FRUSTRATION = re.compile(
    r"\b(wtf|wth|stfu|dumb|stupid|idiot|downy|useless|"
    r"you missed|u missed|already told you|i told you|that'?s not what|"
    r"not what i (said|meant)|are you (ok|serious|dumb|stupid|kidding)|"
    r"makes no sense|wrong again|still wrong)\b",
    re.I,
)


def looks_like_stall(text: str) -> bool:
    """True if `text` promises an action but (paired with no tool calls) didn't do it."""
    t = (text or "").strip().lower()
    if not t:
        return False
    return t.endswith(":") or t.startswith("on it") or any(m in t for m in _STALL_MARKERS)


# Partial-stall: the model logged SOME items of a multi-item message, then promised
# to log the rest in a later turn ("Salmon's in. Let me get the rest.") instead of
# firing every tool this turn. Unlike looks_like_stall (which requires ZERO tool
# calls), this fires WHEN tools already ran — so it needs its own detector. The
# self-heal that catches it forces the remaining items in the same turn. Critical
# because a conversation history full of past drip-logs primes the model to repeat
# the pattern no matter what the system prompt says.
_PROMISE_MORE_RE = re.compile(
    r"\b(?:get|getting|grab|grabbing|log|logging|do|doing|add|adding|knock(?:ing)?\s+out|"
    r"finish|finishing|handle|handling)\s+(?:the\s+)?(?:rest|others?|remaining|other\s+\w+)\b"
    r"|\bstill\s+(?:waiting on|need|got|have)\b"
    r"|\b(?:let me|i'?ll|gonna|going to)\s+(?:get|grab|do|add|log)\s+(?:the\s+)?(?:rest|others)\b"
    r"|\bone\s+(?:sec|second|moment)\b|\bhang on\b|\bnext up\b|\bonto the\b|\bnow (?:for|onto) the\b",
    re.IGNORECASE,
)


def promises_more_logging(text: str) -> bool:
    """True if the reply says it will log MORE items later ('let me get the rest')."""
    return bool(_PROMISE_MORE_RE.search(text or ""))


# Silent under-log: the message names a long list of foods but only 1-2 log_food
# fired and the reply looked complete (no "let me get the rest" to catch). The
# burrito-bowl incident (2026-07-20): "chicken burrito bowl with 5 oz chicken, ¾ cup
# rice, ½ cup black beans, fajita veggies, corn salsa, pico, cheese, 2 tbsp sour
# cream, chips, half a lemonade" → ONE log_food, complete-looking confirm. The
# promise-based detector can't see it. This estimates items named from the list
# structure so a big shortfall (logged << named) can self-heal — the retry does the
# real extraction, so this only needs to TRIGGER on clear multi-item lists.
_QTY_MARKER_RE = re.compile(
    r"\b\d+\s*(?:oz|ounces?|g|grams?|kg|lb|lbs|ml|cups?|tbsp|tsp|tablespoons?|teaspoons?|"
    r"slices?|pieces?|scoops?|handfuls?|servings?|bars?"
    # Cyrillic units — the 2026-07-20 Russian lunch list ("Рис 200 г, Куриную
    # отбивную в кляре 150г…") scored ZERO items because only Latin units
    # matched, so the under-log self-heal never fired on RU/UK messages.
    r"|г|гр|грамм(?:а|ов)?|кг|мл|л|шт(?:ук[аи]?)?|стакан(?:а|ов)?|"
    r"ложк[аи]|кусоч?к[аи]?|ломтик(?:а|ов)?|порци[яи]|банк[аи]|бутылк[аи])(?=[\s.,;)]|$)"
    r"|\b(?:½|¼|¾|half|quarter|a\s+(?:cup|handful|glass|can|bottle|slice|piece|scoop)|"
    r"small|large|medium|полов[иі]н[аук]|пол-|небольш\w+|маленьк\w+|больш\w+)\b",
    re.IGNORECASE,
)
# Newlines count as separators — users paste meals as one-item-per-line lists.
# Russian/Ukrainian connectors included so RU/UK lists segment like EN ones.
_LIST_SEP_RE = re.compile(
    r",|;|\n|\band\b|\bwith\b|\bplus\b|\balso\b|\bthen\b"
    r"|\bи\b|\bс\b|\bплюс\b|\bеще\b|\bещё\b|\bпотом\b|\bзатем\b|\bтакже\b"
    r"|\bі\b|\bта\b|\bз\b",
    re.IGNORECASE,
)


def estimate_food_items(message: str) -> int:
    """Rough count of distinct foods a multi-item message names, from its list
    structure (comma / 'and' / 'with' separated segments that carry a food or
    quantity signal). Deliberately approximate — used only to spot a big shortfall."""
    if not message:
        return 0
    segs = [s.strip() for s in _LIST_SEP_RE.split(message) if s.strip()]
    n = 0
    for s in segs:
        words = re.findall(r"[a-zа-яё]+", s.lower())
        content = [w for w in words if w not in _LIST_FILLER]
        # a segment is a food item if it carries a quantity marker OR is a short,
        # content-bearing noun phrase (1-4 real words) — "corn salsa", "pico", "fajita
        # veggies". Long clauses ("it was really good") carry no quantity and >4 words.
        if _QTY_MARKER_RE.search(s) or (1 <= len(content) <= 4):
            n += 1
    return n


_LIST_FILLER = {
    "i", "had", "have", "having", "ate", "eating", "some", "a", "an", "the", "of",
    "about", "around", "like", "just", "also", "and", "with", "plus", "then", "my",
    "for", "lunch", "dinner", "breakfast", "snack", "today", "it", "was", "were",
    "drank", "got", "grabbed", "small", "big", "handful", "piece", "cup", "half",
    # Russian / Ukrainian fillers — eating verbs, meal words, prepositions,
    # units. Without these every RU segment counts its verbs as content words.
    "я", "съел", "съела", "поел", "поела", "ел", "ела", "выпил", "выпила",
    "в", "на", "за", "обед", "ужин", "завтрак", "перекус", "сегодня", "вчера",
    "еще", "ещё", "было", "и", "с", "немного", "примерно", "около", "грамм",
    "г", "гр", "кг", "мл", "шт", "штук", "з", "та", "і", "їв", "їла", "з'їв",
}

# A PORTIONED segment carries an explicit amount: a unit quantity ("3/4 cup", "150g")
# OR a leading count ("1 egg", "2 bars", "half a bagel"). Counting bare counts — not
# just units — catches "1 egg plus 3/4 cup of egg whites" (Chaya, 2026-07-21: the egg
# whites dropped, only 1 unit-qty so the old >=2-quantity gate missed it). Still tight:
# "lettuce, tomato, onion + mustard, 20 cal" has no per-item amount → won't trip.
_COUNT_SIGNAL_RE = re.compile(r"^\s*(?:a|an|one|two|three|four|five|half|\d+(?:/\d+)?)\s+[a-z]",
                              re.IGNORECASE)


def looks_like_undercounted_food(message: str, num_food_logs: int) -> bool:
    """True when a message ENUMERATES a multi-item meal (>=2 items, >=2 of them carrying
    an explicit PORTION — a unit quantity or a leading count) but far fewer log_food
    calls fired than items named. The portion requirement keeps a single 'lettuce,
    tomato, onion + mustard, 20 cal' veggie mix and a plain 'chicken and rice' (no
    per-item amounts) from tripping it. The self-heal retry does the real extraction;
    this only needs to trigger. Threshold 4→2 (turkey+rice reference-drop, 2026-07-20);
    counts-as-portions added for the egg+egg-whites drop (2026-07-21)."""
    est = estimate_food_items(message)
    segs = [s for s in _LIST_SEP_RE.split(message or "") if s.strip()]
    portioned = sum(1 for s in segs
                    if _QTY_MARKER_RE.search(s) or _COUNT_SIGNAL_RE.search(s))
    return est >= 2 and portioned >= 2 and num_food_logs <= est // 2


# Bare acknowledgments that are banned as a COMPLETE reply — they dead-end the
# conversation and add nothing. Especially wrong right after the user answered a
# question (that should continue, not close).
_DEAD_END_PHRASES = {
    # single-token forms
    "done", "got it", "gotcha", "logged", "recorded", "noted", "okay", "ok",
    "perfect", "sounds good", "all set", "updated", "great", "nice", "cool",
    "yep", "yup", "sure", "alright", "roger",
    # two-word variants that slip past the single-token filter
    "logged that", "logged it", "got it logged", "all logged", "got that",
    "got that logged", "done for now", "all good", "that's logged",
    # NOTE: "sleep well" / "goodnight" intentionally NOT here — they are correct
    # contextual responses when the user signs off. Including them caused quality
    # repair to fire after a goodnight and re-log food from context (real bug).
}

# Sign-off phrases that the user might say to trigger a goodnight response.
# When the user's message contains one of these, Arnie's "Sleep well 🌙" is
# intentional — NOT a dead-end. Used to gate quality repair and Telegram
# streaming, where a first-pass sign-off can otherwise duplicate after tool follow-up.
_USER_SIGNOFF_PATTERNS = re.compile(
    r"\b(goodnight|good night|night|nite|gn|sleep well|done for today|"
    r"closing it out|i'?m done|going to sleep|go(?:ing|nna)? to sleep|"
    r"gonna sleep|going to bed|go(?:ing|nna)? to bed|off to bed|"
    r"heading to bed|спокойной ночи|ночи|"
    r"dormir|buenas noches|bonne nuit)\b",
    re.IGNORECASE,
)

def looks_like_dead_end(text: str) -> bool:
    """
    True if the WHOLE reply is just a bare acknowledgment ("done", "got it", "logged",
    even "done ✅"). Substance after the word ("done, you're at 450") is fine — only a
    reply that reduces to a dead-end token is flagged.
    """
    t = (text or "").replace("|||", " ").strip().lower()
    if not t:
        return False
    core = re.sub(r"[^a-z' ]+", " ", t)   # strip emoji / digits / punctuation
    core = re.sub(r"\s+", " ", core).strip()
    return core in _DEAD_END_PHRASES


# Phrases that expose internal mechanics the user should never see — tool names,
# sync/resync language, DB confirmation wording. Substring-matched so partial
# sentences containing these are caught ("Updated totals are resynced for you.").
_MECHANICS_PHRASES = (
    "totals are resynced", "totals resynced", "totals have been resynced",
    "totals have been updated", "totals have been synced", "totals synced",
    "entry has been updated", "entry updated successfully", "entry saved",
    "changes saved", "changes have been saved", "database updated",
    "your log has been updated", "the log has been updated", "log has been updated",
    "synced successfully", "resynced successfully",
    "updated in the system", "saved in the system", "stored in the system",
    # Russian equivalents
    "итоги пересинхронизированы", "данные обновлены в системе",
)


# Subset of dead-end phrases that are ALWAYS wrong even on logging turns —
# pure log acknowledgments with no coaching. Unlike "Nice 💪" or "Clean ✅"
# (which ARE valid brief coaching after a tool call), these contain zero
# substance: they only confirm the mechanical act of logging itself.
_LOG_ACK_PHRASES = {
    "logged", "logged that", "logged it", "got it logged", "all logged",
    "got that logged", "that's logged", "done logging",
}


def looks_like_bare_log_ack(text: str) -> bool:
    """
    True for pure log-acknowledgment replies ("Logged that.", "All logged.") that
    are bad even after tool calls. Narrower than looks_like_dead_end — it never
    flags valid brief coaching like "Nice 💪" or "Clean 🔥" on a logging turn.
    """
    t = (text or "").replace("|||", " ").strip().lower()
    if not t:
        return False
    core = re.sub(r"[^a-z' ]+", " ", t).strip()
    return core in _LOG_ACK_PHRASES


# Empty-praise patterns that the voice rules ban but the LLM still occasionally
# generates. These sound like coaching but contain zero substance: no numbers,
# no specific next move. "Great workout! How did it feel?" is the canonical
# example — it loops in lifecycle (pending question) until answered, making
# it look like Arnie is glitching. We catch it here and trigger quality repair
# the same way we catch mechanics narration.
#
# Guard: only fire on SHORT replies (< 150 chars) with NO digits. A reply like
# "Great macro split — 165g protein" has real data and is fine. "Great workout!
# How did it feel?" has no numbers and is caught.
_EMPTY_PRAISE_PATTERNS = re.compile(
    r"\b(great (workout|session|job|work|effort|progress|stuff)|"
    r"amazing (workout|session|job|work|effort)|"
    r"nice (workout|session|job|work|effort)|"
    r"good (workout|session|job|work|effort)|"
    r"solid (workout|session|job|work)(?!\s+\w)|"
    r"excellent (workout|session|job|effort)|"
    r"way to go|"
    r"you('?ve)? got this|"
    r"keep it up|"
    r"proud of you|"
    r"you'?re doing (great|amazing|well|good)|"
    r"stay (consistent|strong|focused|on track))\b",
    re.IGNORECASE,
)


def looks_like_empty_praise(text: str) -> bool:
    """
    True if the reply is short, contains no numeric data, and leads with a
    banned empty-praise phrase ("Great workout!", "Nice job!", etc.).

    These replies are bad because they contain zero coaching value — no
    numbers, no next move — and when stored as conversation hooks they create
    a loop where proactive messages keep re-asking the generic question until
    the user answers. Catching them here triggers the same quality repair as
    mechanics narration.
    """
    t = (text or "").replace("|||", " ").strip()
    if not t or len(t) > 150:
        return False
    if re.search(r'\d', t):  # real numeric data present → not empty praise
        return False
    return bool(_EMPTY_PRAISE_PATTERNS.search(t))


def looks_like_mechanics(text: str) -> bool:
    """
    True if the response leaks internal plumbing language the user should never see
    ('Updated totals are resynced', 'Entry saved', etc.). Substring match so partial
    sentences are caught.
    """
    t = (text or "").strip().lower()
    return any(phrase in t for phrase in _MECHANICS_PHRASES)


def user_is_signing_off(user_text: str) -> bool:
    """True if the user's message is a sign-off (goodnight, going to sleep, etc.)."""
    return bool(user_text and _USER_SIGNOFF_PATTERNS.search(user_text))


def detect_frustration(user_text: str) -> bool:
    return bool(user_text and _FRUSTRATION.search(user_text))


# Short praise-style acks that, on their own, sound positive but read as sarcastic
# when the immediately prior assistant turn shipped a known-bad signal (mechanics
# narration, generic-net fallback, bare logging ack). Matched as the WHOLE user
# message (with punctuation stripped) so a real "Great workout!" never matches.
_SARCASTIC_PRAISE_TOKENS = {
    "great", "perfect", "awesome", "nice", "thanks", "cool", "sure",
    "amazing", "wonderful", "fantastic", "lovely",
}


def detect_sarcastic_ack(user_text: str, prior_assistant_text: str = "") -> bool:
    """True if the user's whole message is a one-word praise token AND the prior
    assistant turn carried a known-bad signal (mechanics narration, generic-net
    "Got that. / You're at X cal today", or a bare-log ack). In that context a
    cheerful "Great" is virtually always sarcastic frustration — Arnie should
    recover, not steam past it.

    Pure function for telemetry + system-prompt enrichment; never alters the
    user's turn itself.
    """
    if not user_text:
        return False
    import re as _re
    core = _re.sub(r"[^a-z' ]+", " ", user_text.lower()).strip()
    core = _re.sub(r"\s+", " ", core)
    if core not in _SARCASTIC_PRAISE_TOKENS:
        return False
    if not prior_assistant_text:
        return False
    # Bad-signal heuristics on the prior turn — substring matched.
    prior = prior_assistant_text.lower()
    if looks_like_mechanics(prior):
        return True
    if ("got that." in prior or "on the board." in prior) and "calories today" in prior:
        return True  # the generic-net deterministic_confirmation pattern (old + new head)
    if looks_like_bare_log_ack(prior):
        return True
    return False


# Calorie/macro estimate pattern — signals that a food photo's nutrition analysis
# text is present in the first-pass response. Used to detect when the LLM narrates
# macro numbers instead of calling log_food (partial stall from photo turns).
# Calorie unit, EN + RU. A third of the beta (Anya) logs in Russian, where the
# unit is "калорий"/"ккал" — an EN-only unit let her stated totals (and the
# phantom log behind them) sail past BOTH the day-total guard and the total-claim
# rescue ("690 / 1,570 калорий", zero tool calls → nothing logged, she had to
# re-send). Every calorie-figure detector below shares this alternation.
_CAL_UNIT = r"(?:cal|cals|calories|kcal|ккал|калори\w*)"
_CALORIE_ESTIMATE_RE = re.compile(rf'\d+\s*{_CAL_UNIT}\b', re.I)


# ── Day-total truth guard ────────────────────────────────────────────────────
# Divergence (in calories) between the total Arnie STATES and the committed DB
# total that still counts as "matches" — absorbs per-item rounding, never a whole
# missing item (the smallest real food is ~15 cal, a phantom bar/beer is 90+).
DAY_TOTAL_TOLERANCE = 30

# The two confirmation shapes Arnie uses to state the running DAY total, and only
# those — both are current-day-total forms, so a match is reliably the figure we
# can check against today_log.total_calories:
#   • "984 / 2,165 calories"  /  "984/2165 cal"     (the standard confirm line)
#   • "Total: 984 calories"                          (the rerun/list summary)
# Deliberately NARROW: a bare "200 calories" (a single item's macros) or
# "1,181 calories left" (remaining) must NOT match, or the guard fires on
# legitimate per-item / remaining numbers.
_STATED_DAY_TOTAL_RES = (
    re.compile(rf"\b([\d,]{{2,6}})\s*/\s*[\d,]{{2,6}}\s*{_CAL_UNIT}\b", re.I),
    re.compile(rf"\b(?:total|итого|всего):?\s*\**\s*([\d,]{{2,6}})\s*{_CAL_UNIT}\b", re.I),
)


def extract_stated_day_calories(text: str) -> int | None:
    """Pull the day-total calorie figure Arnie stated in a reply, or None if the
    reply states no day total. Only the two current-day-total shapes match (see
    _STATED_DAY_TOTAL_RES) so per-item macros and 'X left' never register.

    Used by the day-total truth guard to compare what Arnie SAID against the
    committed DB total — a divergence means a phantom log or carried-forward
    arithmetic, and the number is corrected before it reaches the user."""
    if not text:
        return None
    for rx in _STATED_DAY_TOTAL_RES:
        m = rx.search(text)
        if m:
            try:
                return int(m.group(1).replace(",", ""))
            except (ValueError, AttributeError):
                continue
    return None


# Past-tense "it's recorded" claims — the sibling of _STALL_MARKERS (which are
# future-tense promises). When one of these appears with NO tool call on a turn
# where the user clearly reported a loggable set, the model confirmed a write that
# never happened — and the set silently vanishes (Danny 2026-06-25: "11 on left
# side 13 rig" → "Unilateral, noted" with no log_exercise → set lost; the resend
# then got a false "already on the board"). High-precision ONLY in conjunction
# with a set-report user message + zero tool calls.
_RECORDED_CLAIM = (
    "on the board", "noted", "logged", "got it logged", "locked in",
    "in the books", "on the books", "recorded", "added that", "that's in",
    "got that down",
    # Correction / UPDATE claims — "I've got yours in at…", "updated", "fixed it",
    # "adjusted", "trimmed/bumped it to…" said with NO update_food_entry (Danny's Royo
    # bagel + Happy Wolf, 2026-07-21): a claimed edit that never wrote.
    "got yours in", "got that in", "updated", "adjusted it", "fixed it",
    "fixed now", "trimmed", "bumped it", "changed it to", "both fixed", "all fixed",
    # RU past-tense success claims — Anya 2026-07-19: "Кофе и кола внесены ☕"
    # with ZERO tool calls sailed straight through the EN-only list. A third
    # of the beta logs in Russian; the phantom detector must too.
    "внесены", "внесен", "внесла", "внёс", "внесено",
    "записано", "записала", "записал", "добавлено", "добавила", "добавил",
    "залогировано", "залогировала", "занесла", "занёс", "в логе", "в дневнике",
)

# Exercise set-report shapes in the USER's message: "190x14", "11 x40", "3x12",
# "13 reps", "11 on left", "12 on the right". Numbers paired with rep/side context
# — deliberately narrow so a bare number or a food amount doesn't match.
_SET_REPORT_RE = re.compile(
    r"\b\d+\s*[x×]\s*\d+\b"                       # 190x14, 3x12
    r"|\b\d+\s*reps?\b"                           # 13 reps
    r"|\b\d+\s*on\s*(?:the\s*)?(?:left|right)\b"  # 11 on left / 13 on the right
    r"|\b(?:left|right)\s*side\b[^\d]*\b\d+\b",   # left side ... 11
    re.IGNORECASE,
)

# Food-report shapes in the USER's message: an eating verb ("had", "ate",
# "grabbed", "for lunch") or a common food/snack noun. Deliberately broad but
# still anchored to food language, so it pairs with a recorded-claim reply to
# catch a phantom FOOD log the same way _SET_REPORT_RE catches a phantom set.
# The screenshot bug: "I had quest chips and caramel cashew" → "logged, 340 cal"
# with NO log_food call → nothing written, false confirmation.
_FOOD_REPORT_RE = re.compile(
    r"\b(had|ate|eating|grabbed|just\s+had|for\s+(?:breakfast|lunch|dinner|a\s+snack))\b"
    r"|\b(bar|shake|chips|bagel|meal|snack|smoothie|protein|coffee|latte)\b",
    re.IGNORECASE,
)

# Loggable INTENT the food-report regex misses — the model claimed success on these
# and fired nothing (Danny 2026-07-21): imperative adds ("add a happy wolf", "log the
# rice"), "also had X" continuations, and CORRECTIONS that state macros ("Royo bagels
# are 80 cal 10g protein", "make it 200 cal"). Any of these + a recorded-claim reply +
# zero tools = a phantom that must be rescued into a real log_food/update_food_entry.
_LOG_INTENT_RE = re.compile(
    r"\b(add|log|put|track|note|include|throw\s+in|toss\s+in|jot\s+down)\b"
    r"|\balso\s+(had|ate|got|grabbed|have)\b"
    r"|\b(is|are|should\s+be|make\s+it|change\s+it\s+to|actually)\b[^.]*\b\d+\s*(?:cal|cals|calorie|kcal)\b"
    r"|\b\d+\s*(?:cal|cals|calorie|kcal)\b[^.]*\b(?:protein|carbs?|fat)\b",
    re.IGNORECASE,
)

# WEIGHT report in the USER's message — "weighed in at 194", "weight looks like 194.2
# this morning", "I'm 194 lbs", "down to 88kg". Danny 2026-07-21: "Weight looks like
# 194.2 this morning" → "194.2 logged" with ZERO log_body_weight → weight never saved.
# The food/set gates missed it, so the phantom rescue never fired. Conservative: keys
# on weigh/weight verbs or an explicit weight UNIT (never a bare number → no "I'm 25").
_WEIGHT_REPORT_RE = re.compile(
    r"\bweigh(?:ed|ing|s|-?\s*in)?\b"
    r"|\bweight(?:'?s)?\s+(?:is|was|looks?|at|of|today|down|up|holding|steady)\b"
    r"|\b\d{2,3}(?:\.\d)?\s*(?:lbs?|kgs?|pounds?)\b"
    r"|\bdown\s+to\s+\d{2,3}(?:\.\d)?\s*(?:lbs?|kgs?|pounds?)\b",
    re.IGNORECASE,
)


# PAST/PRESENT food-consumption report vs a PLAN. "I had 2 pieces of starburst"
# is consumed; "probably ground turkey later" is a plan. Used by the OMISSION net.
_CONSUMED_RE = re.compile(
    r"\b(had|ate|eaten|having|grabbed|finished|snacked|downed|"
    r"just\s+(?:had|ate|grabbed|finished|got|made)|"
    r"for\s+(?:breakfast|lunch|dinner|a\s+snack|dessert))\b", re.I)
_PLAN_RE = re.compile(
    r"\b(gonna|going\s+to|about\s+to|planning|plan\s+to|might|maybe|probably|"
    r"thinking\s+(?:about|of)|will\s+(?:have|eat|grab|do)|later\b|in\s+\d+\s*min|"
    r"not\s+sure|i'?ll\s+(?:have|eat|grab|do))\b", re.I)
# A LOOKUP/advice question, not a food to log ("how many cal in a banana",
# "what should I eat"). Keyed on a leading question word or a '?'.
_QUESTION_RE = re.compile(
    r"^\s*(how|what|why|when|where|which|who|whose|whom|is|are|am|was|were|do|"
    r"does|did|can|could|should|would|will|has|have|any)\b", re.I)
# A bare acknowledgment ("ok", "thanks", "nice") — usually the trigger for a
# day-total RECAP, not a food report. Whole-message match only.
_ACK_RE = re.compile(
    r"^(ok(ay)?|k+|thx|thanks|thank\s+you|ty|cool|nice|great|sweet|got\s+it|"
    r"gotcha|yes|yeah|yep|yup|sure|no+|nope|word|bet|perfect|awesome|amazing|"
    r"love\s+it|good|alright|right|damn|lol|haha)[.!,\s]*$", re.I)


def looks_like_unlogged_food_report(user_text: str, response_text: str) -> bool:
    """True when the reply QUANTIFIED a food (stated calories/macros) but — the
    caller confirms — fired NO log tool and asked no question: the model recognized
    a loggable item and narrated it instead of logging it.

    Broadened 2026-07-21 (Danny: 'he keeps missing actually logging foods'): the
    tell is the reply's macro figure, NOT a consumption verb in the message — a
    BARE FOOD NAME ('Barebells caramel cashew' from a voice note → '200 cal for
    20g protein… 1,569 on the day', never logged) must count too, not just 'I had
    X'. High-precision exclusions instead: a PLAN ('probably turkey later'), a
    LOOKUP question ('how many cal in a banana'), a bare ACK ('ok'/'nice' → a
    recap, not a report), or any reply that asked a question ('?' → legit defer)."""
    u = (user_text or "").strip()
    r = (response_text or "").strip()
    if not u or not r:
        return False
    # The reply must state a food's calories/macros — the recognized-but-unlogged tell.
    if not (_CALORIE_ESTIMATE_RE.search(r)
            or re.search(r"\d+\s*g\s+(?:protein|carbs?|fat)", r, re.I)):
        return False
    if "?" in r:
        return False                 # the model asked something → legit clarify/defer
    if _PLAN_RE.search(u):
        return False                 # a plan they haven't eaten yet
    if "?" in u or _QUESTION_RE.search(u):
        return False                 # a lookup/advice question, not a log
    if _ACK_RE.match(u):
        return False                 # bare ack → the reply is a recap, not a food report
    return True


_INVOKE_RE = re.compile(r'<invoke\s+name="([^"]+)"\s*>(.*?)</invoke>', re.S | re.I)
_PARAM_RE = re.compile(r'<parameter\s+name="([^"]+)"\s*>(.*?)</parameter>', re.S | re.I)


def has_leaked_tool_xml(text: str) -> bool:
    """True if the reply contains function-call markup the model wrote as text
    instead of executing (the Denys #7129 catastrophe)."""
    t = (text or "").lower()
    return "<invoke" in t or "<parameter" in t


def extract_leaked_tool_calls(text: str) -> list:
    """Recover real tool calls from leaked <invoke>/<parameter> markup so the
    intended log actually lands. Only fully-closed blocks are parsed (a
    truncated fragment can't be trusted). Numeric params are coerced."""
    calls = []
    for m in _INVOKE_RE.finditer(text or ""):
        name, body, inp = m.group(1), m.group(2), {}
        for pm in _PARAM_RE.finditer(body):
            v = pm.group(2).strip()
            if re.fullmatch(r"-?\d+", v):
                inp[pm.group(1)] = int(v)
            elif re.fullmatch(r"-?\d+\.\d+", v):
                inp[pm.group(1)] = float(v)
            else:
                inp[pm.group(1)] = v
        calls.append({"name": name, "input": inp})
    return calls


def looks_like_phantom_log_claim(user_text: str, response_text: str,
                                 has_tool_calls: bool) -> bool:
    """True when the user reported a loggable SET or FOOD but the model claimed it
    was recorded ("noted", "on the board", "logged") WITHOUT firing any tool — a
    confirmation with no write behind it, which silently drops the entry.

    Narrow by construction: requires a set-report OR food-report user message AND a
    recorded-claim reply AND zero tool calls. So it never fires on a normal
    clarifying question ("was that a weight PR?"), an actually-logged turn (a tool
    fired), or generic chat. Drives quality repair so the model owns the miss and
    re-logs on the retry."""
    if has_tool_calls:
        return False
    u = (user_text or "").strip()
    r = (response_text or "").strip().lower()
    if not u or not r:
        return False
    if not (_SET_REPORT_RE.search(u) or _FOOD_REPORT_RE.search(u)
            or _LOG_INTENT_RE.search(u) or _WEIGHT_REPORT_RE.search(u)):
        return False
    return any(p in r for p in _RECORDED_CLAIM)


_TOTAL_CLAIM_RE = re.compile(
    rf"(\d[\d,]{{2,5}})\s*/\s*(\d[\d,]{{2,5}})\s*{_CAL_UNIT}\b", re.IGNORECASE)


def claimed_day_total(text: str):
    """The largest 'N / M calories' running-total claim in a reply, or None.
    The medjool-dates incident (2026-07-20, ON OPUS): no claim-word, no tool —
    the reply simply STATED a recomputed total over a row never written. A
    stated total is checkable arithmetic; this extracts it for the check."""
    best = None
    for m in _TOTAL_CLAIM_RE.finditer(text or ""):
        try:
            n = int(m.group(1).replace(",", ""))
        except ValueError:
            continue
        if best is None or n > best:
            best = n
    return best


def looks_like_partial_narration(text: str, has_food_calls: bool) -> bool:
    """
    True when the first-pass text alongside log_food tool calls contains calorie
    estimates — the model described food items inline instead of tool-calling them.
    'rice ~200cal' fires; 'Nice 💪' does not.
    Only relevant when at least one log_food was already called (partial, not full stall).
    """
    if not has_food_calls or not text:
        return False
    return bool(_CALORIE_ESTIMATE_RE.search(text))


def detect_turn_flags(
    *,
    user_text: str,
    response_text: str,
    has_tool_calls: bool,
    stop_reason: str | None,
    retried: bool,
    tool_error: bool,
    source_type: str | None = None,
    tool_names: set | None = None,
    prior_assistant_text: str = "",
) -> list[str]:
    """
    Return the list of health flags for a completed turn. Empty list = clean turn.
    Order is stable so persisted strings are deterministic.

    source_type: "text" | "image" | "voice" — used for image-specific checks.
    tool_names:  set of tool names called this turn — used for cross-tool checks.
    """
    flags: list[str] = []
    tool_names = tool_names or set()
    if stop_reason == "max_tokens":
        flags.append("truncated")
    if retried:
        flags.append("retried")
    if tool_error:
        flags.append("tool_error")
    if not has_tool_calls and looks_like_stall(response_text):
        flags.append("stall_shipped")
    if detect_frustration(user_text):
        flags.append("user_frustrated")
    if detect_sarcastic_ack(user_text, prior_assistant_text):
        flags.append("user_sarcastic")
    if looks_like_mechanics(response_text):
        flags.append("mechanics_narration")
    if looks_like_empty_praise(response_text):
        flags.append("empty_praise")
    if looks_like_phantom_log_claim(user_text, response_text, has_tool_calls):
        flags.append("phantom_log_claim")
    # Image turn where log_body_weight fired without log_food — almost always a
    # nutrition-analysis false positive (macro gram numbers mistaken for body weight).
    if (source_type == "image"
            and "log_body_weight" in tool_names
            and "log_food" not in tool_names):
        flags.append("image_body_weight_misroute")
    return flags
