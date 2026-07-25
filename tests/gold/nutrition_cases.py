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
