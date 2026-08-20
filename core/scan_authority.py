"""⛔⛔ ONE SCAN AUTHORITY *(CF5c, Danny 2026-08-19; rebuilt under the P17
closure directive, Phase 1, the same evening)*.

A scan attachment is the strongest identity statement a user can make. Four
production-shaped routes were found around the guards that were supposed to
honour it, and each fix added another local guard:

    ios:D3B7757E   implicit ratio correction of a board row   (CF5b)
    mixed turn     attachment read as binding                 (CF5b review 2)
    undecidable    the decision itself failed open            (CF5b review 3)
    zero-op        early return before any decision ran       (CF5c)
    prompt line    binding decided from the ATTACHMENT, in    (9cf29b9,
                   the interpreter's prompt, before any plan   superseded)

The pattern is the finding: guards placed where the damage SURFACED, each
re-deriving "is this bound?" from whatever it had to hand. So the decision is
ONE pure classification over typed inputs, and every other guard reads it:

    UnverifiedScanAttachment  ->  VerifiedScanEvidence  ->  ScanDecision
      (ingress: an id)           (ONE repository read)     (this module)

    PRE-PLAN     NOTHING. The planner is attachment-blind: the confirm replay
                 runs, a pending prior is consulted, the interpreter is told
                 nothing about the scan. Every subject the turn names survives
                 into the typed plan.

    GATE         `decide_from_plan(plan, evidence)` — called ONCE, from the
                 validation stage, the first place the COMPLETE plan is known.
                 A REFUSED decision is raised HERE, before execution; the
                 executor never sees a refused turn.

    SETTLEMENT   `require_bound_evidence()` is the ONLY way evidence reaches
                 settlement; a discarded or refused decision keeps its
                 evidence for audit and confers no authority. `require_shape`
                 is enforcement of shape, not a second decision.

THE OUTCOMES — explicit, each with its disposition:

    BOUND                BOUND      the single subject is a statement about
                                    the scanned product
    MULTI_ITEM           DISCARDED  several subjects: the turn runs exactly as
                                    unscanned; the reply SAYS the scan was
                                    not used
    EXPLICIT_OTHER_FOOD  DISCARDED  the one statement names another food;
                                    same handling as MULTI_ITEM
    PRIOR_CONFLICT       REFUSED    the plan is an EARLIER action (a confirm
                                    replay; a plan carrying a prior's held
                                    writes and nothing fresh) — a scan-attached
                                    ambiguous answer must not execute it
    IDENTITY_CONFLICT    REFUSED    the user's literal mention names the
                                    snapshot's brand with another product
    ATTACHMENT_CONFLICT  REFUSED    two different attachments in one turn
    UNDECIDABLE          REFUSED    the decision cannot be made: no subject,
                                    no verifiable statement, unreadable
                                    evidence, a negated or questioned
                                    consumption, a producer error

"I could not tell" (UNDECIDABLE) is never "it binds nothing" (DISCARDED):
the second is a decision downstream may act on, the first refuses.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

#: Operations that name a food on the board. Declared once, here, because a
#: second copy at a guard site is a second definition of "bound".
FOOD_OPS = frozenset({"log_food", "update_food_entry", "delete_food_entry"})

#: The clarification fields that leave QUANTITY as the only open question. An
#: ask limited to these on a single bound product is the CF9 case.
QUANTITY_FIELDS = frozenset({"quantity"})

#: ⛔ CF14 — EVERY MATERIAL SETTLEMENT FIELD A BOUND ASK MAY HOLD, declared
#: once beside `QUANTITY_FIELDS` for the same reason: a second copy at a
#: guard site is a second definition of what a bound ask is allowed to ask.
#:
#: Names are the PLAN-STAGE vocabulary (`core/turns/stages/food._canon_field`
#: after `_FIELD_ALIASES`), not the field registry's — this gate reads the
#: producer's typed `ambiguities`, and the interpreter names `consumed` and
#: `serving` in its own words. Both spellings are accepted because the alias
#: table maps neither today, and a gate that silently missed the interpreter's
#: actual word would refuse the turn it exists to serve.
#:
#: ⛔ `food_identity` IS DELIBERATELY ABSENT. The snapshot answers identity;
#: an ask that offered it would let prose overwrite a scanned product's own
#: label, which is the Salty Peanut incident with a nicer interface. An
#: explicit prose/snapshot identity conflict asks or refuses through the
#: authority — it never opens a bound ask.
MATERIAL_SETTLEMENT_FIELDS = frozenset({
    "quantity",             # how much
    "consumed", "consumed_fraction",   # how much OF IT was eaten
    "serving", "serving_basis",        # what the label's numbers are per
    "preparation",          # how it was cooked
    "product_variant",      # which variant, WITHIN the scanned identity
})


class ScanAuthorityRefusal(Exception):
    """A scanned turn whose shape cannot be honoured. Raised BEFORE any write,
    any claim and any legacy route — non-mutating by construction — and
    answered in user-grade words at the entrypoint's canonical-refusal seam.
    Typed apart by `reason` so the copy can say what actually happened."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(
            f"scanned turn refused ({reason})"
            + (f": {detail}" if detail else "")
            + " — nothing written, no legacy")


# ── STATE READERS (the holder is the store; these are views) ────────────────

def _state():
    from skills.nutrition.product_acquisition import state
    return state()


def scan_attached() -> bool:
    """A barcode rode this turn. NOT a binding."""
    st = _state()
    return bool(st is not None and st.attached)


def decision():
    """The recorded ScanDecision, or None before the gate ran / no scan."""
    st = _state()
    return st.decision if st is not None else None


def evidence():
    """The VERIFIED evidence on this turn (any disposition), or None. For
    audit and logs. Settlement must use `require_bound_evidence()`."""
    st = _state()
    if st is None:
        return None
    if st.decision is not None:
        return st.decision.evidence
    return st.evidence


def snapshot_id() -> Optional[int]:
    """The snapshot this turn is ABOUT, for logs and the reply note: the
    decided evidence's id, else the attached id. NOT an authority to settle
    with — that is `require_bound_evidence()`."""
    st = _state()
    if st is None:
        return None
    if st.decision is not None and st.decision.evidence is not None:
        return int(st.decision.evidence.snapshot_id)
    return st.attached_snapshot_id


def disposition() -> Optional[str]:
    """The decided outcome, or None when no scan rode this turn.

    ⛔ An ATTACHED scan that has not been decided reads as UNDECIDABLE, not as
    "not bound": a reader that cannot distinguish "binds nothing" from "no
    decision was made" is the fail-open this module exists to delete."""
    from skills.nutrition.product_acquisition import (ATTACHMENT_CONFLICT,
                                                      CONSUMED, UNDECIDABLE)
    st = _state()
    if st is None or not st.attached:
        return None
    # an attachment conflict dominates every reader, whenever it arrived —
    # a second product attached after the decision still refuses
    if st.attachment_conflict:
        return ATTACHMENT_CONFLICT
    if st.decision is None:
        return UNDECIDABLE
    if st.consumed and st.decision.is_bound:
        return CONSUMED
    return st.decision.outcome


def is_bound() -> bool:
    """The ONE question, one answer. Never re-derived from operation shape.
    ⛔ CONSUMED AUTHORITY IS SPENT *(finding 1)*: once the binding settled or
    was handed to an ask, nothing later in the turn is bound any more."""
    st = _state()
    return bool(st is not None and not st.attachment_conflict
                and not st.consumed
                and st.decision is not None and st.decision.is_bound)


def require_bound_evidence():
    """⛔ THE ONLY DOOR TO SETTLEMENT AUTHORITY. Returns the VerifiedScanEvidence
    of a BOUND decision; raises for anything else — a discarded or refused
    decision keeps its evidence for audit and confers nothing."""
    st = _state()
    if st is not None and st.attachment_conflict:
        raise ScanAuthorityRefusal("attachment_conflict", st.attachment_conflict)
    if st is None or st.decision is None:
        raise ScanAuthorityRefusal("undecidable", "no binding decision on this turn")
    if st.consumed:
        # ⛔ finding 1: consumed authority cannot be handed out again — the
        # settlement or the durable ask already holds it
        raise ScanAuthorityRefusal(
            "consumed", "this turn's binding was already settled or handed "
            "to an ask; the evidence cannot authorise a second settlement")
    d = st.decision
    if not d.is_bound or d.evidence is None:
        raise ScanAuthorityRefusal(
            d.outcome if d.outcome else "undecidable",
            f"the scan is not bound on this turn ({d.disposition}: {d.reason})")
    return d.evidence


def consume() -> None:
    """The binding has been settled or handed to an ask that holds it."""
    try:
        from skills.nutrition.product_acquisition import consume_binding
        consume_binding()
    except Exception:                                    # noqa: BLE001
        logger.warning("scan authority: consume failed", exc_info=True)


def claim(turn_id: str) -> None:
    """`run_turn` binds the holder to its request (request scoping)."""
    from skills.nutrition.product_acquisition import claim as _claim
    _claim(turn_id)


# ── THE TYPED LITERAL READING OF THE MESSAGE ────────────────────────────────
#
# No leftover-token heuristic. Three TYPED parses of the user's literal words,
# each a stop-list or a regex the codebase already trusts:
#   · a MENTION is a producer label (any carrier of the subject) whose content
#     words the user literally wrote — verified against the message, tolerant
#     of plural/possessive; only that mention is compared with the evidence
#   · a FRESH STATEMENT signal is a stated amount, consumption language, or a
#     deictic reference ("this", "these") — the identity-free case
#   · a NEGATED or QUESTIONED consumption refuses a write outright

#: words that never identify a product: pronouns, generic packaged-food nouns,
#: measures and function words
_GENERIC_WORDS = frozenset("""
this these that those it them one ones some any another thing stuff item items
product products food foods snack snacks bar bars protein pack packs package
packet sachet piece pieces serving servings portion portions scan scanned
barcode label wrapper bottle can cans cup cups slice slices half whole small
large big mini regular size sized g gram grams oz ounce ounces ml kcal cal
calories of the a an my his her their our and or with for to at in on from
had have has ate eat eaten drank drink drinks just only about around roughly
again more less extra plain
""".split())

#: ⛔ ONE STRUCTURE, BOTH DERIVATIONS *(second-round finding 2)*. The unit
#: vocabulary used to be scraped out of the regex TEXT with
#: `re.findall(r"[a-z]+", ...)`, which shredded `millilit(?:er|re)s?` into
#: `millilit`, `er`, `re` — so the amount parser accepted "2 milliliters"
#: while the grammar called `milliliters` an unaccounted identity word and
#: refused the same message. The forms are declared ONCE, here, and every
#: consumer reads them (a parity test asserts it over every form).
_UNIT_FORMS = (
    ("serving", "servings"),
    ("bar", "bars"),
    ("piece", "pieces"),
    ("slice", "slices"),
    ("square", "squares"),
    ("scoop", "scoops"),
    ("pack", "packs"),
    ("packet", "packets"),
    ("bottle", "bottles"),
    ("can", "cans"),
    ("cup", "cups"),
    ("g", "gram", "grams"),
    ("kg", "kilogram", "kilograms"),
    ("oz", "ounce", "ounces"),
    ("lb", "pound", "pounds"),
    ("ml", "milliliter", "milliliters", "millilitre", "millilitres"),
    ("l", "liter", "liters", "litre", "litres"),
    ("tbsp", "tablespoon", "tablespoons"),
    ("tsp", "teaspoon", "teaspoons"),
)
_UNIT_TOKENS = frozenset(form for forms in _UNIT_FORMS for form in forms)


#: ⛔ ONE TYPED PARSER FOR THE QUANTITY PHRASE *(third-round blocker)*. The
#: amount signal and the identity accounting used to be two mechanisms — a
#: regex and a positional scan — over two vocabularies, so they disagreed in
#: both directions: "a couple of bars" was an amount to the regex and an
#: identity claim to the scan (a valid quantity refused), while "2 bars from
#: ONE" was neither, because a global quantifier list accounted for `one`
#: wherever it appeared (a wrong bind). Now ONE grammar produces typed spans
#: and BOTH readers consume it.
#:
#:     PHRASE   := QUANTIFIER MODIFIER* HEAD
#:     QUANTIFIER := [det] CORE [of] [det]
#:     CORE     := digits | number word | quantity noun
#:     HEAD     := UNIT | DEICTIC        (a partitive may head on a deictic:
#:                                        "some of this" is a quantity phrase)
#:     MODIFIER := anything else — it modifies the head, so it NAMES something
#:
#: Only a quantifier INSIDE a parsed quantifier span is accounted as a
#: quantifier. The same word outside one ("…bars from ONE") is an ordinary
#: token and must match the verified evidence like any other identity word.
_QUANT_CORE_WORDS = (
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "eleven", "twelve", "dozen",
    "half", "quarter", "third",
    "couple", "few", "several", "some", "many", "handful", "bit", "lot",
    "lots", "plenty", "double", "triple",
)
_QUANT_DETERMINERS = frozenset("a an the this that these those my our your "
                               "his her their its".split())
#: the determiners that are ALSO a quantity of one — "a bar" is an amount,
#: "the bar" is not
_ARTICLE_CORES = frozenset({"a", "an"})
_QUANT_CORE = frozenset(_QUANT_CORE_WORDS)

#: how far past the quantifier the head may sit before the phrase is abandoned
_PHRASE_WINDOW = 5


@dataclass(frozen=True)
class AmountPhrase:
    """One parsed quantity phrase, as TOKEN INDEX SPANS — the typed result
    both the amount signal and the identity accounting read."""
    quantifier: tuple          # indices forming the quantifier span
    fillers: tuple             # determiners / "of" between quantifier and head
    modifiers: tuple           # indices that MODIFY the head: identity-bearing
    head: int                  # index of the unit or deictic head
    head_is_unit: bool

    @property
    def accounted(self) -> frozenset:
        """Indices this phrase accounts for — everything but its modifiers."""
        return frozenset(self.quantifier) | frozenset(self.fillers) | {self.head}


def _is_number(tok: str) -> bool:
    return tok.replace(",", "").replace(".", "").isdigit()


def parse_amount_phrases(message: str) -> list:
    """Every quantity phrase in the message, as typed spans. Left to right,
    non-overlapping; a quantifier with no head within the window yields no
    phrase at all (so a bare number states no amount)."""
    toks = _positional_tokens(message)
    units = _unit_vocabulary()
    phrases: list = []
    i, n = 0, len(toks)
    while i < n:
        start = i
        quant: list = []
        j = i
        if toks[j] in _QUANT_DETERMINERS and j + 1 < n and (
                _is_number(toks[j + 1]) or toks[j + 1] in _QUANT_CORE):
            quant.append(j)                                  # leading "a"/"the"
            j += 1
        if j < n and (_is_number(toks[j]) or toks[j] in _QUANT_CORE):
            quant.append(j)
            j += 1
        elif j < n and toks[j] in _ARTICLE_CORES:
            # ⛔ THE ARTICLE IS ITSELF A QUANTITY *(fourth-round regression)*.
            # The retired regex listed `a|an` among the number words, so "a
            # bar" / "an ounce" stated an amount. In the parser they were only
            # LEADING determiners before another core, so those phrases
            # vanished and — without consumption language, or when the label
            # omits the unit word — the turn refused instead of binding. `a`
            # and `an` may head the quantifier when they are not introducing
            # another core; `the` may not ("the bar" quantifies nothing).
            quant.append(j)
            j += 1
        else:
            i = start + 1
            continue
        fillers: list = []
        if j < n and toks[j] == "of":                        # partitive
            fillers.append(j)
            j += 1
        if j < n and toks[j] in _QUANT_DETERMINERS:
            # ⛔ A DEICTIC AFTER THE PARTITIVE IS THE HEAD, NOT A FILLER:
            # "some of this" is a complete quantity phrase whose head is the
            # pronoun. It is only a filler when a real head follows it
            # ("2 of these bars").
            if (toks[j] in _DEICTIC_WORDS
                    and not any(toks[k] in units
                                for k in range(j + 1, min(j + 1 + _PHRASE_WINDOW, n)))):
                phrases.append(AmountPhrase(tuple(quant), tuple(fillers), (),
                                            j, False))
                i = j + 1
                continue
            fillers.append(j)
            j += 1
        # the head, within a short window; everything before it modifies it
        modifiers: list = []
        head, head_is_unit = None, False
        limit = min(j + _PHRASE_WINDOW, n)
        while j < limit:
            tok = toks[j]
            if tok in units:
                head, head_is_unit = j, True
                break
            if tok in _DEICTIC_WORDS:
                head, head_is_unit = j, False
                break
            if _is_number(tok) or tok in _CONSUMPTION_WORDS:
                break                        # a new clause: this phrase has no head
            modifiers.append(j)
            j += 1
        if head is None:
            i = start + 1
            continue
        phrases.append(AmountPhrase(tuple(quant), tuple(fillers),
                                    tuple(modifiers), head, head_is_unit))
        i = head + 1
    return phrases


_NEGATION_RE = re.compile(
    r"\b(didn'?t|did not|haven'?t|have not|hadn'?t|had not|never|not)\s+"
    r"(?:\w+\s+){0,2}(?:had|eat|ate|eaten|have|drink|drank|finish|finished|touch)\b"
    r"|\bskipped\b|\bno\s+(?:more|bars?|food)\b", re.I)
_QUESTION_RE = re.compile(r"\?\s*$|^\s*(should|can|could|may|is|are|do|does|would|"
                          r"how|what|which|why|when)\b", re.I)
_CORRECTION_RE = re.compile(
    r"\b(actually|instead|make (?:it|that|the|this|those|them)|change|correct|"
    r"fix|edit|update|should (?:be|have been)|it was|that was|was actually|"
    r"not \d|wrong|rather than|move|undo|remove|delete)\b", re.I)


def _tokens(text) -> list:
    r"""Unicode-aware word tokens *(finding 4)* — `\w` is Unicode in Python 3,
    so non-Latin identity words survive (the food-memory `normalize_name`
    lesson: an ASCII class silently EMPTIES Cyrillic identity). Pure digits
    are dropped; underscores are not words."""
    return [t for t in re.findall(r"[\w']+", str(text or "").lower())
            if t and t != "_" and not t.replace("_", "").isdigit()
            and not t.startswith("_")]


def _stem(t: str) -> str:
    t = t.rstrip("'").replace("'s", "")
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("es") and t[-3] in "sxz":
        return t[:-2]
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def _tok_match(a: str, b: str) -> bool:
    """Exact, or exact after plural/possessive normalisation — NOTHING
    fuzzier *(finding 4)*: prefix identity equated kind/kindly and
    quest/question, which is not identity."""
    return a == b or _stem(a) == _stem(b)


def _content(words) -> set:
    return {w for w in words if w not in _GENERIC_WORDS
            and _stem(w) not in _GENERIC_WORDS}


def fresh_statement_signal(message: str) -> str:
    """'' when the words carry no fresh product statement; else which typed
    signal they carry: 'consumption' | 'amount'. Bare "yes", "thanks", an
    emoji or empty text carry none — and *(finding 2)* neither does a bare
    DEICTIC: "this" alone cannot authorise a producer-generated write; it
    needs consumption language or a real amount beside it ("I had this",
    "2 servings of this")."""
    body = str(message or "").strip()
    if not body:
        return ""
    try:
        from core.food_turn import STATE_CONSUMED, consumption_state
        if consumption_state(body) == STATE_CONSUMED:
            return "consumption"
    except Exception:                                    # noqa: BLE001
        pass
    if any(p.head_is_unit for p in parse_amount_phrases(body)):
        return "amount"
    return ""


def consumption_denied(message: str) -> str:
    """'negated' / 'question' when the words deny or ask about eating —
    "I didn't eat this", "should I eat this?" — else ''. A write under either
    is refused whatever the producer emitted."""
    body = str(message or "").strip()
    if not body:
        return ""
    if _NEGATION_RE.search(body):
        return "negated"
    if _QUESTION_RE.search(body):
        return "question"
    return ""


def verified_mention(labels, message: str) -> set:
    """The literal MENTION: of every producer label for this subject, the
    content words the user ACTUALLY WROTE — verified one by one against the
    message. A label's words the user did not write are the producer's own
    additions (a board row's full name, a canonical name) and contribute
    nothing; a label NONE of whose words the user wrote contributes nothing at
    all. Empty set = no verifiable mention. Only this set is ever compared
    with the evidence — never the rest of the message."""
    msg = _tokens(message)
    out: set = set()
    for label in labels or ():
        words = _content(_tokens(label))
        wrote = {w for w in words if any(_tok_match(w, m) for m in msg)}
        out |= wrote
    return out


def evidence_aliases(ev) -> tuple:
    """(brand words, product words) of the verified evidence, content only."""
    if ev is None:
        return set(), set()
    brand = _content(_tokens(str(ev.brand or "").replace(",", " ")))
    product = _content(_tokens(ev.product_name)) - brand
    return brand, product


# ── THE POSITIVE UTTERANCE GRAMMAR *(finding 3, second round)* ─────────────
#
# ⛔ NOT A STOP LIST. The previous cut (`identity_residual`) subtracted a
# growing list of "words that are not identity" and asked whether anything
# remained — a leftover-token heuristic under a new name, and it let a
# producer that relabelled EVERY carrier bind anyway: "I had 2 plain bars"
# and "I had 2 Perfect Bars" both subtract to nothing when the stop list
# happens to contain the identifying word.
#
# The rule is inverted. Every token of the user's message must be POSITIVELY
# ACCOUNTED FOR by one of a small number of CLOSED roles:
#
#     FUNCTION    pronouns, determiners, prepositions, conjunctions,
#                 auxiliaries — a closed word class, finite by definition
#     QUANTIFIER  numbers and number words
#     UNIT        the measure vocabulary the amount parser already owns
#     CONSUMPTION the eating/drinking verbs
#     DEICTIC     this / these / that one / those
#     EVIDENCE    a word of the scanned product's own brand or product name
#     MENTION     a word of a producer label the user literally wrote
#
# A token matching NO role is an identity claim nothing accounts for, and the
# identity-free path refuses (`unaccounted_identity`). "plain" and "Perfect"
# are unaccounted, so both refuse; "I had 2 bars" is fully accounted and
# binds; a product word the LABEL carries ("protein", when the scanned
# product is a protein bar) is accounted by the EVIDENCE role rather than by
# a list of exceptions.

#: ⛔ GENUINELY CLOSED CLASS ONLY *(finding 1 of the third round)*. The
#: previous list carried evaluative and contrastive ADJECTIVES — good, nice,
#: great, same, different, other, previous — and pronoun "one". Those are not
#: function words, they are product-name material: "I had 2 Good Bars",
#: "I had 2 ONE bars", "I had 2 other bars" were all fully "accounted" and
#: could bind the wrong scan, and `other`/`different` explicitly CONTRADICT
#: the scanned identity. Pronouns, determiners, prepositions, conjunctions,
#: auxiliaries and negation are closed classes; adjectives are not.
_FUNCTION_WORDS = frozenset("""
i me my mine we us our ours you your yours he him his she her hers it its
they them their theirs this that these those there here who whom whose which
what a an the and or but nor so if because while when whenever
of in on at to from for with without into onto off out up down over under
about around by via per each every both all any none
too very really quite rather more less most least
is are was were be been being am do does did doing done have has had having
will would shall should can could may might must
not no never dont didnt cant wont isnt wasnt arent im ive id
please thanks thank ok okay yes yeah yep sure nope nah sorry hey hi hello
today tonight yesterday tomorrow now later earlier morning afternoon evening
night before after during ago just then also again
""".split())

_CONSUMPTION_WORDS = frozenset("""
had have has ate eat eaten eating drank drink drinking drunk finished finish
snacked downed consumed devoured munched grabbed got bought ordered
""".split())

#: ⛔ "one"/"ones" are NOT deictics here: ONE is a bar brand, and "2 ONE bars"
#: must not read as a quantity word in a modifier slot.
_DEICTIC_WORDS = frozenset("this these that those it them".split())

def _unit_vocabulary() -> frozenset:
    """The measure words the amount parser owns — the SAME structure the
    regex is built from, never a re-parse of the regex text."""
    return _UNIT_TOKENS


def _positional_tokens(text) -> list:
    """Word tokens INCLUDING numbers, in order — the phrase parser needs the
    quantity itself as a position, which `_tokens` deliberately drops."""
    return [t for t in re.findall(r"[\w']+", str(text or "").lower())
            if t and not t.startswith("_")]


def unaccounted_identity(message: str, ev, mention: set) -> set:
    """⛔ THE ONE ACCOUNTING. Tokens of the user's message that nothing
    accounts for — an identity claim the producer's labels never verified.
    Non-empty means the identity-free path must NOT bind.

    Roles come from the PARSE, not from global membership:

      · inside a parsed quantifier span, or its fillers, or the head — the
        phrase accounts for it
      · a MODIFIER of a head names something: identity, unless the scanned
        label or a verified mention says that word
      · everywhere else, a token is accounted only as a function word, a
        consumption verb, a deictic, a bare number, or a word of the label /
        of a verified mention

    A quantifier word OUTSIDE a quantifier span gets no quantifier role, so
    "2 bars from ONE" is an identity claim about ONE, while "a couple of
    bars" and "a few bars" are quantities the parser itself recognises."""
    toks = _positional_tokens(message)
    phrases = parse_amount_phrases(message)
    accounted_idx: set = set()
    modifier_idx: set = set()
    for phrase in phrases:
        accounted_idx |= set(phrase.accounted)
        modifier_idx |= set(phrase.modifiers)
    # the label's own words, raw: "does the scanned label contain this word"
    # is a fact, so a generic word the label genuinely carries is accounted
    # by the label and never by an exception list
    aliases = set(_tokens(str(getattr(ev, "brand", "") or "").replace(",", " ")))
    aliases |= set(_tokens(getattr(ev, "product_name", "") or ""))

    def _evidence_says(tok: str) -> bool:
        return (any(_tok_match(tok, a) for a in aliases)
                or any(_tok_match(tok, m) for m in (mention or ())))

    out: set = set()
    for idx, tok in enumerate(toks):
        if _evidence_says(tok):
            continue
        if idx in modifier_idx:
            out.add(tok)                      # modifies a head: it names one
            continue
        if idx in accounted_idx or _is_number(tok):
            continue
        stem = _stem(tok)
        if (tok in _FUNCTION_WORDS or stem in _FUNCTION_WORDS
                or tok in _CONSUMPTION_WORDS or stem in _CONSUMPTION_WORDS
                or tok in _DEICTIC_WORDS or stem in _DEICTIC_WORDS):
            continue
        out.add(tok)
    return out


SAME, OTHER, CONFLICT = "same", "other", "conflict"


def compare_mention(mention: set, ev) -> str:
    """The verified mention against the evidence's aliases — and ONLY the
    mention, never the rest of the message. SAME: every mention word is a
    brand or product word; OTHER: no word overlaps; CONFLICT: the brand (or a
    product word) overlaps and other mention words do not — "Barebells Salty
    Peanut" against a Caramel Cashew label."""
    brand, product = evidence_aliases(ev)
    aliases = brand | product
    matched = {w for w in mention if any(_tok_match(w, a) for a in aliases)}
    if not matched:
        return OTHER
    if len(matched) == len(mention):
        return SAME
    return CONFLICT


# ── THE DECISION ────────────────────────────────────────────────────────────

def foods_in_plan(plan) -> int:
    """How many foods this turn is ABOUT — read off the TYPED subjects only.
    A plan without the attribute counts as UNKNOWN — refused, not guessed."""
    subjects = getattr(plan, "food_subjects", None)
    if subjects is None:
        raise ValueError("plan carries no food_subjects — the producer-to-plan "
                         "contract was not honoured")
    return len(tuple(subjects))


def _labels_of(plan, subject) -> list:
    """Every producer label for this subject across the carriers (the write's
    food_name/food_hint, the raw interpretation row, the question label) —
    the subject's own `labels` when the normaliser recorded them, else its
    name."""
    labels = list(getattr(subject, "labels", ()) or ())
    if not labels:
        labels = [getattr(subject, "name", "")]
    return [str(x) for x in labels if x]


def _prior_held_ops(plan) -> int:
    """Ops the interpreter joined from a pending prior's stash — causal
    provenance that the plan executes an EARLIER action."""
    n = 0
    for op in getattr(plan, "operations", ()) or ():
        inp = (op or {}).get("input") if isinstance(op, dict) else None
        if isinstance(inp, dict) and inp.get("_prior_held"):
            n += 1
    return n


def decide_from_plan(plan, ev=None):
    """THE decision. Called once, from the validation stage, with the COMPLETE
    plan and the VERIFIED evidence (None when no scan rode the turn, or when
    the attachment could not be verified). Records and returns the
    ScanDecision; returns None when no scan is attached at all.

        no evidence (attachment conflict / unverifiable) -> REFUSED
        replay / deterministic origin                    -> PRIOR_CONFLICT
        only prior-held writes, nothing fresh            -> PRIOR_CONFLICT
        no subjects                                      -> UNDECIDABLE
        two or more fresh subjects                       -> MULTI_ITEM
        one fresh subject:
            consumption negated / questioned             -> UNDECIDABLE
            a verified mention:  SAME / OTHER / CONFLICT -> BOUND /
                                   EXPLICIT_OTHER_FOOD / IDENTITY_CONFLICT
            no verifiable mention:
                a fresh-statement signal (amount,
                consumption, deictic)                    -> BOUND
                none (bare "yes", "thanks", emoji, "")   -> UNDECIDABLE

    Fails closed: any failure to decide on a SCANNED turn records UNDECIDABLE
    rather than leaving the turn undecided."""
    from skills.nutrition.product_acquisition import (ATTACHMENT_CONFLICT,
                                                      BOUND, DISP_BOUND,
                                                      DISP_DISCARDED,
                                                      DISP_REFUSED,
                                                      EXPLICIT_OTHER_FOOD,
                                                      IDENTITY_CONFLICT,
                                                      MULTI_ITEM,
                                                      PRIOR_CONFLICT,
                                                      UNDECIDABLE,
                                                      ScanDecision, decide)
    st = _state()
    if st is None or not st.attached:
        return None
    if st.attachment_conflict is not None:
        return decide(ScanDecision(ATTACHMENT_CONFLICT, None, DISP_REFUSED,
                                   st.attachment_conflict))
    if ev is None:
        ev = st.evidence
    if ev is None:
        why = st.verification_failure or "unverified"
        return decide(ScanDecision(UNDECIDABLE, None, DISP_REFUSED,
                                   f"identity_unknown:{why}"))
    try:
        count = foods_in_plan(plan)
        subjects = tuple(getattr(plan, "food_subjects", ()) or ())
        origin = str(getattr(plan, "origin", "") or "")
        src = getattr(plan, "source", None)
        message = (src.get("_message") if isinstance(src, dict) else "") or ""
        held = _prior_held_ops(plan)
        fresh_ops = [op for op in (getattr(plan, "operations", ()) or ())
                     if isinstance(op, dict)
                     and not ((op.get("input") or {}).get("_prior_held"))]
        if origin and origin != "interpreter":
            out = ScanDecision(PRIOR_CONFLICT, ev, DISP_REFUSED, f"origin={origin}")
        elif held and not fresh_ops and count <= held:
            out = ScanDecision(PRIOR_CONFLICT, ev, DISP_REFUSED,
                               f"prior_held={held} fresh=0")
        elif count == 0:
            out = ScanDecision(UNDECIDABLE, ev, DISP_REFUSED, "no_food")
        else:
            fresh_subjects = [s for s in subjects
                              if not str(getattr(s, "key", "")).startswith("prior:")]
            if len(fresh_subjects) >= 2:
                out = ScanDecision(MULTI_ITEM, ev, DISP_DISCARDED,
                                   f"multi={len(fresh_subjects)}")
            else:
                sub = fresh_subjects[0] if fresh_subjects else subjects[0]
                out = _decide_single(sub, plan, message, ev)
    except Exception:                                    # noqa: BLE001
        logger.warning("scan authority: the plan could not be classified",
                       exc_info=True)
        out = ScanDecision(UNDECIDABLE, ev, DISP_REFUSED, "error")
    decide(out)
    logger.info("event=scan_authority_decided outcome=%s disposition=%s "
                "snapshot=%s reason=%s", out.outcome, out.disposition,
                out.snapshot_id, out.reason)
    return out


def _decide_single(sub, plan, message: str, ev):
    from skills.nutrition.product_acquisition import (BOUND, DISP_BOUND,
                                                      DISP_DISCARDED,
                                                      DISP_REFUSED,
                                                      EXPLICIT_OTHER_FOOD,
                                                      IDENTITY_CONFLICT,
                                                      UNDECIDABLE,
                                                      ScanDecision)
    denied = consumption_denied(message)
    if denied:
        return ScanDecision(UNDECIDABLE, ev, DISP_REFUSED, f"consumption_{denied}")
    key = str(getattr(sub, "key", "") or "")
    if key.startswith("entry:") and _CORRECTION_RE.search(message or ""):
        # the user addressed an EXISTING entry with correction language: a
        # correction of another statement, not a report of the scanned product
        return ScanDecision(EXPLICIT_OTHER_FOOD, ev, DISP_DISCARDED,
                            "explicit_correction")
    mention = verified_mention(_labels_of(plan, sub), message)
    if mention:
        cls = compare_mention(mention, ev)
        if cls == SAME:
            return ScanDecision(BOUND, ev, DISP_BOUND, "mention_same")
        if cls == CONFLICT:
            return ScanDecision(IDENTITY_CONFLICT, ev, DISP_REFUSED,
                                f"mention={' '.join(sorted(mention))}")
        return ScanDecision(EXPLICIT_OTHER_FOOD, ev, DISP_DISCARDED,
                            f"mention={' '.join(sorted(mention))}")
    # no verifiable mention. ⛔ finding 3: every token of the message must be
    # positively accounted for by a closed role or by the evidence itself.
    # A token nothing accounts for is an identity claim the producer erased
    # (it relabelled every carrier) — the identity-free path must not bind.
    unaccounted = unaccounted_identity(message, ev, mention)
    if unaccounted:
        return ScanDecision(UNDECIDABLE, ev, DISP_REFUSED,
                            f"unaccounted_identity={' '.join(sorted(unaccounted))}")
    # identity-free: the words must carry a fresh product statement
    signal = fresh_statement_signal(message)
    if signal:
        return ScanDecision(BOUND, ev, DISP_BOUND, f"fresh_{signal}")
    return ScanDecision(UNDECIDABLE, ev, DISP_REFUSED, "no_fresh_statement")


# ── GATE + ENFORCEMENT ──────────────────────────────────────────────────────

def raise_if_refused() -> None:
    """⛔ THE GATE. Called by the validation stage right after the decision:
    a REFUSED disposition is raised HERE, before any execution stage runs, so
    the refusal is the dominance gate's — never an executor backstop."""
    from skills.nutrition.product_acquisition import DISP_REFUSED
    d = decision()
    if d is None or d.disposition != DISP_REFUSED:
        return
    raise ScanAuthorityRefusal(_refusal_reason(d), d.reason)


def _refusal_reason(d) -> str:
    from skills.nutrition.product_acquisition import UNDECIDABLE
    if d.outcome == UNDECIDABLE:
        r = str(d.reason or "")
        if r.startswith("identity_unknown"):
            return "identity_unknown"
        if r.startswith("consumption_"):
            return r
        if r == "no_fresh_statement":
            return "no_fresh_statement"
        if r.startswith("unaccounted_identity"):
            return "unaccounted_identity"
        return "undecidable"
    return d.outcome


def require_shape(ops) -> None:
    """⛔ ENFORCEMENT, NOT DECISION — consumed before every early return,
    correction route and legacy route. Reads the decision and checks the
    shape against it; never counts its way to a different answer.

      no scan                       -> proceed
      decided REFUSED               -> raise (the gate should already have)
      undecided attached scan       -> raise (an unknown about authority)
      BOUND + exactly one log_food  -> proceed
      BOUND + anything else         -> raise impossible_shape
      BOUND + no ops                -> the caller owns this branch (CF9 ask)
      DISCARDED (multi/other food)  -> proceed unchanged (the reply notes it)
    """
    from skills.nutrition.product_acquisition import (BOUND, DISP_REFUSED,
                                                      UNDECIDABLE)
    st = _state()
    if st is None or not st.attached:
        return
    if st.attachment_conflict:
        raise ScanAuthorityRefusal("attachment_conflict", st.attachment_conflict)
    d = st.decision
    if d is None:
        raise ScanAuthorityRefusal(
            "undecidable",
            "a barcode rode this turn and whether it binds was never decided")
    if d.disposition == DISP_REFUSED:
        raise ScanAuthorityRefusal(_refusal_reason(d), d.reason)
    if d.outcome != BOUND:
        return
    ops = list(ops or ())
    if not ops:
        return                                   # the caller owns this branch
    logs = [op for op in ops if isinstance(op, dict) and op.get("name") == "log_food"]
    if len(ops) != 1 or len(logs) != 1:
        raise ScanAuthorityRefusal(
            "impossible_shape",
            f"BOUND requires exactly one log_food; this turn holds "
            f"{[op.get('name') for op in ops]}")


def bound_ask_subject(plan, *, fields=MATERIAL_SETTLEMENT_FIELDS):
    """The single consumed food subject whose open fields are all material
    settlement fields, or None.

    ⛔ CF14 GENERALISES CF9 *(Phase 3)*. This began as
    `quantity_only_subject`: one consumed product with the amount unknown.
    The holder was always general — it holds a snapshot against an operation
    — and only this gate was quantity-shaped, so a bound scan whose open
    question was PREPARATION refused instead of asking, and the user lost the
    exact label they had just scanned.

    `fields` is a parameter so the CF9 case remains expressible (pass
    `QUANTITY_FIELDS`) without a second copy of the subject-shape rules."""
    subjects = tuple(getattr(plan, "food_subjects", None) or ())
    if len(subjects) != 1:
        return None
    sub = subjects[0]
    if not getattr(sub, "consumed", False):
        return None
    open_now = tuple(getattr(sub, "open_fields", ()) or ())
    # an INFERRED field is spelled "quantity?" by the producer and is not
    # accepted here — an un-typed question refuses rather than asks
    if not open_now or not all(f in fields for f in open_now):
        return None
    return sub


def quantity_only_subject(plan):
    """The CF9 case, unchanged: quantity is the only open question."""
    return bound_ask_subject(plan, fields=QUANTITY_FIELDS)


def scan_unused_note() -> Optional[str]:
    """⛔ A SCAN THAT BOUND NOTHING IS SAID SO, NEVER DROPPED SILENTLY. When
    the decision was DISCARDED (multi-item, another food) the turn ran as
    unscanned — the reply must tell the user the scanned product was not
    used, or the silent loss of an exact snapshot reads as a log."""
    from skills.nutrition.product_acquisition import DISP_DISCARDED
    d = decision()
    if d is None or d.disposition != DISP_DISCARDED:
        return None
    return ("The scanned product wasn't logged with that — send it on its "
            "own with how much you had and I'll log it from the label.")
