"""Multi-turn food transcripts (PR #28).

The gold set in nutrition_cases.py pins ONE resolution: given these candidates,
what number comes out. That is half the system. The other half is what happens
across turns — whether we ask, what we ask, whether the answer binds to the
right row, what commits and what waits, and whether the second turn remembers
the first.

A transcript is a conversation with fixed interpreter output and fixed
expectations at every step. Nothing here calls a model or a database: what is
under test is the clarification lifecycle, not whether the interpreter parsed
the sentence.

Each turn is one of:

    log(...)      the user says what they ate; the interpreter's output is
                  stated verbatim, and the pipeline decides
    reply(...)    the user answers the outstanding question; the narrow parser
                  reads it and the answer is applied to the staged row
    learn(...)    a past confirmation becomes a stored preference, so the next
                  log can be resolved from it

and each carries `expect`, which is the assertion. The vocabulary is small on
purpose — a transcript that needs a new expectation key usually wants a new
production contract, not a new test flag.

Adding a transcript is how a clarification bug stays fixed.
"""

# ── turn constructors ─────────────────────────────────────────────────────────
def log(message, items=(), ambiguities=(), calls=None, expect=None):
    """The user logs food. `items` and `ambiguities` are the interpreter's
    output, stated rather than derived."""
    return {"kind": "log", "message": message,
            "data": {"items": list(items),
                     "ambiguities": list(ambiguities),
                     "_calls": list(calls if calls is not None else
                                    [{"input": {"food_name": i["food"]}}
                                     for i in items])},
            "expect": dict(expect or {})}


def reply(message, expect=None):
    """The user answers the question the previous turn asked."""
    return {"kind": "reply", "message": message, "expect": dict(expect or {})}


def learn(term, field, value, confirmations=1, expect=None):
    """A confirmed identity becomes a preference the next log can use."""
    return {"kind": "learn", "term": term, "field": field, "value": value,
            "confirmations": confirmations, "expect": dict(expect or {})}


def transcript(tid, category, turns, mode="moderate", expect=None):
    return {"id": tid, "category": category, "mode": mode,
            "turns": list(turns), "expect": dict(expect or {})}


def item(food, amount=None, unit=None, brand=None, basis=None,
         is_packaged=False, calories=None):
    """`calories` is the interpreter's own per-item estimate.

    It is not decoration. The materiality policy's fraction rule reads it — a
    190-calorie span is 95% of a protein bar and a fifth of a platter, and
    without the item's size the scorer sees only the flat threshold. Production
    interpreter output always carries it; these fixtures did not, which made
    them quietly untestable against the proportional half of the policy.
    """
    out = {"food": food, "is_packaged": is_packaged}
    if calories is not None:
        out["calories"] = calories
    if amount is not None:
        out["amount"] = amount
    if unit is not None:
        out["unit"] = unit
    if brand is not None:
        out["brand"] = brand
    if basis is not None:
        out["basis"] = basis
    return out


def amb(food, field, options=(), impact_cal=0.0, impact_protein=0.0):
    return {"item": food, "field": field, "options": list(options),
            "impact_cal": impact_cal, "impact_protein": impact_protein}


# ══ clarification lifecycle ══════════════════════════════════════════════════
# The question is asked, the answer is parsed by the schema we asked for, the
# answer lands on the row it was about, and the item commits. Every step here
# has failed in production at least once.
CLARIFICATION = [
    transcript("fairlife-line-then-commit", "clarification", [
        log("had a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite",
                              "Nutrition Plan"], impact_cal=190,
                             impact_protein=16)],
            expect={"asks": True, "fields": ["product_line"],
                    "committed": 0, "held": 1}),
        reply("the elite one",
              expect={"values": {"product_line": "Core Power Elite"},
                      "asks_after": False, "committed_after": 1}),
    ]),

    transcript("portion-question-then-commit", "clarification", [
        log("ate some rice",
            items=[item("white rice", calories=205)],
            ambiguities=[amb("white rice", "portion", ["1 cup", "2 cups"],
                             impact_cal=205)],
            expect={"asks": True, "fields": ["estimated_mass_g"],
                    "committed": 0}),
        reply("about a cup",
              expect={"resolves": True, "asks_after": False,
                      "committed_after": 1}),
    ]),

    transcript("a-skip-command-is-not-an-answer", "clarification", [
        log("a fairlife and a banana",
            items=[item("fairlife", brand="Fairlife", calories=170),
                   item("banana", amount=1, unit="piece", basis="stated")],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 1, "held": 1}),
        reply("skip it",
              expect={"command": "skip_item", "asks_after": False}),
    ]),

    transcript("estimate-command-ends-the-question", "clarification", [
        log("some chips",
            items=[item("tortilla chips")],
            ambiguities=[amb("tortilla chips", "portion",
                             ["28g", "100g"], impact_cal=360)],
            expect={"asks": True}),
        reply("just estimate it",
              expect={"command": "estimate", "asks_after": False}),
    ]),

    transcript("cancel-drops-the-whole-meal", "clarification", [
        log("a fairlife and a bagel",
            items=[item("fairlife", brand="Fairlife", calories=170),
                   item("bagel")],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("cancel the meal", expect={"command": "cancel_meal"}),
    ]),

    transcript("an-unparseable-answer-does-not-guess", "clarification", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("it was in the blue fridge at my mum's",
              expect={"unparsed": True, "values": {}}),
    ]),

    transcript("the-answer-binds-to-the-item-it-was-about", "clarification", [
        log("a fairlife and a chobani",
            items=[item("fairlife", brand="Fairlife", calories=170),
                   item("chobani", brand="Chobani", calories=140)],
            ambiguities=[
                amb("fairlife", "brand", ["Core Power", "Core Power Elite"],
                    impact_cal=190, impact_protein=16),
                amb("chobani", "variant", ["Zero Sugar", "Complete"],
                    impact_cal=60, impact_protein=8)],
            expect={"asks": True, "questions": 2, "committed": 0, "held": 2}),
        reply("elite",
              expect={"values": {"product_line": "Core Power Elite"},
                      "bound_to": "fairlife", "committed_after": 1,
                      "asks_after": True}),
    ]),

    transcript("a-clear-item-commits-while-its-neighbour-waits",
               "clarification", [
        log("two eggs and a fairlife",
            items=[item("egg", amount=2, unit="piece", basis="stated"),
                   item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 1, "held": 1,
                    "policy": "partial_commit"}),
    ]),

    transcript("strict-holds-the-clear-item-too", "clarification", [
        log("two eggs and a fairlife",
            items=[item("egg", amount=2, unit="piece", basis="stated"),
                   item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 0, "held": 2,
                    "policy": "atomic_hold"}),
    ], mode="strict"),

    transcript("quick-commits-a-clear-leader-with-an-assumption",
               "clarification", [
        # One option is not a choice — it is an estimate we made. Quick commits
        # it and says so. (Two interpreter options arrive with equal
        # confidence, which quick correctly treats as a coin toss; that is the
        # transcript below, not this one.)
        log("some rice",
            items=[item("white rice", calories=205)],
            ambiguities=[amb("white rice", "portion", ["about a cup"],
                             impact_cal=205)],
            expect={"asks": False, "committed": 1, "assumptions_min": 1,
                    "policy": "commit_with_assumptions"}),
    ], mode="quick"),

    transcript("rounds-run-out-and-the-questions-stop", "clarification", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("hmm", expect={"unparsed": True}),
        reply("not sure", expect={"command": "estimate"}),
    ]),

    transcript("two-questions-is-the-ceiling", "clarification", [
        log("a fairlife, a chobani, a quest bar and a kind bar",
            items=[item("fairlife", brand="Fairlife", calories=170),
                   item("chobani", brand="Chobani", calories=140),
                   item("quest bar", brand="Quest", calories=190),
                   item("kind bar", brand="KIND", calories=200)],
            ambiguities=[
                amb("fairlife", "brand", ["Core Power", "Elite"],
                    impact_cal=190, impact_protein=16),
                amb("chobani", "variant", ["Zero Sugar", "Complete"],
                    impact_cal=60, impact_protein=8),
                amb("quest bar", "variant", ["Bar", "Chips"],
                    impact_cal=100, impact_protein=3),
                amb("kind bar", "variant", ["Dark Chocolate", "Peanut"],
                    impact_cal=30, impact_protein=2)],
            expect={"asks": True, "questions": 2, "held_min": 3}),
    ]),

    transcript("the-highest-value-question-is-asked-first", "clarification", [
        log("a kind bar and a fairlife",
            items=[item("kind bar", brand="KIND", calories=200),
                   item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[
                amb("kind bar", "variant", ["Dark Chocolate", "Peanut"],
                    impact_cal=30, impact_protein=2),
                amb("fairlife", "brand", ["Core Power", "Elite"],
                    impact_cal=190, impact_protein=16)],
            expect={"asks": True, "first_question_about": "fairlife"}),
    ]),

    transcript("a-tiny-doubt-never-becomes-a-question", "clarification", [
        log("a kind bar",
            items=[item("kind bar", brand="KIND", amount=1, unit="bar",
                        basis="stated", calories=200)],
            ambiguities=[amb("kind bar", "variant",
                             ["Dark Chocolate", "Almond"], impact_cal=12,
                             impact_protein=1)],
            expect={"asks": False, "committed": 1}),
    ]),

    transcript("no-ambiguity-means-no-turn-spent", "clarification", [
        log("200g chicken breast and 150g rice",
            items=[item("chicken breast", amount=200, unit="g",
                        basis="stated"),
                   item("white rice", amount=150, unit="g", basis="stated", calories=205)],
            expect={"asks": False, "committed": 2, "held": 0}),
    ]),

    transcript("a-question-about-an-item-we-dropped-is-not-asked",
               "clarification", [
        log("a bagel",
            items=[item("bagel", amount=1, unit="piece", basis="stated")],
            ambiguities=[amb("something else entirely", "brand",
                             ["A", "B"], impact_cal=400)],
            expect={"asks": False, "committed": 1}),
    ]),

    transcript("commit-ready-logs-the-rest", "clarification", [
        log("a fairlife and a banana",
            items=[item("fairlife", brand="Fairlife", calories=170),
                   item("banana", amount=1, unit="piece", basis="stated")],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 1}),
        reply("just log the rest", expect={"command": "commit_ready"}),
    ]),

    transcript("start-over-is-a-command-not-a-product", "clarification", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("start over", expect={"command": "restart"}),
    ]),

    transcript("a-numeric-answer-to-a-product-question-is-not-a-product",
               "clarification", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("42", expect={"unparsed": True}),
    ]),

    transcript("half-answers-the-portion-not-the-product", "clarification", [
        log("some of a quest bar",
            items=[item("quest bar", brand="Quest", calories=190)],
            ambiguities=[amb("quest bar", "consumed",
                             ["all of it", "half"], impact_cal=100)],
            expect={"asks": True, "fields": ["consumed_fraction"]}),
        reply("about half",
              expect={"resolves": True, "not_field": "product_line"}),
    ]),

    transcript("a-yes-is-only-an-answer-to-a-yes-no-question",
               "clarification", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("yes", expect={"unparsed": True}),
    ]),

    transcript("an-answer-naming-the-option-verbatim-parses",
               "clarification", [
        log("a chobani",
            items=[item("chobani", brand="Chobani", calories=140)],
            ambiguities=[amb("chobani", "variant",
                             ["Zero Sugar", "Complete"], impact_cal=60,
                             impact_protein=8)],
            expect={"asks": True}),
        reply("Zero Sugar", expect={"values": {"variant": "Zero Sugar"}}),
    ]),

    transcript("an-ordinal-answer-selects-an-option", "clarification", [
        log("a chobani",
            items=[item("chobani", brand="Chobani", calories=140)],
            ambiguities=[amb("chobani", "variant",
                             ["Zero Sugar", "Complete"], impact_cal=60,
                             impact_protein=8)],
            expect={"asks": True}),
        reply("the first one", expect={"resolves": True}),
    ]),

    transcript("quick-still-asks-about-a-coin-toss", "clarification", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 0}),
    ], mode="quick"),

    transcript("an-empty-meal-plans-nothing", "clarification", [
        log("hey", items=[], expect={"decision": None}),
    ]),
]


# ══ user preferences and corrections ═════════════════════════════════════════
# What the user has already told us must not be asked again — and must be
# disclosed, not applied silently, so a correction has something to contradict.
PREFERENCES = [
    transcript("a-confirmed-preference-answers-the-question", "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "committed": 1, "assumptions_min": 1,
                    "assumption_contains": "usual"}),
    ]),

    transcript("one-confirmation-is-not-yet-a-preference", "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=1),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
    ]),

    transcript("a-preference-for-another-food-does-not-apply", "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a chobani",
            items=[item("chobani", brand="Chobani", calories=140)],
            ambiguities=[amb("chobani", "variant",
                             ["Zero Sugar", "Complete"], impact_cal=60,
                             impact_protein=8)],
            expect={"asks": True}),
    ]),

    transcript("a-preference-is-applied-as-a-stated-assumption",
               "preferences", [
        learn("my shake", "product_line", "Core Power Elite",
              confirmations=3),
        log("my shake",
            items=[item("my shake")],
            ambiguities=[amb("my shake", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "assumptions_min": 1,
                    "assumption_contains": "usual"}),
    ]),

    transcript("a-preference-does-not-silence-a-different-field",
               "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "portion", ["1 bottle", "half"],
                             impact_cal=120)],
            expect={"asks": True, "fields": ["estimated_mass_g"]}),
    ]),

    transcript("strict-confirms-a-young-preference-rather-than-using-it",
               "preferences", [
        # Three confirmations promote a default for moderate. Strict wants two
        # more before it stops asking — a learned default is still a guess, and
        # strict is the mode that does not accept guesses.
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 0, "held": 1,
                    "policy": "atomic_hold"}),
    ], mode="strict"),

    transcript("a-well-established-preference-satisfies-strict-too",
               "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=5),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            # Applied and disclosed. Atomic hold is all-or-nothing, not
            # nothing: with the only item resolved there is no partial commit
            # to prevent, so the meal commits as one transaction.
            expect={"asks": False, "committed": 1, "held": 0,
                    "assumption_contains": "usual",
                    "policy": "atomic_hold"}),
    ], mode="strict"),

    transcript("a-contradicted-preference-stops-applying-immediately",
               "preferences", [
        learn("fairlife", "product_line", "Core Power", confirmations=3),
        # The learn turn below contradicts it. One disagreement demotes — a
        # default that has been wrong should stop applying now, not after it
        # has been wrong three times.
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=4),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False}),
    ]),

    transcript("a-preference-on-a-possessive-phrase", "preferences", [
        learn("my usual shake", "product_line", "Core Power Elite",
              confirmations=3),
        log("my usual shake",
            items=[item("my usual shake")],
            ambiguities=[amb("my usual shake", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "committed": 1,
                    "assumption_contains": "usual"}),
    ]),

    transcript("a-preference-does-not-match-a-different-phrasing",
               "preferences", [
        learn("my usual shake", "product_line", "Core Power Elite",
              confirmations=3),
        log("a protein shake",
            items=[item("a protein shake")],
            ambiguities=[amb("a protein shake", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
    ]),

    transcript("preferences-are-matched-case-and-space-insensitively",
               "preferences", [
        learn("Fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("  FAIRLIFE ",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "committed": 1}),
    ]),

    transcript("a-preference-on-a-variant-fills-the-variant", "preferences", [
        learn("chobani", "variant", "Zero Sugar", confirmations=3),
        log("a chobani",
            items=[item("chobani", brand="Chobani", calories=140)],
            ambiguities=[amb("chobani", "variant",
                             ["Zero Sugar", "Complete"], impact_cal=60,
                             impact_protein=8)],
            expect={"asks": False, "committed": 1,
                    "assumption_contains": "usual"}),
    ]),

    transcript("a-preference-applies-to-one-item-not-the-meal",
               "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a fairlife and a chobani",
            items=[item("fairlife", brand="Fairlife", calories=170),
                   item("chobani", brand="Chobani", calories=140)],
            ambiguities=[
                amb("fairlife", "brand", ["Core Power", "Core Power Elite"],
                    impact_cal=190, impact_protein=16),
                amb("chobani", "variant", ["Zero Sugar", "Complete"],
                    impact_cal=60, impact_protein=8)],
            expect={"asks": True, "questions": 1, "committed": 1, "held": 1}),
    ]),

    transcript("a-preference-that-does-not-cover-the-asked-field-still-asks",
               "preferences", [
        learn("fairlife", "variant", "chocolate", confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "portion", ["1 bottle", "half"],
                             impact_cal=120)],
            expect={"asks": True, "fields": ["estimated_mass_g"]}),
    ]),

    transcript("quick-mode-uses-a-preference-without-asking", "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "committed": 1,
                    "policy": "commit_with_assumptions"}),
    ], mode="quick"),

    transcript("no-preference-at-all-behaves-as-before", "preferences", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True, "committed": 0}),
    ]),

    transcript("a-preference-never-overrides-a-stated-amount", "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("two fairlifes",
            items=[item("fairlife", brand="Fairlife", amount=2,
                        unit="bottle", basis="stated", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "committed": 1}),
    ]),

    transcript("a-preference-plus-a-portion-question-asks-only-the-portion",
               "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("some of a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[
                amb("fairlife", "brand", ["Core Power", "Core Power Elite"],
                    impact_cal=190, impact_protein=16),
                amb("fairlife", "consumed", ["all of it", "half"],
                    impact_cal=110)],
            expect={"asks": True, "questions": 1,
                    "fields": ["consumed_fraction"],
                    "assumption_contains": "usual"}),
    ]),

    transcript("an-answer-to-a-preference-backed-item-still-parses",
               "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("some of a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[
                amb("fairlife", "brand", ["Core Power", "Core Power Elite"],
                    impact_cal=190, impact_protein=16),
                amb("fairlife", "consumed", ["all of it", "half"],
                    impact_cal=110)],
            expect={"asks": True}),
        reply("about half",
              expect={"values": {"consumed_fraction": 0.5},
                      "asks_after": False, "committed_after": 1}),
    ]),

    transcript("a-promoted-preference-is-still-only-an-assumption",
               "preferences", [
        learn("fairlife", "product_line", "Core Power Elite",
              confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            # The distinction that makes a correction possible: what was
            # applied is recorded as an assumption with visible text, not as a
            # fact the user has no way to see or contradict.
            expect={"asks": False, "assumptions_min": 1,
                    "assumption_contains": "core power elite"}),
    ]),
]


# ══ corrections after the fact ═══════════════════════════════════════════════
# A correction is not a new log. It contradicts a specific assumption, and what
# it teaches is which pairs we keep confusing.
CORRECTIONS = [
    transcript("a-correction-contradicts-the-assumption-it-names",
               "corrections", [
        learn("fairlife", "product_line", "Core Power", confirmations=3),
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": False, "assumptions_min": 1}),
        reply("no, it was the elite",
              expect={"correction": {"field": "product_line",
                                     "corrected": "Core Power Elite"},
                      "demotes": True}),
    ]),

    transcript("a-correction-on-a-quick-assumption-is-the-same-shape",
               "corrections", [
        log("a fairlife",
            items=[item("fairlife", brand="Fairlife", calories=170)],
            ambiguities=[amb("fairlife", "brand",
                             ["Core Power", "Core Power Elite"],
                             impact_cal=190, impact_protein=16)],
            expect={"asks": True}),
        reply("core power", expect={"resolves": True}),
    ], mode="quick"),
]


ALL_TRANSCRIPTS = CLARIFICATION + PREFERENCES + CORRECTIONS
