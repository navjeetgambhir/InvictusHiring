"""
Integration tests — analytics agent live schema introspection.

Verifies that _fetch_live_schema() correctly reads the real database
schema, excludes internal tables, and produces a prompt-ready string
that the SQL generation prompt can use.
"""
import pytest

pytestmark = pytest.mark.asyncio

_EXPECTED_TABLES = {
    "jd_requests",
    "jd_drafts",
    "candidate_applications",
    "chat_messages",
    "job_postings",
    "interview_invitations",
    "users",
}

_EXCLUDED_TABLES = {"agent_runs", "past_jds"}


async def test_fetch_live_schema_includes_analytics_tables(db):
    from app.services.analytics_agent import _fetch_live_schema

    # Reset the module-level cache so we read from the real DB
    import app.services.analytics_agent as aa_mod
    aa_mod._schema_cache = None

    schema = await _fetch_live_schema(db)

    for table in _EXPECTED_TABLES:
        assert table in schema, f"Expected table '{table}' missing from schema string"


async def test_fetch_live_schema_excludes_internal_tables(db):
    from app.services.analytics_agent import _fetch_live_schema
    import app.services.analytics_agent as aa_mod
    aa_mod._schema_cache = None

    schema = await _fetch_live_schema(db)

    for table in _EXCLUDED_TABLES:
        assert table not in schema, f"Internal table '{table}' should be excluded from schema"


async def test_fetch_live_schema_includes_key_columns(db):
    from app.services.analytics_agent import _fetch_live_schema
    import app.services.analytics_agent as aa_mod
    aa_mod._schema_cache = None

    schema = await _fetch_live_schema(db)

    # Spot-check important columns that the analytics SQL prompt relies on
    assert "session_id" in schema
    assert "screening_score" in schema
    assert "shortlisted" in schema
    assert "status" in schema


async def test_fetch_live_schema_is_cached(db):
    """Second call should return the same object without hitting the DB again."""
    from app.services.analytics_agent import _fetch_live_schema
    import app.services.analytics_agent as aa_mod
    aa_mod._schema_cache = None

    first = await _fetch_live_schema(db)
    second = await _fetch_live_schema(db)

    assert first is second  # same object — cache returned


async def test_fetch_live_schema_cache_can_be_reset(db):
    """Clearing _schema_cache forces a fresh read."""
    from app.services.analytics_agent import _fetch_live_schema
    import app.services.analytics_agent as aa_mod

    aa_mod._schema_cache = None
    first = await _fetch_live_schema(db)

    aa_mod._schema_cache = None
    second = await _fetch_live_schema(db)

    # Content should be the same even after reset
    assert first == second