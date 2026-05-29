TRIGGERS = ["how was my week", "weekly recap", "week review", "how did I do this week"]

PROMPT = """\
Pull last 7 days from [WEEKLY BREAKDOWN] + [RECENT HISTORY]. Format:
  Week — [Mon DD] to [Sun DD]
  Calories   avg X / target   (N/logged days on target)
  Protein    avg Xg / target
  Workouts   X / 7 days
  [1 honest coaching line with real numbers]
  [1 next-week focus]
Max 10 lines. No preamble. Bold key numbers.\
"""
