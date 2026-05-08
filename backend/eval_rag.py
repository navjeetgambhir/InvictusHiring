"""
RAG Pipeline Evaluation using RAGAS.

Evaluates the pgvector retrieval used in JD drafting across four metrics:
  - Faithfulness      : generated JD is grounded in retrieved context (no hallucination)
  - Answer Relevancy  : generated JD answers the original query
  - Context Precision : retrieved chunks that are relevant come first
  - Context Recall    : retrieved chunks cover all key points in the reference

Usage
-----
# Run with synthetic golden dataset (no DB required):
  PYTHONPATH=backend python backend/eval_rag.py

# Run with real DB + live RAG retrieval (requires DB + OpenAI key):
  PYTHONPATH=backend python backend/eval_rag.py --live

# Adjust k and threshold:
  PYTHONPATH=backend python backend/eval_rag.py --top-k 3 --threshold 0.70

Output
------
Prints a per-metric score table and saves results to eval_rag_results.json.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

# ── Environment ──────────────────────────────────────────────────────────────

def _check_openai_key() -> None:
    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("Error: OPENAI_API_KEY environment variable is not set.")


# ── Golden evaluation dataset ────────────────────────────────────────────────
#
# Each sample is a dict with:
#   query        – the job requirement free-text sent to the RAG system
#   reference    – the ideal answer (used for Context Recall + Context Precision)
#   contexts     – list of retrieved JD excerpts (populated by retrieval or synthetic)
#   response     – the generated JD draft (populated by generation or synthetic)
#
# The synthetic versions allow running the evaluator offline against the golden
# dataset without a live DB or real generation calls.

GOLDEN_SAMPLES: list[dict[str, Any]] = [
    {
        "query": (
            "We need a Senior Python Engineer for our fintech platform in London. "
            "They should have 5+ years Python, FastAPI, PostgreSQL, Redis, and ideally "
            "Docker/Kubernetes. Salary £80–100k."
        ),
        "reference": (
            "A UK-compliant job description for a Senior Python Engineer in London at "
            "a fintech company. The JD should cover: 5+ years Python experience, "
            "FastAPI or Django REST Framework, PostgreSQL database skills, Redis caching, "
            "Docker/Kubernetes as nice-to-have, salary band £80,000–£100,000, "
            "gender-neutral language, bullet-pointed responsibilities."
        ),
        "synthetic_contexts": [
            (
                "Title: Senior Software Engineer – Fintech\n"
                "Department: Engineering\n"
                "We are looking for an experienced Python developer to join our London-based "
                "fintech team. The ideal candidate has 5+ years of Python experience, strong "
                "knowledge of FastAPI or Flask, PostgreSQL, and Redis. "
                "Salary: £75,000–£95,000."
            ),
            (
                "Title: Backend Engineer – Payments\n"
                "Department: Platform Engineering\n"
                "Join our payment infrastructure team in London. You will design and build "
                "scalable microservices using Python 3, FastAPI, and PostgreSQL. "
                "Experience with Docker and Kubernetes is a bonus. "
                "Salary: £70,000–£90,000."
            ),
        ],
        "synthetic_response": (
            "# Senior Python Engineer — London\n\n"
            "**About InvictusHiring**\n"
            "We are a growing fintech company building next-generation payment infrastructure.\n\n"
            "**The Role**\n"
            "We are seeking a Senior Python Engineer to join our platform team in London. "
            "You will design, build, and maintain high-performance microservices that power "
            "our core fintech platform.\n\n"
            "**Key Responsibilities**\n"
            "- Design and develop scalable Python microservices using FastAPI\n"
            "- Maintain and optimise PostgreSQL databases\n"
            "- Build and monitor Redis-based caching layers\n"
            "- Write clean, well-tested code with full CI/CD coverage\n"
            "- Collaborate with cross-functional teams on technical roadmap\n\n"
            "**Required Skills**\n"
            "- 5+ years Python development experience\n"
            "- Strong proficiency with FastAPI or Django REST Framework\n"
            "- PostgreSQL — schema design, query optimisation\n"
            "- Redis for caching and queuing\n\n"
            "**Nice to Have**\n"
            "- Docker and Kubernetes\n"
            "- Experience in fintech or regulated environments\n\n"
            "**What We Offer**\n"
            "Salary: £80,000–£100,000 | Remote-friendly | London HQ"
        ),
    },
    {
        "query": (
            "Marketing Manager role in Manchester. Need someone with 3+ years digital marketing, "
            "SEO, Google Ads, social media strategy. Team lead experience preferred. £45–55k."
        ),
        "reference": (
            "A UK-compliant job description for a Marketing Manager in Manchester. "
            "Must include: 3+ years digital marketing experience, SEO expertise, Google Ads, "
            "social media strategy, team leadership as preferred, salary £45,000–£55,000, "
            "structured with responsibilities as bullet points, gender-neutral language."
        ),
        "synthetic_contexts": [
            (
                "Title: Digital Marketing Manager\n"
                "Department: Marketing\n"
                "We are looking for a Digital Marketing Manager based in Manchester to lead "
                "our online growth strategy. You will manage SEO, paid search (Google Ads), "
                "and social channels. 3+ years in digital marketing required. "
                "Salary: £42,000–£52,000."
            ),
            (
                "Title: Marketing Lead – Growth\n"
                "Department: Marketing\n"
                "Drive customer acquisition through data-driven marketing campaigns. "
                "The role requires experience with SEO, Google Analytics, and paid social. "
                "Manchester-based with hybrid working. £48,000–£58,000."
            ),
        ],
        "synthetic_response": (
            "# Marketing Manager — Manchester\n\n"
            "**About InvictusHiring**\n"
            "We are a fast-growing organisation seeking a skilled Marketing Manager.\n\n"
            "**The Role**\n"
            "Lead and execute our digital marketing strategy from our Manchester office, "
            "driving brand visibility and lead generation across all digital channels.\n\n"
            "**Key Responsibilities**\n"
            "- Develop and implement digital marketing campaigns across SEO, PPC, and social\n"
            "- Manage Google Ads accounts — budget allocation, A/B testing, performance reporting\n"
            "- Build and execute social media strategy across LinkedIn, Instagram, and Twitter/X\n"
            "- Analyse campaign performance using Google Analytics and present insights to stakeholders\n"
            "- Mentor and develop a small marketing team\n\n"
            "**Required Skills**\n"
            "- 3+ years digital marketing experience\n"
            "- Proficiency in SEO (on-page and technical)\n"
            "- Google Ads certification or equivalent experience\n"
            "- Strong social media strategy skills\n\n"
            "**Nice to Have**\n"
            "- Team leadership or line management experience\n"
            "- HubSpot or similar CRM experience\n\n"
            "**What We Offer**\n"
            "Salary: £45,000–£55,000 | Hybrid | Manchester city centre"
        ),
    },
    {
        "query": (
            "Data Scientist position, remote-first UK. Must have Python, scikit-learn, "
            "SQL, experience with NLP and large language models. PhD or 4+ years industry experience. "
            "Salary £70–90k."
        ),
        "reference": (
            "A UK-compliant job description for a Data Scientist (remote UK). "
            "Must include: Python, scikit-learn, SQL, NLP, LLM experience, "
            "PhD or 4+ years experience, salary £70,000–£90,000, "
            "clear split between required and nice-to-have skills, bullet-pointed responsibilities."
        ),
        "synthetic_contexts": [
            (
                "Title: Senior Data Scientist – NLP\n"
                "Department: AI Research\n"
                "Remote-first UK role. We are building advanced NLP solutions and need a "
                "Data Scientist with strong Python, scikit-learn, and SQL skills. "
                "Experience with transformer models and LLMs highly valued. "
                "£65,000–£85,000."
            ),
            (
                "Title: Machine Learning Engineer\n"
                "Department: Data & ML\n"
                "UK remote. Work on production ML systems — model training, evaluation pipelines, "
                "and LLM integrations. Python, PyTorch, SQL required. "
                "Industry PhD or equivalent experience preferred. £75,000–£95,000."
            ),
        ],
        "synthetic_response": (
            "# Data Scientist — Remote UK\n\n"
            "**About InvictusHiring**\n"
            "We are at the forefront of applied AI, building intelligent products that matter.\n\n"
            "**The Role**\n"
            "Join our remote-first UK team as a Data Scientist, leading applied research and "
            "productionising ML and NLP models at scale.\n\n"
            "**Key Responsibilities**\n"
            "- Design, train, and evaluate ML models using scikit-learn and PyTorch\n"
            "- Build and maintain NLP pipelines (classification, NER, embedding, RAG)\n"
            "- Integrate and fine-tune large language models for product use cases\n"
            "- Query and analyse large datasets using SQL\n"
            "- Collaborate with engineering to deploy models to production\n"
            "- Write reproducible research and clear technical documentation\n\n"
            "**Required Skills**\n"
            "- Python (numpy, pandas, scikit-learn)\n"
            "- SQL — complex joins, aggregations, window functions\n"
            "- NLP experience — text classification, embeddings, language models\n"
            "- PhD in a quantitative discipline or 4+ years industry experience\n\n"
            "**Nice to Have**\n"
            "- Experience with OpenAI API or HuggingFace ecosystem\n"
            "- MLflow, Weights & Biases, or equivalent experiment tracking\n\n"
            "**What We Offer**\n"
            "Salary: £70,000–£90,000 | Fully remote (UK) | Flexible hours"
        ),
    },
]


# ── Live retrieval + generation (optional) ────────────────────────────────────

async def _live_retrieve(query: str, top_k: int, threshold: float) -> list[str]:
    """Call the real RAG pipeline against the live DB. Requires DB connection."""
    from app.core.database import AsyncSessionLocal
    from app.services.rag import retrieve_similar_jds

    async with AsyncSessionLocal() as db:
        results = await retrieve_similar_jds(query, db)

    return [
        f"Title: {r['title']}\nDepartment: {r['department']}\n{r['content']}"
        for r in results
    ]


async def _live_generate(query: str, contexts: list[str]) -> str:
    """Generate a JD draft from the query + retrieved contexts using the JD agent.

    Uses stream_initial_draft() with a synthesised requirements dict so the live
    evaluation path does not require a real DB session for generation.
    """
    from app.services.jd_agent import stream_initial_draft
    from app.core.database import AsyncSessionLocal

    requirements = {
        "title": "Evaluation Role",
        "department": "Unknown",
        "location": "UK",
        "salary_band": "",
        "required_skills": [],
        "nice_to_have_skills": [],
        "company_description": "",
        "additional_context": query,
        "_override_past_jds": contexts,
    }

    chunks: list[str] = []
    async with AsyncSessionLocal() as db:
        async for chunk in stream_initial_draft(requirements, db):
            if isinstance(chunk, str):
                chunks.append(chunk)

    return "".join(chunks)


# ── Build RAGAS dataset ───────────────────────────────────────────────────────

async def build_evaluation_dataset(
    live: bool = False,
    top_k: int = 5,
    threshold: float = 0.75,
) -> "EvaluationDataset":  # noqa: F821 (imported below)
    from ragas import EvaluationDataset
    from ragas.dataset_schema import SingleTurnSample

    samples: list[SingleTurnSample] = []

    for i, gold in enumerate(GOLDEN_SAMPLES, 1):
        query = gold["query"]
        print(f"  [{i}/{len(GOLDEN_SAMPLES)}] Processing: {query[:60]}…")

        if live:
            print("    → Fetching live contexts from DB…")
            contexts = await _live_retrieve(query, top_k, threshold)
            if not contexts:
                print("    ⚠ No contexts retrieved — using synthetic fallback.")
                contexts = gold["synthetic_contexts"]
            print("    → Generating JD draft…")
            response = await _live_generate(query, contexts)
        else:
            contexts = gold["synthetic_contexts"]
            response = gold["synthetic_response"]

        samples.append(
            SingleTurnSample(
                user_input=query,
                response=response,
                retrieved_contexts=contexts,
                reference=gold["reference"],
            )
        )

    return EvaluationDataset(samples=samples)


# ── Evaluate ──────────────────────────────────────────────────────────────────

def run_evaluation(dataset: "EvaluationDataset") -> dict[str, float]:
    from ragas import evaluate
    from ragas.metrics import Faithfulness, AnswerRelevancy, ContextPrecision, ContextRecall
    from langchain_openai import ChatOpenAI, OpenAIEmbeddings

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-small")

    metrics = [
        Faithfulness(llm=llm),
        AnswerRelevancy(llm=llm, embeddings=embeddings),
        ContextPrecision(llm=llm),
        ContextRecall(llm=llm),
    ]

    print("\nRunning RAGAS evaluation (this calls OpenAI)…")
    result = evaluate(dataset=dataset, metrics=metrics)
    return dict(result)


# ── Report ────────────────────────────────────────────────────────────────────

def _print_report(scores: dict[str, float]) -> None:
    METRIC_LABELS = {
        "faithfulness": "Faithfulness      (no hallucination)",
        "answer_relevancy": "Answer Relevancy  (answers the query)",
        "context_precision": "Context Precision (relevant chunks ranked first)",
        "context_recall": "Context Recall    (reference covered by context)",
    }

    print("\n" + "=" * 60)
    print("  RAGAS Evaluation Results — RAG Pipeline")
    print("=" * 60)
    for key, label in METRIC_LABELS.items():
        val = scores.get(key)
        if val is not None:
            bar = "█" * int(val * 20)
            print(f"  {label:<42}  {val:.4f}  {bar}")
        else:
            print(f"  {label:<42}  N/A")
    print("=" * 60)

    overall = [v for v in scores.values() if v is not None]
    if overall:
        avg = sum(overall) / len(overall)
        print(f"  Average                                              {avg:.4f}")
    print()


def _thresholds_check(scores: dict[str, float]) -> bool:
    THRESHOLDS = {
        "faithfulness": 0.70,
        "answer_relevancy": 0.70,
        "context_precision": 0.60,
        "context_recall": 0.60,
    }
    passed = True
    for metric, threshold in THRESHOLDS.items():
        val = scores.get(metric)
        if val is not None and val < threshold:
            print(f"  ⚠ {metric} = {val:.4f} is below threshold {threshold:.2f}")
            passed = False
    return passed


# ── Main ──────────────────────────────────────────────────────────────────────

async def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the RAG pipeline with RAGAS.")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real DB retrieval and LLM generation (requires running DB + OpenAI key).",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.75)
    parser.add_argument(
        "--output", default="eval_rag_results.json", help="Path to save JSON results."
    )
    args = parser.parse_args()

    _check_openai_key()

    mode = "LIVE (real DB + generation)" if args.live else "SYNTHETIC (golden dataset)"
    print(f"\nRAG Evaluation Mode: {mode}")
    print(f"Samples: {len(GOLDEN_SAMPLES)}\n")

    print("Building evaluation dataset…")
    dataset = await build_evaluation_dataset(
        live=args.live, top_k=args.top_k, threshold=args.threshold
    )

    scores = run_evaluation(dataset)
    _print_report(scores)

    passed = _thresholds_check(scores)

    out_path = Path(args.output)
    out_path.write_text(json.dumps({"mode": mode, "scores": scores}, indent=2))
    print(f"Results saved to {out_path}\n")

    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    asyncio.run(main())