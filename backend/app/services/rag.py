from loguru import logger
from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings

_client = AsyncOpenAI(api_key=settings.openai_api_key)


async def embed(text_input: str) -> list[float]:
    logger.debug(f"Embedding text ({len(text_input)} chars)")
    response = await _client.embeddings.create(
        model="text-embedding-3-small",
        input=text_input,
    )
    return response.data[0].embedding


async def retrieve_similar_jds(query: str, db: AsyncSession) -> list[dict]:
    """Return top-k past JDs most similar to the query using pgvector cosine similarity."""
    logger.info(f"RAG retrieval | query='{query[:80]}…'")
    query_embedding = await embed(query)

    rows = await db.execute(
        text("""
            SELECT title, department, content,
                   1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM past_jds
            WHERE 1 - (embedding <=> CAST(:embedding AS vector)) >= :threshold
            ORDER BY similarity DESC
            LIMIT :k
        """),
        {
            "embedding": str(query_embedding),
            "threshold": settings.rag_similarity_threshold,
            "k": settings.rag_top_k,
        },
    )

    results = [
        {"title": r.title, "department": r.department, "content": r.content, "similarity": r.similarity}
        for r in rows.fetchall()
    ]
    scores = [f"{r['title']} ({r['similarity']:.3f})" for r in results]
    logger.info(f"RAG retrieved {len(results)} similar JD(s): {scores}")
    return results