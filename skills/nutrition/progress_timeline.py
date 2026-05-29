TRIGGERS = ["show my progress", "how much have I lost", "how much have I gained", "am I making progress", "my progress"]

PROMPT = """\
Pull from [WEIGHT PROGRESS] and [WEEKLY BREAKDOWN]. Format:
  Progress — [start date] to today
  Weight    [start] to [current] kg  ([+/- X]kg · N weeks · rate/wk)
  Goal      [X]kg  ([Y]kg to go)
  Avg cal   X / target
  Avg pro   Xg / targetg
  Workouts  X/week (last 4 weeks)
  [2 sentence coaching read: is the trend on track? biggest lever?]
If < 2 weight entries: say so, encourage 3x weekly weigh-ins.\
"""
