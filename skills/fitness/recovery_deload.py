TRIGGERS = ["should I deload", "feeling beat up", "lifts are dropping", "overtrained", "WHOOP is red", "rest day", "active recovery", "burnt out"]

PROMPT = """\
Check [COACHING STATE] and [EXERCISE HISTORY] first.
Deload if 3+ signals: performance down, soreness 72h+, poor sleep, low motivation, red recovery 5+ days, 5+ consecutive training days.
Deload options: Volume (cut sets 40-50%, keep weight) / Intensity (cut weight 50-60%, keep volume) / Full rest (burnout only).
Active recovery: 20-30 min walk, yin yoga, easy swim — NOT sitting on the couch.
Format: "Recovery check\nSignals: [list from context]\nVerdict: [action]\n[Protocol]\n[1 nutrition note]"
If [COACHING STATE] shows "recovery" readiness, always recommend deload regardless of other signals.\
"""
