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
import uuid
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


#: The composer's prompt names the foods it is allowed to talk about on lines
#: of this shape. Reading them back is how the stand-in stays a stand-in: it
#: asserts nothing of its own, so a failed invariant is the PLAN's fault.
_PROMPT_FOOD_RE = re.compile(r"^\s*[-•*]?\s*([A-Z][^:\n,(]{2,40})", re.M)


def _composer_line(system: str) -> str:
    """A reply that names the foods the prompt handed over, and asks when asked.

    Deliberately mechanical — the composer's real job is voice, and voice is
    not what this file gates.

    IT MUST SATISFY `validate()`. The first version returned a bare statement,
    so every ask turn came back `missing_question`, the composer retried, and
    the bubble under test was the deterministic FALLBACK rather than the
    composed reply. The invariants were reading a path production rarely takes.
    """
    s = system or ""
    names = []
    for block in ("NOT LOGGED, still open", "UNDERSTOOD but NOT YET WRITTEN",
                  "LOGGED", "WROTE"):
        i = s.find(block)
        if i == -1:
            continue
        for m in _PROMPT_FOOD_RE.finditer(s[i:i + 400]):
            n = m.group(1).strip()
            if n and n.lower() not in (x.lower() for x in names):
                names.append(n)
    body = ("Got " + ", ".join(names[:6]) + ".") if names else "Got it."
    # A question is REQUIRED whenever the plan holds something open; supplying
    # one keeps us on the composed path instead of the fallback.
    if re.search(r"ASK|question|still open|NOT LOGGED", s, re.I):
        body += " How much was it, a cup or more than that?"
    return body


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
    # Same reason, second flag. `micros_deferred_enabled` defaults FALSE in code
    # and render.yaml ships it TRUE, so the suite was exercising the INLINE
    # micro estimate while production defers it past the reply. A harness whose
    # whole purpose is replaying production should not differ from it on which
    # side of a turn's latency budget a model call falls — and matching it also
    # takes eleven stubbed model calls out of a single day's replay.
    monkeypatch.setenv("FOOD_MICROS_DEFERRED", "true")

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
    """A real schema bound into the app — on POSTGRES when one is offered.

    `TEST_POSTGRES_URL` switches the backing store to a private schema on the
    real engine. Without it, the shared in-memory SQLite engine as before
    (StaticPool, because the app opens a session per call and a default
    in-memory SQLite would hand each one its own empty database).

    WHY THE SWITCH EXISTS. B-1b.1 asks for production-like Postgres, and
    "the suite passed with TEST_POSTGRES_URL set" is not the same claim as
    "these scenarios ran on Postgres" — the harness was SQLite either way, so
    every conversation-level assertion in this repo was proving itself against
    an engine production does not use. That difference is not academic here:
    it is exactly where a model default the migrations never created stayed
    invisible, because every suite builds its schema from the models.

    A PRIVATE SCHEMA PER FIXTURE, not a shared one. These tests write real
    rows and read them back by count; a neighbour's leftovers would not fail
    loudly, they would fail as an off-by-one in an unrelated assertion.
    """
    import os

    import db.database as D
    from db.database import Base, _migrate, make_engine
    from db import models  # noqa: F401 — registers tables

    pg = os.getenv("TEST_POSTGRES_URL")
    schema = None
    if pg:
        from sqlalchemy import text
        schema = f"harness_{uuid.uuid4().hex[:12]}"
        # make_engine, never create_async_engine: the codebase refuses an
        # unpinned Postgres engine by construction (the one-clock rule).
        #
        # THE URL IS USED AS CONFIGURED, NOT REWRITTEN. This asked for
        # `+asyncpg` — a driver `17da24f` removed from `requirements.txt` in
        # favour of psycopg3, which `requirements.txt` says was "chosen over
        # asyncpg because it [supports] Python 3.14". The two halves of that
        # commit disagreed, and the disagreement is invisible without a
        # Postgres: `db.database`'s asyncpg→psycopg normalisation only runs on
        # `DATABASE_URL` from the environment, never on a URL passed here.
        #
        # `options`, NOT `server_settings`. The latter is asyncpg's spelling;
        # psycopg3 takes libpq's, and a `-c` option string is what actually
        # pins the search path. Getting the URL right and leaving these would
        # trade a missing driver for a silently ignored schema — the same
        # failure with a longer fuse, since the tests would then read and write
        # `public` while believing they were isolated.
        eng = make_engine(pg, connect_args={
            "options": f"-csearch_path={schema}"})
        async with eng.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    else:
        # ⚠ create_async_engine HERE, DELIBERATELY, AND IT IS A HARNESS LIMIT
        # RATHER THAN A PREFERENCE. `make_engine` would apply
        # `fix_sqlite_savepoints`, which takes transaction control from the
        # driver and emits BEGIN itself — correct, and incompatible with a
        # StaticPool that hands every session THE SAME connection: two
        # concurrent sessions then race to BEGIN and the second dies with
        # "cannot start a transaction within a transaction". Measured
        # 2026-08-16 — it breaks `test_two_concurrent_taps_write_one_meal`.
        #
        # The APPLICATION engine is fixed (db/database.py) and gated. Closing
        # this gap needs an in-memory SQLite that can serve more than one
        # connection (a shared-cache URI rather than StaticPool); filed, not
        # bodged here.
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
        # DISPOSE FIRST, THEN DROP. `DROP SCHEMA ... CASCADE` needs every other
        # connection to have let go; issuing it while this engine still holds
        # pooled connections deadlocks against itself — observed as
        # asyncpg DeadlockDetectedError on the first full Postgres run. The
        # drop therefore runs on a throwaway connection after the pool is gone.
        await eng.dispose()
        if schema:
            from sqlalchemy import text
            cleanup = make_engine(pg)
            try:
                async with cleanup.begin() as conn:
                    await conn.execute(
                        text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            finally:
                await cleanup.dispose()


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


#: Two-sided energy-density band, kcal/g, against the STATED portion.
#:
#: The FLOOR is 0.05, not the 0.2 this started at. 0.2 looked defensible and
#: false-positived immediately on jalapenos (5 cal / 35 g = 0.14) — and it
#: would also have failed lettuce (~0.15), celery (~0.16) and cucumber (~0.15),
#: which are real foods that really are that thin. 0.05 still separates the
#: production defect by a wide margin: one cup of rice priced at 1 cal is
#: 0.006 kcal/g, thirty times under the floor and twenty times under the
#: thinnest vegetable. A bound that only holds when you pick the examples is
#: not a bound.
#:
#: The CEILING is `sanity.MAX_KCAL_PER_G`, and it is honestly not the whole
#: story. The other half of the rice defect — 528 cal for one cup — is
#: 3.3 kcal/g: a DRY-grain density on a portion the user described as cooked.
#: No universal ceiling can catch that, because 3.3 is perfectly ordinary for
#: something else. Catching it needs the food's OWN expected density, which is
#: what routing `normalize_quantity().grams` into pricing gives us, and it is
#: gated separately once that lands. Stating the gap here rather than choosing
#: a ceiling low enough to look like it covers the case.
DENSITY_FLOOR = 0.05
DENSITY_CEILING = 9.0


def check_i5(entries):
    """No row may sit outside the band. See DENSITY_FLOOR for what it does and
    does not cover."""
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
        if d < DENSITY_FLOOR or d > DENSITY_CEILING:
            bad.append(f"{e.parsed_food_name!r} {e.quantity!r} "
                       f"{cal:g} cal / {grams:g} g = {d:.3f} kcal/g")
    assert not bad, "I5: implausible energy density — " + "; ".join(bad)


HOLD_RE = re.compile(r"holding the (.+?)(?:\s*[-—.]|$)", re.I)


def check_i3(text, entries, payload):
    """Nothing may be named as HELD while its own receipt says it landed.

    What shipped: "Holding the Challah bread and Honey turkey slices and
    Jalapenos - tell me which kind and it goes on too", one inch under a
    receipt panel reading "Logged Challah bread, 140 cal". `note_held_items`
    diffs the prior turn's FULL parse against THIS turn's commits and has no
    notion of the board, so a row written a turn ago reads as missing.

    The canned tail is the tell: blueberries and fries have no "kind".
    """
    m = HOLD_RE.search(text or "")
    if not m:
        return
    held = [h.strip().lower() for h in re.split(r"\band\b", m.group(1)) if h.strip()]
    on_board = [(e.parsed_food_name or "").lower() for e in entries]
    receipts = " ".join(
        s.get("label", "") for s in
        ((payload.get("reasoning") or {}).get("steps") or [])).lower()
    for h in held:
        clash = [b for b in on_board if h in b or b in h]
        assert not clash, (
            f"I3: {h!r} is named as held but is already on the board as "
            f"{clash!r} — reply={text!r}")
        assert f"logged {h}" not in receipts, (
            f"I3: {h!r} is named as held but its own receipt says Logged — "
            f"receipts={receipts!r}")


#: What `build_prompt` calls the day block it hands the composer.
DAY_STANDS_RE = re.compile(
    r"so\s+(-?[\d,]+)\s+calories\s+and\s+(-?[\d,]+)g?\s+protein\s+left", re.I)


def check_i6(composer_prompts, payload):
    """The number the composer is TOLD and the number the card computes must
    be the same number.

    The shipped turn read "789 cal still in the tank" above a card saying
    "788 cal left". Two independent computations over the same day:
    `TransactionSnapshot.cal_left` is `max(0, target - int(day_cal))` —
    truncate, floor at zero — while the card's `rem_c` is
    `int(round(target - total_cal))` — half-even, negatives allowed. The
    reconciler that was meant to join them writes to `inp["_receipt"]`, a key
    the executor stopped populating when command input became immutable, so it
    has been dead code.

    This asserts the INPUTS rather than the prose, because the prose is a
    model's and the defect is not.
    """
    told = None
    for p in composer_prompts:
        m = DAY_STANDS_RE.search(p or "")
        if m:
            told = (int(m.group(1).replace(",", "")),
                    int(m.group(2).replace(",", "")))
    if told is None:
        return
    for card in cards_of(payload):
        pay = card.get("payload") or {}
        rem_c, rem_p = pay.get("remaining_cal"), pay.get("remaining_protein")
        if rem_c is None and rem_p is None:
            continue
        assert (rem_c, rem_p) == told, (
            f"I6: composer told {told} but the card says "
            f"{(rem_c, rem_p)} — two owners for one day")


def check_i2(payload, entries):
    """A card must stand for a row, and a row should reach the user.

    Two ways this broke. A card with no row is the phantom log — `_logged_entry_card`
    is gated on a real `entry_id` now, so that side is closed. The open side is
    a row with no card: `update_food_entry` renders as `{"type":
    "macro_card_patch"}`, and the shipped client has no decoder case for it, so
    a corrected food updates a real row and draws nothing at all.
    """
    ids = {e.id for e in entries}
    for card in cards_of(payload):
        eid = (card.get("payload") or {}).get("entry_id")
        if eid is None:
            continue
        assert eid in ids, (
            f"I2: card claims entry {eid}, which is not on the board {sorted(ids)}")


def check_i7(composer_prompts, plan):
    """Every food the interpreter parsed must reach the composer.

    "a piece of challah with 3 slice honey turkey and some mayo and jalapaenos"
    came back as "Reading this as challah with three honey turkey slices and a
    small handful of jalapenos" — the MAYO silently absent, then asked about
    separately as if it were new.

    There is no readback template to inspect: the sentence is composer prose.
    So this asserts the INPUT, which is where the loss happens —
    `food_response._priced` drops any item with falsy calories, and the calorie
    join is exact-lowered-name against `data["items"]` only. `validate()` has an
    INVENTED-item rule and no MISSING-item rule, so nothing downstream can
    notice.
    """
    prompt = " ".join(composer_prompts or []).lower()
    if not prompt:
        return
    missing = [it["food"] for it in (plan.get("items") or [])
               if it.get("food", "").lower() not in prompt]
    assert not missing, (
        f"I7: the interpreter parsed {missing} and the composer was never told "
        f"about them — they cannot appear in the readback")


def check_i8_shape(payload):
    """An ask must ship answers, not leave the client to guess them.

    `conversation.py` is the only producer of `Response.buttons`, and on the
    interpreter branch its only option source used to be a branded Open Food
    Facts shelf — so an unbranded portion question shipped nothing and
    `QuickReplyEngine.swift` parsed Arnie's own sentence into "Rice / Cup /
    More than that" for a question about grilled versus fried. Telegram and
    iMessage have no parser at all and shipped no options whatsoever.
    """
    pend = pending_of(payload)
    if not pend:
        return
    for entry in pend:
        for q in (entry.get("questions") or []):
            assert q.get("options"), (
                f"I8: the ask {q.get('text')!r} shipped no options — the "
                f"client has nothing to offer but a guess")


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


# ── The session that prompted all of this ─────────────────────────────────────

#: The 2026-08-03 transcript, verbatim, as (message, interpreter reply) pairs.
#: The interpreter replies are what the model actually decided that evening —
#: including the parts it got wrong, because the invariants are about what the
#: SYSTEM does with a fallible interpreter, not about making the model better.
THE_DAY = [
    ("I just had some ground beef and rice",
     {"action": "ask",
      "points": [{"label": "Ground beef", "qs": ["how much, and what fat %?"]}],
      "items": [item("Ground beef", 240, unit="cup"),
                item("White rice", 205, unit="cup")]}),
    ("Like a cup of each",
     {"action": "log",
      "items": [item("Ground beef, 85/15, cooked", 240, unit="cup"),
                item("White rice, cooked", 205, unit="cup")]}),
    ("I also some chicken and rice",
     {"action": "ask",
      "points": [{"label": "Chicken", "qs": ["grilled or fried, and how much?"]}],
      "items": [item("Chicken", 230, unit="cup")]}),
    ("Grilled like a cup",
     {"action": "log",
      "items": [item("Grilled Chicken", 230, unit="cup")]}),
    ("I also had 3 blueberries 5 French fries and a burger",
     {"action": "ask",
      "points": [{"label": "Burger", "qs": ["fast food or homemade?"]}],
      "items": [item("Blueberries", 3, amount=3, unit="piece"),
                item("French fries", 25, amount=5, unit="piece"),
                item("Burger", 500, unit="burger")]}),
    ("Home made",
     {"action": "log",
      "items": [item("Homemade Burger", 500, unit="burger")]}),
    ("I am also eating a piece of challah with 3 slice honey turkey "
     "and some mayo and jalapaenos",
     {"action": "ask",
      "points": [{"label": "Mayo", "qs": ["a light scrape or a real spread?"]}],
      "items": [item("Challah bread", 140, unit="slice"),
                item("Honey turkey slices", 68, amount=3, unit="slice"),
                item("Jalapenos", 5, unit="handful"),
                item("Mayo", 280, amount=3, unit="tbsp")]}),
    ("Like a few tbsp",
     {"action": "log",
      "items": [item("Mayo", 280, amount=3, unit="tbsp")]}),
]

#: Every food the user reported across the day, once each.
THE_DAYS_FOODS = ["Ground beef", "rice", "Chicken", "Blueberries",
                  "French fries", "Burger", "Challah", "turkey", "Jalapenos",
                  "Mayo"]


@pytest.mark.asyncio
async def test_the_day_that_started_this(client, seeded, edges):
    """The whole exchange, turn by turn, with every applicable invariant.

    This is the regression gate for the session itself. It is deliberately one
    test rather than eight: the defects were in the JOIN between turns, and a
    per-turn test is exactly the shape that missed them the first time.
    """
    board_before = []
    for i, (message, plan) in enumerate(THE_DAY):
        edges.plans.append(plan)
        edges.composer_prompts.clear()
        r = await client.post("/api/v1/chat", json={"message": message})
        assert_turn_ran(edges, r, expect_plans_used=i + 1)
        payload = r.json()
        text = " ".join(payload.get("bubbles") or [])
        board = await rows(seeded)

        where = f"turn {i + 1}/{len(THE_DAY)} ({message[:40]!r})"
        try:
            check_i1(payload)
            check_i2(payload, board)
            check_i3(text, board_before, payload)
            check_i5(board)
            check_i6(edges.composer_prompts, payload)
            check_i7(edges.composer_prompts, plan)
            check_i8_shape(payload)
            check_i9(text)
        except AssertionError as e:
            raise AssertionError(f"{where}: {e}") from None
        board_before = board

    # I4 last: conservation is a claim about the EXCHANGE, not any one turn.
    check_i4(await rows(seeded), THE_DAYS_FOODS)


@pytest.mark.asyncio
async def test_the_card_and_the_sentence_round_the_day_the_same_way(
        client, seeded, edges):
    """I6, forced onto the boundary instead of left to luck.

    The day has two owners with different arithmetic:

      prose  `TransactionSnapshot.protein_left` = max(0, target - day_protein)
             where `day_protein` is an INT FIELD, so the total truncates on the
             way in                                    (core/food_ledger.py)
      card   `rem_p = int(round(protein_target - total_protein))` over a float,
             so it rounds at the end, half-to-even       (core/receipt.py)

    They agree on most numbers, which is why this shipped: the first version of
    this test caught the divergence only because an unrelated duplicate row
    happened to put the day on a .5. Remove the duplicate and it went quiet
    while the bug was untouched.

    So put it on the boundary deliberately. 22.75g + 22.75g = 45.5g against a
    180g target: truncate gives 180-45 = 135, round gives round(134.5) = 134.
    """
    edges.plans.append({"action": "log", "items": [
        dict(item("Cottage cheese", 200), protein=22.75),
        dict(item("Greek yogurt", 150), protein=22.75),
    ]})
    r = await client.post("/api/v1/chat",
                          json={"message": "cottage cheese and greek yogurt"})
    assert_turn_ran(edges, r, expect_plans_used=1)
    payload = r.json()

    told = None
    for p in edges.composer_prompts:
        m = DAY_STANDS_RE.search(p or "")
        if m:
            told = (int(m.group(1).replace(",", "")),
                    int(m.group(2).replace(",", "")))
    assert told is not None, (
        "the composer was never told where the day stands — this test cannot "
        "see the divergence it exists for")
    seen = [((c.get("payload") or {}).get("remaining_cal"),
             (c.get("payload") or {}).get("remaining_protein"))
            for c in cards_of(payload)
            if (c.get("payload") or {}).get("remaining_protein") is not None]
    assert seen, "no card carried remaining figures — nothing to compare"
    for card_vals in seen:
        assert card_vals == told, (
            f"I6: composer told {told}, card says {card_vals} — the day has "
            f"two owners with different rounding")


# ── The other two channels ────────────────────────────────────────────────────
#
# WHY NOT THROUGH THE WEBHOOKS. `POST /webhook/{token}` needs a live
# python-telegram-bot Application on `app.state` (503 without one) and `POST
# /imessage` needs a BlueBubbles signature — and BOTH answer 200 immediately and
# do the turn in a background task, so the HTTP response carries no reply to
# assert against. That plumbing is real, but it is not where food bugs live, and
# `test_webhook_signatures.py` already covers it.
#
# `run_chat_turn` is the seam that matters: its own docstring says the caller
# owns identity and delivery and "this function owns everything in between" —
# routing, the interpreter, pricing, the executor, the renderer. Driving it with
# `platform` varying is what actually asks whether the three channels are equal.

CHANNELS = ("ios", "telegram", "imessage")


async def turn(user_id, text, *, platform):
    """One turn on a given channel, below the transport."""
    import db.database as D
    from core.chat_service import run_chat_turn
    from db.queries import reload_user
    async with D.AsyncSessionLocal() as s:
        user = await reload_user(s, user_id)
        return await run_chat_turn(s, user, text, platform=platform,
                                   schedule_background=False)


@pytest.mark.parametrize("platform", CHANNELS)
@pytest.mark.asyncio
async def test_every_channel_logs_the_same_meal(seeded, edges, platform):
    """The same exchange, the same rows, whichever channel it arrived on.

    Memory's standing rule is three EQUAL channels, and the food lane is shared
    below the transport — so a divergence here would mean something in routing,
    rendering or the executor is reading `platform` when it should not.
    """
    edges.plans.append(THE_DAY[0][1])
    edges.plans.append(THE_DAY[1][1])
    t1 = await turn(seeded, THE_DAY[0][0], platform=platform)
    t2 = await turn(seeded, THE_DAY[1][0], platform=platform)
    assert t1 is not None and t2 is not None

    board = await rows(seeded)
    check_i4(board, ["Ground beef", "rice"])
    check_i5(board)


@pytest.mark.parametrize("platform", CHANNELS)
@pytest.mark.asyncio
async def test_every_channel_gets_the_same_answer_chips(seeded, edges, platform):
    """An ask must offer its choices on every channel, not just the one with a
    client-side parser.

    Only iOS ever had chips, and only because `QuickReplyEngine.swift` guesses
    them from the rendered sentence. Telegram and iMessage shipped none at all —
    the same question, and on two channels out of three the user types. That is
    the asymmetry `_stated_options` closes, and this is what pins it.
    """
    edges.plans.append({
        "action": "ask",
        "points": [{"label": "Burger", "qs": ["fast food or homemade?"]}],
        "items": [item("Burger", 500, unit="burger")],
    })
    t = await turn(seeded, "I had a burger", platform=platform)
    labels = [b.label for b in (t.response.buttons or [])]
    assert labels == ["Fast food", "Homemade"], (
        f"{platform}: expected the question's own choices, got {labels!r}")


@pytest.mark.asyncio
async def test_a_russian_meal_still_reaches_the_lane(seeded, edges):
    """The structured gate is EN-keyed, and that has shipped unlogged food.

    With the model gate on — which is production — a Russian report routes like
    any other. `test_the_regex_gate_alone_cannot_read_russian` below pins the
    blindspot itself, so the day this flag is ever turned off, the cost is
    written down rather than rediscovered.
    """
    edges.plans.append({"action": "log", "items": [
        item("Гречка", 340, unit="cup"), item("Куриная грудка", 165, unit="cup")]})
    t = await turn(seeded, "я съел гречку и куриную грудку", platform="telegram")
    assert t is not None
    board = await rows(seeded)
    assert len(board) == 2, [e.parsed_food_name for e in board]
    check_i5(board)


@pytest.mark.asyncio
async def test_the_regex_gate_admits_russian_without_the_model(seeded, edges,
                                                               monkeypatch):
    """The blindspot is CLOSED, and this is what keeps it closed.

    I wrote this test expecting the opposite. The EN-keyed gate did once ship
    unlogged food in Russian, and the version of this test that asserted that
    failed — because `_food_route_reason` now has an explicit `_non_latin`
    escape that returns "" (admit) instead of "no_food_shape". Its own comment
    records the cost of the old behaviour: "98 of the 301 real food logs this
    gate turned away were rejected for no reason but their alphabet."

    That distinction is the valuable part and it is subtle enough to be worth a
    gate of its own: a message our ASCII shape rules cannot READ is not a
    message that isn't food. So this runs with FOOD_GATE_MODEL OFF deliberately
    — if the escape were ever removed as dead code, the model gate would hide
    it in production and only this test would notice.
    """
    monkeypatch.setenv("FOOD_GATE_MODEL", "false")
    edges.plans.append({"action": "log", "items": [
        item("Гречка", 340, unit="cup"), item("Куриная грудка", 165, unit="cup")]})
    await turn(seeded, "я съел гречку и куриную грудку", platform="telegram")
    board = await rows(seeded)
    assert len(board) == 2, (
        f"a Russian meal did not reach the lane without the model gate: "
        f"{[e.parsed_food_name for e in board]}")


@pytest.mark.asyncio
async def test_the_days_totals_agree_across_endpoints(client, seeded, edges):
    """I10. The card, the reply and GET /api/v1/day are three readers of one
    day; a user who scrolls up must not see a fourth number."""
    for message, plan in THE_DAY:
        edges.plans.append(plan)
        r = await client.post("/api/v1/chat", json={"message": message})
        assert r.status_code == 200, r.text

    board = await rows(seeded)
    day = await client.get("/api/v1/day")
    assert day.status_code == 200, day.text
    body = day.json()

    from_rows = sum(int(e.calories or 0) for e in board)
    from_day = int((body.get("totals") or {}).get("calories") or 0)
    assert from_day == from_rows, (
        f"I10: /api/v1/day reports {from_day} cal, the rows total "
        f"{from_rows} — {[(e.parsed_food_name, e.calories) for e in board]}")
    assert len(body.get("food_entries") or []) == len(board), (
        f"I10: /api/v1/day lists {len(body.get('food_entries') or [])} entries, "
        f"the board has {len(board)}")
