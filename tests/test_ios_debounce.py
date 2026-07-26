"""Rapid-fire messages on iOS coalesce into one turn.

Telegram and iMessage have had `schedule_message` from the beginning; iOS
never did. Its WebSocket loop awaited each turn, so a message sent while the
previous one was still running simply waited and then got answered on its own
— which is why iOS is the surface where "chicken" / "and rice" / "for lunch"
reliably produced three logs and three confirmations.

The tests cover the coalescing itself and the one interaction that is easy to
get wrong: debouncing must not erase the prior-reply-unseen signal, because a
message held for a trailing run executes AFTER the lock clears, and the lock
is what used to answer that question.
"""
import asyncio

import pytest

import bot.message_debounce as deb


@pytest.fixture(autouse=True)
def _clean_debounce_state():
    """The module keeps process-wide buffers; tests must not inherit them."""
    deb._buffers.clear()
    deb._tasks.clear()
    deb._running.clear()
    yield
    deb._buffers.clear()
    deb._tasks.clear()
    deb._running.clear()


async def test_three_quick_messages_become_one_turn():
    """The reported bug: three texts, three replies. They are one thought."""
    runs = []

    async def runner(combined: str) -> None:
        runs.append(combined)

    for part in ("chicken", "and rice", "for lunch"):
        await deb.schedule_message("ios:u1", part, runner, delay=0.05)
    await asyncio.sleep(0.3)

    assert len(runs) == 1, f"expected one coalesced turn, got {runs}"
    assert runs[0] == "chicken\nand rice\nfor lunch"


async def test_a_lone_message_is_untouched():
    """Coalescing may not change the ordinary case."""
    runs = []

    async def runner(combined: str) -> None:
        runs.append(combined)

    await deb.schedule_message("ios:u2", "had a banana", runner, delay=0.05)
    await asyncio.sleep(0.2)
    assert runs == ["had a banana"]


async def test_a_repeated_tap_does_not_log_twice():
    """Rapid identical taps are one claim, not three."""
    runs = []

    async def runner(combined: str) -> None:
        runs.append(combined)

    for _ in range(3):
        await deb.schedule_message("ios:u3", "just had a banana", runner,
                                   delay=0.05)
    await asyncio.sleep(0.25)
    assert runs == ["just had a banana"]


async def test_two_users_never_share_a_buffer():
    runs = {}

    def make(uid):
        async def runner(combined: str) -> None:
            runs[uid] = combined
        return runner

    await deb.schedule_message("ios:a", "steak", make("a"), delay=0.05)
    await deb.schedule_message("ios:b", "salmon", make("b"), delay=0.05)
    await asyncio.sleep(0.25)
    assert runs == {"a": "steak", "b": "salmon"}


# ── the interaction that is easy to get wrong ────────────────────────────────

async def test_is_running_is_true_while_a_runner_executes():
    """The signal the WebSocket loop captures at buffer time. Without it,
    debouncing would silently defeat prior-reply-unseen: a message held for a
    trailing run executes after the lock clears, so asking the lock then would
    answer "seen" about a message typed before the reply existed."""
    seen = {}

    async def slow(combined: str) -> None:
        seen["during"] = deb.is_running("ios:u4")
        await asyncio.sleep(0.15)

    await deb.schedule_message("ios:u4", "first", slow, delay=0.02)
    await asyncio.sleep(0.06)                 # runner has started
    seen["outside"] = deb.is_running("ios:u4")
    await asyncio.sleep(0.3)

    assert seen["during"] is True
    assert seen["outside"] is True
    assert deb.is_running("ios:u4") is False  # and clears when it finishes


async def test_a_message_arriving_mid_run_gets_its_own_trailing_turn():
    """The debouncer never cancels a running turn, so a mid-run message is a
    SEPARATE turn — which is exactly why it still needs the unseen flag."""
    runs = []

    async def slow(combined: str) -> None:
        runs.append(combined)
        await asyncio.sleep(0.15)

    await deb.schedule_message("ios:u5", "first", slow, delay=0.02)
    await asyncio.sleep(0.08)                 # first runner is executing
    await deb.schedule_message("ios:u5", "second", slow, delay=0.02)
    await asyncio.sleep(0.5)

    assert runs == ["first", "second"], (
        "a mid-run message must trail, not merge into the running turn")


def test_the_window_is_tighter_than_the_bots():
    """The bots are push surfaces where a pause is invisible; an iOS user is
    watching the screen they just typed into."""
    from api.chat import _debounce_seconds
    assert 0 < _debounce_seconds() < 2.0


def test_a_bad_window_value_cannot_break_chat(monkeypatch):
    monkeypatch.setenv("IOS_DEBOUNCE_SECONDS", "not-a-number")
    from api.chat import _debounce_seconds
    assert _debounce_seconds() == 1.5
