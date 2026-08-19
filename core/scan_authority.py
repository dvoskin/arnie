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
from typing import Optional

logger = logging.getLogger(__name__)

#: Operations that name a food on the board. Declared once, here, because a
#: second copy at a guard site is a second definition of "bound".
FOOD_OPS = frozenset({"log_food", "update_food_entry", "delete_food_entry"})

#: The clarification fields that leave QUANTITY as the only open question. An
#: ask limited to these on a single bound product is the CF9 case.
QUANTITY_FIELDS = frozenset({"quantity"})


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

#: A STATED AMOUNT is a value WITH a food unit *(finding 2)* — "2 servings",
#: "110 g", "half a bar" — never a bare number ("my glucose was 110",
#: "version 2" are not amounts) and never a bare "some"/"half".
_UNIT_WORDS = (r"(?:servings?|bars?|pieces?|g|grams?|oz|ounces?|ml|"
               r"millilit(?:er|re)s?|cups?|slices?|packs?|packets?|bottles?|"
               r"cans?|scoops?|squares?|tbsp|tsp|tablespoons?|teaspoons?)")
_NUM_WORDS = (r"(?:\d+(?:[.,]\d+)?|a|an|one|two|three|four|five|six|seven|"
              r"eight|nine|ten|half|quarter|couple(?:\s+of)?|few)")
_AMOUNT_RE = re.compile(
    rf"\b{_NUM_WORDS}\s+(?:of\s+)?(?:the\s+)?(?:[\w']+\s+)?{_UNIT_WORDS}\b"
    rf"|\b\d+(?:[.,]\d+)?\s*(?:g|grams?|oz|ml)\b"
    rf"|\bhalf\s+(?:a|an|the|of)\b", re.I)
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
    if _AMOUNT_RE.search(body):
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


#: words that are never product identity, over and above _GENERIC_WORDS —
#: used ONLY by `identity_residual` (never by the mention/alias comparison,
#: where "morning" may genuinely be a product word)
_NON_IDENTITY_EXTRA = frozenset("""
i we you he she they me us was were is are am be been being did do does done
doing not no dont didnt cant wont isnt wasnt arent im ive id
after before during while then later now today tonight yesterday tomorrow
morning afternoon evening right really very too also still already again
please thanks thank ok okay yeah yes sure cool nice great awesome alright
perfect good fine got gotcha word bet lol haha nope nah
""".split())


def identity_residual(message: str) -> set:
    """⛔ finding 3 — the message's content words that NOTHING accounts for:
    not generic, not consumption/amount vocabulary, not function words. If
    this is non-empty and no producer label verified against the message, the
    user named SOMETHING and the producer erased it — the identity-free
    amount path must NOT bind; the turn is UNDECIDABLE."""
    toks = _content(_tokens(_AMOUNT_RE.sub(" ", str(message or ""))))
    return {t for t in toks
            if t not in _NON_IDENTITY_EXTRA and _stem(t) not in _NON_IDENTITY_EXTRA}


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
    # no verifiable mention. ⛔ finding 3: if the user's words still carry
    # identity-class content NOTHING attributed (a product name every carrier
    # relabelled away), the identity-free path must not bind on a guess.
    residual = identity_residual(message)
    if residual:
        return ScanDecision(UNDECIDABLE, ev, DISP_REFUSED,
                            f"unattributed_identity_words="
                            f"{' '.join(sorted(residual))}")
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
        if r.startswith("unattributed_identity_words"):
            return "no_fresh_statement"          # same user story: name+amount
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


def quantity_only_subject(plan):
    """The single food subject whose ONLY open field is quantity, or None.
    The CF9 case: one consumed product, the amount unknown — a durable ask
    holding the snapshot, not a refusal."""
    subjects = tuple(getattr(plan, "food_subjects", None) or ())
    if len(subjects) != 1:
        return None
    sub = subjects[0]
    if not getattr(sub, "consumed", False):
        return None
    fields = tuple(getattr(sub, "open_fields", ()) or ())
    if not fields or not all(f in QUANTITY_FIELDS for f in fields):
        return None
    return sub


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
