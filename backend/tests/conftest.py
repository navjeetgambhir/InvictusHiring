"""
Shared fixtures for all tests.

Strategy:
- No real DB or OpenAI calls — everything is mocked.
- FastAPI dependency overrides replace `get_db` with an AsyncMock session.
- OpenAI client is patched at the module level before any test runs.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

# Patch settings before the app is imported so config validation passes
from cryptography.fernet import Fernet as _Fernet  # noqa: E402

_TEST_FERNET_KEY = _Fernet.generate_key().decode()

_MOCK_SETTINGS = MagicMock(
    openai_api_key="test-key",
    openai_model="gpt-4o",
    database_url="postgresql+asyncpg://x:x@localhost/x",
    redis_url="redis://localhost:6379/0",
    rag_top_k=5,
    rag_similarity_threshold=0.75,
    encryption_key=_TEST_FERNET_KEY,
    jwt_secret_key="test-jwt-secret-key-at-least-32-chars!!",
    jwt_expire_minutes=480,
    smtp_host="",
    smtp_port=587,
    smtp_user="",
    smtp_password="",
    smtp_from="noreply@test.com",
    smtp_use_tls=False,
    app_base_url="http://localhost:8000",
    linkedin_access_token="",
    linkedin_author_urn="",
    indeed_publisher_id="",
    google_service_account_json="",
    langsmith_api_key="",
    langsmith_project="test",
    langsmith_tracing="false",
    langsmith_endpoint="https://api.smith.langchain.com",
)

_settings_patch = patch("app.core.config.Settings", return_value=_MOCK_SETTINGS)
_settings_patch.start()

# Also patch the module-level `settings` object used by services
import app.core.config as _cfg  # noqa: E402
_cfg.settings = _MOCK_SETTINGS  # type: ignore[assignment]

from app.main import app  # noqa: E402  (must come after settings patch)
from app.core.database import get_db  # noqa: E402
from app.core.dependencies import get_current_user  # noqa: E402


# ── DB session mock ───────────────────────────────────────────────────────────

def make_db_session() -> AsyncMock:
    """Return a fresh AsyncMock that quacks like an AsyncSession."""
    session = AsyncMock()
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    # execute() returns an object with scalar_one_or_none() and scalars()
    execute_result = MagicMock()
    execute_result.scalar_one_or_none = MagicMock(return_value=None)
    execute_result.scalars = MagicMock(return_value=iter([]))
    session.execute = AsyncMock(return_value=execute_result)
    return session


@pytest.fixture
def db_session() -> AsyncMock:
    return make_db_session()


@pytest_asyncio.fixture
async def client(db_session):
    """AsyncClient with DB and auth dependencies overridden (authenticated as HR)."""
    async def _override_db():
        yield db_session

    def _override_auth():
        return MagicMock(id=uuid.uuid4(), role="hr", name="Test HR")

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_auth
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def unauth_client(db_session):
    """AsyncClient with only DB overridden — auth is NOT bypassed (tests 401 behaviour)."""
    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Reusable test data ────────────────────────────────────────────────────────

@pytest.fixture
def valid_requirements() -> dict:
    return {
        "submitted_by": "hr@example.com",
        "role": "hr",
        "title": "Software Engineer",
        "department": "Engineering",
        "location": "London, UK",
        "salary_band": "£60,000 – £80,000",
        "required_skills": ["Python", "FastAPI", "PostgreSQL"],
        "nice_to_have_skills": ["Docker", "Kubernetes"],
        "company_description": "A leading fintech company.",
        "additional_context": None,
    }


@pytest.fixture
def sample_session_id() -> uuid.UUID:
    return uuid.uuid4()