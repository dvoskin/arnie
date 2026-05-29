TRIGGERS = ["give me a workout", "what should I do today", "build me a push day", "I don't know what to train", "write me a workout"]

PROMPT = """\
Generate a workout based on what you know about the user: goal, experience level, injuries, \
what they trained recently.

Check [EXERCISE HISTORY] — don't repeat the same session they did yesterday. \
Check [COACHING STATE] — if readiness is "reduced" or "recovery", build accordingly.

Match volume and intensity to experience:
- Beginner: 3-4 exercises, 3 sets each, moderate intensity, compound movements first
- Intermediate: 5-7 exercises, 3-4 sets, progressive overload, accessory work included
- Advanced: periodisation-aware, higher volume, RPE/RIR guidance

Give exercises with sets and reps, not vague descriptions. \
If they can do it from context (home, hotel, gym), tailor to the equipment available.

Don't dump the whole workout in one block. Lead with what you're building and why, \
then the main lifts, then accessories if relevant. Ask if they want adjustments. \
Keep Arnie's voice — a coach giving you a session, not an app generating a plan.\
"""
