"""Tests for the RAG retrieval service."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ── embed() ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_embed_returns_list_of_floats():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    with patch("app.services.rag._client") as mock_client:
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        from app.services.rag import embed
        result = await embed("software engineer london")

    assert result == [0.1, 0.2, 0.3]
    mock_client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small",
        input="software engineer london",
    )


@pytest.mark.asyncio
async def test_embed_passes_full_text():
    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.5] * 1536)]

    with patch("app.services.rag._client") as mock_client:
        mock_client.embeddings.create = AsyncMock(return_value=mock_response)

        from app.services.rag import embed
        result = await embed("x" * 500)

    assert len(result) == 1536


# ── retrieve_similar_jds() ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_retrieve_similar_jds_returns_mapped_dicts():
    fake_row = MagicMock()
    fake_row.title = "Backend Engineer"
    fake_row.department = "Engineering"
    fake_row.content = "We are looking for..."
    fake_row.similarity = 0.92

    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.fetchall = MagicMock(return_value=[fake_row])
    mock_db.execute = AsyncMock(return_value=execute_result)

    with patch("app.services.rag._client") as mock_client:
        mock_client.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
        )
        from app.services.rag import retrieve_similar_jds
        results = await retrieve_similar_jds("backend engineer python", mock_db)

    assert len(results) == 1
    assert results[0]["title"] == "Backend Engineer"
    assert results[0]["similarity"] == 0.92
    assert "content" in results[0]


@pytest.mark.asyncio
async def test_retrieve_similar_jds_empty_when_no_matches():
    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.fetchall = MagicMock(return_value=[])
    mock_db.execute = AsyncMock(return_value=execute_result)

    with patch("app.services.rag._client") as mock_client:
        mock_client.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(embedding=[0.0] * 1536)])
        )
        from app.services.rag import retrieve_similar_jds
        results = await retrieve_similar_jds("obscure role", mock_db)

    assert results == []


@pytest.mark.asyncio
async def test_retrieve_similar_jds_passes_threshold_and_k():
    mock_db = AsyncMock()
    execute_result = MagicMock()
    execute_result.fetchall = MagicMock(return_value=[])
    mock_db.execute = AsyncMock(return_value=execute_result)

    with patch("app.services.rag._client") as mock_client:
        mock_client.embeddings.create = AsyncMock(
            return_value=MagicMock(data=[MagicMock(embedding=[0.1] * 1536)])
        )
        from app.services.rag import retrieve_similar_jds
        await retrieve_similar_jds("query", mock_db)

    call_kwargs = mock_db.execute.call_args[0][1]
    assert call_kwargs["threshold"] == 0.75
    assert call_kwargs["k"] == 5