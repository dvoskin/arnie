# DEACTIVATED during foundation-stabilization pass (kept on disk for later).
# Re-enable by removing this flag once the retrieval-gated skill layer exists.
ENABLED = False

TRIGGERS = ["aggressive cut today", "hard deficit today", "cut day protocol", "want to cut hard"]

PROMPT = """\
When a user on a cut asks for a plan or is running very low on calories, help them maximise fat loss while protecting muscle.

Priority order: hit protein target first (minimum 0.8g x bodyweight in lbs), fill remaining calories with volume foods (lean protein, vegetables), minimise fats and liquid calories.

Pull remaining calories and protein from [TODAY]: build the advice around what's actually left, not a generic template.

Flag it in one line if the deficit is dangerously aggressive (>1000 cal below TDEE) and note the muscle-loss risk.

Tell them exactly what to eat for the rest of the day given their remaining budget.\
"""
