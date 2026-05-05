"""
Indeed UK scraper via SerpAPI — no CAPTCHA, no browser needed.

Setup:
    1. Get a free API key at https://serpapi.com  (100 searches/month free)
    2. pip install serpapi  (already in pyproject.toml)
    3. Set SERPAPI_KEY env var or paste it into API_KEY below

Run:
    SERPAPI_KEY=your_key python Data/scrape_indeed.py
"""

import json
import csv
import os
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from serpapi import GoogleSearch


# ── Config ────────────────────────────────────────────────────────────────────
API_KEY       = os.getenv("SERPAPI_KEY", "YOUR_SERPAPI_KEY_HERE")
SEARCH_QUERY  = "AI Engineer"
LOCATION      = "United Kingdom"
MAX_PAGES     = 10          # 10 pages × 15 results ≈ 150 jobs
DELAY_SECONDS = 1.5         # polite pause between pages

OUTPUT_JSON   = Path(__file__).parent / "indeed_ai_jobs.json"
OUTPUT_CSV    = Path(__file__).parent / "indeed_ai_jobs.csv"
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class Job:
    title: str = ""
    company: str = ""
    location: str = ""
    salary: str = ""
    job_type: str = ""
    posted: str = ""
    description: str = ""
    url: str = ""
    job_id: str = ""
    highlights: list[str] = field(default_factory=list)
    extensions: list[str] = field(default_factory=list)


def parse_result(r: dict) -> Job:
    return Job(
        title       = r.get("title", ""),
        company     = r.get("company_name", ""),
        location    = r.get("location", ""),
        salary      = r.get("salary", ""),
        job_type    = ", ".join(r.get("extensions", [])),
        posted      = r.get("detected_extensions", {}).get("posted_at", ""),
        description = r.get("description", ""),
        url         = r.get("link", ""),
        job_id      = r.get("job_id", ""),
        highlights  = [
            item.get("items", [""])[0]
            for item in r.get("job_highlights", [])
            if item.get("items")
        ],
        extensions  = r.get("extensions", []),
    )


def fetch_page(start: int) -> tuple[list[Job], bool]:
    """Fetch one page of results. Returns (jobs, has_more)."""
    params = {
        "engine":    "indeed",
        "q":         SEARCH_QUERY,
        "l":         LOCATION,
        "start":     start,
        "country":   "gb",
        "hl":        "en",
        "sort":      "date",
        "api_key":   API_KEY,
    }
    search  = GoogleSearch(params)
    data    = search.get_dict()

    results = data.get("jobs_results", [])
    jobs    = [parse_result(r) for r in results]

    has_more = bool(data.get("serpapi_pagination", {}).get("next"))
    return jobs, has_more


def main() -> None:
    if API_KEY == "YOUR_SERPAPI_KEY_HERE":
        print("ERROR: Set your SerpAPI key via SERPAPI_KEY env var or edit API_KEY in this file.")
        return

    all_jobs: list[Job] = []
    seen_ids: set[str]  = set()

    for page_num in range(MAX_PAGES):
        start = page_num * 10
        print(f"[Page {page_num + 1}] fetching start={start} ...")

        try:
            jobs, has_more = fetch_page(start)
        except Exception as e:
            print(f"  [error] {e}")
            break

        if not jobs:
            print("  No results — done.")
            break

        new_jobs = [j for j in jobs if j.job_id not in seen_ids]
        for j in new_jobs:
            seen_ids.add(j.job_id)
            all_jobs.append(j)
            print(f"  + {j.title} @ {j.company} ({j.location})")

        print(f"  Page total: {len(new_jobs)} new / {len(all_jobs)} total so far")

        if not has_more:
            print("  No more pages.")
            break

        time.sleep(DELAY_SECONDS)

    # ── Save outputs ──────────────────────────────────────────────────────────
    OUTPUT_JSON.write_text(
        json.dumps([asdict(j) for j in all_jobs], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"\nSaved {len(all_jobs)} jobs → {OUTPUT_JSON}")

    if all_jobs:
        keys = list(asdict(all_jobs[0]).keys())
        with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            for job in all_jobs:
                row = asdict(job)
                row["highlights"] = " | ".join(row["highlights"])
                row["extensions"] = ", ".join(row["extensions"])
                writer.writerow(row)
        print(f"Saved {len(all_jobs)} jobs → {OUTPUT_CSV}")


if __name__ == "__main__":
    main()