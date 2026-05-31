"""Debounce concurrency guarantees: coalescing, no concurrent runs, no interrupt
of an in-flight runner (the double-process risk this addresses)."""
import asyncio
import pytest
import bot.message_debounce as deb


@pytest.fixture(autouse=True)
def _clean():
    deb._buffers.clear(); deb._tasks.clear(); deb._running.clear()
    yield
    deb._buffers.clear(); deb._tasks.clear(); deb._running.clear()


async def test_rapid_messages_coalesce_into_one_run():
    calls = []
    async def runner(text): calls.append(text)
    for frag in ("chicken", "and rice", "for lunch"):
        await deb.schedule_message("u1", frag, runner, delay=0.05)
        await asyncio.sleep(0.01)  # all within the window
    await asyncio.sleep(0.2)
    assert calls == ["chicken\nand rice\nfor lunch"]  # exactly one combined run


async def test_never_runs_concurrently_and_does_not_interrupt():
    order = []
    started = asyncio.Event()
    async def runner(text):
        order.append(("start", text))
        if text == "first":
            started.set()
            await asyncio.sleep(0.15)  # long run; a new msg arrives during this
        order.append(("end", text))

    await deb.schedule_message("u1", "first", runner, delay=0.02)
    await started.wait()                       # runner for "first" is mid-flight
    await deb.schedule_message("u1", "second", runner, delay=0.02)  # arrives during run
    await asyncio.sleep(0.4)

    # "first" must COMPLETE before "second" starts — no interrupt, no overlap.
    assert order == [
        ("start", "first"), ("end", "first"),
        ("start", "second"), ("end", "second"),
    ], order


async def test_separate_users_run_independently():
    calls = []
    async def runner(text): calls.append(text)
    await deb.schedule_message("a", "ax", runner, delay=0.03)
    await deb.schedule_message("b", "bx", runner, delay=0.03)
    await asyncio.sleep(0.15)
    assert set(calls) == {"ax", "bx"}
