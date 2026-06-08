"""
Inspect what Arnie has learned about a user — the "show me the notebook" tool.

Dumps the full self-taught profile for one user so you can SEE the database
teaching itself:
  • THE FORM      — typed columns you stated (name, age, weight, goal, targets…)
  • THE NOTEBOOK  — every learned attribute, by category (value, confidence,
                    source, tier, status) — this is the user_attributes table
  • THE BIO       — the generated dashboard summary
  • THE MARKDOWN  — the synthesized Profile Matrix (head)

Usage (from arnie/):
    .venv/bin/python inspect_profile.py <telegram_id | webhook_token>
    .venv/bin/python inspect_profile.py <id> --sync          # force synthesis NOW
                                                             # (skips 3h throttle)
    .venv/bin/python inspect_profile.py <id> --consolidate   # force nightly cleanup
                                                             # (discontinue redundant
                                                             #  attrs, shorten verbose)
    .venv/bin/python inspect_profile.py <id> --sync --consolidate  # both
    .venv/bin/python inspect_profile.py --list               # list known users

Reads the LOCAL arnie.db by default. To inspect a REAL user, point DATABASE_URL
at production first (read-only; --sync costs one Sonnet call; --consolidate costs
one Haiku call).
"""
import asyncio
import sys

from dotenv import load_dotenv
load_dotenv(override=True)

G = "\033[92m"; R = "\033[91m"; C = "\033[96m"; Y = "\033[93m"; B = "\033[1m"; X = "\033[0m"; D = "\033[90m"

CONF_MARK = {"confirmed": f"{G}●{X}", "inferred": f"{Y}●{X}", "needs_verification": f"{R}●{X}"}


async def _resolve(db, ident):
    from db.models import User
    from sqlalchemy import select, or_
    return (await db.execute(
        select(User).where(or_(User.telegram_id == ident, User.webhook_token == ident))
    )).scalar_one_or_none()


async def list_users():
    from db.database import AsyncSessionLocal
    from db.models import User
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User).order_by(User.id))).scalars().all()
        print(f"\n{B}Known users:{X}")
        for u in users:
            print(f"  {u.telegram_id:<22} {D}{u.name or '(no name)'}{X}")
        print()


async def inspect(ident, do_sync, do_consolidate=False):
    from db.database import AsyncSessionLocal
    from sqlalchemy.orm import selectinload
    from db.models import User
    from sqlalchemy import select
    from memory.attribute_store import get_all_attributes
    from memory.profile_manager import read_profile

    async with AsyncSessionLocal() as db:
        user = await _resolve(db, ident)
        if not user:
            print(f"{R}No user found for '{ident}'. Try --list.{X}")
            return
        # eager prefs
        user = (await db.execute(
            select(User).where(User.id == user.id).options(selectinload(User.preferences))
        )).scalar_one()
        uid = user.id

        if do_sync:
            print(f"{Y}Forcing the teaching step (synthesis + attribute extraction + bio)…{X}")
            from memory.profile_updater import maybe_update_profile
            ok = await maybe_update_profile(user, db, force=True)
            print(f"{'✓ synthesis ran' if ok else '· synthesis made no changes'}\n")
            user = (await db.execute(
                select(User).where(User.id == uid).options(selectinload(User.preferences))
            )).scalar_one()

        if do_consolidate:
            print(f"{Y}Forcing nightly profile cleanup (Haiku pass)…{X}")
            from memory.profile_consolidator import consolidate_user_profile
            result = await consolidate_user_profile(user, db)
            print(f"✓ discontinued {result['discontinued']}, shortened {result['shortened']}\n")
            # Reload so the dump below reflects the post-cleanup state
            user = (await db.execute(
                select(User).where(User.id == uid).options(selectinload(User.preferences))
            )).scalar_one()

        prefs = user.preferences
        attrs = await get_all_attributes(db, uid)
        bio = user.user_bio
        md = await read_profile(user.telegram_id)

    # ── THE FORM ──
    print(f"\n{B}{C}{'═'*60}{X}")
    print(f"{B}{C} PROFILE — {user.name or 'User'}  ({user.telegram_id}){X}")
    print(f"{B}{C}{'═'*60}{X}")
    print(f"\n{B}THE FORM{X} {D}(typed columns — what you stated directly){X}")
    form = [
        ("Age", user.age), ("Sex", user.sex), ("Height(cm)", user.height_cm),
        ("Weight(kg)", user.current_weight_kg), ("Goal wt(kg)", user.goal_weight_kg),
        ("Goal", user.primary_goal), ("Experience", user.training_experience),
        ("Diet", user.dietary_preferences), ("Injuries", user.injuries),
        ("Timezone", user.timezone),
    ]
    if prefs:
        form += [("Calorie target", prefs.calorie_target), ("Protein target", prefs.protein_target),
                 ("Coaching style", prefs.coaching_style), ("Accountability", prefs.accountability_level)]
    for k, v in form:
        if v not in (None, "", "none"):
            print(f"  {D}{k:<16}{X} {v}")

    # ── THE NOTEBOOK ──
    active = [a for a in attrs if a.attribute_status == "active"]
    other = [a for a in attrs if a.attribute_status != "active"]
    print(f"\n{B}THE NOTEBOOK{X} {D}(learned attributes — what Arnie figured out){X}  "
          f"{G}{len(active)} active{X}" + (f", {D}{len(other)} archived{X}" if other else ""))
    if not active:
        print(f"  {D}(nothing learned yet — chat more, or run with --sync){X}")
    else:
        by_cat = {}
        for a in active:
            by_cat.setdefault(a.category or "custom", []).append(a)
        for cat in sorted(by_cat):
            print(f"  {B}{Y}{cat}{X}")
            for a in by_cat[cat]:
                mark = CONF_MARK.get(a.confidence, "·")
                unit = f" {a.unit}" if a.unit else ""
                tier = f"{D}[{a.relevance_tier}]{X}"
                src = f"{D}via {a.source}{X}"
                print(f"    {mark} {a.display_name or a.attribute_key}: {B}{a.value}{unit}{X} {tier} {src}")
    print(f"\n  {D}legend: {CONF_MARK['confirmed']} confirmed  {CONF_MARK['inferred']} inferred  "
          f"{CONF_MARK['needs_verification']} needs-verification{X}")

    # ── THE BIO ──
    print(f"\n{B}THE BIO{X} {D}(generated dashboard summary){X}")
    if bio:
        # wrap to ~76 cols
        import textwrap
        for line in textwrap.wrap(bio, 76):
            print(f"  {line}")
    else:
        print(f"  {D}(no bio yet — needs a few learned attributes; run with --sync){X}")

    # ── THE MARKDOWN (head) ──
    print(f"\n{B}THE MARKDOWN{X} {D}(synthesized Profile Matrix — first 16 lines){X}")
    if md:
        for line in md.splitlines()[:16]:
            print(f"  {D}{line}{X}")
        print(f"  {D}… ({len(md.splitlines())} lines total){X}")
    else:
        print(f"  {D}(none yet){X}")
    print()


async def main():
    args = [a for a in sys.argv[1:]]
    if "--list" in args:
        await list_users()
        return
    do_sync = "--sync" in args
    do_consolidate = "--consolidate" in args
    idents = [a for a in args if not a.startswith("--")]
    if not idents:
        print(__doc__)
        return
    await inspect(idents[0], do_sync, do_consolidate)


if __name__ == "__main__":
    asyncio.run(main())
