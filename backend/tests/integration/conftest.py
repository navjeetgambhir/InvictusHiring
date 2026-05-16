"""
Shared fixtures for integration tests.

Strategy:
- A real hiring_db_test Postgres database is created once per session.
- Schema is applied from 000_full_schema.sql + migrations 009/010.
- Each test runs inside a transaction that is rolled back on teardown,
  so tests are fully isolated and leave no data behind.
- All OpenAI calls are still mocked — only DB interactions are real.
- If Postgres is unreachable the entire integration suite is skipped.
"""
import asyncio
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

_TEST_DB = "hiring_db_test"
_SYS_DSN = "postgresql://hiring_user:hiring_pass@localhost:5432/postgres"
_TEST_DSN = f"postgresql://hiring_user:hiring_pass@localhost:5432/{_TEST_DB}"
_TEST_ASYNC_URL = f"postgresql+asyncpg://hiring_user:hiring_pass@localhost:5432/{_TEST_DB}?ssl=disable"

_MIGRATIONS_DIR = Path(__file__).parent.parent.parent / "migrations"

_MOCK_SETTINGS = MagicMock(
    openai_api_key="test-key",
    openai_model="gpt-4o",
    database_url=_TEST_ASYNC_URL,
    redis_url="redis://localhost:6379/0",
    rag_top_k=5,
    rag_similarity_threshold=0.5,
    encryption_key="dGVzdGtleXRlc3RrZXl0ZXN0a2V5dGVzdGtleXQ=",
)


def _apply_settings_patch():
    import app.core.config as _cfg
    _cfg.settings = _MOCK_SETTINGS  # type: ignore[assignment]


def _create_test_db() -> None:
    """Synchronously create the test database and apply the full schema."""
    import asyncpg

    async def _setup():
        # Create database (must connect to postgres system DB)
        sys_conn = await asyncpg.connect(_SYS_DSN)
        try:
            await sys_conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
            await sys_conn.execute(f"CREATE DATABASE {_TEST_DB}")
        finally:
            await sys_conn.close()

        # Apply schema
        test_conn = await asyncpg.connect(_TEST_DSN)
        try:
            await test_conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            for filename in [
                "000_full_schema.sql",
                "009_ml_predictions.sql",
                "010_interview_feedback.sql",
            ]:
                sql = (_MIGRATIONS_DIR / filename).read_text()
                await test_conn.execute(sql)
        finally:
            await test_conn.close()

    asyncio.run(_setup())


def _drop_test_db() -> None:
    import asyncpg

    async def _teardown():
        sys_conn = await asyncpg.connect(_SYS_DSN)
        try:
            await sys_conn.execute(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{_TEST_DB}'"
            )
            await sys_conn.execute(f"DROP DATABASE IF EXISTS {_TEST_DB}")
        finally:
            await sys_conn.close()

    asyncio.run(_teardown())


# ── Session-scoped engine ─────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def integration_engine():
    """Create the test DB, apply schema, yield engine, drop DB on teardown."""
    import asyncpg

    # Check DB is reachable
    async def _ping():
        conn = await asyncpg.connect(_SYS_DSN)
        await conn.close()

    try:
        asyncio.run(_ping())
    except Exception:
        pytest.skip("Postgres not reachable — skipping integration tests")

    _apply_settings_patch()
    _create_test_db()

    engine = create_async_engine(_TEST_ASYNC_URL, echo=False)
    yield engine

    asyncio.run(engine.dispose())
    _drop_test_db()


# ── Per-test transactional session ───────────────────────────────────────────

@pytest_asyncio.fixture
async def db(integration_engine):
    """
    Yield a real AsyncSession bound to an open transaction.
    Rolls back after each test so no data persists between tests.
    """
    conn = await integration_engine.connect()
    await conn.begin()
    session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
    yield session
    await session.close()
    await conn.rollback()
    await conn.close()


# ── FastAPI client backed by real DB ─────────────────────────────────────────

@pytest_asyncio.fixture
async def integration_client(db):
    """AsyncClient with real DB session injected and auth bypassed."""
    from httpx import AsyncClient, ASGITransport

    with patch("app.core.config.settings", _MOCK_SETTINGS):
        from app.main import app
        from app.core.database import get_db
        from app.core.dependencies import get_current_user

        async def _override_db():
            yield db

        def _override_auth():
            return MagicMock(id=uuid.uuid4(), role="hr", name="Integration HR")

        app.dependency_overrides[get_db] = _override_db
        app.dependency_overrides[get_current_user] = _override_auth

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac

        app.dependency_overrides.clear()