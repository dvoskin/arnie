TRIGGERS = ["show my progress", "how much have I lost", "how much have I gained", "am I making progress", "my progress"]

PROMPT = """\
Pull from [WEIGHT PROGRESS] and [WEEKLY BREAKDOWN] in context. Use real numbers only.

Cover: starting weight and current weight, total change, time span, weekly rate, how that rate compares to what's healthy for their goal (healthy cut = 0.3-0.7kg/wk, healthy bulk = 0.2-0.4kg/wk), and how far they are from their goal weight.

Be honest about whether the trend is on track. If the rate is too fast or too slow, say so and explain what to adjust: calories, protein, training frequency.

If there are fewer than 2 weight entries, say so plainly and tell them why consistent weigh-ins matter.\
"""
