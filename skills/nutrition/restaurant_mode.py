TRIGGERS = ["I'm at", "eating at", "what should I order at", "ordering from"]

PROMPT = """\
Check [TODAY] for remaining calories and protein before giving recommendations. \
That context shapes what makes sense — don't ignore it.

Give 3-5 real options from that restaurant that fit their remaining budget and goal. \
Be specific about what to order, not just the category. \
Include approximate macros inline, not in a table.

One practical ordering tip — something actually useful like "get the sauce on the side" \
or "the bowl is 200 cal less than the burrito" — not generic advice.

Respond conversationally: state where they stand for the day, then the options, \
then the tip. Two to three bubbles. Keep macros approximate and inline.\
"""
