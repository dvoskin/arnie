"""A food turn is written by the same Arnie, in the same thread, as every other.

There were two. `core/food_response` carried a 323-token `ARNIE_VOICE` defined
inline and imported nothing from `core/prompts/arnie`, so a logged meal was
written by a smaller model against a miniature persona — no bubble rules, no
emoji policy, no register — while every other turn in the product got ~3,400
tokens of it. And `compose_async` called the model with one hard-coded message,
`"Write the response."`, so that writer had never seen a word of the
conversation it was writing into. "Sound context-aware" was in the persona and
impossible to obey.

That is why a logged meal read like a different assistant had taken over the
thread. Not a copy bug — two definitions of who Arnie is, and one of them
deaf.

What must NOT come back with the voice: the model choosing the writes. Legacy
felt intelligent and dropped tool calls because one model did both jobs. The
interpreter still decides; this one only writes.
"""
import core.food_response as FR
from core.food_response import (CARD_FACTS, FoodItemSummary, FoodResponseIntent,
                                FoodResponsePlan, apply_policy, arnie_voice,
                                build_prompt, with_context)


def _plan(**kw):
    base = dict(intent=FoodResponseIntent.COMMIT,
                committed_items=(FoodItemSummary(name="Salmon"),),
                card_will_render=True, facts_visible_in_card=CARD_FACTS)
    base.update(kw)
    return apply_policy(FoodResponsePlan(**base))


# ── one persona ───────────────────────────────────────────────────────────────
def test_the_food_lane_reads_the_shared_persona():
    from core.prompts.arnie import EMOJI_SYSTEM, IDENTITY, LANGUAGE, VOICE
    voice = arnie_voice()
    for block in (IDENTITY, LANGUAGE, VOICE, EMOJI_SYSTEM):
        assert block in voice


def test_the_shared_persona_has_one_definition():
    """`voice_core()` is what `build_arnie_system` composes from, so a change to
    how Arnie sounds cannot land in one lane and not the other."""
    from core.prompts.arnie import VOICE_CORE, build_arnie_system, voice_core
    system = build_arnie_system("web")
    for block in VOICE_CORE:
        assert block in system and block in voice_core()


def test_the_lane_still_adds_only_what_is_lane_specific():
    """What survives locally is about not inventing numbers and not reciting a
    card — not about who he is."""
    voice = arnie_voice()
    assert "Do not add, alter, recompute" in voice
    assert "Do not repeat information marked as visible" in voice


# ── in the thread ─────────────────────────────────────────────────────────────
def test_the_composer_is_given_the_conversation():
    plan = with_context(_plan(), messages=[
        {"role": "user", "content": "what should I eat tonight"},
        {"role": "assistant", "content": "something with protein"},
        {"role": "user", "content": "had salmon"}])
    msgs = FR._composer_messages(plan)
    assert [m["content"] for m in msgs[:-1]] == [
        "what should I eat tonight", "something with protein", "had salmon"]
    assert msgs[-1]["content"] == "Write the response."


def test_non_text_turns_are_dropped_rather_than_flattened():
    """Photo and tool turns arrive as content BLOCKS. Flattening them would put
    tool JSON in the thread."""
    plan = with_context(_plan(), messages=[
        {"role": "user", "content": [{"type": "image"}]},
        {"role": "user", "content": "had salmon"}])
    assert [m["content"] for m in FR._composer_messages(plan)] == [
        "had salmon", "Write the response."]


def test_the_thread_never_opens_on_an_assistant_turn():
    plan = with_context(_plan(), messages=[
        {"role": "assistant", "content": "morning"},
        {"role": "user", "content": "had salmon"}])
    assert FR._composer_messages(plan)[0]["role"] == "user"


def test_a_plan_with_no_history_still_writes():
    assert FR._composer_messages(_plan()) == [
        {"role": "user", "content": "Write the response."}]


# ── the same model ────────────────────────────────────────────────────────────
def test_the_composer_uses_the_general_model_by_default(monkeypatch):
    monkeypatch.delenv("FOOD_COMPOSER_MODEL", raising=False)
    monkeypatch.setenv("DEFAULT_MODEL", "claude-opus-4-7")
    assert FR._composer_model() == "claude-opus-4-7"


def test_the_override_still_wins(monkeypatch):
    monkeypatch.setenv("FOOD_COMPOSER_MODEL", "claude-haiku-4-5-20251001")
    assert FR._composer_model() == "claude-haiku-4-5-20251001"


# ── with the evidence ─────────────────────────────────────────────────────────
def test_sourcing_reaches_the_brief_as_reasoning_not_as_subject():
    prompt = build_prompt(_plan(sourcing=(
        {"name": "Salmon", "detail": "From the product label"},)))
    assert "Salmon: From the product label" in prompt
    assert "never the subject" in prompt
    assert "Never name a database" in prompt


def test_no_sourcing_adds_no_block():
    assert "WHERE THESE NUMBERS CAME FROM" not in build_prompt(_plan())


# ── and the client can render it ──────────────────────────────────────────────
def test_the_prompt_does_not_promise_tables_the_app_cannot_render():
    """A markdown table arrives as "com / pone / nt" down a phone-width column.
    The prompt was telling him to reach for one."""
    from core.prompts.arnie import IOS_STYLE
    assert "does NOT\nrender tables" in IOS_STYLE
    assert "or a small table" not in IOS_STYLE
