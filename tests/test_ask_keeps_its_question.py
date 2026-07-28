"""A clarifying turn shows the user the question it asked.

Audit I-1, ranked the most severe live defect in the lane.

Since partial commit, an ask CARRIES the ready items' `log_food` calls. So on a
mixed meal `has_logging` is True, and the narration chain in
`core/conversation.py` ran on a turn whose reply had already been decided.
`"ask"` was absent from the structured-render branch, `_is_pure_food_log` was
True for a clean `log_food` batch, and the `elif _pure_food` arm replaced the
clarification with a deterministic log confirmation.

The user saw "logged" on a turn that had asked them a question. The pending was
recorded regardless, so their NEXT message was parsed as the answer to a
question they were never shown — and the item the question was about stayed
unresolved while the conversation moved on.

Note the symmetry this file and `test_ask_still_commits_what_it_cleared.py`
together pin: legacy kept the writes and lost the question; the native lane kept
the question and lost the writes. Neither did what the design says, and each
looked like the other's policy decision.
"""
import pytest

# The end-to-end harness lives in test_pipeline (in-memory DB, captured
# bubbles, stubbed transport). Imported rather than duplicated: a second copy
# of the pipeline fixture is a second thing to keep in step with the pipeline.
from tests.test_pipeline import _seed_user, pipeline_env  # noqa: F401

pytestmark = pytest.mark.asyncio

QUESTION = "Was the chicken closer to 100g or 200g?"
READY_CALL = {"name": "log_food",
              "input": {"food_name": "Barebells bar", "calories": 200,
                        "protein": 20, "carbs": 18, "fats": 8}}


def _ask_with_partial_commit():
    """What `core.food_turn.run` returns for a mixed meal: one item cleared by
    the veto, one still in question."""
    async def _run(*a, **k):
        return {"action": "ask", "text": QUESTION,
                "tool_calls": [READY_CALL],
                "points": [QUESTION],
                "response_schema": "quantity",
                "question_id": "q1", "staged_item_id": "sid-chicken",
                "requested_fields": ["consumed_fraction"], "options": [],
                "meal_group_id": "mg1"}
    return _run


async def test_the_user_is_shown_the_question_not_a_log_confirmation(
        pipeline_env, monkeypatch):
    env = pipeline_env

    await _seed_user(env["Maker"])

    import core.conversation as C
    import core.food_turn as FT

    async def _never(*a, **k):
        return "LEGACY LOG VOICE — MUST NOT SHIP"
    monkeypatch.setattr(C, "voice_log", _never)
    monkeypatch.setattr(FT, "run", _ask_with_partial_commit())
    # The gate is not what is under test; keep it out of the way.
    async def _is_food(*a, **k):
        return True
    monkeypatch.setattr(FT, "food_relevance", _is_food)
    env["set_llm"](text="", tool_calls=[], follow_up_text="MUST NOT RUN")

    await env["H"].run_imessage_pipeline(
        "+15550001111", "iMessage;-;+15550001111",
        "had a bar and some chicken", message_guid="ask-1")

    sent = "\n".join(env["sent"])
    assert QUESTION in sent, f"the question never reached the user: {env['sent']}"
    assert "MUST NOT SHIP" not in sent
    assert "MUST NOT RUN" not in sent


async def test_the_cleared_item_still_lands(pipeline_env, monkeypatch):
    """Keeping the question must not cost the partial commit.

    The failure mode this guards is the obvious over-correction: suppress the
    narration chain and suppress the writes with it, turning I-1 into A1.
    """
    env = pipeline_env

    await _seed_user(env["Maker"])

    import core.conversation as C
    import core.food_turn as FT

    async def _never(*a, **k):
        return "MUST NOT SHIP"

    async def _is_food(*a, **k):
        return True
    monkeypatch.setattr(C, "voice_log", _never)
    monkeypatch.setattr(FT, "run", _ask_with_partial_commit())
    monkeypatch.setattr(FT, "food_relevance", _is_food)
    env["set_llm"](text="", tool_calls=[], follow_up_text="MUST NOT RUN")

    await env["H"].run_imessage_pipeline(
        "+15550001111", "iMessage;-;+15550001111",
        "had a bar and some chicken", message_guid="ask-2")

    from sqlalchemy import select
    from db.models import FoodEntry
    async with env["Maker"]() as db:
        names = list((await db.execute(
            select(FoodEntry.parsed_food_name))).scalars().all())
    assert any("barebells" in (n or "").lower() for n in names), names
    # ...and only the cleared one. The held item is what the question is FOR.
    assert not any("chicken" in (n or "").lower() for n in names), names


# ── T-1b: a question the turn did not consume stays open ──────────────────────

async def test_a_fall_through_to_legacy_leaves_the_question_open(
        pipeline_env, monkeypatch):
    """Audit T-1b, straight from the production transcript.

    The user answers the brand question; the interpreter returns None (their
    reply comes back as a web_search with no log_food) and the turn falls
    through to legacy. The pending used to be closed anyway, so the NEXT turn
    arrived cold — no prior, no ask_count, no stashed items, nothing for
    `parse_prior_answer` to read.

    That is what cost three turns to log one roll: the answer was lost and the
    question with it.
    """
    env = pipeline_env
    await _seed_user(env["Maker"])

    import core.food_turn as FT
    from db.queries import get_open_pending_question, record_pending_question

    async def _is_food(*a, **k):
        return True

    async def _declines(*a, **k):
        return None                      # structured lane hands the turn back

    monkeypatch.setattr(FT, "food_relevance", _is_food)
    monkeypatch.setattr(FT, "run", _declines)
    env["set_llm"](text="looking it up", tool_calls=[], follow_up_text="ok")

    async with env["Maker"]() as db:
        from db.models import User
        from sqlalchemy import select
        uid = (await db.execute(select(User.id))).scalars().first()
        await record_pending_question(
            db, uid, kind=FT.ASK_KIND, question="Which brand?",
            tier="food_clarification", hook_style="question")
        await db.commit()

    await env["H"].run_imessage_pipeline(
        "+15550001111", "iMessage;-;+15550001111",
        "its from a brand called Legendary Foods", message_guid="t1b")

    async with env["Maker"]() as db:
        still_open = await get_open_pending_question(db, uid, FT.ASK_KIND)
    assert still_open is not None, (
        "the question was closed by a turn that never answered it — the next "
        "turn arrives cold and the user pays for it")
