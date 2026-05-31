TRIGGERS = ["how was my week", "weekly recap", "week review", "how did I do this week"]

PROMPT = """\
Pull last 7 days from [WEEKLY BREAKDOWN] and [RECENT HISTORY] in context. Use real numbers, don't estimate or hedge.

Cover: average daily calories vs target, average protein vs target, number of workout days, any standout patterns (consistently low protein, one good day surrounded by bad ones, etc.).

If the week was off, say so with the actual number. If it was solid, acknowledge it without being sycophantic.

One genuine coaching observation based on what the data actually shows. One specific focus for next week: not generic, tied to what you see. A few key numbers, a real read, a next step.\
"""
