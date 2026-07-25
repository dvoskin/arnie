"""The nutrition gold set (review 2026-07-25, work order step 9).

Fixed cases with fixed expectations, so nutrient correctness is a number that
moves rather than a series of anecdotes. Every case names what each source
WOULD have returned, which makes the whole suite deterministic and offline:
what is under test is the resolution logic — precedence, scaling, validation,
unknown-handling and the ask ladder — not whether USDA is up.

Each case asserts, where it is meaningful:

    source        which authority class won
    identity      the canonical name that was selected
    calories      within a stated tolerance
    protein       within a stated tolerance
    known         fields that must be populated
    unknown       fields that must be NULL, not zero
    rejects       sources that must have lost, and been recorded losing
    asks          whether each logging mode should interrupt

Cases come from the incident history and from the review's categories:
branded labels, generic mass foods, piece counts, composite restaurant meals,
and the micronutrient cases that have produced impossible numbers.

Adding a case is the cheapest way to make a nutrition bug stay fixed.
"""
from skills.nutrition.provenance import MatchGrade, SourceTier

# Shorthand for the tiers, so a case reads like the thing it describes.
LABEL = SourceTier.USER_LABEL
REGULAR = SourceTier.USER_REGULAR
BRANDED = SourceTier.BRANDED_EXACT
GENERIC = SourceTier.GENERIC_EXACT
ESTIMATE = SourceTier.ESTIMATED
PROVISIONAL = SourceTier.PROVISIONAL


def c(source, tier, name, basis="per_100g", grade=MatchGrade.EXACT,
      brand=None, variant=None, serving_mass_g=None, **values):
    return {"source": source, "tier": tier, "name": name, "basis": basis,
            "grade": grade, "brand": brand, "variant": variant,
            "serving_mass_g": serving_mass_g, "values": values}


def case(cid, category, food, quantity, candidates, expect, **request):
    return {"id": cid, "category": category,
            "request": dict(food_name=food, raw_quantity=quantity, **request),
            "candidates": candidates, "expect": expect}


# ── branded labels ────────────────────────────────────────────────────────────
BRANDED_CASES = [
    case("royo-plain-label-beats-usda", "branded",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("usda", GENERIC, "Bagel, plain, enriched",
               grade=MatchGrade.CATEGORY, calories=290, protein=11, sodium=534),
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo",
               calories=80, protein=8, carbs=6, fat=1)],
         expect={"source": "off", "identity": "Royo Plain Bagel",
                 "calories": (79, 81), "protein": (7.9, 8.1),
                 "rejects": [], "asks": {"quick": False, "strict": False}}),

    case("royo-everything-is-not-royo-plain", "branded",
         "Royo Plain Bagel", "100g", brand="Royo", variant="plain",
         candidates=[
             c("off", BRANDED, "Royo Everything Bagel", brand="Royo",
               variant="everything", calories=110, protein=9)],
         expect={"source": "unresolved", "known": [],
                 "rejects": ["off"]}),

    case("wrong-brand-loses-unopposed", "branded",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Thomas Plain Bagel", brand="Thomas",
               calories=250, protein=9)],
         expect={"source": "unresolved", "rejects": ["off"]}),

    case("quest-bar-label", "branded",
         "Quest Chocolate Chip Cookie Dough Bar", "100g", brand="Quest",
         candidates=[
             c("off", BRANDED, "Quest Chocolate Chip Cookie Dough Bar",
               brand="Quest", calories=333, protein=35, carbs=42, fat=13,
               fiber=23, sugar=1, sodium=460)],
         expect={"source": "off",
                 "identity": "Quest Chocolate Chip Cookie Dough Bar",
                 "calories": (330, 336),
                 "known": ["calories", "protein", "fiber", "sodium"]}),

    case("chobani-yogurt", "branded",
         "Chobani Plain Nonfat Greek Yogurt", "150g", brand="Chobani",
         candidates=[
             c("off", BRANDED, "Chobani Plain Nonfat Greek Yogurt",
               brand="Chobani", calories=59, protein=10, carbs=3.6, fat=0,
               sodium=36)],
         expect={"source": "off",
                 "identity": "Chobani Plain Nonfat Greek Yogurt",
                 "calories": (87, 90), "protein": (14.5, 15.5)}),

    case("starbucks-latte-web-label", "branded",
         "Starbucks Grande Latte", "1 serving", brand="Starbucks",
         is_packaged=True,
         candidates=[
             c("web_label", BRANDED, "Starbucks Grande Latte",
               basis="per_serving", grade=MatchGrade.CLOSE, brand="Starbucks",
               calories=190, protein=13, carbs=19, fat=7)],
         expect={"source": "web_label", "identity": "Starbucks Grande Latte",
                 "calories": (188, 192)}),

    case("saved-regular-beats-off", "branded",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=110),
             c("user_regular", REGULAR, "Royo Plain Bagel", brand="Royo",
               calories=80, protein=8)],
         expect={"source": "user_regular", "identity": "Royo Plain Bagel",
                 "calories": (79, 81)}),

    case("user-label-beats-everything", "branded",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("user_regular", REGULAR, "Royo Plain Bagel", brand="Royo",
               calories=110),
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=95),
             c("user_label", LABEL, "Royo Plain Bagel", brand="Royo",
               calories=80, protein=8)],
         expect={"source": "user_label", "identity": "Royo Plain Bagel",
                 "calories": (79, 81)}),

    case("exact-grade-beats-category-in-tier", "branded",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Bagel Assortment", brand="Royo",
               grade=MatchGrade.CATEGORY, calories=200),
             c("web_label", BRANDED, "Royo Plain Bagel", brand="Royo",
               calories=80)],
         expect={"source": "web_label", "identity": "Royo Plain Bagel",
                 "calories": (79, 81)}),
]

# ── generic mass foods ────────────────────────────────────────────────────────
GENERIC_CASES = [
    case("chicken-200g", "generic",
         "chicken breast, roasted", "200g",
         candidates=[c("usda", GENERIC, "Chicken breast, roasted, skinless",
                       calories=165, protein=31, fat=3.6, sodium=74)],
         expect={"source": "usda", "calories": (329, 331),
                 "protein": (61.5, 62.5), "asks": {"strict": False}}),

    case("steak-6oz", "generic",
         "sirloin steak, grilled", "6 oz",
         candidates=[c("usda", GENERIC, "Beef, sirloin, grilled",
                       calories=206, protein=29, fat=9)],
         expect={"source": "usda", "calories": (345, 355)}),

    case("cooked-rice-100g", "generic",
         "white rice, cooked", "100g",
         candidates=[c("usda", GENERIC, "Rice, white, cooked",
                       calories=130, protein=2.7, carbs=28)],
         expect={"source": "usda", "calories": (129, 131)}),

    case("raw-is-not-cooked", "generic",
         "chicken breast, roasted", "200g",
         candidates=[c("usda", GENERIC, "Chicken breast, raw",
                       grade=MatchGrade.EXACT, calories=120, protein=23)],
         expect={"source": "usda", "grade": MatchGrade.CATEGORY,
                 "calories": (239, 241)}),

    case("banana-piece", "generic",
         "banana", "1 banana",
         candidates=[c("usda", GENERIC, "Banana, raw", calories=89,
                       protein=1.1, carbs=23, fiber=2.6, potassium=358)],
         expect={"source": "usda", "calories": (100, 110),
                 "known": ["calories", "fiber"]}),

    case("oats-40g", "generic",
         "rolled oats", "40g",
         candidates=[c("usda", GENERIC, "Oats, rolled, dry", calories=379,
                       protein=13, carbs=67, fiber=10)],
         expect={"source": "usda", "calories": (150, 154)}),

    case("olive-oil-tbsp", "generic",
         "olive oil", "1 tbsp",
         candidates=[c("usda", GENERIC, "Oil, olive", basis="per_100ml",
                       calories=884, fat=100)],
         expect={"source": "usda", "calories": (128, 134)}),
]

# ── piece counts ──────────────────────────────────────────────────────────────
PIECE_CASES = [
    case("six-fries", "pieces",
         "french fry", "6 fries",
         candidates=[c("usda", GENERIC, "Potatoes, french fried",
                       calories=312, protein=3.4, fat=15, sodium=210)],
         expect={"source": "usda", "calories": (140, 160),
                 "assumption_contains": "estimated",
                 "asks": {"quick": False}}),

    case("three-turkey-slices", "pieces",
         "turkey deli slice", "3 slices",
         candidates=[c("usda", GENERIC, "Turkey breast, deli slice",
                       calories=104, protein=17, sodium=1020)],
         expect={"source": "usda", "calories": (50, 62),
                 "assumption_contains": "estimated"}),

    case("two-pizza-slices", "pieces",
         "pizza slice", "2 slices",
         candidates=[c("usda", GENERIC, "Pizza, cheese", calories=266,
                       protein=11, carbs=33, fat=10, sodium=598)],
         expect={"source": "usda", "calories": (520, 610),
                 "asks": {"strict": True}}),

    case("half-a-bar", "pieces",
         "protein bar", "half a bar",
         candidates=[c("off", BRANDED, "protein bar", calories=333,
                       protein=33)],
         expect={"source": "off", "calories": (95, 105)}),

    case("thin-slices-weigh-less", "pieces",
         "bread slice", "2 thin slices",
         candidates=[c("usda", GENERIC, "Bread, white", calories=266,
                       protein=9, carbs=49)],
         expect={"source": "usda", "calories": (95, 110)}),

    case("unweighable-portion-is-unknown", "pieces",
         "grandma's mystery casserole", "2 servings",
         candidates=[c("provisional", PROVISIONAL,
                       "grandma's mystery casserole", basis="per_serving",
                       grade=MatchGrade.CATEGORY, calories=400, protein=20)],
         expect={"source": "provisional",
                 "assumption_contains": "portion mass unknown"}),
]

# ── composite restaurant meals ────────────────────────────────────────────────
COMPOSITE_CASES = [
    case("shawarma-platter", "composite",
         "chicken shawarma platter", "1 platter",
         candidates=[
             c("web_label", ESTIMATE, "chicken shawarma platter",
               basis="per_serving", grade=MatchGrade.CATEGORY,
               calories=1100, protein=60, carbs=110, fat=45)],
         expect={"source": "web_label", "calories": (1090, 1110),
                 "assumption_contains": "estimate"}),

    case("poke-bowl", "composite",
         "salmon poke bowl", "1 bowl",
         candidates=[
             c("web_label", ESTIMATE, "salmon poke bowl", basis="per_serving",
               grade=MatchGrade.CATEGORY, calories=700, protein=35, carbs=80,
               fat=25)],
         expect={"source": "web_label", "calories": (690, 710)}),

    case("cheeseburger-and-partial-fries", "composite",
         "cheeseburger", "1 burger",
         candidates=[
             c("web_label", ESTIMATE, "cheeseburger", basis="per_serving",
               grade=MatchGrade.CLOSE, calories=550, protein=30, carbs=40,
               fat=28)],
         expect={"source": "web_label", "calories": (545, 555)}),

    case("homemade-stew-is-provisional", "composite",
         "homemade beef stew", "1 bowl",
         candidates=[
             c("provisional", PROVISIONAL, "homemade beef stew",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=400,
               protein=28, carbs=30, fat=18)],
         expect={"source": "provisional",
                 "assumption_contains": "estimate"}),

    case("composite-micros-stay-unknown", "composite",
         "chicken shawarma platter", "1 platter",
         candidates=[
             c("web_label", ESTIMATE, "chicken shawarma platter",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=1100,
               protein=60)],
         expect={"source": "web_label",
                 "unknown": ["sodium", "fiber", "sugar"]}),
]

# ── the dangerous micronutrient cases ─────────────────────────────────────────
MICRO_CASES = [
    case("garlic-is-not-garlic-powder", "micros",
         "garlic", "10g",
         candidates=[
             c("usda", GENERIC, "Garlic powder", calories=331, protein=17,
               sodium=60),
             c("usda", GENERIC, "Garlic, raw", calories=149, protein=6,
               sodium=17)],
         expect={"source": "usda", "identity": "Garlic, raw",
                 "rejects": ["usda"]}),

    case("seasoning-sodium-is-impossible-for-a-breast", "micros",
         "chicken breast", "200g",
         candidates=[
             c("usda", GENERIC, "Chicken breast, roasted", calories=165,
               protein=31, sodium=20378)],
         expect={"source": "usda", "calories": (329, 331),
                 "unknown": ["sodium"]}),

    case("soy-sauce-is-allowed-to-be-salty", "micros",
         "soy sauce", "15ml",
         candidates=[
             c("usda", GENERIC, "Soy sauce", basis="per_100ml", calories=53,
               protein=8, sodium=5493)],
         expect={"source": "usda", "known": ["sodium"]}),

    case("bouillon-cousin-is-rejected", "micros",
         "chicken broth", "240ml",
         candidates=[
             c("usda", GENERIC, "Chicken bouillon, powder",
               basis="per_100ml", calories=240, sodium=24000)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("missing-sodium-stays-missing", "micros",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=80,
               protein=8, carbs=6, fat=1)],
         expect={"source": "off", "unknown": ["sodium", "fiber", "sugar"],
                 "warning_contains": "unknown"}),

    case("sugar-alcohol-product-passes-energy-check", "micros",
         "Quest Chocolate Chip Cookie Dough Bar", "100g", brand="Quest",
         candidates=[
             c("off", BRANDED, "Quest Chocolate Chip Cookie Dough Bar",
               brand="Quest", calories=333, protein=35, carbs=42, fat=13,
               fiber=23)],
         expect={"source": "off", "calories": (330, 336)}),

    case("macros-that-do-not-add-up-are-rejected", "micros",
         "mystery shake", "100g",
         candidates=[
             c("off", BRANDED, "mystery shake", calories=100, protein=30,
               carbs=40, fat=20)],
         expect={"source": "unresolved", "rejects": ["off"]}),

    case("micros-fill-from-an-exact-generic-match", "micros",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("user_label", LABEL, "Royo Plain Bagel", brand="Royo",
               calories=80, protein=8, carbs=6, fat=1),
             c("usda", GENERIC, "Royo Plain Bagel", calories=290, protein=11,
               sodium=400, fiber=3)],
         expect={"source": "user_label", "calories": (79, 81),
                 "known": ["sodium", "fiber"],
                 "assumption_contains": "from usda"}),

    case("impossible-calories-condemn-the-candidate", "micros",
         "white rice, cooked", "100g",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=4000)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("energy-check-skipped-when-a-macro-is-unknown", "micros",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=80,
               protein=8, carbs=6)],
         expect={"source": "off", "unknown": ["fat"]}),
]

# ── mode / ask-ladder cases ───────────────────────────────────────────────────
MODE_CASES = [
    case("exact-mass-never-asks", "modes",
         "chicken breast, roasted", "200g",
         candidates=[c("usda", GENERIC, "Chicken breast, roasted",
                       calories=165, protein=31)],
         expect={"asks": {"quick": False, "moderate": False, "strict": False}}),

    case("unweighable-large-item-asks-below-quick", "modes",
         "shawarma platter", "1 platter",
         candidates=[c("web_label", ESTIMATE, "shawarma platter",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=1100)],
         expect={"asks": {"quick": True, "moderate": True, "strict": True}}),

    case("material-source-disagreement-asks-in-strict", "modes",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=80),
             c("web_label", BRANDED, "Royo Plain Bagel", brand="Royo",
               calories=260)],
         expect={"asks": {"strict": True}}),
]

ALL_CASES = (BRANDED_CASES + GENERIC_CASES + PIECE_CASES + COMPOSITE_CASES
             + MICRO_CASES + MODE_CASES)


# ── tranche 2: breadth ────────────────────────────────────────────────────────
# The first tranche pins the failure classes. This one covers the everyday
# surface area, where regressions hide precisely because nothing dramatic
# happens: ordinary foods, ordinary portions, ordinary units.

BRANDED_CASES_2 = [
    case("clif-bar", "branded", "Clif Bar Chocolate Chip", "68g", brand="Clif",
         candidates=[c("off", BRANDED, "Clif Bar Chocolate Chip", brand="Clif",
                       calories=368, protein=13, carbs=64, fat=8, fiber=6,
                       sugar=31, sodium=221)],
         expect={"source": "off", "identity": "Clif Bar Chocolate Chip",
                 "calories": (248, 252), "known": ["sodium"]}),

    case("fairlife-milk", "branded", "Fairlife 2% Milk", "240ml",
         brand="Fairlife",
         candidates=[c("off", BRANDED, "Fairlife 2% Milk", basis="per_100ml",
                       brand="Fairlife", calories=50, protein=5.4, carbs=2.5,
                       fat=2, sodium=50)],
         expect={"source": "off", "identity": "Fairlife 2% Milk",
                 "calories": (118, 122)}),

    case("core-power-shake", "branded", "Core Power Vanilla Shake", "414ml",
         brand="Core Power",
         candidates=[c("off", BRANDED, "Core Power Vanilla",
                       basis="per_100ml", brand="Core Power", calories=41,
                       protein=6, carbs=3, fat=0.9)],
         expect={"source": "off", "identity": "Core Power Vanilla",
                 "calories": (168, 172)}),

    case("halo-top-pint", "branded", "Halo Top Vanilla Bean", "473ml",
         brand="Halo Top",
         candidates=[c("off", BRANDED, "Halo Top Vanilla Bean",
                       basis="per_100ml", brand="Halo Top", calories=57,
                       protein=4, carbs=13, fat=1.5, fiber=3, sugar=5)],
         expect={"source": "off", "identity": "Halo Top Vanilla Bean",
                 "calories": (267, 272)}),

    case("siggis-yogurt", "branded", "Siggi's Vanilla Skyr", "150g",
         brand="Siggi's",
         candidates=[c("off", BRANDED, "Siggi's Vanilla Skyr", brand="Siggi's",
                       calories=74, protein=10.7, carbs=7.3, fat=0)],
         expect={"source": "off", "identity": "Siggi's Vanilla Skyr",
                 "calories": (110, 112)}),

    case("rx-bar", "branded", "RXBAR Chocolate Sea Salt", "52g", brand="RXBAR",
         candidates=[c("off", BRANDED, "RXBAR Chocolate Sea Salt",
                       brand="RXBAR", calories=404, protein=23, carbs=44,
                       fat=17, fiber=10, sodium=250)],
         expect={"source": "off", "identity": "RXBAR Chocolate Sea Salt",
                 "calories": (208, 212)}),

    case("kind-bar-flavour-conflict", "branded", "KIND Dark Chocolate Nut",
         "40g", brand="KIND", variant="dark chocolate",
         candidates=[c("off", BRANDED, "KIND Peanut Butter Bar", brand="KIND",
                       variant="peanut butter", calories=500)],
         expect={"source": "unresolved", "rejects": ["off"]}),

    case("barcode-exact-beats-generic", "branded", "Kirkland Protein Bar",
         "60g", brand="Kirkland",
         candidates=[
             c("usda", GENERIC, "Snack bar, protein",
               grade=MatchGrade.CATEGORY, calories=380, protein=20),
             c("off", BRANDED, "Kirkland Protein Bar", brand="Kirkland",
               calories=350, protein=33, fiber=15)],
         expect={"source": "off", "identity": "Kirkland Protein Bar",
                 "calories": (208, 212)}),

    case("store-brand-with-no-off-hit-falls-to-usda", "branded",
         "store brand greek yogurt", "170g",
         candidates=[c("usda", GENERIC, "Yogurt, Greek, plain, nonfat",
                       grade=MatchGrade.CLOSE, calories=59, protein=10)],
         expect={"source": "usda", "identity": "Yogurt, Greek, plain, nonfat",
                 "calories": (99, 102)}),

    case("provisional-only-is-last-resort", "branded",
         "some new energy drink", "1 can",
         candidates=[c("provisional", PROVISIONAL, "some new energy drink",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=110, sugar=27)],
         expect={"source": "provisional",
                 "assumption_contains": "estimate"}),
]

GENERIC_CASES_2 = [
    case("egg-two", "generic", "egg", "2 eggs",
         candidates=[c("usda", GENERIC, "Egg, whole, raw", calories=143,
                       protein=13, fat=9.5, cholesterol=372)],
         expect={"source": "usda", "calories": (135, 150),
                 "known": ["cholesterol"]}),

    case("salmon-6oz", "generic", "salmon, baked", "6 oz",
         candidates=[c("usda", GENERIC, "Salmon, Atlantic, baked",
                       calories=206, protein=22, fat=12)],
         expect={"source": "usda", "calories": (345, 355)}),

    case("broccoli-cup", "generic", "broccoli, steamed", "1 cup",
         candidates=[c("usda", GENERIC, "Broccoli, cooked", calories=35,
                       protein=2.4, carbs=7, fiber=3.3)],
         expect={"source": "usda", "known": ["fiber"]}),

    case("almonds-28g", "generic", "almonds", "28g",
         candidates=[c("usda", GENERIC, "Nuts, almonds", calories=579,
                       protein=21, fat=50, fiber=12.5)],
         expect={"source": "usda", "calories": (160, 165)}),

    case("sweet-potato-200g", "generic", "sweet potato, baked", "200g",
         candidates=[c("usda", GENERIC, "Sweet potato, baked", calories=90,
                       protein=2, carbs=21, fiber=3.3, potassium=475)],
         expect={"source": "usda", "calories": (179, 181),
                 "known": ["potassium"]}),

    case("ground-beef-93-5", "generic", "ground beef 93/7, cooked", "4 oz",
         candidates=[c("usda", GENERIC, "Beef, ground, 93% lean, cooked",
                       calories=182, protein=25, fat=9)],
         expect={"source": "usda", "calories": (204, 208)}),

    case("quinoa-cooked-185g", "generic", "quinoa, cooked", "185g",
         candidates=[c("usda", GENERIC, "Quinoa, cooked", calories=120,
                       protein=4.4, carbs=21, fiber=2.8)],
         expect={"source": "usda", "calories": (221, 223)}),

    case("black-beans-canned", "generic", "black beans, canned", "130g",
         candidates=[c("usda", GENERIC, "Beans, black, canned", calories=91,
                       protein=6, carbs=16, fiber=6.4, sodium=331)],
         expect={"source": "usda", "known": ["sodium", "fiber"]}),

    case("avocado-half", "generic", "avocado", "half an avocado",
         candidates=[c("usda", GENERIC, "Avocado, raw", calories=160,
                       protein=2, fat=15, fiber=7)],
         expect={"source": "usda"}),

    case("peanut-butter-tbsp", "generic", "peanut butter", "2 tbsp",
         candidates=[c("usda", GENERIC, "Peanut butter, smooth",
                       calories=588, protein=25, fat=50, sodium=429)],
         expect={"source": "usda"}),

    case("dried-is-not-fresh", "generic", "apricot", "50g",
         candidates=[c("usda", GENERIC, "Apricots, dried", calories=241,
                       protein=3.4, carbs=63)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("frozen-preparation-downgrades", "generic",
         "broccoli, steamed", "150g",
         candidates=[c("usda", GENERIC, "Broccoli, frozen", calories=28,
                       protein=3)],
         expect={"source": "usda", "grade": MatchGrade.CATEGORY}),
]

PIECE_CASES_2 = [
    case("four-chicken-wings", "pieces", "chicken wing", "4 wings",
         candidates=[c("usda", GENERIC, "Chicken wing, roasted", calories=290,
                       protein=27, fat=19)],
         expect={"source": "usda", "assumption_contains": "estimated"}),

    case("ten-nuggets", "pieces", "chicken nugget", "10 nuggets",
         candidates=[c("usda", GENERIC, "Chicken nuggets", calories=296,
                       protein=15, fat=19, sodium=557)],
         expect={"source": "usda", "asks": {"quick": False}}),

    case("two-cookies", "pieces", "cookie", "2 cookies",
         candidates=[c("usda", GENERIC, "Cookies, chocolate chip",
                       calories=488, protein=5, carbs=64, fat=24)],
         expect={"source": "usda", "assumption_contains": "estimated"}),

    case("handful-of-chips", "pieces", "potato chip", "15 chips",
         candidates=[c("usda", GENERIC, "Potato chips", calories=536,
                       protein=7, fat=35, sodium=525)],
         expect={"source": "usda"}),

    case("three-bacon-slices", "pieces", "bacon slice", "3 slices",
         candidates=[c("usda", GENERIC, "Bacon, cooked", calories=541,
                       protein=37, fat=42, sodium=1717)],
         expect={"source": "usda", "known": ["sodium"]}),

    case("large-eggs-weigh-more", "pieces", "egg", "2 large eggs",
         candidates=[c("usda", GENERIC, "Egg, whole, raw", calories=143,
                       protein=13)],
         expect={"source": "usda", "assumption_contains": "estimated"}),

    case("one-thick-pizza-slice", "pieces", "pizza slice", "1 thick slice",
         candidates=[c("usda", GENERIC, "Pizza, cheese", calories=266,
                       protein=11)],
         expect={"source": "usda", "assumption_contains": "estimated"}),

    case("two-cheese-slices", "pieces", "cheese slice", "2 slices",
         candidates=[c("usda", GENERIC, "Cheese, cheddar", calories=403,
                       protein=25, fat=33, sodium=621)],
         expect={"source": "usda"}),
]

COMPOSITE_CASES_2 = [
    case("cava-bowl", "composite", "CAVA chicken bowl", "1 bowl",
         candidates=[c("web_label", ESTIMATE, "CAVA chicken bowl",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=760, protein=45, carbs=70, fat=32)],
         expect={"source": "web_label", "calories": (755, 765),
                 "unknown": ["sodium"]}),

    case("chipotle-burrito-bowl", "composite", "Chipotle burrito bowl",
         "1 bowl", brand="Chipotle",
         candidates=[c("web_label", BRANDED, "Chipotle chicken burrito bowl",
                       basis="per_serving", grade=MatchGrade.CLOSE,
                       brand="Chipotle", calories=630, protein=45, carbs=55,
                       fat=22, sodium=1370)],
         expect={"source": "web_label", "known": ["sodium"]}),

    case("pad-thai", "composite", "pad thai", "1 plate",
         candidates=[c("web_label", ESTIMATE, "pad thai", basis="per_serving",
                       grade=MatchGrade.CATEGORY, calories=900, protein=30,
                       carbs=110, fat=35)],
         expect={"source": "web_label", "asks": {"strict": True}}),

    case("mom-made-lasagna", "composite", "homemade lasagna", "1 piece",
         candidates=[c("provisional", PROVISIONAL, "homemade lasagna",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=450, protein=25, carbs=35, fat=22)],
         expect={"source": "provisional", "unknown": ["sodium", "fiber"]}),

    case("protein-shake-homemade", "composite", "homemade protein shake",
         "1 shake",
         candidates=[c("provisional", PROVISIONAL, "homemade protein shake",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=320, protein=40, carbs=25, fat=6)],
         expect={"source": "provisional"}),

    case("breakfast-sandwich", "composite", "bacon egg and cheese sandwich",
         "1 sandwich",
         candidates=[c("web_label", ESTIMATE, "bacon egg and cheese sandwich",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=520, protein=22, carbs=40, fat=30)],
         expect={"source": "web_label"}),
]

MICRO_CASES_2 = [
    case("onion-is-not-onion-powder", "micros", "onion", "50g",
         candidates=[
             c("usda", GENERIC, "Onion powder", calories=341, sodium=73),
             c("usda", GENERIC, "Onions, raw", calories=40, protein=1.1,
               fiber=1.7)],
         expect={"source": "usda", "identity": "Onions, raw",
                 "rejects": ["usda"]}),

    case("tomato-is-not-tomato-paste", "micros", "tomato", "100g",
         candidates=[c("usda", GENERIC, "Tomato paste", calories=82,
                       sodium=59, sugar=12)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("ginger-is-not-ginger-extract", "micros", "ginger", "10g",
         candidates=[c("usda", GENERIC, "Ginger extract", calories=350)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("stock-concentrate-rejected", "micros", "beef broth", "240ml",
         candidates=[c("usda", GENERIC, "Beef stock concentrate",
                       basis="per_100ml", calories=180, sodium=18000)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("hot-sauce-is-a-condiment", "micros", "hot sauce", "15ml",
         candidates=[c("usda", GENERIC, "Hot sauce", basis="per_100ml",
                       calories=11, sodium=2643)],
         expect={"source": "usda", "known": ["sodium"]}),

    case("salad-dressing-is-a-condiment", "micros", "ranch dressing", "30ml",
         candidates=[c("usda", GENERIC, "Ranch dressing", basis="per_100ml",
                       calories=430, fat=45, sodium=1100)],
         expect={"source": "usda", "known": ["sodium"]}),

    case("impossible-protein-per-100g-rejected", "micros", "chicken breast",
         "200g",
         candidates=[c("usda", GENERIC, "Chicken breast, roasted",
                       calories=165, protein=95)],
         expect={"source": "unresolved", "rejects": ["usda"]}),

    case("impossible-fibre-drops-that-field", "micros", "white rice, cooked",
         "150g",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=130,
                       protein=2.7, fiber=95)],
         expect={"source": "usda", "unknown": ["fiber"],
                 "calories": (194, 196)}),

    case("negative-value-drops-that-field", "micros", "white rice, cooked",
         "100g",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=130,
                       sodium=-5)],
         expect={"source": "usda", "unknown": ["sodium"]}),

    case("restaurant-micros-are-honestly-unknown", "micros",
         "restaurant fried rice", "1 plate",
         candidates=[c("web_label", ESTIMATE, "restaurant fried rice",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=560, protein=14, carbs=80, fat=20)],
         expect={"source": "web_label",
                 "unknown": ["sodium", "fiber", "sugar", "cholesterol"]}),

    case("a-real-zero-is-allowed", "micros", "Fairlife 2% Milk", "240ml",
         brand="Fairlife",
         candidates=[c("off", BRANDED, "Fairlife 2% Milk", basis="per_100ml",
                       brand="Fairlife", calories=50, protein=5.4, fiber=0.0)],
         expect={"source": "off", "known": ["fiber"]}),

    case("micros-do-not-fill-from-a-weak-match", "micros",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=80,
               protein=8),
             c("usda", GENERIC, "Bagel, cinnamon raisin",
               grade=MatchGrade.CATEGORY, calories=274, sodium=330)],
         expect={"source": "off", "unknown": ["sodium"]}),
]

MODE_CASES_2 = [
    case("known-mass-branded-never-asks", "modes", "Quest Bar", "60g",
         brand="Quest",
         candidates=[c("off", BRANDED, "Quest Bar", brand="Quest",
                       calories=333, protein=35)],
         expect={"asks": {"quick": False, "moderate": False, "strict": False}}),

    case("small-piece-estimate-does-not-ask", "modes", "cracker",
         "5 crackers",
         candidates=[c("usda", GENERIC, "Crackers, saltine", calories=421,
                       protein=9)],
         expect={"asks": {"quick": False, "moderate": False, "strict": False}}),

    case("big-unweighable-meal-asks-everywhere", "modes",
         "catering tray of pasta", "1 tray",
         candidates=[c("provisional", PROVISIONAL, "catering tray of pasta",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=2400, protein=80)],
         expect={"asks": {"quick": True, "moderate": True, "strict": True}}),

    case("three-pizza-slices-ask-in-every-mode", "modes", "pizza slice",
         "3 slices",
         candidates=[c("usda", GENERIC, "Pizza, cheese", calories=266,
                       protein=11)],
         # ~560 calories ride on how big those slices were. That clears even
         # quick mode's threshold, and should.
         expect={"asks": {"quick": True, "moderate": True, "strict": True}}),
]

ALL_CASES = (ALL_CASES + BRANDED_CASES_2 + GENERIC_CASES_2 + PIECE_CASES_2
             + COMPOSITE_CASES_2 + MICRO_CASES_2 + MODE_CASES_2)


# ══ tranche 3: adversarial near-neighbours and identity depth ════════════════
# The first two tranches pinned the failure classes and the everyday surface.
# This one goes after the cases that LOOK resolved and are not: the same brand
# with two lines, the same line in two sizes, the flavour that moves sugar, and
# the product whose nearest neighbour differs by more than the tolerance.
#
# Every case here carries an explicit `identity`, because top-1 accuracy is only
# a real number when the expected answer is stated.

BRANDED_CASES_3 = [
    # ── same brand, different line ───────────────────────────────────────────
    case("fairlife-core-power-not-elite", "branded",
         "Fairlife Core Power", "414ml", brand="Fairlife",
         variant="core power",
         candidates=[
             c("off", BRANDED, "Fairlife Core Power Elite", brand="Fairlife",
               variant="elite", basis="per_100ml", calories=56, protein=10.1),
             c("off", BRANDED, "Fairlife Core Power", brand="Fairlife",
               variant="core power", basis="per_100ml", calories=41,
               protein=6.3)],
         expect={"source": "off", "identity": "Fairlife Core Power",
                 "calories": (168, 172), "rejects": ["off"]}),

    case("fairlife-elite-not-core-power", "branded",
         "Fairlife Core Power Elite", "414ml", brand="Fairlife",
         variant="elite",
         candidates=[
             c("off", BRANDED, "Fairlife Core Power", brand="Fairlife",
               variant="core power", basis="per_100ml", calories=41,
               protein=6.3),
             c("off", BRANDED, "Fairlife Core Power Elite", brand="Fairlife",
               variant="elite", basis="per_100ml", calories=56,
               protein=10.1)],
         expect={"source": "off", "identity": "Fairlife Core Power Elite",
                 "calories": (230, 234)}),

    case("chobani-zero-not-complete", "branded",
         "Chobani Zero Sugar Vanilla", "150g", brand="Chobani",
         variant="zero sugar",
         candidates=[
             c("off", BRANDED, "Chobani Complete Vanilla", brand="Chobani",
               variant="complete", calories=80, protein=15),
             c("off", BRANDED, "Chobani Zero Sugar Vanilla", brand="Chobani",
               variant="zero sugar", calories=40, protein=7.3, sugar=0)],
         expect={"source": "off", "identity": "Chobani Zero Sugar Vanilla",
                 "calories": (59, 61), "known": ["sugar"]}),

    case("quest-bar-not-quest-chips", "branded",
         "Quest Bar Cookies and Cream", "60g", brand="Quest",
         variant="bar",
         candidates=[
             c("off", BRANDED, "Quest Tortilla Chips", brand="Quest",
               variant="chips", calories=500, protein=32),
             c("off", BRANDED, "Quest Bar Cookies and Cream", brand="Quest",
               variant="bar", calories=333, protein=35, fiber=23)],
         expect={"source": "off", "identity": "Quest Bar Cookies and Cream",
                 "calories": (198, 202)}),

    case("premier-protein-shake-not-bar", "branded",
         "Premier Protein Shake Chocolate", "325ml", brand="Premier Protein",
         variant="shake",
         candidates=[
             c("off", BRANDED, "Premier Protein Bar", brand="Premier Protein",
               variant="bar", calories=350, protein=30),
             c("off", BRANDED, "Premier Protein Shake Chocolate",
               brand="Premier Protein", variant="shake", basis="per_100ml",
               calories=49, protein=9.2)],
         expect={"source": "off",
                 "identity": "Premier Protein Shake Chocolate",
                 "calories": (158, 162)}),

    # ── same line, different size ────────────────────────────────────────────
    case("starbucks-grande-not-venti", "branded",
         "Starbucks Grande Latte", "1 serving", brand="Starbucks",
         is_packaged=True, variant="grande",
         candidates=[
             c("web_label", BRANDED, "Starbucks Venti Latte",
               basis="per_serving", brand="Starbucks", variant="venti",
               calories=290, protein=19),
             c("web_label", BRANDED, "Starbucks Grande Latte",
               basis="per_serving", brand="Starbucks", variant="grande",
               calories=190, protein=13)],
         expect={"source": "web_label", "identity": "Starbucks Grande Latte",
                 "calories": (188, 192)}),

    case("halo-top-pint-not-single-serve", "branded",
         "Halo Top Chocolate pint", "473ml", brand="Halo Top",
         variant="pint",
         candidates=[
             c("off", BRANDED, "Halo Top Chocolate single serve",
               brand="Halo Top", variant="single serve", basis="per_100ml",
               calories=57, protein=4)],
         expect={"source": "unresolved", "rejects": ["off"]}),

    # ── flavour that moves the numbers ───────────────────────────────────────
    case("kind-dark-chocolate-not-peanut", "branded",
         "KIND Dark Chocolate Nuts and Sea Salt", "40g", brand="KIND",
         variant="dark chocolate",
         candidates=[
             c("off", BRANDED, "KIND Peanut Butter Dark Chocolate",
               brand="KIND", variant="peanut butter", calories=530,
               protein=17),
             c("off", BRANDED, "KIND Dark Chocolate Nuts and Sea Salt",
               brand="KIND", variant="dark chocolate", calories=500,
               protein=15, fiber=17)],
         expect={"source": "off",
                 "identity": "KIND Dark Chocolate Nuts and Sea Salt",
                 "calories": (198, 202)}),

    case("rxbar-chocolate-sea-salt-not-blueberry", "branded",
         "RXBAR Chocolate Sea Salt", "52g", brand="RXBAR",
         variant="chocolate sea salt",
         candidates=[
             c("off", BRANDED, "RXBAR Blueberry", brand="RXBAR",
               variant="blueberry", calories=385, protein=23),
             c("off", BRANDED, "RXBAR Chocolate Sea Salt", brand="RXBAR",
               variant="chocolate sea salt", calories=404, protein=23,
               fiber=10)],
         expect={"source": "off", "identity": "RXBAR Chocolate Sea Salt",
                 "calories": (208, 212)}),

    case("siggis-vanilla-not-plain", "branded",
         "Siggi's Vanilla Skyr", "150g", brand="Siggi's", variant="vanilla",
         candidates=[
             c("off", BRANDED, "Siggi's Plain Skyr", brand="Siggi's",
               variant="plain", calories=59, protein=11),
             c("off", BRANDED, "Siggi's Vanilla Skyr", brand="Siggi's",
               variant="vanilla", calories=74, protein=10.7, sugar=5.3)],
         expect={"source": "off", "identity": "Siggi's Vanilla Skyr",
                 "calories": (110, 112)}),

    # ── the saved regular and the label outrank the databases ────────────────
    case("saved-regular-beats-a-closer-off-name", "branded",
         "my protein shake", "300ml",
         candidates=[
             c("off", BRANDED, "Protein Shake Vanilla", basis="per_100ml",
               calories=60, protein=8),
             c("user_regular", REGULAR, "my protein shake", basis="per_100ml",
               calories=45, protein=10)],
         expect={"source": "user_regular", "calories": (134, 136)}),

    case("user-label-beats-a-perfect-branded-match", "branded",
         "Royo Plain Bagel", "100g", brand="Royo",
         candidates=[
             c("off", BRANDED, "Royo Plain Bagel", brand="Royo", calories=95,
               protein=9),
             c("user_label", LABEL, "Royo Plain Bagel", brand="Royo",
               calories=80, protein=8)],
         expect={"source": "user_label", "identity": "Royo Plain Bagel",
                 "calories": (79, 81)}),

    # ── near-neighbours that must NOT resolve ────────────────────────────────
    case("a-different-brand-entirely-is-unresolved", "branded",
         "Oatly Barista", "240ml", brand="Oatly",
         candidates=[
             c("off", BRANDED, "Alpro Barista Oat", brand="Alpro",
               basis="per_100ml", calories=59, protein=1)],
         expect={"source": "unresolved", "rejects": ["off"]}),

    case("a-generic-cannot-stand-in-for-a-named-brand-variant", "branded",
         "Chobani Zero Sugar Vanilla", "150g", brand="Chobani",
         variant="zero sugar",
         candidates=[
             c("usda", GENERIC, "Yogurt, Greek, vanilla",
               grade=MatchGrade.CATEGORY, calories=95, protein=8)],
         expect={"source": "usda", "grade": MatchGrade.CATEGORY,
                 "calories": (141, 144)}),

    case("barcode-wins-without-any-other-dimension", "branded",
         "that bar", "60g",
         candidates=[
             c("off", BRANDED, "Kirkland Protein Bar Chocolate Chip",
               calories=350, protein=33, fiber=15)],
         expect={"source": "off",
                 "identity": "Kirkland Protein Bar Chocolate Chip",
                 "calories": (208, 212)}),

    case("two-branded-records-of-the-same-product-agree", "branded",
         "Clif Bar Chocolate Chip", "68g", brand="Clif",
         candidates=[
             c("off", BRANDED, "Clif Bar Chocolate Chip", brand="Clif",
               calories=368, protein=13),
             c("web_label", BRANDED, "Clif Bar Chocolate Chip", brand="Clif",
               calories=371, protein=13)],
         expect={"source": "off", "identity": "Clif Bar Chocolate Chip",
                 "calories": (248, 252),
                 "asks": {"quick": False, "moderate": False,
                          "strict": False}}),

    case("fairlife-milk-not-fairlife-shake", "branded",
         "Fairlife 2% Milk", "240ml", brand="Fairlife", variant="milk",
         candidates=[
             c("off", BRANDED, "Fairlife Core Power", brand="Fairlife",
               variant="core power", basis="per_100ml", calories=41,
               protein=6.3),
             c("off", BRANDED, "Fairlife 2% Milk", brand="Fairlife",
               variant="milk", basis="per_100ml", calories=50, protein=5.4)],
         expect={"source": "off", "identity": "Fairlife 2% Milk",
                 "calories": (118, 122)}),

    case("thomas-bagel-not-english-muffin", "branded",
         "Thomas' Plain Bagel", "95g", brand="Thomas'", variant="bagel",
         candidates=[
             c("off", BRANDED, "Thomas' Original English Muffin",
               brand="Thomas'", variant="english muffin", calories=232,
               protein=8),
             c("off", BRANDED, "Thomas' Plain Bagel", brand="Thomas'",
               variant="bagel", calories=274, protein=11)],
         expect={"source": "off", "identity": "Thomas' Plain Bagel",
                 "calories": (259, 263)}),

    case("dunkin-medium-not-large", "branded",
         "Dunkin' Medium Iced Coffee", "1 serving", brand="Dunkin'",
         is_packaged=True, variant="medium",
         candidates=[
             c("web_label", BRANDED, "Dunkin' Medium Iced Coffee",
               basis="per_serving", brand="Dunkin'", variant="medium",
               calories=120, protein=2)],
         expect={"source": "web_label",
                 "identity": "Dunkin' Medium Iced Coffee",
                 "calories": (118, 122)}),

    case("mcdonalds-big-mac-not-quarter-pounder", "branded",
         "McDonald's Big Mac", "1 serving", brand="McDonald's",
         is_packaged=True, variant="big mac",
         candidates=[
             c("web_label", BRANDED, "McDonald's Quarter Pounder",
               basis="per_serving", brand="McDonald's",
               variant="quarter pounder", calories=520, protein=30),
             c("web_label", BRANDED, "McDonald's Big Mac",
               basis="per_serving", brand="McDonald's", variant="big mac",
               calories=563, protein=26)],
         expect={"source": "web_label", "identity": "McDonald's Big Mac",
                 "calories": (560, 566)}),
]

# ── serving-basis traps: the product is right, the BASIS is not ──────────────
BRANDED_CASES_4 = [
    case("per-serving-label-is-not-per-100g", "branded",
         "Kodiak Cakes mix", "50g", brand="Kodiak",
         candidates=[
             c("web_label", BRANDED, "Kodiak Cakes Buttermilk Mix",
               basis="per_serving", serving_mass_g=53, brand="Kodiak",
               calories=190, protein=14)],
         expect={"source": "web_label", "calories": (177, 182)}),

    case("per-100ml-drink-scaled-by-volume", "branded",
         "Fairlife 2% Milk", "355ml", brand="Fairlife", variant="milk",
         candidates=[
             c("off", BRANDED, "Fairlife 2% Milk", brand="Fairlife",
               variant="milk", basis="per_100ml", calories=50, protein=5.4)],
         expect={"source": "off", "calories": (176, 180),
                 "protein": (19.0, 19.3)}),

    case("a-serving-basis-with-no-mass-cannot-be-scaled-by-grams", "branded",
         "Trader Joe's cauliflower gnocchi", "150g",
         brand="Trader Joe's",
         candidates=[
             c("web_label", BRANDED, "Trader Joe's Cauliflower Gnocchi",
               basis="per_serving", brand="Trader Joe's", calories=140,
               protein=2)],
         # The user weighed it; the SOURCE is the one with no serving mass.
         # 140 calories is per serving, and a serving is an unknown number of
         # grams, so nothing can be logged for 150 g of it.
         expect={"unknown": ["calories", "protein"],
                 "warning_contains": "per-serving values need a serving mass"}),

    case("branded-with-only-macros-leaves-micros-unknown", "branded",
         "Barebells Cookies and Cream", "55g", brand="Barebells",
         candidates=[
             c("off", BRANDED, "Barebells Cookies and Cream",
               brand="Barebells", calories=364, protein=36, carbs=33,
               fat=15)],
         expect={"source": "off", "calories": (198, 202),
                 "known": ["carbs", "fat"],
                 "unknown": ["sodium", "fiber", "sugar", "potassium"]}),

    case("a-branded-record-with-impossible-energy-is-rejected", "branded",
         "mystery protein cookie", "60g", brand="Mystery",
         candidates=[
             c("off", BRANDED, "Mystery Protein Cookie", brand="Mystery",
               calories=100, protein=40, carbs=40, fat=20),
             c("usda", GENERIC, "Cookie, protein", grade=MatchGrade.CATEGORY,
               calories=430, protein=20, carbs=50, fat=16)],
         expect={"rejects": ["off"]}),

    case("zero-sodium-from-a-source-that-said-zero-is-kept", "branded",
         "Chobani Zero Sugar Vanilla", "150g", brand="Chobani",
         variant="zero sugar",
         candidates=[
             c("off", BRANDED, "Chobani Zero Sugar Vanilla", brand="Chobani",
               variant="zero sugar", calories=40, protein=7.3, sugar=0)],
         expect={"source": "off", "known": ["sugar"]}),

    case("a-close-branded-match-is-graded-close-not-exact", "branded",
         "Clif Bar Chocolate Brownie", "68g", brand="Clif",
         candidates=[
             c("off", BRANDED, "Clif Bar Chocolate Brownie", brand="Clif",
               grade=MatchGrade.CLOSE, calories=368, protein=13)],
         expect={"source": "off", "grade": MatchGrade.CLOSE,
                 "calories": (248, 252)}),

    case("provisional-loses-to-any-real-source", "branded",
         "Optimum Nutrition Gold Standard Whey", "31g",
         brand="Optimum Nutrition",
         candidates=[
             c("provisional", PROVISIONAL, "whey protein scoop",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=150,
               protein=25),
             c("off", BRANDED, "Optimum Nutrition Gold Standard Whey",
               brand="Optimum Nutrition", calories=387, protein=77)],
         expect={"source": "off", "calories": (118, 122),
                 "rejects": ["provisional"]}),

    case("an-estimate-loses-to-a-generic-exact", "branded",
         "chicken breast", "150g",
         candidates=[
             c("web_label", ESTIMATE, "grilled chicken", basis="per_serving",
               grade=MatchGrade.CATEGORY, calories=280, protein=45),
             c("usda", GENERIC, "Chicken breast, roasted", calories=165,
               protein=31)],
         expect={"source": "usda", "calories": (245, 250),
                 "rejects": ["web_label"]}),

    case("the-user-label-wins-even-when-it-disagrees-wildly", "branded",
         "my mom's protein balls", "40g",
         candidates=[
             c("usda", GENERIC, "Snack, energy ball",
               grade=MatchGrade.CATEGORY, calories=430, protein=12),
             c("user_label", LABEL, "my mom's protein balls", calories=250,
               protein=20)],
         expect={"source": "user_label", "calories": (99, 101),
                 "rejects": ["usda"]}),

    case("two-sizes-of-the-same-line-both-present-is-ambiguous", "branded",
         "Premier Protein Shake", "1 serving", brand="Premier Protein",
         is_packaged=True,
         candidates=[
             c("web_label", BRANDED, "Premier Protein Shake 11oz",
               basis="per_serving", brand="Premier Protein", calories=160,
               protein=30),
             c("web_label", BRANDED, "Premier Protein Shake 14oz",
               basis="per_serving", brand="Premier Protein", calories=210,
               protein=40)],
         expect={"asks": {"strict": True}}),

    case("nothing-at-all-is-unresolved-not-zero", "branded",
         "Zbrandi Krunch", "45g", brand="Zbrandi",
         candidates=[],
         expect={"source": "unresolved",
                 "unknown": ["calories", "protein", "carbs", "fat"]}),
]


# ══ tranche 4: ambiguity that must and must not interrupt ════════════════════
# What is under test here is the ask ladder, not the numbers. Each case states
# what every mode should do, because the failure that actually reaches users is
# a threshold that either interrogates them or waves through a coin toss.
AMBIGUITY_CASES = [
    case("a-tight-spread-never-asks-in-any-mode", "ambiguity",
         "Greek yogurt", "170g",
         candidates=[
             c("usda", GENERIC, "Yogurt, Greek, plain, nonfat", calories=59,
               protein=10.3),
             c("usda", GENERIC, "Yogurt, Greek, plain, lowfat", calories=63,
               protein=9.9)],
         expect={"asks": {"quick": False, "moderate": False,
                          "strict": False}}),

    case("a-doubled-calorie-count-asks-in-strict-only", "ambiguity",
         "granola", "60g",
         candidates=[
             c("usda", GENERIC, "Cereal, granola, homemade", calories=489,
               protein=13),
             c("usda", GENERIC, "Cereal, granola, lowfat", calories=380,
               protein=8)],
         # Calibration datum, not an aspiration: a 109-calorie doubt on a
         # 293-calorie item is 37%, under the 50% fraction rule, so moderate
         # stays quiet. If that is the wrong line it should move here first.
         expect={"asks": {"quick": False, "moderate": False, "strict": True}}),

    case("a-small-absolute-span-on-a-small-food-still-matters", "ambiguity",
         "rice cake", "9g",
         candidates=[
             c("usda", GENERIC, "Rice cake, plain", calories=387, protein=8),
             c("usda", GENERIC, "Rice cake, chocolate", calories=420,
               protein=6)],
         expect={"asks": {"quick": False}}),

    case("a-large-span-on-a-large-meal-is-still-worth-asking", "ambiguity",
         "burrito", "1 burrito",
         candidates=[
             c("web_label", ESTIMATE, "Burrito, chicken", basis="per_serving",
               grade=MatchGrade.CATEGORY, calories=800, protein=40),
             c("web_label", ESTIMATE, "Burrito, carnitas", basis="per_serving",
               grade=MatchGrade.CATEGORY, calories=1100, protein=45)],
         expect={"asks": {"strict": True}}),

    case("strict-asks-where-moderate-does-not", "ambiguity",
         "peanut butter", "32g",
         candidates=[
             c("usda", GENERIC, "Peanut butter, smooth", calories=588,
               protein=25, fat=50),
             c("usda", GENERIC, "Peanut butter, reduced fat", calories=520,
               protein=25, fat=34)],
         expect={"asks": {"quick": False}}),

    case("quick-never-asks-about-a-clear-leader", "ambiguity",
         "milk", "240ml",
         candidates=[
             c("usda", GENERIC, "Milk, 2%", basis="per_100ml", calories=50,
               protein=3.4),
             c("usda", GENERIC, "Milk, whole", basis="per_100ml",
               grade=MatchGrade.CATEGORY, calories=61, protein=3.2)],
         expect={"asks": {"quick": False}}),

    case("protein-spread-alone-is-not-yet-material", "ambiguity",
         "whey protein", "31g",
         candidates=[
             c("off", BRANDED, "Whey protein isolate", calories=380,
               protein=80, carbs=6, fat=4),
             c("off", BRANDED, "Whey protein blend", calories=390, protein=60,
               carbs=25, fat=6)],
         # A 20 g/100 g protein gap is 6 g on this scoop and the calorie spans
         # barely differ, so nothing asks. The gap the ladder cannot see: it
         # ranks on calories, and protein is why people buy the isolate.
         expect={"source": "off",
                 "asks": {"quick": False, "moderate": False}}),

    case("a-single-candidate-is-never-ambiguous", "ambiguity",
         "cottage cheese", "226g",
         candidates=[c("usda", GENERIC, "Cheese, cottage, lowfat",
                       calories=81, protein=11)],
         expect={"asks": {"quick": False, "moderate": False,
                          "strict": False}}),

    case("identical-numbers-from-two-sources-are-not-a-choice", "ambiguity",
         "banana", "118g",
         candidates=[
             c("usda", GENERIC, "Banana, raw", calories=89, protein=1.1),
             c("off", GENERIC, "Banana", calories=89, protein=1.1)],
         expect={"asks": {"moderate": False, "strict": False}}),

    case("the-user-label-ends-the-ambiguity", "ambiguity",
         "my overnight oats", "300g",
         candidates=[
             c("usda", GENERIC, "Oats, rolled", grade=MatchGrade.CATEGORY,
               calories=389, protein=17),
             c("usda", GENERIC, "Oatmeal, cooked", grade=MatchGrade.CATEGORY,
               calories=71, protein=2.5),
             c("user_label", LABEL, "my overnight oats", calories=120,
               protein=8)],
         expect={"source": "user_label",
                 "asks": {"moderate": False, "strict": False}}),

    case("a-saved-regular-ends-the-ambiguity-too", "ambiguity",
         "my usual smoothie", "400ml",
         candidates=[
             c("usda", GENERIC, "Smoothie, fruit", basis="per_100ml",
               grade=MatchGrade.CATEGORY, calories=54, protein=1),
             c("user_regular", REGULAR, "my usual smoothie",
               basis="per_100ml", calories=70, protein=6)],
         expect={"source": "user_regular",
                 "asks": {"moderate": False, "strict": False}}),

    case("preparation-changes-everything-and-strict-asks", "ambiguity",
         "chicken thigh", "150g",
         candidates=[
             c("usda", GENERIC, "Chicken thigh, roasted, skinless",
               calories=179, protein=25, fat=8),
             c("usda", GENERIC, "Chicken thigh, fried, with skin",
               calories=280, protein=22, fat=20)],
         expect={"asks": {"quick": False, "strict": True}}),

    case("raw-vs-cooked-is-a-material-identity-choice", "ambiguity",
         "pasta", "100g",
         candidates=[
             c("usda", GENERIC, "Pasta, dry", calories=371, protein=13),
             c("usda", GENERIC, "Pasta, cooked", calories=131, protein=5)],
         expect={"asks": {"moderate": True, "strict": True}}),

    case("mode-does-not-change-the-number-only-the-friction", "ambiguity",
         "granola", "60g",
         candidates=[
             c("usda", GENERIC, "Cereal, granola, homemade", calories=489,
               protein=13),
             c("usda", GENERIC, "Cereal, granola, lowfat", calories=380,
               protein=8)],
         expect={"source": "usda"}),
]


# ══ tranche 5: package size vs consumed amount ═══════════════════════════════
# The distinction the old path could not represent: how big the thing was and
# how much of it was eaten are two different unknowns, and answering one does
# not answer the other.
PORTION_CASES = [
    # A bag is 28 g or 300 g depending on the bag. There is no honest middle,
    # so the package size stays unknown, nothing is logged, and every mode has
    # something worth asking about. Inventing a mass here is the exact failure
    # the package-size/consumed-amount split exists to prevent.
    case("half-a-bag-of-chips-has-an-unknown-package-size", "portioning",
         "tortilla chips", "half a bag",
         candidates=[c("off", BRANDED, "Tortilla chips", calories=500,
                       protein=7, fat=25)],
         expect={"unknown": ["calories", "protein", "fat"],
                 "warning_contains": "portion not scaled",
                 "asks": {"moderate": True, "strict": True}}),

    case("a-whole-bag-is-no-more-known-than-half-of-one", "portioning",
         "tortilla chips", "1 bag",
         candidates=[c("off", BRANDED, "Tortilla chips", calories=500,
                       protein=7)],
         expect={"unknown": ["calories", "protein"],
                 "asks": {"moderate": True, "strict": True}}),

    case("two-thirds-of-a-container-of-unknown-size", "portioning",
         "Greek yogurt", "two thirds of the tub",
         candidates=[c("usda", GENERIC, "Yogurt, Greek, plain, nonfat",
                       calories=59, protein=10.3)],
         expect={"unknown": ["calories", "protein"],
                 "asks": {"moderate": True, "strict": True}}),

    case("a-stated-mass-needs-no-portion-assumption", "portioning",
         "Greek yogurt", "170g",
         candidates=[c("usda", GENERIC, "Yogurt, Greek, plain, nonfat",
                       calories=59, protein=10.3)],
         expect={"source": "usda", "calories": (99, 102),
                 "asks": {"quick": False, "moderate": False}}),

    case("a-handful-is-a-range-not-a-number", "portioning",
         "almonds", "a handful",
         candidates=[c("usda", GENERIC, "Nuts, almonds", calories=579,
                       protein=21, fat=50)],
         expect={"assumption_contains": "estimated"}),

    case("some-blueberries-is-disclosed-not-silent", "portioning",
         "blueberries", "some blueberries",
         candidates=[c("usda", GENERIC, "Blueberries, raw", calories=57,
                       protein=0.7)],
         expect={"assumption_contains": "estimated"}),

    case("a-bowl-of-rice-uses-the-cooked-form-distribution", "portioning",
         "white rice", "a bowl",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=130,
                       protein=2.7)],
         expect={"assumption_contains": "estimated"}),

    case("a-glass-of-juice-is-a-volume-not-a-mass", "portioning",
         "orange juice", "a glass",
         candidates=[c("usda", GENERIC, "Orange juice, raw",
                       basis="per_100ml", calories=45, protein=0.7)],
         # The glass gives a volume, and a per-100ml source needs exactly
         # that. No density is claimed for juice, so no mass is asserted — and
         # the glass's own size is disclosed as the assumption it is.
         expect={"source": "usda", "calories": (111, 114),
                 "assumption_contains": "glass estimated at 250ml"}),

    case("a-scoop-of-protein-powder", "portioning",
         "whey protein", "1 scoop",
         candidates=[c("off", BRANDED, "Whey protein isolate", calories=380,
                       protein=87)],
         expect={"assumption_contains": "estimated"}),

    case("a-tablespoon-of-olive-oil", "portioning",
         "olive oil", "1 tbsp",
         candidates=[c("usda", GENERIC, "Oil, olive", calories=884, fat=100)],
         expect={"source": "usda", "calories": (115, 125),
                 "assumption_contains": "density"}),

    # The case that found the worst bug in the set: a per-100g source and a
    # volume portion used to leave the per-100g row unscaled, so a teaspoon of
    # sugar was logged as 387 calories.
    case("a-teaspoon-of-sugar-is-not-a-hundred-grams-of-it", "portioning",
         "sugar", "1 tsp",
         candidates=[c("usda", GENERIC, "Sugars, granulated", calories=387,
                       carbs=100)],
         expect={"source": "usda", "calories": (14, 18),
                 "assumption_contains": "density"}),

    case("a-cup-of-cooked-pasta", "portioning",
         "cooked pasta", "1 cup",
         candidates=[c("usda", GENERIC, "Pasta, cooked", calories=131,
                       protein=5)],
         expect={"source": "usda", "calories": (178, 190),
                 "assumption_contains": "density"}),

    case("a-cup-of-a-solid-the-density-table-does-not-know", "portioning",
         "broccoli florets", "1 cup",
         candidates=[c("usda", GENERIC, "Broccoli, raw", calories=34,
                       protein=2.8, fiber=2.6)],
         # No density for broccoli, so the ontology's cup row answers — and
         # says how broad it is being. 120 g ± 90 is honest about a cup of
         # florets; 236 g (water) would not be.
         expect={"source": "usda",
                 "assumption_contains": "ontology:fallback:default_cup"}),

    case("a-plate-is-not-a-unit-and-must-be-disclosed", "portioning",
         "roast lamb", "a plate",
         candidates=[c("usda", GENERIC, "Lamb, roasted", calories=258,
                       protein=25, fat=17)],
         expect={"assumption_contains": "estimated"}),

    case("a-piece-of-cake", "portioning",
         "chocolate cake", "a slice",
         candidates=[c("usda", GENERIC, "Cake, chocolate, with frosting",
                       calories=371, protein=4, carbs=51, fat=17)],
         expect={"assumption_contains": "estimated"}),

    case("a-few-crackers", "portioning",
         "crackers", "a few crackers",
         candidates=[c("usda", GENERIC, "Crackers, saltine", calories=418,
                       protein=9, sodium=1100)],
         expect={"assumption_contains": "estimated"}),

    case("most-of-it-is-not-all-of-it", "portioning",
         "chicken shawarma platter", "most of the platter",
         candidates=[
             c("web_label", ESTIMATE, "chicken shawarma platter",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=1100,
               protein=60)],
         expect={"assumption_contains": "estimate"}),

    case("a-couple-of-bites-is-a-small-fraction", "portioning",
         "cheesecake", "a couple of bites",
         candidates=[c("usda", GENERIC, "Cheesecake", calories=321,
                       protein=6, fat=22)],
         expect={"assumption_contains": "estimated"}),

    case("a-large-portion-modifier-moves-the-mass-up", "portioning",
         "white rice", "a large bowl",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=130,
                       protein=2.7)],
         expect={"assumption_contains": "estimated"}),

    case("a-small-portion-modifier-moves-the-mass-down", "portioning",
         "white rice", "a small bowl",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=130,
                       protein=2.7)],
         expect={"assumption_contains": "estimated"}),

    case("an-explicit-gram-weight-beats-every-descriptor", "portioning",
         "white rice", "185g",
         candidates=[c("usda", GENERIC, "Rice, white, cooked", calories=130,
                       protein=2.7)],
         expect={"source": "usda", "calories": (238, 243)}),

    case("a-vague-quantity-on-a-vague-food-is-doubly-estimated", "portioning",
         "leftovers", "some",
         candidates=[c("provisional", PROVISIONAL, "leftovers",
                       basis="per_serving", grade=MatchGrade.CATEGORY,
                       calories=450, protein=25)],
         expect={"assumption_contains": "estimate"}),

    # ── named containers ─────────────────────────────────────────────────────
    case("a-can-is-a-volume-and-a-count", "portioning",
         "cola", "1 can",
         candidates=[c("off", BRANDED, "Cola", basis="per_100ml",
                       calories=42, carbs=10.6)],
         expect={"source": "off", "calories": (147, 152),
                 "assumption_contains": "can estimated at 355ml"}),

    case("a-canned-food-with-a-per-serving-label-still-scales", "portioning",
         "tuna", "1 can",
         candidates=[c("off", BRANDED, "Tuna, canned in water",
                       basis="per_serving", calories=110, protein=25)],
         # The count survives the volume conversion on purpose: "a can" is one
         # container as well as 355 ml, and a per-serving label scales by the
         # count.
         expect={"source": "off", "calories": (108, 112)}),

    case("two-bottles-are-two-vessels", "portioning",
         "sparkling water", "2 bottles",
         candidates=[c("off", BRANDED, "Sparkling water", basis="per_100ml",
                       calories=0)],
         expect={"source": "off",
                 "assumption_contains": "bottles estimated at 500ml"}),

    case("a-mug-of-soup-gets-a-volume-and-a-mass", "portioning",
         "chicken soup", "a mug",
         candidates=[c("usda", GENERIC, "Soup, chicken noodle", calories=36,
                       protein=2.5, sodium=340)],
         # Two assumptions, both stated: the mug's volume, then the density
         # that turns it into the mass a per-100g source needs.
         expect={"source": "usda", "calories": (105, 112),
                 "assumption_contains": "density"}),

    case("a-glass-of-milk-is-not-a-mass-of-milk", "portioning",
         "milk", "a glass",
         candidates=[c("usda", GENERIC, "Milk, 2%", basis="per_100ml",
                       calories=50, protein=3.4)],
         # No density claimed for milk, and none needed: the source speaks in
         # volume and so does the glass.
         expect={"source": "usda", "calories": (123, 127),
                 "unknown": ["fiber", "sodium"]}),

    case("a-package-count-multiplies-cleanly", "portioning",
         "protein bar", "2 bars",
         candidates=[c("off", BRANDED, "Protein bar", basis="per_serving",
                       serving_mass_g=60, calories=350, protein=33)],
         expect={"source": "off"}),
]


# ══ tranche 6: restaurant and composite depth ════════════════════════════════
# Composite meals are where the honest answer is a wide one. What must not
# happen is a confident number with no disclosure, or micros invented from a
# macro-only estimate.
COMPOSITE_CASES_3 = [
    case("chipotle-bowl-is-an-estimate-and-says-so", "composite",
         "Chipotle chicken bowl", "1 bowl", brand="Chipotle",
         candidates=[
             c("web_label", ESTIMATE, "Chipotle chicken burrito bowl",
               basis="per_serving", grade=MatchGrade.CLOSE, calories=630,
               protein=45, carbs=60, fat=20)],
         expect={"source": "web_label", "calories": (625, 635),
                 "assumption_contains": "estimate"}),

    case("a-restaurant-pasta-has-no-trustworthy-sodium", "composite",
         "restaurant carbonara", "1 plate",
         candidates=[
             c("web_label", ESTIMATE, "Pasta carbonara, restaurant",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=1000,
               protein=35, carbs=90, fat=50)],
         expect={"unknown": ["sodium", "fiber"]}),

    case("a-sushi-roll-count-is-pieces-not-servings", "composite",
         "spicy tuna roll", "8 pieces",
         candidates=[
             c("usda", GENERIC, "Sushi, tuna roll", calories=160,
               protein=8, carbs=25)],
         # No piece weight for sushi and no ontology row for it either, so the
         # mass is unknown and stays unknown. The right next move is a piece
         # weight, not a guess — and the ask is how we find that out.
         expect={"assumption_contains": "portion mass unknown",
                 "unknown": ["calories", "protein"],
                 "asks": {"moderate": True, "strict": True}}),

    case("a-salad-with-dressing-is-not-a-salad-without", "composite",
         "caesar salad with dressing", "1 salad",
         candidates=[
             c("web_label", ESTIMATE, "Caesar salad, with dressing",
               basis="per_serving", grade=MatchGrade.CLOSE, calories=470,
               protein=12, fat=38),
             c("usda", GENERIC, "Salad, garden, no dressing",
               grade=MatchGrade.CATEGORY, calories=20, protein=1)],
         # Tier beats identity here: a generic exact outranks a restaurant
         # estimate even when the estimate names the dish and the generic does
         # not. The 450-calorie gap is reported, and every mode asks — which is
         # the safety net, not the answer. Worth revisiting in calibration.
         expect={"source": "usda", "rejects": ["web_label"],
                 "asks": {"quick": True, "moderate": True, "strict": True}}),

    case("a-buffet-plate-cannot-be-represented-confidently", "composite",
         "buffet plate", "1 plate",
         candidates=[
             c("provisional", PROVISIONAL, "buffet plate",
               basis="per_serving", grade=MatchGrade.NONE, calories=900,
               protein=40)],
         # Nothing survives, but what we assumed about the portion still
         # travels with the answer — an unresolved turn is the one that most
         # needs to say what it thought was eaten.
         expect={"source": "unresolved",
                 "assumption_contains": "plate estimated at"}),

    case("a-named-chain-item-beats-a-category-estimate", "composite",
         "McDonald's Big Mac", "1 serving", brand="McDonald's",
         is_packaged=True,
         candidates=[
             c("web_label", ESTIMATE, "Hamburger, fast food",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=400,
               protein=20),
             c("web_label", BRANDED, "McDonald's Big Mac",
               basis="per_serving", brand="McDonald's", calories=563,
               protein=26)],
         expect={"source": "web_label", "identity": "McDonald's Big Mac",
                 "calories": (560, 566)}),

    case("a-homemade-dish-is-provisional-not-generic", "composite",
         "my chicken curry", "1 bowl",
         candidates=[
             c("provisional", PROVISIONAL, "my chicken curry",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=520,
               protein=35, carbs=30, fat=28)],
         expect={"source": "provisional", "calories": (515, 525),
                 "assumption_contains": "estimate"}),

    case("a-composite-with-a-saved-regular-uses-it", "composite",
         "my usual chipotle bowl", "1 bowl",
         candidates=[
             c("web_label", ESTIMATE, "Chipotle chicken burrito bowl",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=630,
               protein=45),
             c("user_regular", REGULAR, "my usual chipotle bowl",
               basis="per_serving", calories=705, protein=52)],
         expect={"source": "user_regular", "calories": (700, 710),
                 "rejects": ["web_label"]}),

    case("two-composite-estimates-that-disagree-widely-ask", "composite",
         "pad thai", "1 plate",
         candidates=[
             c("web_label", ESTIMATE, "Pad thai, chicken",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=700,
               protein=30),
             c("web_label", ESTIMATE, "Pad thai, shrimp, large",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=1100,
               protein=35)],
         expect={"asks": {"strict": True}}),

    case("a-composite-never-reports-zero-fiber-it-did-not-learn", "composite",
         "chicken shawarma platter", "1 platter",
         candidates=[
             c("web_label", ESTIMATE, "chicken shawarma platter",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=1100,
               protein=60, carbs=110, fat=45)],
         expect={"unknown": ["fiber", "sugar", "cholesterol"]}),

    case("a-side-eaten-partially-is-still-an-estimate", "composite",
         "french fries", "half the fries",
         candidates=[
             c("usda", GENERIC, "Potatoes, french fried", calories=312,
               protein=3.4, fat=15)],
         expect={"assumption_contains": "estimated"}),

    case("a-breakfast-platter-macros-must-be-internally-consistent",
         "composite", "diner breakfast platter", "1 platter",
         candidates=[
             c("web_label", ESTIMATE, "Breakfast platter, diner",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=980,
               protein=40, carbs=70, fat=55)],
         expect={"source": "web_label", "calories": (975, 985)}),

    case("a-drink-with-the-meal-is-its-own-item", "composite",
         "large soda", "1 serving", is_packaged=True,
         candidates=[
             c("web_label", ESTIMATE, "Soda, cola, large",
               basis="per_serving", grade=MatchGrade.CATEGORY, calories=310,
               carbs=86)],
         expect={"source": "web_label", "calories": (305, 315),
                 "unknown": ["protein", "fat"]}),

    case("a-composite-with-nothing-behind-it-is-unresolved", "composite",
         "whatever they served at the wedding", "1 plate",
         candidates=[],
         expect={"source": "unresolved"}),
]


ALL_CASES = (ALL_CASES + BRANDED_CASES_3 + BRANDED_CASES_4 + AMBIGUITY_CASES
             + PORTION_CASES + COMPOSITE_CASES_3)
