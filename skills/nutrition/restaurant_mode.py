# DEACTIVATED during foundation-stabilization pass (kept on disk for later).
# Re-enable by removing this flag once the retrieval-gated skill layer exists.
ENABLED = False

TRIGGERS = ["I'm at", "eating at", "what should I order at", "ordering from"]

PROMPT = """\
Check [TODAY] for remaining calories and protein before giving recommendations. That context shapes what makes sense, don't ignore it.

Give 3-5 real options from that restaurant that fit their remaining budget and goal. Be specific about what to order, not just the category. Include approximate macros inline.

One practical ordering tip, specific and actually useful, not generic.\
"""
