TRIGGERS = ["what should I eat", "what can I have", "suggest a meal", "I'm hungry", "meal ideas"]

PROMPT = """\
Pull remaining cal/protein from [TODAY]. Suggest 3 real, concrete meals with ~macros.
Lead with high-protein options if >25g behind protein target.
Format: "[X] cal · [Y]g protein left\n• Option 1 (~cal, Pg P)\n• Option 2\n• Option 3"
No clarifying questions. Never suggest foods that violate dietary preferences.\
"""
