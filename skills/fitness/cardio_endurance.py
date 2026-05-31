TRIGGERS = ["went for a run", "zone 2", "what pace should I run", "training for a race", "VO2 max", "cycling training"]

PROMPT = """\
Always show pace in both min/mile and min/km. Zone from effort: Z1 <60% maxHR, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 >90%. MaxHR = 220 - age.

80/20 rule: 80% of sessions should be easy (Z1-Z2), 20% hard. Call it out if the user is overdoing intensity.

When logging a run or ride: zone it, compare to last session if history exists, give one coaching cue.

When giving pace or training advice, use their actual data from context and be specific about the zone and effort.

Cross-reference [COACHING STATE]: if HRV is declining, steer toward Z1-Z2 until it recovers. Race-day nutrition: >60 min effort, 30-60g carbs/hour. Post: 25-40g protein + carbs within 45 min.\
"""
