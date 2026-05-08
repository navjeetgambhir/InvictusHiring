"""
Seed script — loads jobs_results.json and inserts each job into the
past_jds pgvector table with a text-embedding-3-small embedding.

Run from the Capstone root:
    PYTHONPATH=backend python Data/seed_past_jds.py
"""

import asyncio
import json
import sys
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
JSON_PATH  = SCRIPT_DIR / "jobs_results.json"

# ── Department inference ──────────────────────────────────────────────────────
# Rules are checked in order — first match wins, so more specific terms
# (e.g. "nlp") must appear before broader ones (e.g. "machine learning").
_DEPT_RULES: list[tuple[list[str], str]] = [
    (["nlp", "natural language"],              "NLP Engineering"),
    (["computer vision", "cv engineer"],        "Computer Vision"),
    (["deep learning"],                         "Deep Learning"),
    (["machine learning", "ml engineer"],       "Machine Learning"),
    (["ai researcher", "ai research"],          "AI Research"),
    (["ai engineer", "ai software"],            "AI Engineering"),
    (["ai consultant"],                         "AI Consulting"),
    (["ai product", "product manager"],         "AI Product"),
    (["data scientist", "data science"],        "Data Science"),
    (["data engineer", "big data"],             "Data Engineering"),
    (["data analyst", "business intelligence"], "Data Analytics"),
    (["data architect"],                        "Data Architecture"),
    (["devops", "cloud engineer"],              "DevOps / Cloud"),
]

def infer_department(title: str) -> str:
    lower = title.lower()
    for keywords, dept in _DEPT_RULES:
        if any(k in lower for k in keywords):
            return dept
    # Default bucket for titles that don't match any known pattern
    return "Technology"


def build_content(job: dict) -> str:
    """Compose a rich text blob suitable for embedding and RAG retrieval."""
    ext = job.get("detected_extensions", {})
    salary   = ext.get("salary", "")
    schedule = ext.get("schedule_type", "")

    # Structured header fields make the embedding more discriminative for
    # title/location queries even when the description doesn't repeat them.
    parts = [
        f"Job Title: {job.get('job_title') or job.get('title', '')}",
        f"Company: {job.get('company_name', '')}",
        f"Location: {job.get('location', '')}",
    ]
    # Only include optional fields if present — avoids "Salary: " noise in the embedding
    if salary:
        parts.append(f"Salary: {salary}")
    if schedule:
        parts.append(f"Employment Type: {schedule}")
    parts.append("")  # blank line separates header from body
    parts.append(job.get("description", "").strip())

    # Single blob per JD — no chunking needed; JDs are short enough to embed whole
    return "\n".join(parts)


# ── Embedding batch helper ────────────────────────────────────────────────────
async def embed_texts(client, texts: list[str]) -> list[list[float]]:
    """Embed a list of texts in a single OpenAI API call."""
    print(f"  embedding {len(texts)} texts in batch …")
    response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=texts,
    )
    # OpenAI may return embeddings out of input order; sort by index to realign
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# ── Main ──────────────────────────────────────────────────────────────────────
async def main() -> None:
    # Deferred imports so PYTHONPATH=backend must be set before this script runs
    from openai import AsyncOpenAI
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.orm import sessionmaker
    from app.core.config import settings
    from app.db.models import PastJD, Base

    print(f"Loading {JSON_PATH} …")
    with open(JSON_PATH) as f:
        jobs: list[dict] = json.load(f)
    print(f"  {len(jobs)} jobs found")

    # ── Build rows ────────────────────────────────────────────────────────────
    rows: list[dict] = []
    for job in jobs:
        title   = (job.get("job_title") or job.get("title", "")).strip()
        dept    = infer_department(title)
        content = build_content(job)
        if not content.strip():
            # Skip malformed records that would produce a useless zero-signal embedding
            print(f"  skip (empty content): {title}")
            continue
        rows.append({"title": title, "department": dept, "content": content})

    print(f"  {len(rows)} rows to embed and insert")

    # ── Embed ─────────────────────────────────────────────────────────────────
    oai = AsyncOpenAI(api_key=settings.openai_api_key)
    print("Generating embeddings via text-embedding-3-small …")
    embeddings = await embed_texts(oai, [r["content"] for r in rows])
    print(f"  {len(embeddings)} embeddings received")

    # ── Insert ────────────────────────────────────────────────────────────────
    engine = create_async_engine(settings.database_url, echo=False)

    # Ensure tables exist — safe no-op if migration 001_init.sql has already run
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # expire_on_commit=False keeps ORM objects accessible after commit
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with async_session() as session:
        for row, emb in zip(rows, embeddings):
            session.add(PastJD(
                title=row["title"],
                department=row["department"],
                content=row["content"],
                embedding=emb,  # 1536-dim float list stored as pgvector column
            ))
        await session.commit()

    print(f"\n✓ Inserted {len(rows)} rows into past_jds")

    # Release DB connections before the event loop exits
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())