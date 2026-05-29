TRIGGERS = ["I'm at", "eating at", "what should I order at", "ordering from"]

PROMPT = """\
List 3-5 best options for that restaurant ranked by goal fit.
Reference remaining cal/protein from [TODAY]. Show ~macros per item.
Format: "[Restaurant] — [X] cal · [Y]g P remaining\n• Item (~cal, Pg P, Cg C, Fg F)\n...\n[1 ordering tip]"
Max 8 lines. All macros are approximations (~).\
"""
