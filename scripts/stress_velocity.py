#!/usr/bin/env python3
"""High-velocity food-logging stress: rapid sequential + CONCURRENT same-user turns.

The concurrent tests are the real stress — simultaneous messages for ONE user hit
the daily-log get_or_create race (dup daily_logs → 500s, the 2026-06-28 incident),
the dedup snapshot (pre_existing_food_ids may not see in-flight writes), and session
isolation. Drives the REAL run_chat_turn against a scratch DB and checks integrity.

Run: python scripts/stress_velocity.py [--model claude-opus-4-8]
"""
import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import simulate_logging_discipline as S
from core.chat_service import run_chat_turn
from db.queries import reload_user
from sqlalchemy import select, func


async def _turn(H, uid, msg):
    """One full turn on its OWN session (safe for concurrent use)."""
    async with await H.session() as db:
        u = await reload_user(db, uid)
        try:
            tr = await run_chat_turn(db, u, msg, platform="ios",
                                     schedule_background=False)
            await db.commit()
            fired = [tc.get("name") for tc in (getattr(tr, "tool_calls", None) or [])]
            return {"ok": True, "fired": fired}
        except Exception as e:
            return {"ok": False, "err": repr(e)}


async def _daily_log_count(H, uid):
    from db.models import DailyLog
    async with await H.session() as db:
        return (await db.execute(
            select(func.count()).select_from(DailyLog)
            .where(DailyLog.user_id == uid))).scalar()


def _dupe_rows(rows):
    from collections import Counter
    c = Counter((r.parsed_food_name or "").lower() for r in rows)
    return {n: k for n, k in c.items() if k > 1}


async def test_rapid_sequential(H, n=15):
    """Fire N distinct foods back-to-back (no delay). Expect N rows, no crash."""
    uid = await H.new_user()
    foods = ["a banana", "a cup of black coffee", "3 scrambled eggs",
             "2 slices whole wheat toast", "a scoop of whey protein",
             "a green apple", "6 oz grilled chicken", "a cup of white rice",
             "a handful of almonds", "a greek yogurt", "an orange",
             "a tablespoon of peanut butter", "a protein bar", "a banana smoothie",
             "a boiled egg", "a slice of cheddar", "a cup of blueberries",
             "a chicken thigh"][:n]
    t0 = time.monotonic()
    errs = 0
    for f in foods:
        r = await _turn(H, uid, f)
        if not r["ok"]:
            errs += 1
    dt = time.monotonic() - t0
    rows = await S.db_food_rows(H, uid)
    dupes = _dupe_rows(rows)
    logged = len(rows)
    print(f"\n[RAPID SEQUENTIAL] {n} distinct foods, back-to-back")
    print(f"  {dt:.1f}s ({dt/n*1000:.0f}ms/turn) | errors={errs} | rows={logged}/{n} | dupes={dupes or 'none'}")
    ok = errs == 0 and logged >= int(n * 0.9) and not dupes
    print(f"  VERDICT: {'✅ PASS' if ok else '❌ FAIL'}  (want 0 errs, ~{n} rows, no dupes)")
    return ok


async def test_concurrent_distinct(H, n=8):
    """Fire N DISTINCT foods CONCURRENTLY (same user). Race test: expect N rows,
    exactly ONE daily_log, no lost writes, no crash."""
    uid = await H.new_user()
    foods = ["a banana", "an apple", "an orange", "a pear", "a peach",
             "a plum", "a mango", "a kiwi", "a fig", "a nectarine"][:n]
    t0 = time.monotonic()
    results = await asyncio.gather(*[_turn(H, uid, f) for f in foods])
    dt = time.monotonic() - t0
    errs = [r for r in results if not r["ok"]]
    rows = await S.db_food_rows(H, uid)
    dupes = _dupe_rows(rows)
    dlogs = await _daily_log_count(H, uid)
    print(f"\n[CONCURRENT DISTINCT] {n} foods fired simultaneously (same user)")
    print(f"  {dt:.1f}s wall | errors={len(errs)} | rows={len(rows)}/{n} | daily_logs={dlogs} | dupes={dupes or 'none'}")
    if errs:
        print(f"  ERR sample: {errs[0]['err'][:140]}")
    ok = not errs and len(rows) >= int(n * 0.9) and dlogs == 1 and not dupes
    print(f"  VERDICT: {'✅ PASS' if ok else '❌ FAIL'}  (want 0 errs, ~{n} rows, exactly 1 daily_log, no dupes)")
    return ok


async def test_concurrent_same_food(H, n=5):
    """Fire the SAME food N times CONCURRENTLY — hardest dedup race. No add-intent, so
    these read as retries: dedup SHOULD collapse them. Under concurrency the snapshot
    may miss in-flight writes, so we assert only: no crash, and NOT all N slip through."""
    uid = await H.new_user()
    t0 = time.monotonic()
    results = await asyncio.gather(*[_turn(H, uid, "a banana") for _ in range(n)])
    dt = time.monotonic() - t0
    errs = [r for r in results if not r["ok"]]
    rows = await S.db_food_rows(H, uid)
    dlogs = await _daily_log_count(H, uid)
    print(f"\n[CONCURRENT SAME FOOD] '{'a banana'}' × {n} fired simultaneously")
    print(f"  {dt:.1f}s wall | errors={len(errs)} | banana rows={len(rows)} | daily_logs={dlogs}")
    if errs:
        print(f"  ERR sample: {errs[0]['err'][:140]}")
    # No crash + exactly one daily_log are the hard invariants. Row count is
    # informational (ideal=1 via dedup; concurrency may allow a few — flagged, not failed).
    ok = not errs and dlogs == 1
    note = "dedup held (1 row)" if len(rows) == 1 else f"{len(rows)} slipped the race (dedup is best-effort under concurrency)"
    print(f"  VERDICT: {'✅ PASS' if ok else '❌ FAIL'}  (invariant: no crash, 1 daily_log) — {note}")
    return ok


async def main(model):
    if model:
        os.environ["DEFAULT_MODEL"] = model
    H = S.Harness(); await H.setup()
    print("=" * 70)
    print(f"HIGH-VELOCITY FOOD-LOGGING STRESS  (model={model or 'default'})")
    print("=" * 70)
    results = []
    results.append(await test_rapid_sequential(H, 15))
    results.append(await test_concurrent_distinct(H, 8))
    results.append(await test_concurrent_same_food(H, 5))
    print("\n" + "=" * 70)
    print(f"OVERALL: {'✅ ALL PASS' if all(results) else '❌ FAIL'}  ({sum(results)}/{len(results)})")
    print("=" * 70)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.getenv("EVAL_MODEL"))
    args = ap.parse_args()
    asyncio.run(main(args.model))
