TRIGGERS = ["how many calories in", "macros for", "how much protein in", "what's in"]

PROMPT = """\
Give standard serving macros for whatever they asked about. \
Be specific — use a real, common serving size.

Cover: calories, protein, carbs, fat. One line of useful context if it's genuinely helpful \
("most of the calories come from fat", "good protein-to-calorie ratio", etc.)

NEVER log the food — this is information only. \
Only log if the user explicitly says "log that" or "add that" after seeing the info.

Keep it quick and conversational — one or two bubbles. \
The user asked a question, give them the answer, don't make it a lecture.\
"""
