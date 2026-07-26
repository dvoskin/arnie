"""Four failures from one live session, and the seams behind them.

The transcript, in order:

    Arnie:  Here's how I'm interpreting that:
            · Four honey turkey deli slices
            · One some of mustard
            · A royo everything bagel
            Which Royo Everything Bagel was it?
    User:   All right
    Arnie:  Bagel, turkey, mustard, solid evening plate. 973 in, …
    User:   Look it
    Arnie:  That's already on the board from earlier, nothing new logged.
            Already on the board: Mustard (1 tsp, 3 cal), logged 01:24 (22s ago).

    User:   I had 2 chicken thighs grilled marinated teriyaki
    Arnie:  Here's what I'm about to log:
            · Two chicken thigh, grilled teriyaki marinateds

Three separate defects, plus the branded-macro problem that runs underneath
the whole session. Each gets its own section below.
"""
import core.food_response as FR
import skills.nutrition.authority as authority
from handlers.tool_executor import (_looks_branded, _names_a_product,
                                    blocked_log_reply, user_asked_to_log)


# ── 1. the receipt for a request nobody made ──────────────────────────────────
#
# "Look it" is not a log request. The model has the whole thread in context, so
# it re-proposed the meal that had just been logged; the dedup blocked it; and
# the block was then reported to the user as though they had asked. Nothing was
# written and nothing was requested, so the turn had no news in it at all.
_MUSTARD = "Already on the board: Mustard (1 tsp, 3 cal), logged 01:24 (22s ago) #14."
_CALLS = [{"name": "log_food", "input": {"food_name": "Mustard"}}]
_RESULTS = {"log_food": _MUSTARD}


def test_look_it_gets_no_dedup_receipt():
    assert blocked_log_reply(_CALLS, _RESULTS, user_message="Look it") is None


def test_naming_the_food_still_earns_the_receipt():
    """The 00:38 turkey incident: the user really did re-log it, and telling
    them it was already down is the entire point of this reply."""
    out = blocked_log_reply(_CALLS, _RESULTS, user_message="add mustard")
    assert out is not None and "Already on the board" in out


def test_a_bare_log_cue_still_earns_the_receipt():
    """"log it" names no food but is unmistakably a request to log one."""
    assert blocked_log_reply(_CALLS, _RESULTS, user_message="log it") is not None


def test_a_partial_name_counts_as_naming_it():
    assert user_asked_to_log("was the mustard already down?", [_MUSTARD])


def test_callers_that_pass_no_message_keep_the_old_behaviour():
    """Back-compat: a caller with no message cannot tell the cases apart, and
    silence would lose a real receipt."""
    assert blocked_log_reply(_CALLS, _RESULTS) is not None


def test_a_successful_log_is_still_not_a_block():
    assert blocked_log_reply(
        _CALLS, {"log_food": "Logged: Mustard, 3 cal, 0g protein"},
        user_message="add mustard") is None


# ── 2. "Two chicken thigh, grilled teriyaki marinateds" ───────────────────────
#
# The interpreter names a prepared food in the appositive form — head noun,
# comma, preparation. The head span ran to the end of the string, so the count
# inflected the preparation instead of the food.
def test_the_comma_ends_the_head_noun():
    assert FR._plural_food("chicken thigh, grilled teriyaki marinated", 2) == \
        "chicken thighs, grilled teriyaki marinated"


def test_prepositions_still_end_the_head():
    assert FR._plural_food("mozzarella sticks with marinara", 2) == \
        "mozzarella sticks with marinara"


def test_a_plain_food_is_unaffected():
    assert FR._plural_food("egg", 2) == "eggs"
    assert FR._plural_food("Peanut M&M's", 2) == "Peanut M&M's"


def test_one_of_them_does_not_inflect_at_all():
    assert FR._plural_food("chicken thigh, grilled teriyaki marinated", 1) == \
        "chicken thigh, grilled teriyaki marinated"


# ── 3. the branded products that never got a branded lookup ───────────────────
#
# The package-noun list was written by hand in whatever form came to mind:
# "bagels" without "bagel", "crackers" without "cracker", "tortillas" without
# "tortilla". Half of every pair was a silent miss. A named product with no
# product signal takes the GENERIC ladder, which is how a Royo Everything Bagel
# gets generic bagel macros while the reply correctly calls it a Royo.
_NAMED_PRODUCTS = ["Royo Everything Bagel", "Legendary Cinnamon Roll",
                   "Nissin Cup Noodles", "Barebells Cookies and Cream",
                   "Jif Peanut Butter", "Chobani Yogurt"]
_PLAIN_FOODS = ["everything bagel", "cinnamon roll", "grilled chicken",
                "peanut butter", "scrambled eggs", "white rice",
                "chicken thigh, grilled teriyaki marinated"]


def test_a_named_product_gets_a_product_signal():
    missed = [n for n in _NAMED_PRODUCTS if not _looks_branded(n)]
    assert not missed, missed


def test_a_named_product_takes_the_manufactured_ladder():
    generic = [n for n in _NAMED_PRODUCTS
               if authority.classify(n, is_packaged=_looks_branded(n))
               is not authority.FoodClass.MANUFACTURED]
    assert not generic, generic


def test_a_plain_food_is_still_plain():
    """The same words in lowercase are a plain food. The capitalisation
    requirement in the pattern had been void — a module-wide `re.I` applied to
    the `[A-Z]` too — so completing the noun list would have swept these in."""
    branded = [n for n in _PLAIN_FOODS if _looks_branded(n)]
    assert not branded, branded


def test_every_package_noun_carries_both_inflections():
    """The rule that makes the list un-half-writable."""
    from skills.nutrition.branded import _PACKAGE_NOUN_FORMS, _inflect
    for stem in ("bagel", "roll", "cracker", "tortilla", "wrap", "noodle"):
        for form in _inflect(stem):
            assert form in _PACKAGE_NOUN_FORMS, form


# ── 4. a WEAK guess must not open the web-label lane ──────────────────────────
#
# `is_packaged` was rebound to include the heuristic and then handed to the
# STRONG gate, so a capitalised word in front of a package noun arrived at the
# web lane as though the model had declared the item packaged. The lane's own
# comment forbids exactly that: OFF is a branded index whose answer survives
# identity validation, while the web lane parses a label out of search results
# and has a history of finding the wrong product.
def test_the_heuristic_alone_does_not_open_the_web_lane():
    assert not _names_a_product("Royo Everything Bagel", False)


def test_the_model_declaring_it_packaged_does_open_it():
    assert _names_a_product("Royo Everything Bagel", True)


def test_a_name_that_is_strong_on_its_own_still_opens_it():
    """"Barebells Cookies and Cream" carries an explicit conjunction-shaped
    product line — strong without anyone declaring anything."""
    assert _names_a_product("Barebells Cookies and Cream", False)
