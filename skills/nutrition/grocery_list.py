TRIGGERS = ["what should I buy", "grocery list", "meal prep ideas", "what should I stock up on", "going to the store"]

PROMPT = """\
Build a practical grocery list based on what you know about the user: their calorie and protein targets, dietary preferences, and recent food patterns.

Check [FOOD HISTORY] and [WEEKLY BREAKDOWN]: if they've been low on protein all week, load the list with protein staples. If they tend to over-eat certain things, leave those off without making a thing of it.

Focus on high-protein whole foods first: chicken breast, eggs, Greek yogurt, cottage cheese, lean beef, fish, tofu if relevant. Then flexible carbs and fats.

Keep it to 10-15 items. Cover why these items, the list itself, and one practical tip (meal prep, what to buy in bulk).\
"""
