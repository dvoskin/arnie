TRIGGERS = ["what should I eat", "what can I have", "suggest a meal", "I'm hungry", "meal ideas"]

PROMPT = """\
Pull remaining calories and protein from [TODAY] before suggesting anything. \
If the user is >25g behind on protein, lead with high-protein options.

Suggest 3 real, concrete meals — not generic ("chicken and rice") but specific \
("6oz grilled chicken breast, cup of jasmine rice, handful of broccoli, ~480 cal, 42g P"). \
Never suggest foods that violate their dietary preferences.

Don't ask clarifying questions — just give them three good options and move on. \
Deliver it conversationally: state where they're at, then the options across a couple bubbles. \
Keep approximate macros short and inline, not in a table.\
"""
