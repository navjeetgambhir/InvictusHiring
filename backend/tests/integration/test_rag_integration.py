"""
Integration tests — pgvector RAG retrieval against a real Postgres database.

Verifies that similarity search, threshold filtering, and result ranking
work correctly with actual vector operations.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import text

from app.db.models import PastJD

pytestmark = pytest.mark.asyncio

_DIM = 1536


def _unit_vector(index: int, dim: int = _DIM) -> list[float]:
    """Return a vector with 1.0 at position `index` and 0.0 elsewhere."""
    v = [0.0] * dim
    v[index] = 1.0
    return v


def _close_vector(index: int, dim: int = _DIM, noise: float = 0.01) -> list[float]:
    """Return a vector very similar to _unit_vector(index)."""
    v = _unit_vector(index, dim)
    v[index] = 1.0 - noise
    v[(index + 1) % dim] = noise
    return v


def _orthogonal_vector(index: int, dim: int = _DIM) -> list[float]:
    """Return a vector orthogonal to _unit_vector(index) — cosine similarity = 0."""
    v = [0.0] * dim
    v[(index + 100) % dim] = 1.0
    return v


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _insert_past_jd(db, title: str, department: str, embedding: list[float]) -> PastJD:
    jd = PastJD(
        title=title,
        department=department,
        content=f"Sample JD for {title}.",
        embedding=embedding,
    )
    db.add(jd)
    await db.flush()
    return jd


# ── Tests ─────────────────────────────────────────────────────────────────────

async def test_retrieve_returns_similar_jd(db):
    """Insert a JD with a known vector; querying with a near-identical vector should return it."""
    from app.services.rag import retrieve_similar_jds

    vec = _unit_vector(0)
    await _insert_past_jd(db, "Software Engineer", "Engineering", vec)

    query_vec = _close_vector(0)  # very similar to vec above

    with patch("app.services.rag.embed", AsyncMock(return_value=query_vec)):
        results = await retrieve_similar_jds("software engineer python", db)

    assert len(results) >= 1
    titles = [r["title"] for r in results]
    assert "Software Engineer" in titles


async def test_retrieve_excludes_below_threshold(db):
    """A JD with an orthogonal vector (similarity ≈ 0) should not be returned."""
    from app.services.rag import retrieve_similar_jds

    # Insert a JD whose embedding is orthogonal to our query
    await _insert_past_jd(db, "Unrelated Role", "Finance", _orthogonal_vector(0))

    query_vec = _unit_vector(0)
    with patch("app.services.rag.embed", AsyncMock(return_value=query_vec)):
        results = await retrieve_similar_jds("software engineer", db)

    titles = [r["title"] for r in results]
    assert "Unrelated Role" not in titles


async def test_retrieve_ranks_by_similarity(db):
    """Most similar JD should appear first in results."""
    from app.services.rag import retrieve_similar_jds

    # vec_a is very close to query; vec_b is slightly less similar
    query_vec = _unit_vector(5)
    vec_a = _close_vector(5, noise=0.001)   # similarity ≈ 0.999
    vec_b = _close_vector(5, noise=0.05)    # similarity ≈ 0.95

    await _insert_past_jd(db, "Role B", "Dept", vec_b)
    await _insert_past_jd(db, "Role A", "Dept", vec_a)

    with patch("app.services.rag.embed", AsyncMock(return_value=query_vec)):
        results = await retrieve_similar_jds("role", db)

    ranked = [r["title"] for r in results]
    assert ranked.index("Role A") < ranked.index("Role B")


async def test_retrieve_returns_empty_when_no_jds(db):
    """No past JDs in DB → empty list, no error."""
    from app.services.rag import retrieve_similar_jds

    query_vec = _unit_vector(10)
    with patch("app.services.rag.embed", AsyncMock(return_value=query_vec)):
        results = await retrieve_similar_jds("anything", db)

    assert results == []


async def test_retrieve_respects_top_k(db):
    """At most RAG_TOP_K results should be returned (settings.rag_top_k = 5)."""
    from app.services.rag import retrieve_similar_jds

    query_vec = _unit_vector(20)
    # Insert 8 very similar JDs
    for i in range(8):
        v = _close_vector(20, noise=0.001 * (i + 1))
        await _insert_past_jd(db, f"Role {i}", "Eng", v)

    with patch("app.services.rag.embed", AsyncMock(return_value=query_vec)):
        results = await retrieve_similar_jds("role", db)

    assert len(results) <= 5  # rag_top_k = 5 in test settings


async def test_retrieve_result_schema(db):
    """Each result dict should have title, department, content, and similarity keys."""
    from app.services.rag import retrieve_similar_jds

    vec = _unit_vector(30)
    await _insert_past_jd(db, "Data Analyst", "Analytics", vec)

    query_vec = _close_vector(30)
    with patch("app.services.rag.embed", AsyncMock(return_value=query_vec)):
        results = await retrieve_similar_jds("data analyst", db)

    assert len(results) >= 1
    result = results[0]
    assert "title" in result
    assert "department" in result
    assert "content" in result
    assert "similarity" in result
    assert isinstance(result["similarity"], float)
    assert 0.0 <= result["similarity"] <= 1.0