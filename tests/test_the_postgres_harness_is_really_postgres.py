"""The Postgres harness must actually be Postgres, and actually be isolated.

`17da24f` replaced asyncpg with psycopg3 in `requirements.txt` — "chosen over
asyncpg because it [supports] Python 3.14" — and left `test_a_full_day_of_food`
rewriting the engine URL back to `+asyncpg`. The shared `app_db` fixture
therefore raised `ModuleNotFoundError` at setup, and every suite depending on it
errored before running a line.

Measured 2026-08-09 against a real PostgreSQL 16: **115 errors across ten
files**, every one that same import, all funnelling through that one fixture.
Among them `test_b1b1_system_matrix.py`, which IS the B-1b.1 promotion gate
("production-like system matrix green, real enrichment exercised") — so for
three days that gate was not merely undischarged, its 22 tests were absent while
the pricing workstream and B-1.5E landed on top of it.

TWO FAILURE MODES, AND THE SECOND IS THE DANGEROUS ONE. A missing driver is
loud: nothing runs and CI is red. But `connect_args={"server_settings": …}` is
asyncpg's spelling, and psycopg3 ignores it — so fixing only the URL would have
left every harness test reading and writing `public` while believing it had a
private schema. That is green, wrong, and invisible: the tests write real rows
and count them back, so a neighbour's leftovers do not fail loudly, they fail as
an off-by-one somewhere unrelated. Hence a test for the isolation itself and not
just for the connection.

Everything here needs a real Postgres and skips without one.
"""
import os
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text

PG = os.getenv("TEST_POSTGRES_URL")
pg_only = pytest.mark.skipif(not PG, reason="needs a real Postgres")


def _code_without_comments(path: str) -> str:
    """The file's CODE, with comments stripped.

    Written after the naive version of this check failed on the comment
    explaining why `+asyncpg` is wrong. A ratchet that cannot tell code from
    the prose warning about it is a ratchet that punishes documentation — and
    the next person's fix is to delete the explanation, which is exactly
    backwards.
    """
    import io
    import tokenize

    kept = []
    with open(path, "rb") as handle:
        for token in tokenize.tokenize(handle.readline):
            if token.type != tokenize.COMMENT:
                kept.append(token.string)
    return "\n".join(kept)


def test_the_harness_does_not_rewrite_the_configured_driver():
    """THE CONTRACT IS "USE WHAT WAS CONFIGURED", not "asyncpg must not exist".

    An earlier version of this asserted `find_spec("asyncpg") is None`. That is
    a stronger claim than the contract and belongs to dependency policy, not to
    this harness: if asyncpg were installed tomorrow as some unrelated
    package's transitive dependency, that assertion would fail while the
    harness remained perfectly correct. A ratchet that fires on a change it
    does not actually care about is one people learn to delete.

    What genuinely must hold is that the harness passes the configured URL
    through. `17da24f` broke exactly this — it moved the project to psycopg3
    and left the fixture rewriting the URL back to `+asyncpg`, so the harness
    asked for a driver the project had just removed and every dependent suite
    errored at setup.

    Runs without Postgres on purpose: it is a statement about the source, and
    the point is that it fires on a machine where nobody would otherwise
    notice. Whether the configured driver is actually installed is a different
    question, asked below against the real URL.
    """
    code = _code_without_comments("tests/test_a_full_day_of_food.py")
    assert "+asyncpg" not in code, (
        "the Postgres harness rewrites its URL to a driver other than the "
        "configured one; this is the 115-error failure from 2026-08-06")
    assert "server_settings" not in code, (
        "server_settings is asyncpg's spelling and psycopg3 IGNORES it — the "
        "schema would silently fall back to public")


@pg_only
def test_the_configured_driver_can_actually_be_loaded():
    """Whatever `TEST_POSTGRES_URL` names must be importable.

    Driver-agnostic by construction: it asks SQLAlchemy to resolve the DBAPI
    for the URL as configured, so it keeps working if the project ever moves
    to a different driver — and it fails, loudly and early, if the configured
    one is missing. That is the failure CI actually had, expressed as its own
    cause rather than as 115 downstream setup errors.
    """
    from sqlalchemy.engine import make_url

    url = make_url(PG)
    dialect = url.get_dialect()
    try:
        dialect.import_dbapi()
    except ImportError as exc:                      # pragma: no cover - the bug
        raise AssertionError(
            f"TEST_POSTGRES_URL names driver {url.drivername!r}, whose DBAPI "
            f"is not installed ({exc}). Every Postgres-backed suite will error "
            f"at fixture setup.") from exc


@pytest_asyncio.fixture
async def isolated():
    """A private schema on the real engine, exactly as `app_db` builds one."""
    from db.database import make_engine

    schema = f"probe_{uuid.uuid4().hex[:12]}"
    engine = make_engine(PG, connect_args={"options": f"-csearch_path={schema}"})
    async with engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema}"'))
    yield engine, schema
    await engine.dispose()
    cleanup = make_engine(PG)
    try:
        async with cleanup.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
    finally:
        await cleanup.dispose()


@pg_only
@pytest.mark.asyncio
async def test_the_engine_connects_at_all(isolated):
    engine, _ = isolated
    async with engine.begin() as conn:
        assert (await conn.execute(text("SELECT 1"))).scalar() == 1
        version = (await conn.execute(text("SHOW server_version"))).scalar()
    assert version, "connected to something that is not Postgres"


@pg_only
@pytest.mark.asyncio
async def test_a_table_lands_in_the_private_schema_not_public(isolated):
    """THE ASSERTION THAT MATTERS. `SHOW search_path` reflecting the schema is
    not proof — it would also be set if the option were applied and then
    overridden. Where the table physically lands is the fact.

    ASK ABOUT *THIS* SCHEMA, never "which schema has a table called X". The
    database is shared: an interrupted run or a concurrent harness can leave a
    `probe_row` behind elsewhere, and then an unqualified catalog lookup
    returns several rows and `.scalar()` picks one arbitrarily — reporting a
    correctly isolated engine as broken. That is not hypothetical; the `users`
    assertion below was written the wrong way first and did exactly that.
    """
    engine, schema = isolated
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE probe_row (id int)"))
        here = (await conn.execute(text(
            "SELECT count(*) FROM pg_tables "
            "WHERE schemaname = :s AND tablename = 'probe_row'"),
            {"s": schema})).scalar()

    # ONE ASSERTION, AND ONLY ABOUT OUR OWN SCHEMA. It is sufficient: if the
    # search_path option were ignored, the CREATE would land in `public` and
    # this count would be 0.
    #
    # A companion `public has no probe_row` check was written here and removed.
    # It fails on a leftover this engine did not create — an interrupted run,
    # another harness — which makes the test a statement about the shared
    # database's tidiness rather than about isolation. That is the same
    # shared-state fragility the unqualified lookup had, wearing a stricter
    # face, and a test that fails for reasons outside its subject is how a
    # suite earns the right to be ignored.
    assert here == 1, (
        f"the harness did not write into its private schema {schema!r} — "
        f"tests would be sharing state and failing as unrelated off-by-ones")


@pg_only
@pytest.mark.asyncio
async def test_two_harnesses_do_not_see_each_other(isolated):
    """What the isolation is FOR. Two fixtures alive at once must not read one
    another's rows — the property that makes a count-based assertion safe."""
    from db.database import make_engine

    engine, schema = isolated
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE shared_name (id int)"))
        await conn.execute(text("INSERT INTO shared_name VALUES (1), (2)"))

    other_schema = f"probe_{uuid.uuid4().hex[:12]}"
    other = make_engine(PG, connect_args={
        "options": f"-csearch_path={other_schema}"})
    try:
        async with other.begin() as conn:
            await conn.execute(
                text(f'CREATE SCHEMA IF NOT EXISTS "{other_schema}"'))
            await conn.execute(text("CREATE TABLE shared_name (id int)"))
            mine = (await conn.execute(
                text("SELECT count(*) FROM shared_name"))).scalar()
        assert mine == 0, (
            f"a second harness saw {mine} rows from the first — the schemas "
            f"are not isolated and every count assertion in the suite is "
            f"reading someone else's data")
    finally:
        await other.dispose()
        cleanup = make_engine(PG)
        try:
            async with cleanup.begin() as conn:
                await conn.execute(
                    text(f'DROP SCHEMA IF EXISTS "{other_schema}" CASCADE'))
        finally:
            await cleanup.dispose()


@pg_only
@pytest.mark.asyncio
async def test_the_app_harness_itself_builds_and_isolates():
    """The real fixture, not a reconstruction of it. If `app_db` regresses,
    this fails here rather than as 115 errors somewhere else.
    """
    from tests.test_a_full_day_of_food import app_db

    agen = app_db.__wrapped__()
    engine = await agen.__anext__()
    try:
        async with engine.begin() as conn:
            path = (await conn.execute(text("SHOW search_path"))).scalar()
            # ASK WHETHER THE TABLE IS IN *THIS* SCHEMA — do not ask which
            # schema has a table called `users`. Other suites in this repo bind
            # `make_engine(PG)` with no schema and build their tables in
            # `public`, so that second question has several right answers and
            # returns an arbitrary one. The first version of this assertion did
            # exactly that and reported a passing fixture as broken.
            here = (await conn.execute(text(
                "SELECT count(*) FROM pg_tables "
                "WHERE schemaname = :s AND tablename = 'users'"),
                {"s": path})).scalar()
            total = (await conn.execute(text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = :s"),
                {"s": path})).scalar()
        assert path.startswith("harness_"), \
            f"app_db did not pin a private schema (search_path={path!r})"
        assert here == 1, \
            f"app_db's own schema {path!r} has no `users` table — its DDL went " \
            f"somewhere else, and every count assertion in the suite is then " \
            f"reading another schema's rows"
        assert total > 10, \
            f"only {total} tables in {path!r}; the harness did not build the " \
            f"full schema it claims to"
    finally:
        with pytest.raises(StopAsyncIteration):
            await agen.__anext__()
