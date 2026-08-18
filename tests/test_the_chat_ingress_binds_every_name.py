"""⭐ THE CHAT INGRESS BINDS EVERY NAME IT READS — `except: pass` hid a dead
path in `_backfill_city`, and a NameError in `_stream_turn` hid behind iOS's
REST fallback (both ba8e62a). The regressions Danny asked for, widened to the
whole module.

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
        # nested defs / lambdas bind their own parameters
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)) and n is not node:
            a = n.args
            for p_ in a.args + a.kwonlyargs + getattr(a, "posonlyargs", []):
                bound.add(p_.arg)
            if a.vararg: bound.add(a.vararg.arg)
            if a.kwarg: bound.add(a.kwarg.arg)
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


def test_every_function_in_the_chat_ingress_binds_every_name():
    """⛔⛔ THE SAME PASTE HIT `_stream_turn` — the WebSocket turn, i.e. EVERY
    iOS turn — and there was no `except: pass` to hide it: the handler
    answered {"type": "error"} and iOS silently fell back to REST /chat, so
    production kept working while every turn paid a failed WS round-trip and
    coalescing never ran. Static check over the WHOLE module: a name a
    function reads must be bound somewhere it can see."""
    import api.chat as chat
    offenders = {}
    for name, obj in vars(chat).items():
        if inspect.isfunction(obj) and getattr(obj, "__module__", "") == chat.__name__:
            try:
                free = _free_names(obj)
            except (OSError, TypeError, SyntaxError):
                continue
            if free:
                offenders[name] = free
    assert not offenders, f"api.chat functions reading unbound names: {offenders}"


@pytest.mark.asyncio
async def test_a_websocket_frame_carries_the_barcode_to_the_turn(monkeypatch):
    """TRANSPORT: the WS frame's `barcode` reaches `_stream_turn` (sanitised
    like the REST field), and `_stream_turn` binds it for the turn through the
    same contextvar the settle path reads. iOS turns are WS turns; P17f.5
    shipped the field on REST only — a dead transport for the producer that
    matters (CF6)."""
    import api.chat as chat
    from skills.nutrition.product_acquisition import SCANNED_PRODUCT_EVIDENCE

    seen = {}
    async def fake_acquire(db, code, **k):
        seen["code"] = code
        return 4242
    monkeypatch.setattr("skills.nutrition.product_acquisition.acquire_product_evidence",
                        fake_acquire)

    class _DB:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def commit(self): pass
    monkeypatch.setattr(chat, "AsyncSessionLocal", lambda: _DB())
    async def resolve(db, identity):
        class U: id = 26; city = "x"; preferences = None
        return U()
    monkeypatch.setattr(chat, "resolve_user", resolve)

    bound = {}
    async def fake_run_chat_turn(*a, **k):
        # record what the turn would see, then stop — `_stream_turn` catches
        # and reports the failure to the socket; the turn itself is not under test
        bound["snapshot"] = SCANNED_PRODUCT_EVIDENCE.get()
        raise RuntimeError("stop here — the turn itself is not under test")
    monkeypatch.setattr(chat, "run_chat_turn", fake_run_chat_turn, raising=False)

    class _WS:
        sent = []
        async def send_json(self, m): self.sent.append(m)
    await chat._stream_turn(_WS(), "ios:test", "2 barebells bars",
                            client_msg_id="m1", barcode="0070004199")
    assert seen["code"] == "0070004199"
    assert bound["snapshot"] == 4242, "the scan did not bind the turn"
    # and the frame sanitiser matches the REST field's rule
    assert chat.ChatRequest._digits_or_none("00-7000-4199") == "0070004199"
    assert chat.ChatRequest._digits_or_none("12") is None


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
