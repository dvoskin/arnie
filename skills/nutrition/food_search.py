TRIGGERS = ["how many calories in", "macros for", "how much protein in", "what's in"]

PROMPT = """\
Return standard serving macros in 3-4 lines. NEVER log the food — inform only.
Format: "[Food] ([serving]):\n[X] cal | [P]g P | [C]g C | [F]g F\n[optional 1-line note]"
Only log if user explicitly says "log that" or "add that" after seeing the info.\
"""
