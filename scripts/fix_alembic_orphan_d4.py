#!/usr/bin/env python3
"""One-time fix for the alembic_version orphan caused by the failed
first deploy of f7e8d9c0b1a2_add_non_training_activity.py
(originally d4e5f6a7b8c9_add_non_training_activity.py).

USAGE
  · Locally pointing at Render Postgres (paste External Database URL):
      DATABASE_URL='postgresql://...' python scripts/fix_alembic_orphan_d4.py
  · From a Render shell on arnie-bot (env vars already populated):
      python scripts/fix_alembic_orphan_d4.py

Idempotent — safe to run multiple times. Does nothing if there's no orphan.
"""
import os
import sys

# Reuse the app's URL resolver so we hit the same DB the bot does
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.database import _resolve_database_url  # noqa: E402
from sqlalchemy import create_engine, text     # noqa: E402

ORPHAN_REV = "d4e5f6a7b8c9"
TARGET_REV = "f7e8d9c0b1a2"


def main():
    url = _resolve_database_url()
    # Coerce async drivers to sync (same as alembic/env.py)
    url = url.replace("sqlite+aiosqlite://", "sqlite://")
    url = url.replace("postgresql+asyncpg://", "postgresql+psycopg://")

    print(f"Connecting to: {url.split('@')[-1] if '@' in url else url}")
    engine = create_engine(url)

    with engine.begin() as conn:
        # 1) Show current state
        rows = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).fetchall()
        current = [r[0] for r in rows]
        print(f"\nCurrent alembic_version: {current}")

        # 2) Check if column exists (confirms the partially-applied migration ran)
        col_check = conn.execute(text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'users' AND column_name = 'non_training_activity'"
        )).fetchone()
        column_exists = bool(col_check)
        print(f"users.non_training_activity column exists: {column_exists}")

        # 3) Decide what to do
        if ORPHAN_REV not in current:
            print(f"\n✓ No orphan {ORPHAN_REV} in alembic_version — nothing to fix.")
            print("  (If deploy still fails, the issue is elsewhere; check the full deploy log.)")
            return 0

        if not column_exists:
            print(f"\n⚠ Found orphan {ORPHAN_REV} but column does NOT exist.")
            print("  Rolling back the orphan to its parent (a1b2c3d4e5f6) so alembic")
            print("  can apply f7e8d9c0b1a2 fresh on next deploy.")
            conn.execute(text(
                "UPDATE alembic_version SET version_num = 'a1b2c3d4e5f6' "
                "WHERE version_num = :orphan"
            ), {"orphan": ORPHAN_REV})
        else:
            print(f"\n→ Relabeling orphan {ORPHAN_REV} → {TARGET_REV} "
                  "(column already exists from the failed first deploy).")
            conn.execute(text(
                "UPDATE alembic_version SET version_num = :target "
                "WHERE version_num = :orphan"
            ), {"target": TARGET_REV, "orphan": ORPHAN_REV})

        # 4) Show final state
        rows = conn.execute(text("SELECT version_num FROM alembic_version ORDER BY version_num")).fetchall()
        final = [r[0] for r in rows]
        print(f"\n✓ Final alembic_version: {final}")
        print(f"  Expected heads: ['b2c3d4e5f6a7', 'c9d0e1f2a3b4', '{TARGET_REV}']")
        print("\nNow re-trigger the Render deploy. preDeployCommand should succeed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
