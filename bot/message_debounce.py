"""
Message debounce — coalesce rapid-fire messages from the same user into a single
pipeline run, so 3 quick texts become 1 LLM call with all the context.

Without this, a user firing "chicken" / "and rice" / "for lunch" as separate
texts would trigger 3 separate pipeline runs racing each other.

Concurrency guarantees (per user_key):
  1. Messages within `delay`s of each other coalesce into one runner call.
  2. A runner that has ALREADY started is never cancelled — cancelling mid-pipeline
     could interrupt a DB write and double-process. New messages that arrive during
     a run are buffered and flushed in a trailing run after the current one ends.
  3. At most one runner executes at a time for a user_key (no concurrent runs).

This makes "can't double-process" a property of the debounce itself, independent of
any per-handler lock (the handlers keep a lock too, as defense-in-depth + parity).
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_buffers: dict[str, list] = {}          # pending text fragments per user
_tasks: dict[str, asyncio.Task] = {}    # the in-flight debounce/flush task per user
_running: set[str] = set()              # user_keys whose runner is currently executing


async def schedule_message(user_key: str, text: str, runner, delay: float = 2.0):
    """
    Buffer `text` for `user_key`; after `delay`s of quiet, call runner(combined).
    A new message within the window resets the timer and appends to the buffer.
    A new message while a runner is executing is buffered for a trailing run.
    """
    _buffers.setdefault(user_key, []).append(text)

    # Re-arm the debounce timer ONLY if a runner isn't already executing. Never
    # cancel an in-flight runner (would interrupt the pipeline mid-write).
    if user_key not in _running:
        t = _tasks.get(user_key)
        if t and not t.done():
            t.cancel()
        _tasks[user_key] = asyncio.create_task(_debounce_and_run(user_key, runner, delay))
    # else: the executing runner's trailing-flush loop will pick up this buffer.


async def _debounce_and_run(user_key: str, runner, delay: float):
    try:
        await asyncio.sleep(delay)
    except asyncio.CancelledError:
        return  # superseded by a newer message — that task will run instead

    if user_key in _running:
        return  # a run is already in progress; it will drain the buffer
    _running.add(user_key)
    try:
        # Drain: if new messages arrive during a run, flush them too (no interrupt).
        while _buffers.get(user_key):
            combined = "\n".join(_buffers.pop(user_key, []))
            try:
                await runner(combined)
            except Exception as e:
                logger.error(f"debounce runner failed for {user_key}: {e}")
    finally:
        _running.discard(user_key)

    # No await between discard and this check → atomic in asyncio. If a message
    # landed right at the boundary, re-arm a fresh debounce for it.
    if _buffers.get(user_key):
        _tasks[user_key] = asyncio.create_task(_debounce_and_run(user_key, runner, delay))
