"""Dry-run brain cleanup for Danny (prod user_id=2), driven by BRAIN_TAXONOMY.md.

Read-only by default — prints the plan. Set APPLY=1 to commit.

Applies the lane contract to Danny's existing active attributes:
  • Lane-3 leaks (live/transient: HRV, recovery, RHR, last-night sleep, today's
    session, streak, weight) → discontinue (they surface live, not stored).
  • Lane-1 restatements (calorie/carb/fat targets) → discontinue (columns own them).
  • Misclassified foods filed under health_supplement_* (protein bars/shakes,
    energy drinks) → discontinue (they're food; macros live in logs/nutrition rows).
  • Aggregate supplement rows when per-item rows exist → discontinue.
  • Synonym keys that canonicalize onto another active row → merge (keep most-recent).

Nothing is deleted — rows are soft-discontinued (recoverable, history preserved).
"""
import asyncio
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv(override=True)

from sqlalchemy import select, or_, func
from db.database import AsyncSessionLocal
from db.models import User, UserAttribute, UserPreferences
from memory.attribute_store import canonicalize_key, is_live_metric_key

APPLY = os.environ.get("APPLY") == "1"

# Lane-1: facts that have their own typed column / UI — never an attribute.
LANE1_RESTATEMENTS = {
    "nutrition_calorie_range",   # → UserPreferences.calorie_target
    "nutrition_carb_target",     # → UserPreferences.carb_target
    "nutrition_fat_target",      # → UserPreferences.fat_target
    "nutrition_protein_target",  # → UserPreferences.protein_target
}

# health_supplement_<token> tokens that are ACTUAL supplements. Anything else under
# health_supplement_* is a misclassified food/drink and gets re-homed (discontinued).
REAL_SUPPLEMENT_TOKENS = {
    "fish_oil", "vitamin_d", "vitamin_c", "vitamin_b12", "b12", "magnesium",
    "zinc", "creatine", "ferritin", "iron", "calcium", "multivitamin", "omega",
    "omega_3", "protein_powder", "ashwagandha", "melatonin", "probiotic",
}

# Aggregate supplement keys to drop when per-item health_supplement_* rows exist.
SUPPLEMENT_AGGREGATES = {
    "health_supplements", "nutrition_supplement_intake", "health_vitamins_minerals",
}

_conf_rank = {"confirmed": 3, "inferred": 2, "needs_verification": 1}
_epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _ts(r):
    t = r.updated_at or _epoch
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t


def _supp_token(key: str) -> str:
    return key[len("health_supplement_"):] if key.startswith("health_supplement_") else ""


async def main():
    async with AsyncSessionLocal() as db:
        res = await db.execute(select(User).where(
            or_(User.name.ilike("%danny%"), User.name.ilike("%daniel%"))))
        users = res.scalars().all()
        u = max(users, key=lambda x: x.id)  # prod Danny = id 2 (most active)
        # confirm by conv count
        best = None
        bc = -1
        for cand in users:
            c = await db.scalar(select(func.count()).select_from(UserAttribute)
                                .where(UserAttribute.user_id == cand.id))
            if c > bc:
                best, bc = cand, c
        u = best
        print(f"Target: user_id={u.id} ({u.name})\n")

        active = (await db.execute(select(UserAttribute).where(
            UserAttribute.user_id == u.id,
            UserAttribute.attribute_status == "active",
        ))).scalars().all()
        active_keys = {a.attribute_key for a in active}
        has_per_item_supps = any(
            a.attribute_key.startswith("health_supplement_")
            and _supp_token(a.attribute_key) in REAL_SUPPLEMENT_TOKENS
            for a in active
        )

        # action[key] = (verb, reason, keeper_key_or_None)
        actions: dict[str, tuple] = {}
        renames: dict[str, str] = {}  # keeper_key -> canonical_key (applied on commit)

        # 1. Synonym merge: group by canonical key; if a group has >1 active row,
        #    keep ONE and merge the rest. Keeper preference: the row already named
        #    canonically; else the most-recent (then highest-confidence), which is
        #    then renamed to the canonical key so the survivor is canonically named.
        groups: dict[str, list] = {}
        for a in active:
            groups.setdefault(canonicalize_key(a.attribute_key), []).append(a)
        for canon, rows in groups.items():
            if len(rows) < 2:
                continue
            canon_named = [r for r in rows if r.attribute_key == canon]
            ranked = sorted(rows, key=lambda r: (_ts(r), _conf_rank.get(r.confidence, 2)),
                            reverse=True)
            keeper = canon_named[0] if canon_named else ranked[0]
            if keeper.attribute_key != canon:
                renames[keeper.attribute_key] = canon
            for dupe in rows:
                if dupe is keeper:
                    continue
                actions[dupe.attribute_key] = (
                    "MERGE", f"→ {canon} (survivor: '{keeper.value[:28]}')", canon)

        # 2. Per-attribute taxonomy rules (don't override an existing merge action).
        for a in active:
            k = a.attribute_key
            if k in actions:
                continue
            if is_live_metric_key(k):
                actions[k] = ("DISCONTINUE", "Lane-3 live/transient (surfaces live)", None)
            elif k in LANE1_RESTATEMENTS:
                actions[k] = ("DISCONTINUE", "Lane-1 restatement (column owns it)", None)
            elif k.startswith("health_supplement_") and _supp_token(k) not in REAL_SUPPLEMENT_TOKENS:
                actions[k] = ("DISCONTINUE", "misclassified food/drink (not a supplement)", None)
            elif k in SUPPLEMENT_AGGREGATES and has_per_item_supps:
                actions[k] = ("DISCONTINUE", "aggregate dup (per-item rows exist)", None)

        keep = [a for a in active if a.attribute_key not in actions]

        # ---- report ----
        print(f"ACTIVE NOW: {len(active)}   →   AFTER: {len(keep)}   "
              f"({len(actions)} rows actioned)\n")
        by_verb: dict[str, list] = {}
        for k, (verb, reason, _) in actions.items():
            by_verb.setdefault(verb, []).append((k, reason))
        for verb in ("DISCONTINUE", "MERGE"):
            items = by_verb.get(verb, [])
            if not items:
                continue
            print(f"── {verb} ({len(items)}) ──")
            for k, reason in sorted(items):
                cur = next((a for a in active if a.attribute_key == k), None)
                val = (cur.value or "")[:46] if cur else ""
                print(f"   {k:38} [{cur.category:9}] {val:48} ← {reason}")
            print()

        print(f"── KEEP ({len(keep)}) ──")
        for a in sorted(keep, key=lambda x: (x.category, x.attribute_key)):
            print(f"   {a.attribute_key:38} [{a.category:9}] {(a.value or '')[:46]}")

        if not APPLY:
            print(f"\n[DRY RUN] No changes written. Re-run with APPLY=1 to commit "
                  f"({len(actions)} rows → discontinued).")
            return

        now = datetime.now(timezone.utc)
        n_renamed = 0
        for a in active:
            if a.attribute_key in actions:
                a.attribute_status = "discontinued"
                a.updated_at = now
            elif a.attribute_key in renames:
                a.attribute_key = renames[a.attribute_key]
                a.updated_at = now
                n_renamed += 1
        await db.commit()
        print(f"\n[APPLIED] Discontinued {len(actions)} rows"
              f"{f', renamed {n_renamed} keeper(s) to canonical' if n_renamed else ''}. "
              f"Active now: {len(keep)}.")


if __name__ == "__main__":
    asyncio.run(main())
