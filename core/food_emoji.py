"""
Food → emoji pairing for daily-log line items.

Pure, deterministic mapping from a food name to ONE emoji drawn from a curated
palette (no LLM, no I/O) — safe to call on the read path while rendering a whole
day's list. Used by api.native_data.day_data to stamp every food_entry, so the
same icon renders identically in the food-log card and the Today timeline.

Design:
  - First-match-wins over an ORDERED rule list. Order matters: specific compounds
    that contain a more-generic word as a substring ("sweet potato" → 🍠 contains
    "potato", "pineapple" → 🍍 contains "apple") sit in the TRAPS tier up top so
    they win before the generic rule fires.
  - Matching is token-aware to avoid false hits from short words. A keyword
    matches when:
      • it's a phrase (has a space)  → substring of the normalized name
      • it's >= 5 chars              → substring of the normalized name
      • it's < 5 chars               → matches a whole word (stem-aware: peas→pea)
    so "pea" never fires on "peach" / "peanut", but "banana" still fires on
    "bananas".
  - Unknown foods fall back to DEFAULT (🍽️). Nothing ever renders off-palette.

This is intentionally a flat keyword map, not an ontology — it's meant to be
skimmed and hand-tuned. Add a food by dropping a keyword onto the right rule.
"""
import re

DEFAULT = "🍽️"


# ── Ordered rules: (emoji, (keyword, ...)) — FIRST match wins ────────────────────
# Keep substring-trap compounds ABOVE their generic word. Within a tier, order is
# cosmetic. The palette is the full set of emojis that can ever be returned.
_RULES: list[tuple[str, tuple[str, ...]]] = [
    # ── TRAPS — compounds that contain a generic word; must be checked first ──
    ("🍠", ("sweet potato", "sweet potatoes", "yam", "yams")),
    ("🫛", ("green bean", "green beans", "edamame", "snap pea", "snap peas",
            "snow pea", "snow peas", "sugar snap")),
    ("🍨", ("ice cream", "icecream", "frozen yogurt", "froyo", "gelato",
            "sorbet", "sherbet")),
    ("🍿", ("popcorn",)),
    ("🍍", ("pineapple",)),
    ("🍆", ("eggplant", "aubergine")),
    ("🍏", ("green apple", "granny smith")),

    # ── COMPOSITE DISHES — beat single proteins/veg ("chicken salad" → 🥗) ──
    ("🍕", ("pizza",)),
    ("🍔", ("burger", "cheeseburger", "hamburger", "smashburger")),
    ("🌭", ("hot dog", "hotdog", "corndog", "sausage", "bratwurst", "brat",
            "kielbasa")),
    ("🌮", ("taco", "tacos")),
    ("🌯", ("burrito", "wrap", "quesadilla", "chimichanga")),
    ("🥪", ("sandwich", "sub", "blt", "panini", "melt", "club")),
    ("🥙", ("gyro", "shawarma", "pita", "kebab", "souvlaki", "doner")),
    ("🧆", ("falafel",)),
    ("🍣", ("sushi", "sashimi", "nigiri", "maki")),
    ("🍱", ("bento", "poke bowl")),
    ("🥟", ("dumpling", "dumplings", "gyoza", "potsticker", "wonton",
            "empanada", "pierogi")),
    ("🍛", ("curry", "tikka masala", "korma", "vindaloo")),
    ("🍜", ("ramen", "pho", "udon", "noodle soup")),
    ("🍲", ("soup", "stew", "chili", "hotpot", "chowder", "bisque", "gumbo")),
    ("🥗", ("salad", "coleslaw", "slaw")),
    ("🍝", ("pasta", "spaghetti", "lasagna", "lasagne", "penne", "macaroni",
            "mac and cheese", "fettuccine", "linguine", "noodles", "gnocchi")),
    ("🍟", ("fries", "french fries", "tater tots")),
    ("🥡", ("takeout", "leftovers")),

    # ── BREAKFAST / GRAINS / STARCHES ──
    ("🥞", ("pancake", "pancakes", "hotcake", "flapjack")),
    ("🧇", ("waffle", "waffles")),
    ("🥯", ("bagel", "bagels")),
    ("🥐", ("croissant", "danish")),
    ("🥖", ("baguette",)),
    ("🫓", ("tortilla", "naan", "flatbread", "roti")),
    ("🥨", ("pretzel", "pretzels")),
    ("🥣", ("oatmeal", "oats", "oat", "porridge", "cereal", "granola",
            "muesli", "yogurt", "yoghurt", "parfait", "grits")),
    ("🍚", ("rice", "risotto", "quinoa", "couscous", "pilaf")),
    ("🌽", ("corn", "cornbread")),
    ("🥔", ("potato", "potatoes", "mashed potato", "hash brown", "hashbrown")),
    ("🍞", ("bread", "toast", "sourdough", "loaf", "brioche")),

    # ── PROTEINS ──
    ("🍗", ("chicken", "poultry", "turkey", "wing", "wings", "drumstick",
            "nugget", "nuggets", "tender", "tenders", "rotisserie")),
    ("🥓", ("bacon", "prosciutto", "pancetta")),
    ("🥩", ("steak", "beef", "ribeye", "sirloin", "brisket", "filet", "lamb",
            "pork", "chop", "veal", "venison", "roast", "meatball",
            "meatballs", "carne")),
    ("🍖", ("ribs", "rib", "ham", "meat", "drumette")),
    ("🦐", ("shrimp", "prawn", "prawns")),
    ("🦞", ("lobster",)),
    ("🦀", ("crab",)),
    ("🦑", ("calamari", "squid")),
    ("🦪", ("oyster", "oysters", "clam", "clams", "mussel", "mussels",
            "scallop", "scallops")),
    ("🐟", ("fish", "salmon", "tuna", "cod", "tilapia", "halibut", "trout",
            "mackerel", "sardine", "bass", "snapper", "catfish", "anchovy")),
    ("🥚", ("egg", "eggs", "omelette", "omelet", "frittata", "scramble")),
    ("🫘", ("tofu", "tempeh", "bean", "beans", "lentil", "lentils", "chickpea",
            "chickpeas", "garbanzo", "hummus", "seitan")),

    # ── FRUITS — citrus BEFORE grape; watermelon BEFORE melon ──
    ("🍎", ("apple", "applesauce")),
    ("🍌", ("banana", "plantain")),
    ("🫐", ("blueberry", "blueberries")),
    ("🍓", ("strawberry", "strawberries", "raspberry", "raspberries",
            "blackberry", "blackberries", "berry", "berries")),
    ("🍊", ("orange", "grapefruit", "tangerine", "clementine", "mandarin",
            "satsuma")),
    ("🍋", ("lemon", "lime")),
    ("🍇", ("grape", "grapes")),
    ("🍉", ("watermelon",)),
    ("🍈", ("melon", "cantaloupe", "honeydew")),
    ("🍑", ("peach", "nectarine", "apricot")),
    ("🍐", ("pear",)),
    ("🍒", ("cherry", "cherries")),
    ("🥭", ("mango",)),
    ("🥝", ("kiwi",)),
    ("🥥", ("coconut",)),
    ("🫒", ("olive", "olives")),
    ("🍅", ("tomato", "tomatoes")),
    ("🥑", ("avocado", "guacamole", "guac")),

    # ── VEGETABLES ──
    ("🥦", ("broccoli", "cauliflower")),
    ("🥬", ("lettuce", "spinach", "kale", "cabbage", "arugula", "chard",
            "bok choy", "romaine", "collard", "greens")),
    ("🥒", ("cucumber", "pickle", "pickles", "zucchini", "gherkin")),
    ("🌶️", ("jalapeno", "jalapeño", "cayenne", "hot pepper", "chili pepper",
            "sriracha", "habanero", "serrano")),
    ("🫑", ("pepper", "peppers", "bell pepper", "capsicum")),
    ("🥕", ("carrot", "carrots")),
    ("🧅", ("onion", "onions", "shallot", "leek", "scallion")),
    ("🧄", ("garlic",)),
    ("🍄", ("mushroom", "mushrooms", "shiitake", "portobello")),
    ("🫛", ("peas", "pea")),

    # ── NUTS / SEEDS / SPREADS ──
    ("🥜", ("peanut", "peanuts", "almond", "almonds", "cashew", "cashews",
            "walnut", "walnuts", "pecan", "pecans", "pistachio", "hazelnut",
            "nut butter", "peanut butter", "almond butter", "trail mix",
            "nuts")),
    ("🍯", ("honey", "syrup", "maple", "agave", "molasses")),

    # ── DAIRY ──
    ("🧀", ("cheese", "cheddar", "mozzarella", "parmesan", "feta", "brie",
            "gouda", "swiss", "cottage cheese", "ricotta", "paneer")),
    ("🧈", ("butter", "ghee", "margarine")),
    ("🥛", ("milk", "kefir", "protein shake", "whey", "casein",
            "protein powder")),

    # ── SWEETS / DESSERTS ──
    ("🍫", ("chocolate", "cocoa", "brownie", "fudge", "nutella", "protein bar",
            "granola bar")),
    ("🍪", ("cookie", "cookies", "biscuit")),
    ("🍩", ("donut", "doughnut", "donuts")),
    ("🧁", ("cupcake", "muffin", "muffins")),
    ("🍰", ("cake", "cheesecake", "shortcake")),
    ("🥧", ("pie", "tart", "cobbler")),
    ("🍮", ("pudding", "custard", "flan", "creme brulee")),
    ("🍬", ("candy", "caramel", "toffee", "gummy", "gummies")),
    ("🍭", ("lollipop", "sucker")),

    # ── DRINKS ──
    ("☕", ("coffee", "latte", "espresso", "cappuccino", "mocha", "americano",
            "macchiato", "cortado", "flat white", "frappuccino")),
    ("🍵", ("tea", "matcha", "chai")),
    ("🧋", ("boba", "bubble tea", "milk tea")),
    ("🧃", ("juice",)),
    ("🥤", ("soda", "cola", "pop", "soft drink", "smoothie", "milkshake",
            "slushie", "energy drink", "gatorade", "powerade")),
    ("🍺", ("beer", "ale", "lager", "ipa", "stout", "cider")),
    ("🍷", ("wine", "merlot", "cabernet", "chardonnay", "rose", "prosecco",
            "champagne")),
    ("🍸", ("cocktail", "martini", "mojito")),
    ("🍹", ("margarita", "daiquiri", "pina colada", "sangria")),
    ("🥃", ("whiskey", "whisky", "bourbon", "scotch", "vodka", "gin", "rum",
            "tequila", "liquor", "brandy")),
    ("🍶", ("sake",)),
    ("💧", ("water", "seltzer", "sparkling water")),

    # ── CONDIMENTS / MISC ──
    ("🥫", ("sauce", "ketchup", "gravy", "salsa", "marinara", "canned")),
    ("🧂", ("salt", "seasoning", "spice")),

    # ── SUPPLEMENTS ──
    ("💊", ("supplement", "vitamin", "creatine", "multivitamin", "pill",
            "capsule", "omega", "fish oil", "magnesium", "zinc")),
]


def _norm(name: str) -> str:
    """lowercase, strip punctuation (keep spaces), collapse whitespace."""
    n = (name or "").lower().strip()
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _stem(tok: str) -> str:
    """Crude singular stem so short plural tokens match short singular keywords."""
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith("es") and len(tok) > 3:
        return tok[:-2]
    if tok.endswith("s") and len(tok) > 2:
        return tok[:-1]
    return tok


def food_emoji(name: str) -> str:
    """Return one palette emoji for a food name, or DEFAULT (🍽️) if unmatched."""
    norm = _norm(name)
    if not norm:
        return DEFAULT
    tokens = norm.split()
    stems = {_stem(t) for t in tokens}
    for emoji, keys in _RULES:
        for k in keys:
            if " " in k or len(k) >= 5:
                if k in norm:                       # phrase / long → substring
                    return emoji
            elif k in tokens or _stem(k) in stems:  # short → whole-word, stem-aware
                return emoji
    return DEFAULT


if __name__ == "__main__":
    # Eyeball test — screenshot foods first, then a spread of traps & categories.
    samples = [
        # from the screenshot
        "Green Leaf Lettuce", "Kiwi Fruit", "Green Beans Boiled With Salt",
        "Green Bell Peppers, Raw", "Cabbage, Green, Raw", "Green Apple",
        "Green Grape", "Green Peas", "Green Onion",
        # trap-y compounds
        "sweet potato fries", "pineapple", "ice cream", "peanut butter toast",
        "grapefruit", "eggplant parmesan", "watermelon", "popcorn",
        # everyday logs
        "grilled chicken breast", "ribeye steak", "2 scrambled eggs",
        "greek yogurt", "oatmeal with blueberries", "white rice", "salmon fillet",
        "chicken caesar salad", "beef stew", "protein shake", "iced latte",
        "cheddar cheese", "almonds", "dark chocolate", "ipa beer",
        "quest protein bar", "avocado", "broccoli", "banana",
        # should fall through to default
        "mystery casserole surprise", "그것",
    ]
    for s in samples:
        print(f"{food_emoji(s)}  {s}")
