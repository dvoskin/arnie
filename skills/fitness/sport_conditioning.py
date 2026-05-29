TRIGGERS = ["I play", "agility work", "speed training", "plyometrics", "boxing training", "BJJ", "in-season", "off-season", "sport-specific"]

PROMPT = """\
Identify the sport and season (off/pre/in/post). Use [PROFILE] sport field if set. Tailor to sport demands.
Power sports (basketball, sprinting, combat): short max-effort intervals, plyometrics, explosive lifts.
Endurance sports: zone 2 base + lactate threshold. Team sports: repeated sprint ability + agility.
Agility drills: T-drill, 5-10-5 shuttle, ladder in/out, box drill.
Plyos: squat jump → box jump → depth jump → single-leg bounds.
In-season: reduce volume 30-40%, maintain intensity 1-2x/week. Off-season: build base, address weaknesses.
Cross-reference [COACHING STATE] — don't prescribe hard conditioning on recovery days.\
"""
