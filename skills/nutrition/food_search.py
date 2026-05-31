TRIGGERS = ["how many calories in", "macros for", "how much protein in", "what's in"]

PROMPT = """\
Give standard serving macros for whatever they asked about. Be specific: use a real, common serving size.

Cover: calories, protein, carbs, fat. Add one line of useful context only if it's genuinely helpful (e.g. where the calories come from, protein-to-calorie ratio).

NEVER log the food here, this is information only. Only log if the user explicitly says "log that" or "add that" after seeing the info.\
"""
