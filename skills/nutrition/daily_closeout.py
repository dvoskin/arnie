TRIGGERS = ["close the day", "that's it for today", "day done", "wrap it up", "closing out"]

PROMPT = """\
When the user closes their day, give them a brief coaching read: a verdict, not a recap.

Pull today's totals from context. Compare against targets.

Cover: how calories and protein landed vs target, whether a workout happened, and the one most important coaching observation. One concrete focus for tomorrow.

A good day gets acknowledged with real numbers. A rough day gets one direct note.\
"""
