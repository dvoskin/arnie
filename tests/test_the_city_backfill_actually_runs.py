"""⭐ `except: pass` HID A DEAD PATH — the regression Danny asked for.

P17f.5 (ba8e62a) pasted the barcode-acquisition block into `_backfill_city`,
whose signature has no `barcode`. The NameError landed inside the function's
blanket `except Exception: pass`, so from that commit on the city backfill
silently did nothing for every user with coordinates and no city. Nothing
was red: the function "ran", swallowed, and returned.

Two proofs, so the swallow cannot hide it again:
  1. BEHAVIOUR — a user with lat/lng and no city GETS a city.
  2. STRUCTURE — every free name the function's body reads is bound (params,
     locals, imports, module globals, builtins); a pasted-in name fails HERE
     with its name, not in production as a silent no-op.
"""
from __future__ import annotations

import ast
import builtins
import inspect

import pytest


def _free_names(fn) -> set:
    """Names LOADED in fn's body that are neither params, nor assigned/imported
    inside it, nor bound in its module, nor builtins."""
    src = inspect.getsource(fn)
    tree = ast.parse(src.lstrip() if not src.startswith("async def") else src)
    node = tree.body[0]
    bound = {a.arg for a in node.args.args + node.args.kwonlyargs}
    if node.args.vararg: bound.add(node.args.vararg.arg)
    if node.args.kwarg: bound.add(node.args.kwarg.arg)
    loaded = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            if isinstance(n.ctx, ast.Store):
                bound.add(n.id)
            elif isinstance(n.ctx, ast.Load):
                loaded.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for alias in n.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(n, ast.ExceptHandler) and n.name:
            bound.add(n.name)
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(n.name)
    module_names = set(vars(inspect.getmodule(fn)))
    return {n for n in loaded
            if n not in bound and n not in module_names and not hasattr(builtins, n)}


def test_backfill_city_reads_no_unbound_name():
    from api.chat import _backfill_city
    assert _free_names(_backfill_city) == set(), (
        f"_backfill_city reads names it never binds: {_free_names(_backfill_city)} "
        f"— under its `except: pass` that is a silent dead path (ba8e62a)")


@pytest.mark.asyncio
async def test_backfill_city_fills_an_empty_city(monkeypatch, db, make_user):
    """BEHAVIOUR: the geocoder answers, the user has no city -> the city is
    written. Under ba8e62a this stayed None forever."""
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    import api.chat as chat
    from core import geocode
    from db.models import User

    user = await make_user()
    user.city = None
    await db.commit()
    user_id = int(user.id)

    async def fake_reverse(lat, lng):
        return "Brooklyn"
    monkeypatch.setattr(geocode, "reverse", fake_reverse)
    sessions = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(chat, "AsyncSessionLocal", sessions)

    async def resolve(session, identity):
        return await session.get(User, user_id)
    monkeypatch.setattr(chat, "resolve_user", resolve)

    await chat._backfill_city("ios:whoever", 40.68, -73.94)

    async with sessions() as s:
        u = await s.get(User, user_id)
        await s.refresh(u)
        assert u.city == "Brooklyn", "the city backfill is still a dead path"
