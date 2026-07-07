"""Weight-misroute guardrail — pins the prompt + tool-description rules that
stop log_body_weight firing on a FOOD message.

Bug (2026-07-08, prod user 26): "I got a chicken and farro soup it's like sub
200 cal and I ate like 4-5oz grilled chicken with 1oz vinaigrette" fired
log_body_weight ONLY (no log_food), re-logged the user's KNOWN 188.9 from
context (the message contains no body-weight number), replied "Weigh-in
logged", and the food went unlogged. Cause: an evening of weight-talk primed
the context; the old rule required "an explicit numeric body weight" but never
forbade RE-LOGGING a weight from context when the message has none.

These pin the fix in both places the model reads:
  • the routing rule in the system prompt (core/prompts/arnie.py), and
  • the log_body_weight tool description (core/tools.py).
"""
from core.prompts import build_arnie_system
from core.tools import ALL_TOOLS

SYSTEM_PROMPT = " ".join(build_arnie_system(platform="ios").split())


def _weight_tool_desc() -> str:
    for t in ALL_TOOLS:
        if t["name"] == "log_body_weight":
            return " ".join(t["description"].split())
    raise AssertionError("log_body_weight tool not found")


def test_prompt_requires_weight_number_in_current_message():
    s = SYSTEM_PROMPT
    assert "ONLY for an explicit BODY-WEIGHT number the user states in THIS message" in s
    assert "never without a number IN THIS MESSAGE" in s


def test_prompt_forbids_relogging_weight_from_context():
    s = SYSTEM_PROMPT
    assert "NEVER re-log a body weight pulled from context, memory, or an earlier turn" in s
    assert "do NOT call log_body_weight at all" in s


def test_prompt_routes_food_numbers_to_food():
    """A number attached to cal/oz/grams is food, even after weight-talk."""
    s = SYSTEM_PROMPT
    assert '"sub 200 cal"' in s
    assert '"4-5oz chicken"' in s
    assert "even if weight was discussed earlier in the chat" in s


def test_tool_description_requires_current_message_number():
    d = _weight_tool_desc()
    assert "MUST appear in the CURRENT user message" in d
    assert "NEVER re-log a weight pulled from context, memory, or an earlier turn" in d


def test_tool_description_names_food_number_examples():
    d = _weight_tool_desc()
    assert "'sub 200 cal', '4-5oz chicken' are FOOD, not body weight" in d
