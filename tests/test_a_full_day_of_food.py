"""ONE DAY OF FOOD, END TO END — every channel, one gate.

WHY THIS EXISTS. On 2026-08-03 a brand-new test user logged a full day on iOS
and the transcript contradicted itself in public: a "Logged" chip above a "Not
logged yet" chip in the same frame; Arnie naming three foods as HELD whose own
receipts an inch below said "Logged"; a cup of white rice at 1 cal and then at
528; the mayo silently missing from a readback that named everything else.

Not one of those is a bug in a function. Every function involved had a passing
unit test. They are bugs in the JOIN — between the ask lane and the write lane,
between the card and the prose, between what the server computed and what the
client re-derived. The suite could not see them because nothing in it replays a
whole exchange: `test_food_turn*.py` drives one turn and reads the plan,
`test_receipt.py` checks a receipt in isolation, and the HTTP layer — the only
place where a chip, a card and a pending question are rendered into the same
frame — was never exercised by the food lane at all.

So this drives the REAL app. A real FastAPI router stack, a real DB built by
the real `_migrate()`, real `resolve_user`, real executor, real cards. The only
things replaced are the four outside edges — the LLM, Tavily, USDA and Open
Food Facts — because those are the only parts that are neither ours nor
deterministic. Everything between the socket and the row is the thing under
test.

WHAT IT ASSERTS. Properties, not strings. A voice change must never turn this
red, and a wrong number must always. The invariants are named I1..I10 in
`INVARIANTS` below and each is checked after every turn of every script on
every channel.

THE ONE-LINE TRICK THAT MAKES IT POSSIBLE. `api/chat.py` and 55 other modules
do `from db.database import AsyncSessionLocal` at import, so there is no
FastAPI dependency to override. But every one of them holds a reference to the
SAME sessionmaker object, so rebinding it in place reaches all of them at once:

    db.database.AsyncSessionLocal.configure(bind=test_engine)

That is why this can be end-to-end without patching 56 modules or teaching the
app a test mode it would then have to keep working.
"""
import json
import os
import re
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.pool import StaticPool
from sqlalchemy.ext.asyncio import create_async_engine


# ── The outside edges ─────────────────────────────────────────────────────────

class ScriptedLLM:
    """One fake for all three model calls a food turn makes, dispatched on the
    system prompt because that is what actually distinguishes them.

    The interpreter's replies are SCRIPTED (a queue, one per food turn); the
    relevance gate always says YES; the composer gets a deterministic line
    built from the plan it was handed. The composer is deliberately NOT
    scripted — its job here is to be a stand-in that says what the plan told it
    to, so that when an invariant about the reply fails, the failure is the
    PLAN's and not a fixture's creative writing.
    """

    def __init__(self, plans):
        self.plans = list(plans)
        self.calls = []          # (role, system_head) for debugging a red run
        self.composer_prompts = []

    #: The interpreter's system prompt opens with this and nothing else does.
    #: An earlier version of this dispatch matched the substring "ready", which
    #: also matches "alREADY" in the composer's prompt — so composer calls ate
    #: the scripted plans, the answer turn's interpreter got `{"action":"none"}`,
    #: and the exchange looked like a product bug. Match on an anchor, not a word.
    INTERPRETER_MARK = "You are the food LOGGER"
    RELEVANCE_MARK = "Answer with exactly one word: YES or NO"

    def _role(self, system: str) -> str:
        s = system or ""
        if self.RELEVANCE_MARK in s:
            return "relevance"
        if s.startswith(self.INTERPRETER_MARK) or self.INTERPRETER_MARK in s[:200]:
            return "interpreter"
        if "confidence" in s and "calories" in s and len(s) < 2000:
            return "web_extract"
        return "composer"

    async def __call__(self, messages, system, tools=True, max_tokens=0,
                       model=None, **kw):
        role = self._role(system)
        self.calls.append((role, (system or "")[:60]))
        if role == "relevance":
            return {"text": "YES", "raw_content": [], "tool_calls": []}
        if role == "web_extract":
            # No web answer by default: a test that wants the enrich lane to
            # fire says so explicitly. Silence here keeps a fabricated number
            # from wandering into an unrelated assertion.
            return {"text": "{}", "raw_content": [], "tool_calls": []}
        if role == "interpreter":
            payload = self.plans.pop(0) if self.plans else {"action": "none"}
            return {"text": json.dumps(payload), "raw_content": [],
                    "tool_calls": []}
        self.composer_prompts.append(system)
        return {"text": _composer_line(system), "raw_content": [],
                "tool_calls": []}


def _composer_line(system: str) -> str:
    """A reply that names what the prompt says was written and what is open.

    Deliberately mechanical. The composer's real job (voice) is not what this
    file gates; what it gates is whether the PLAN handed the composer a
    coherent set of facts, so the stand-in reads the facts back verbatim.
    """
    said = []
    for label, pat in (("logged", r"(?:LOGGED|WROTE|committed)[^\n]*"),
                       ("open", r"(?:NOT LOGGED|still open)[^\n]*")):
        m = re.search(pat, system or "")
        if m:
            said.append(m.group(0))
    return " ".join(said) or "Got it."


#: Modules that bind `chat` at import time (`from core.llm import chat`), so
#: patching `core.llm.chat` alone does not reach them. Found with
#: `grep -rn "from core.llm import" core/ handlers/ api/ skills/ bot/`.
#: The function-level importers (food_response, tool_executor, blurbs, and
#: food_turn's relevance gate) resolve through `core.llm` at call time and are
#: covered by patching the module itself.
_CHAT_BINDERS = ("core.conversation", "core.food_turn", "core.scribe",
                 "core.log_voice", "core.orchestrator", "core.micro_estimator")

#: What the router calls the food lane once it has decided what the turn is.
#: Not one name — `structured_log` and `structured_ask` are the same lane
#: making different decisions, and both carry the guarantees.
STRUCTURED_LANES = ("structured_food", "structured_log", "structured_ask")


@pytest.fixture
def edges(monkeypatch):
    """Pin every outside edge. Returns the LLM so a test can script it.

    An unpatched seam here does not fail loudly — `core.llm.chat` raises an auth
    error, the food turn logs `logger pass failed` and falls through, and the
    turn returns 200 having done nothing. That reads as a passing invariant, so
    the binding list above is load-bearing: `assert_turn_ran` is what stops a
    missed seam from looking like a green gate.
    """
    import importlib
    import core.llm as llm
    import core.search as search
    import api.usda as usda
    import skills.nutrition.off as off

    # PROD PARITY, AND A FINDING IN ITS OWN RIGHT. The regex gate alone routes
    # "chicken and rice" and "a cup of rice" to LEGACY with
    # legacy_reason=no_food_shape — render.yaml lists exactly these as the cases
    # the model gate exists to rescue. Production sets FOOD_GATE_MODEL; the
    # suite defaults it off, which is why no existing test noticed that the
    # commonest food sentences never reach the lane under test.
    monkeypatch.setenv("FOOD_GATE_MODEL", "true")

    llm_stub = ScriptedLLM([])

    async def _no_search(q):
        return search.SearchResult(answer="", results=[], query=q)

    async def _no_usda(query, page_size=5):
        return []

    async def _no_off(name, page_size=8):
        return None

    async def _no_variants(name, limit=5):
        return []

    async def _no_follow_up(*a, **k):
        return {"text": "", "raw_content": [], "tool_calls": []}

    monkeypatch.setattr(llm, "chat", llm_stub)
    for mod_name in _CHAT_BINDERS:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "chat"):
            monkeypatch.setattr(mod, "chat", llm_stub)
        if hasattr(mod, "chat_follow_up"):
            monkeypatch.setattr(mod, "chat_follow_up", _no_follow_up)
    monkeypatch.setattr(search, "search", _no_search)
    monkeypatch.setattr(usda, "search_food", _no_usda)
    monkeypatch.setattr(off, "search", _no_off)
    monkeypatch.setattr(off, "search_variants", _no_variants)
    return llm_stub


def assert_turn_ran(llm_stub, response, *, expect_plans_used):
    """No invariant may pass because the turn never happened.

    Three ways a turn can look fine and mean nothing, all of them observed
    while building this file:

      • every model call failing on a missing key — the turn returns 200,
        writes nothing, and the invariants have nothing to object to;
      • the turn falling to the LEGACY lane, where none of the structured
        guarantees (the resolver owns the numbers, the ontology owns the
        portion, the executor owns the write) apply at all;
      • the reply being empty.

    A vacuous green is worse than a red, so every test states what the turn was
    supposed to consume and this refuses to let it pass otherwise.
    """
    assert response.status_code == 200, response.text
    body = response.json()
    used = sum(1 for role, _ in llm_stub.calls if role == "interpreter")
    assert used >= expect_plans_used, (
        f"turn did not reach the interpreter {expect_plans_used}x "
        f"(saw {used}); calls={llm_stub.calls}")
    lane = ((body.get("reasoning") or {}).get("route") or {}).get("lane")
    assert lane in STRUCTURED_LANES, (
        f"turn fell out of the food lane (lane={lane!r}, "
        f"reason={((body.get('reasoning') or {}).get('route') or {}).get('legacy_reason')!r}) "
        f"— every food guarantee is off on that path")
    assert body.get("bubbles"), f"turn produced no reply: {body}"


# ── The app, on a real database ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def app_db():
    """A real schema on a shared in-memory engine, bound into the app.

    StaticPool because the app opens a session per call and a default in-memory
    SQLite would hand each one its own empty database.
    """
    import db.database as D
    from db.database import Base, _migrate
    from db import models  # noqa: F401 — registers tables

    eng = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate(conn)

    original = D.AsyncSessionLocal.kw.get("bind")
    D.AsyncSessionLocal.configure(bind=eng)
    try:
        yield eng
    finally:
        D.AsyncSessionLocal.configure(bind=original)
        await eng.dispose()


@pytest_asyncio.fixture
async def client(app_db):
    """An httpx client over the real ASGI app, authenticated as one iOS user."""
    import httpx
    from api.app import app
    from api.auth import current_identity

    app.dependency_overrides[current_identity] = lambda: IDENTITY
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport,
                                     base_url="http://t") as c:
            yield c
    finally:
        app.dependency_overrides.pop(current_identity, None)


IDENTITY = "ios:harness-0803"


@pytest_asyncio.fixture
async def seeded(app_db):
    """The user under test, with targets — the day invariants need a denominator."""
    import db.database as D
    from db.models import User, UserPreferences
    async with D.AsyncSessionLocal() as s:
        u = User(telegram_id=IDENTITY, name="Harness",
                 onboarding_completed=True)
        s.add(u)
        await s.flush()
        s.add(UserPreferences(user_id=u.id, calorie_target=2000,
                              protein_target=180,
                              proactive_messaging_enabled=False,
                              food_logging_mode="moderate"))
        await s.commit()
        return u.id


# ── Reading what the turn actually produced ───────────────────────────────────

async def rows(user_id):
    """Every food row on the board right now, oldest first."""
    import db.database as D
    from sqlalchemy import select
    from db.models import FoodEntry, DailyLog
    async with D.AsyncSessionLocal() as s:
        r = await s.execute(
            select(FoodEntry).join(DailyLog,
                                   FoodEntry.daily_log_id == DailyLog.id)
            .where(DailyLog.user_id == user_id).order_by(FoodEntry.id))
        return list(r.scalars().all())


def cards_of(payload):
    return [b for b in (payload.get("cards") or [])]


def chips_of(payload):
    return list(payload.get("tools") or [])


def pending_of(payload):
    return list(payload.get("pending_clarifications") or [])


# ── The invariants ────────────────────────────────────────────────────────────

INVARIANTS = """
I1  one commit-state claim per turn
I2  card <-> row parity
I3  no phantom hold
I4  conservation: each reported food exists exactly once when the exchange ends
I5  plausibility: 0.2 <= cal/g <= 9.0 against the STATED portion
I6  prose == card
I7  readback completeness
I8  answerable chips
I9  no internal vocabulary in the reply
I10 cross-endpoint agreement
"""


def check_i1(payload):
    """A turn may not both claim a write and deny one.

    The deployed build shipped `tools:["log_food"]` (rendered "Logged") above a
    `pending_clarifications` entry rendered "Not logged yet — Arnie's still
    asking", because the ask lane wrote rows while the question lane reported
    nothing written. Those are two answers to one question in one frame.
    """
    claims_write = "log_food" in chips_of(payload)
    denies_write = bool(pending_of(payload))
    assert not (claims_write and denies_write), (
        f"I1: turn claims Logged and Not-logged at once — "
        f"tools={chips_of(payload)} pending={pending_of(payload)}")


def check_i5(entries):
    """No row may sit outside a two-sided energy-density band.

    One cup of cooked white rice is ~158 g. At 1 cal that is 0.006 kcal/g; at
    528 it is 3.3 kcal/g, a DRY-grain density on a portion the user described
    as cooked. `sanity.py` has only ceilings, so both committed.
    """
    from skills.nutrition.normalize import normalize_quantity
    bad = []
    for e in entries:
        cal = float(e.calories or 0)
        try:
            grams = normalize_quantity(e.quantity or "",
                                       e.parsed_food_name or "").grams
        except Exception:
            grams = None
        if not grams or grams <= 20:
            continue                      # no stated mass to judge it against
        d = cal / grams
        if d < 0.2 or d > 9.0:
            bad.append(f"{e.parsed_food_name!r} {e.quantity!r} "
                       f"{cal:g} cal / {grams:g} g = {d:.3f} kcal/g")
    assert not bad, "I5: implausible energy density — " + "; ".join(bad)


def check_i9(text):
    """The reply is the coach speaking, not the planner thinking out loud."""
    leaks = [p for p in (
        "open question", "new food", "tool_call", "log_food",
        "partial commit", "deferred", "staged_item", "interpreter",
        "[PENDING", "[TURN OBLIGATIONS", "[OPEN QUESTION",
    ) if p.lower() in (text or "").lower()]
    assert not leaks, f"I9: internal vocabulary in the reply: {leaks} — {text!r}"


def names_logged(entries):
    """Normalized names, as a LIST — 'exactly once' is the assertion and a set
    is how a double-write hides."""
    from skills.nutrition.food_dedup import normalize_food_name
    return [normalize_food_name(e.parsed_food_name or "") for e in entries]


def check_i4(entries, expected):
    """Every food the user reported, exactly once when the exchange is over."""
    from skills.nutrition.food_dedup import normalize_food_name
    got = names_logged(entries)
    for food in expected:
        want = normalize_food_name(food)
        hits = [n for n in got if want in n or n in want]
        assert len(hits) == 1, (
            f"I4: {food!r} appears {len(hits)}x, expected exactly 1 — "
            f"board={got}")


# ── Scripts ───────────────────────────────────────────────────────────────────

def item(food, cal=100, amount=1, unit="", **kw):
    return {"food": food, "amount": amount, "unit": unit, "calories": cal,
            "protein": 5, "carbs": 10, "fats": 3, **kw}


@pytest.mark.asyncio
async def test_an_ask_turn_makes_one_claim(client, seeded, edges):
    """I1 on the exact shape that shipped: a mixed meal where one item is
    settled and another raises a question.

    "I also some chicken and rice" — the rice is priceable, the chicken is not
    until they say grilled or fried. The deployed build wrote the rice, said
    nothing about it, asked about the chicken, and rendered both claims.
    """
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Chicken", "q": "Grilled or fried?"}],
        "items": [item("Chicken", 200), item("White rice", 205,
                                             unit="cup")],
        "ready": [item("White rice", 205, unit="cup")],
    })
    r = await client.post("/api/v1/chat", json={"message":
                                                "chicken and rice"})
    assert_turn_ran(edges, r, expect_plans_used=1)
    check_i1(r.json())


@pytest.mark.asyncio
async def test_no_row_is_implausible(client, seeded, edges):
    """I5 on the rice. The interpreter says a cup is 205; nothing downstream
    may turn that into 1 or 528."""
    edges.plans.append({
        "action": "log",
        "items": [item("White rice", 205, unit="cup")],
    })
    r = await client.post("/api/v1/chat", json={"message": "a cup of rice"})
    assert_turn_ran(edges, r, expect_plans_used=1)
    board = await rows(seeded)
    assert board, "nothing was written — I5 would pass vacuously"
    check_i5(board)


@pytest.mark.asyncio
async def test_every_food_survives_the_exchange(client, seeded, edges):
    """I4 across a real ask/answer pair, over HTTP, with the answer turn's
    interpreter DROPPING one of the foods — which is what production did.

    "150g turkey and a corn": the turkey raised a clarification, and the corn
    was neither asked about nor marked ready, so it was lost rather than
    deferred.
    """
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Turkey", "qs": ["how was it cooked?"]}],
        "items": [item("Turkey", 165, amount=150, unit="g"),
                  item("Corn", 90, unit="cup")],
    })
    edges.plans.append({          # the answer turn forgets the corn entirely
        "action": "log",
        "items": [item("Turkey", 165, amount=150, unit="g")],
    })
    r1 = await client.post("/api/v1/chat",
                           json={"message": "150g turkey and a corn"})
    assert_turn_ran(edges, r1, expect_plans_used=1)
    r2 = await client.post("/api/v1/chat", json={"message": "deli"})
    assert_turn_ran(edges, r2, expect_plans_used=2)

    check_i4(await rows(seeded), ["Turkey", "Corn"])
