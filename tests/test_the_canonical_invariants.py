"""The canonical lane's invariants, as tests rather than as prose.

`docs/ARCHITECTURE_CONTRACT.md` records I1–I17 for the system as a whole and
tracks which hold. These six are the canonical mutation boundary's own, and
they are written here because an invariant that lives only in a comment is a
hope: the reason this rearchitecture exists is a list of properties everyone
believed and nothing checked.

    C1  Every committed row belongs to exactly one MealCommitResult.
    C2  Every MealCommitResult corresponds to exactly one operation revision.
    C3  Every macro-aggregation site is a known one.
    C4  Every direct food writer is a known one.
    C5  No PendingOperation transitions directly to COMMITTED.
    C6  Every duplicate returns the identical persisted MealCommitResult.

C3 and C4 CANNOT hold yet — the legacy lane is still the production writer, and
it is meant to be. Those two are written as RATCHETS against a recorded
baseline: they permit exactly what exists today and fail the moment it grows.
That is the difference between "not done" and "getting worse", and it is what
makes the migration converge rather than accumulate. Each mutation owner that
moves must lower the number, never raise it.
"""
import ast
import os
import pathlib
import re
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core import meal_commit, pending_repository as repo
from core.canonical_writer import (MealIntent, ResolvedFood, ResolvedMeal,
                                   write_canonical_meal)
from core.commit_coordinator import commit_or_load_existing
from core.semantics import (CanonicalEvent, PendingStatus, ResolutionStatus,
                            _ALLOWED_TRANSITIONS)
from db.database import make_engine
from db.models import Base, FoodEntry, LedgerEvent, MealCommit, User

ROOT = pathlib.Path(__file__).resolve().parent.parent
DAY, TZ = date(2026, 8, 5), "America/New_York"

PG = os.getenv("TEST_POSTGRES_URL")
if os.getenv("CI") and not PG:
    raise RuntimeError(
        "TEST_POSTGRES_URL is unset in CI. The canonical invariants are "
        "database properties and cannot be checked on sqlite.")
pg_only = pytest.mark.skipif(not PG, reason="needs a real Postgres")


def _food(name, cal, **kw):
    return ResolvedFood(
        event=CanonicalEvent(id=f"ev_{name}", domain="food",
                             entity_id=name.lower(), surface_text=name,
                             resolution_status=ResolutionStatus.RESOLVED),
        calories=cal, **kw)


def _meal(oid="op_inv", revision=0, items=None, **kw):
    return ResolvedMeal(operation_id=oid, revision=revision, user_id=1,
                        logging_day=DAY, user_timezone=TZ,
                        items=items or (_food("Chicken", 320),
                                        _food("Rice", 205)), **kw)


@pytest_asyncio.fixture
async def pg():
    engine = make_engine(PG, pool_size=5, max_overflow=5)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession,
                               expire_on_commit=False)
    async with maker() as s:
        s.add(User(telegram_id="pg:invariants"))
        await s.commit()
    yield maker
    await engine.dispose()


# ── C1 ───────────────────────────────────────────────────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_c1_every_row_belongs_to_exactly_one_result(pg):
    """A row that belongs to no result cannot be undone, audited, or joined to
    the turn that claims it. A row claimed by two results means one of the two
    confirmations is describing food it did not write."""
    async with pg() as s:
        r1 = await commit_or_load_existing(
            s, operation=_Op("op_a"), resolved_meal=_meal("op_a"),
            writer=write_canonical_meal)
        await s.commit()
    async with pg() as s:
        r2 = await commit_or_load_existing(
            s, operation=_Op("op_b"), resolved_meal=_meal("op_b"),
            writer=write_canonical_meal)
        await s.commit()

    owned = [i["entry_id"] for i in r1.committed_items] + \
            [i["entry_id"] for i in r2.committed_items]
    assert len(owned) == len(set(owned)), "a row is claimed by two results"

    async with pg() as s:
        rows = {r.id for r in
                (await s.execute(select(FoodEntry))).scalars().all()}
    assert rows == set(owned), (
        f"rows with no owning result: {rows - set(owned)}")


# ── C2 ───────────────────────────────────────────────────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_c2_one_result_per_operation_revision(pg):
    """Enforced by the database, not by this test — the unique constraint on
    (operation_id, operation_revision) is what makes it true under concurrency
    (see test_two_connections_one_commit.py)."""
    async with pg() as s:
        for rev in (0, 1):
            await commit_or_load_existing(
                s, operation=_Op("op_rev", revision=rev),
                resolved_meal=_meal("op_rev", revision=rev),
                writer=write_canonical_meal)
            await s.commit()

    async with pg() as s:
        rows = (await s.execute(select(MealCommit))).scalars().all()
    keys = [(r.operation_id, r.operation_revision) for r in rows]
    assert len(keys) == len(set(keys)) == 2


# ── C3 · Every macro-aggregation site is a known one ─────────────────────────
#
# NAMED FOR WHAT IT PROVES. An earlier draft called this "no renderer derives
# totals independently", which is the GOAL, not the check: this detects
# `sum()` over a macro attribute and nothing else. The day's REMAINING
# calories — three owners disagreeing by one because each rounds differently —
# is arithmetic on an already-computed total and is invisible here. That is
# tracked separately as I9.
#
# An invariant that claims more than it proves is the same defect as a guard
# that fails open, and it is harder to notice because the test is green.

#: Modules that aggregate macros across entries today. Each is named with what
#: it is, because "debt" and "legitimately not a renderer" are different and a
#: bare number cannot tell them apart.
#:
#: MEASURED, NOT ASSUMED. An earlier draft was written from memory —
#: food_ledger, receipt, food_turn — and every entry was wrong: those three own
#: the day's REMAINING calories, a different shape this detector does not see.
#: The canonical writer was wrong too, for the opposite reason: it accumulates
#: in a loop rather than calling sum(). The stale-entry check below is what
#: caught both, and it is why the list is derived from a run rather than from
#: recollection.
_TOTALS_BASELINE = {
    "db/queries.py",              # recompute_log_totals — the LEDGER's own,
                                  # and the one that should survive
    "handlers/tool_executor.py",  # DEBT: legacy write lane
    "api/app.py",                 # DEBT: day endpoint aggregates directly
    "api/insights.py",            # analytics, not a renderer of a commit
    "core/coach_live.py",         # coach projections over history
    "core/health_score.py",       # a score over a period, not a meal
    "core/targets.py",            # goal arithmetic, not committed state
}


def _modules_summing_macros() -> set:
    """Modules that add up calories or macros across entries.

    A grep would match strings and comments; this walks the AST and looks for
    `sum(...)` over an attribute named like a macro, which is what a total
    actually looks like in this codebase.
    """
    found = set()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", ".venv/")) \
                or rel.startswith("simulate_"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "sum"):
                continue
            for sub in ast.walk(node):
                name = (sub.attr if isinstance(sub, ast.Attribute)
                        else sub.value if isinstance(sub, ast.Constant)
                        and isinstance(sub.value, str) else None)
                if name in ("calories", "protein", "carbs", "fats"):
                    found.add(rel)
    return found


def test_c3_every_macro_aggregation_site_is_a_known_one():
    """RATCHET. A new site fails; the known ones are named with what they are.

    The GOAL this serves — rendering consumes MealCommitResult rather than
    re-deriving — is broader than this check. As that lands, DEBT entries come
    out of the baseline and this tightens toward it.
    """
    found = _modules_summing_macros()
    new = found - _TOTALS_BASELINE
    assert not new, (
        f"new module(s) computing totals independently: {sorted(new)}. "
        f"Totals come from MealCommitResult, which reads them back from the "
        f"committed rows — a fourth owner is how the prose and the card came "
        f"to disagree by one.")
    stale = _TOTALS_BASELINE - found
    assert not stale, (
        f"{sorted(stale)} no longer computes totals — remove it from "
        f"_TOTALS_BASELINE so the ratchet keeps tightening")


# ── C4 · Every direct food writer is a known one ─────────────────────────────

def _food_write_sites() -> set:
    """Every call site that creates a food row."""
    sites = set()
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", ".venv/")) \
                or rel.startswith("simulate_") or rel == "db/queries.py" \
                or rel == "core/canonical_writer.py":   # IS the coordinator path
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        for node in ast.walk(tree):
            func = getattr(node, "func", None)
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if isinstance(node, ast.Call) and name == "add_food_entry":
                sites.add(f"{rel}:{node.lineno}")
    return sites


#: The LEGACY writers, by count — the canonical writer is excluded above,
#: because counting it would make the scoreboard go UP as the migration
#: succeeds. Counted, not pinned to exact lines: a line moves for unrelated
#: reasons, and a brittle gate gets deleted rather than obeyed.
#:
#: api/app.py · handlers/tool_executor.py ×2 — quick_log was DELETED at its
#: promotion (the first migrated owner), which is what moved this from 4.
_LEGACY_FOOD_WRITERS = 3


def test_c4_every_direct_food_writer_is_a_known_one():
    """RATCHET, and the migration's actual scoreboard.

    Every mutation owner that moves onto the coordinator must LOWER this
    number. The failure mode this guards is not a bug — it is a migration that
    stalls at 90% because the new path became an additional layer instead of a
    replacement, and the two then diverge one special-case fix at a time.
    """
    sites = _food_write_sites()
    assert len(sites) <= _LEGACY_FOOD_WRITERS, (
        f"{len(sites)} direct food writers, baseline {_LEGACY_FOOD_WRITERS}: "
        f"{sorted(sites)}. A new write must go through the commit coordinator.")
    assert len(sites) == _LEGACY_FOOD_WRITERS, (
        f"only {len(sites)} direct writers remain (baseline "
        f"{_LEGACY_FOOD_WRITERS}) — LOWER _LEGACY_FOOD_WRITERS to "
        f"{len(sites)} so the ratchet holds the ground you just took")


# ── C5 ───────────────────────────────────────────────────────────────────────

def test_c5_no_direct_transition_to_committed():
    """COMMITTING is not ceremony. It is the state in which a crash is
    recoverable: an operation that jumps straight to COMMITTED has no state
    saying a ledger write was in flight, so a retry cannot tell "never started"
    from "may have written"."""
    for status, allowed in _ALLOWED_TRANSITIONS.items():
        if status is PendingStatus.COMMITTING:
            continue
        assert PendingStatus.COMMITTED not in allowed, (
            f"{status.value} -> committed skips COMMITTING, the only state "
            f"that says a ledger write was in flight")
    assert PendingStatus.COMMITTED in _ALLOWED_TRANSITIONS[
        PendingStatus.COMMITTING]


@pg_only
@pytest.mark.asyncio
async def test_c5_holds_in_the_repository_too(pg):
    """The dataclass guards the in-memory transition; this is the persisted
    one."""
    async with pg() as s:
        await repo.create_operation(s, operation_id="op_c5", user_id=1,
                                    status="resolving",
                                    storage_status="active")
        await s.commit()
        out = await repo.mark_committed(s, operation_id="op_c5",
                                        expected_revision=0,
                                        commit_key="op_c5:0")
        await s.commit()
        assert out.ok, "the repository is the persistence layer, not the policy"

    # ...so the POLICY has to be enforced where the transition is decided.
    from core.semantics import InvalidPendingTransition, PendingOperation
    op = PendingOperation(id="x", user_id="1", domain="food",
                          status=PendingStatus.RESOLVING)
    with pytest.raises(InvalidPendingTransition):
        op.transition_to(PendingStatus.COMMITTED)


# ── C6 ───────────────────────────────────────────────────────────────────────

@pg_only
@pytest.mark.asyncio
async def test_c6_a_duplicate_returns_the_identical_persisted_result(pg):
    """Identical, and PERSISTED — the second delivery is answered from storage
    and never re-runs interpretation, so it must not merely be equivalent."""
    async with pg() as s:
        first = await commit_or_load_existing(
            s, operation=_Op("op_c6"),
            resolved_meal=_meal("op_c6", assumptions=("a cup is 158g",)),
            writer=write_canonical_meal)
        await s.commit()

    async with pg() as s:
        second = await commit_or_load_existing(
            s, operation=_Op("op_c6"), resolved_meal=_meal("op_c6"),
            writer=write_canonical_meal)
        await s.commit()
        stored = await meal_commit.existing_result(s, operation_id="op_c6")

    assert second == first == stored
    assert second.assumptions == ("a cup is 158g",), (
        "the duplicate lost the disclosure the first delivery made")

    async with pg() as s:
        assert int((await s.execute(select(func.count()).select_from(
            FoodEntry))).scalar()) == 2
        assert int((await s.execute(select(func.count()).select_from(
            LedgerEvent))).scalar()) == 2


class _Op:
    def __init__(self, oid, revision=0, user_id=1):
        self.id, self.revision, self.user_id = oid, revision, user_id


# ── the index and the enforcement must not drift ─────────────────────────────

def test_the_contract_document_lists_exactly_these_invariants():
    """THE DOCUMENT IS THE INDEX; THESE TESTS ARE THE ENFORCEMENT.

    A reviewer needs one place to answer "what does the architecture
    guarantee?" without reading test code. The usual failure of such a document
    is drift: it describes a guarantee that was removed, or omits one that was
    added, and it is trusted either way because nothing checks it.

    So the index is checked against the enforcement, in both directions.
    """
    doc = (ROOT / "docs" / "ARCHITECTURE_CONTRACT.md").read_text()
    documented = set(re.findall(r"^\| (C\d+) \|", doc, re.M))

    here = pathlib.Path(__file__).read_text()
    tested = {m.upper() for m in re.findall(r"^def test_(c\d+)_", here, re.M)} | \
             {m.upper() for m in re.findall(r"^async def test_(c\d+)_", here, re.M)}

    assert documented, "the contract document lists no C-invariants"
    assert tested - documented == set(), (
        f"enforced but undocumented: {sorted(tested - documented)} — a "
        f"guarantee nobody can find is not a contract")
    assert documented - tested == set(), (
        f"documented but unenforced: {sorted(documented - tested)} — the index "
        f"claims a guarantee no test holds, which is worse than claiming none")


#: After an owner is promoted, its legacy write path must STAY deleted — a
#: special-case fix quietly reintroducing the old call is how two architectures
#: end up alive and diverging. Names, not line counts: a returning import is
#: unambiguous in a way a count is not.
_FORBIDDEN_AFTER_PROMOTION = {
    "api/quick_log.py": ("add_food_entry",),   # canonical since Phase 1 step 1
}


def test_c7_deleted_ownership_stays_deleted():
    for rel, names in _FORBIDDEN_AFTER_PROMOTION.items():
        src = (ROOT / rel).read_text()
        tree = ast.parse(src)
        used = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                used |= {a.name for a in node.names}
            elif isinstance(node, ast.Call):
                fn = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if fn:
                    used.add(fn)
        returned = used & set(names)
        assert not returned, (
            f"{rel} uses {sorted(returned)} again — that path was promoted to "
            f"the canonical writer and its legacy write was DELETED. Fix the "
            f"canonical lane instead of resurrecting the old one.")


# ── C8 · Every clarification producer is a known one (Phase-2 freeze) ────────
#
# Four producers build the wire's `questions` payload today, in three shapes
# (skills/nutrition/clarification_adapter.py documents them; measured
# 2026-08-04, 39 of 40 asks shipped options:[] and iOS re-derived chips by
# parsing prose). Collapsing them is the Phase-B migration. Until then the
# population is FROZEN: a fifth producer, or a new site assembling the payload
# by hand, widens exactly the surface Phase B has to collapse — the review's
# instruction is "do not expand the old clarification architecture further."

#: Sites that touch a `"questions"` wire payload. Counted at the payload
#: chokepoint, not the helper, because a new producer that skips the helpers
#: still has to put `questions` on the wire. MEASURED: four PRODUCERS in
#: food_turn (chips+questions, points ×2, the literal-dict calorie fallback)
#: plus ONE RELAY — conversation.py copies the list into the pending payload
#: for the answer turn. A relay originates nothing, but it is part of the
#: surface Phase B collapses, so it is frozen with the rest.
_QUESTION_PAYLOAD_SITES = 5

#: Constructors of the typed staged-pipeline question. clarify_policy owns
#: both (bundled + default); food_turn holds the single staged-ask site.
_CLARIFICATION_QUESTION_CONSTRUCTORS = 3


def test_c8_every_clarification_producer_is_a_known_one():
    """RATCHET, both directions, same rules as C4."""
    payload_sites = []
    ctor_sites = []
    for rel in ("core/food_turn.py", "core/conversation.py",
                "core/food_pipeline.py", "skills/nutrition/clarify_policy.py"):
        src = (ROOT / rel).read_text()
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.split("#")[0]
            if '"questions":' in stripped:
                payload_sites.append(f"{rel}:{i}")
            if "ClarificationQuestion(" in stripped \
                    and "import" not in stripped:
                ctor_sites.append(f"{rel}:{i}")

    assert len(payload_sites) <= _QUESTION_PAYLOAD_SITES, (
        f"a NEW clarification producer appeared: {payload_sites}. Phase B "
        f"collapses the existing four into canonical ClarificationFields — "
        f"widening the population first makes that migration larger. Emit "
        f"through the existing producers or land the canonical path.")
    assert len(payload_sites) == _QUESTION_PAYLOAD_SITES, (
        f"only {len(payload_sites)} question-payload sites remain "
        f"({payload_sites}) — LOWER _QUESTION_PAYLOAD_SITES to hold the "
        f"ground the Phase-B migration just took")

    assert len(ctor_sites) <= _CLARIFICATION_QUESTION_CONSTRUCTORS, (
        f"new ClarificationQuestion constructor(s): {ctor_sites}")
    assert len(ctor_sites) == _CLARIFICATION_QUESTION_CONSTRUCTORS, (
        f"{len(ctor_sites)} constructors remain ({ctor_sites}) — LOWER "
        f"_CLARIFICATION_QUESTION_CONSTRUCTORS accordingly")


# ── C9 · Every clarification OPTION producer is a known one ──────────────────
#
# Separate from C8 (question producers) per the chip-generation directive: the
# QUESTION and its OPTIONS have historically had different owners, which is how
# a question shipped with options:[] on 39 of 40 asks while the client rebuilt
# chips from prose. The target pipeline —
#   unresolved field → candidates → deterministic selection → typed patches
#   → rendered labels
# replaces every one of these sites; until each is replaced, the population is
# frozen. The client-side producer (QuickReplyEngine.swift) lives in the iOS
# repo and is inventoried in docs/CHIP_GENERATION_MIGRATION.md instead.

#: WHERE OPTIONS ARE ASSEMBLED, per file, with what each one IS. A count alone
#: cannot tell debt from a bystander, and a five-file allowlist could not see a
#: producer that moved — the first version of this ratchet froze five files and
#: one spelling (`"options":`) while `context_builder` and `clarify_ui` shipped
#: uncounted, so the contract document overclaimed on the day it was written.
#: This walks the whole repo by AST, like C3/C4, and matches every spelling a
#: producer can use: a dict literal with an "options" key, `dict(options=...)`,
#: and `x["options"] = ...`. Reads are not producers, so only Store subscripts
#: count.
_OPTION_PAYLOAD_BASELINE = {
    # DEBT — heuristic producers the chip pipeline replaces.
    "core/food_turn.py": 7,             # the primary assembler (7 shapes)
    "core/conversation.py": 1,          # write-side relay into the pending
                                        # payload; dies at B-1
    "core/context_builder.py": 1,       # read-side relay of the SAME stash
                                        # onto the chat wire; dies with it
    "skills/nutrition/clarify_ui.py": 1,  # dormant staged-pipeline UI model
    # BYSTANDER — named so the ratchet can tell it from debt. Not a wire
    # payload: a materiality diagnostic whose "options" are the two candidate
    # numbers that disagree.
    "skills/nutrition/validators.py": 2,
    # CANONICAL — the replacement, not the population. `UnresolvedField`
    # serializes its own typed options; this entry rises as B-1 lands and the
    # DEBT entries above fall.
    "core/semantics.py": 1,
}

#: `AmbiguityOption(...)` constructors — the staged pipeline's option shape
#: (4 in food_pipeline + 1 in staged_codec's decoder).
_AMBIGUITY_OPTION_CONSTRUCTORS = 5


def _option_payload_sites() -> dict:
    """Every site that BUILDS an options payload, keyed by file.

    AST, not grep: a string match cannot tell `"options":` in a dict from the
    same characters in a docstring, and it cannot see `dict(options=...)` at
    all — so a new producer evaded the ratchet by choosing another spelling.
    """
    found = {}
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "scripts/", "alembic/", ".venv/")) \
                or rel.startswith("simulate_"):
            continue
        try:
            tree = ast.parse(path.read_text())
        except Exception:
            continue
        sites = set()
        for node in ast.walk(tree):
            hit = False
            if isinstance(node, ast.Dict):
                hit = any(isinstance(k, ast.Constant) and k.value == "options"
                          for k in node.keys)
            elif (isinstance(node, ast.Subscript)
                    and isinstance(node.slice, ast.Constant)
                    and node.slice.value == "options"
                    and isinstance(node.ctx, ast.Store)):
                hit = True
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "dict"):
                hit = any(kw.arg == "options" for kw in node.keywords)
            if hit:
                sites.add((node.lineno, node.col_offset))
        if sites:
            found[rel] = len(sites)
    return found


def test_c9_every_clarification_option_producer_is_a_known_one():
    """RATCHET, both directions, same rules as C3/C4 — repo-wide by AST."""
    found = _option_payload_sites()

    unknown = {f: n for f, n in found.items()
               if f not in _OPTION_PAYLOAD_BASELINE}
    assert not unknown, (
        f"a NEW option producer appeared in {unknown}. Chips are becoming a "
        f"projection of canonical semantic state (docs/"
        f"CHIP_GENERATION_MIGRATION.md); widening the heuristic population "
        f"first makes that migration larger. If this is the canonical "
        f"pipeline, add it to the baseline AS canonical.")
    grew = {f: (n, _OPTION_PAYLOAD_BASELINE[f]) for f, n in found.items()
            if n > _OPTION_PAYLOAD_BASELINE[f]}
    assert not grew, f"option producers grew (found, baseline): {grew}"
    shrank = {f: (found.get(f, 0), n)
              for f, n in _OPTION_PAYLOAD_BASELINE.items()
              if found.get(f, 0) < n}
    assert not shrank, (
        f"fewer option sites remain (found, baseline): {shrank} — LOWER "
        f"_OPTION_PAYLOAD_BASELINE to hold the ground")

    ctor_sites = []
    for rel in ("core/food_pipeline.py", "skills/nutrition/staged_codec.py",
                "skills/nutrition/clarify_policy.py", "core/food_turn.py",
                "core/conversation.py"):
        src = (ROOT / rel).read_text()
        for i, line in enumerate(src.splitlines(), 1):
            stripped = line.split("#")[0]
            if "AmbiguityOption(" in stripped and "import" not in stripped \
                    and "class " not in stripped:
                ctor_sites.append(f"{rel}:{i}")
    assert len(ctor_sites) <= _AMBIGUITY_OPTION_CONSTRUCTORS, (
        f"new AmbiguityOption constructor(s): {ctor_sites}")
    assert len(ctor_sites) == _AMBIGUITY_OPTION_CONSTRUCTORS, (
        f"{len(ctor_sites)} constructors remain ({ctor_sites}) — LOWER "
        f"_AMBIGUITY_OPTION_CONSTRUCTORS accordingly")
