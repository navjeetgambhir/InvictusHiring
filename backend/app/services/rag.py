"""
RAG (Retrieval-Augmented Generation) helpers for JD drafting.

embed()              — calls text-embedding-3-small to produce a 1536-dim vector.
retrieve_similar_jds() — cosine-similarity search over the past_jds table via pgvector.

Retrieved JDs are injected as "reference" context in the initial JD draft prompt,
giving the model concrete examples of tone and structure without copying verbatim.
The @traceable decorator makes each retrieval call a child span in LangSmith under
the parent jd_drafter.initial_draft chain.
"""

from typing import Any

from langsmith import traceable
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


@traceable(name="rag.retrieve_similar_jds", run_type="retriever", tags=["rag", "pgvector"])
async def retrieve_similar_jds(query: str, db: AsyncSession) -> list[dict[str, Any]]:
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