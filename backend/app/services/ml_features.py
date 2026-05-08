"""
Feature engineering for the fit and join-prediction ML models.

Two feature sets are built from the same source rows:

  fit_features(app, job)   → dict used to train / predict candidate-to-role fit
  join_features(app, job)  → dict used to train / predict offer acceptance

Both functions are pure (no I/O) and return flat dicts of Python scalars so
they can be fed directly to pandas / sklearn without further transformation.

Typical usage
-------------
    from app.services.ml_features import fit_features, join_features, extract_dataset

    # Build a training row for a single application
    row = fit_features(app, job)

    # Or bulk-export the entire labelled dataset from the DB
    df_fit, df_join = await extract_dataset(db)
"""

from __future__ import annotations

import re
from datetime import timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.db.models import CandidateApplication, JDRequest


# ── Helpers ───────────────────────────────────────────────────────────────────

_SENIORITY_KEYWORDS = {
    "junior": 1, "graduate": 1, "entry": 1,
    "mid": 2, "associate": 2,
    "senior": 3, "lead": 3, "principal": 3, "staff": 3,
    "head": 4, "director": 4, "vp": 4, "chief": 4,
}

_RECOMMENDATION_RANK = {
    "strong_match": 4,
    "good_match": 3,
    "partial_match": 2,
    "poor_match": 1,
}


def _seniority_score(title: str | None) -> int:
    """Map job title to a 1–4 seniority tier (0 = unknown)."""
    if not title:
        return 0
    lower = title.lower()
    for kw, score in _SENIORITY_KEYWORDS.items():
        if kw in lower:
            return score
    return 0


def _skill_overlap(candidate_strengths: list | None, required_skills: list | None) -> float:
    """
    Fraction of required skills mentioned in the candidate's strength list.
    Returns 0.0 when either list is empty.
    """
    if not candidate_strengths or not required_skills:
        return 0.0
    strengths_text = " ".join(candidate_strengths).lower()
    hits = sum(1 for skill in required_skills if skill.lower() in strengths_text)
    return hits / len(required_skills)


def _gap_ratio(candidate_gaps: list | None, required_skills: list | None) -> float:
    """Fraction of required skills that appear in the gap list."""
    if not candidate_gaps or not required_skills:
        return 0.0
    gaps_text = " ".join(candidate_gaps).lower()
    hits = sum(1 for skill in required_skills if skill.lower() in gaps_text)
    return hits / len(required_skills)


def _cover_letter_length(text: str | None) -> int:
    """Word count of cover letter (0 if absent)."""
    if not text:
        return 0
    return len(text.split())


def _location_match(job_location: str | None, cover_letter: str | None) -> int:
    """
    Rough signal: 1 if the job location city appears in the cover letter, else 0.
    A proper implementation would parse the CV — this is a fast proxy.
    """
    if not job_location or not cover_letter:
        return 0
    city = job_location.split(",")[0].strip().lower()
    return 1 if city and city in cover_letter.lower() else 0


def _days_between(early, late) -> int | None:
    """Return calendar days between two aware datetimes, or None if either is missing."""
    if early is None or late is None:
        return None
    e = early.replace(tzinfo=timezone.utc) if early.tzinfo is None else early
    l = late.replace(tzinfo=timezone.utc) if late.tzinfo is None else late
    return max(0, (l - e).days)


# ── Public feature builders ───────────────────────────────────────────────────

def fit_features(app: CandidateApplication, job: JDRequest) -> dict:
    """
    Feature dict for the candidate-to-role fit model.

    Target label: app.outcome  ("hired" → 1, anything else → 0)
    Only rows where app.outcome is not None are usable for supervised training.
    """
    required = job.required_skills or []
    nice = job.nice_to_have_skills or []

    return {
        # AI screener signals
        "screening_score":          app.screening_score or 0,
        "recommendation_rank":      _RECOMMENDATION_RANK.get(app.screening_recommendation or "", 0),
        "skill_overlap":            _skill_overlap(app.screening_strengths, required),
        "gap_ratio":                _gap_ratio(app.screening_gaps, required),
        "nice_skill_overlap":       _skill_overlap(app.screening_strengths, nice),

        # Candidate engagement signals
        "has_cv":                   1 if app.cv_path else 0,
        "cover_letter_words":       _cover_letter_length(app.cover_letter),
        "has_phone":                1 if app.phone else 0,

        # Role context
        "seniority_tier":           _seniority_score(job.title),
        "required_skill_count":     len(required),
        "nice_skill_count":         len(nice),
        "location_signal":          _location_match(job.location, app.cover_letter),

        # Pipeline progression (weak signal — shortlisting is HR judgement)
        "was_shortlisted":          1 if app.shortlisted else 0,
        "reached_interview":        1 if app.interview_status in ("scheduled", "completed") else 0,

        # Label — None means this row cannot be used for supervised training yet
        "label_hired":              1 if app.outcome == "hired" else (0 if app.outcome else None),
    }


def join_features(app: CandidateApplication, job: JDRequest) -> dict:
    """
    Feature dict for the join prediction (offer acceptance) model.

    Target label: app.offer_accepted  (True → 1, False → 0)
    Only rows where app.offer_extended is True are relevant.
    """
    required = job.required_skills or []

    # Days from application to offer
    days_to_offer = _days_between(app.applied_at, app.offer_date)

    # Days from interview invite to candidate reply (HR-recorded)
    days_to_respond = app.days_to_respond

    return {
        # Candidate quality signals
        "screening_score":          app.screening_score or 0,
        "recommendation_rank":      _RECOMMENDATION_RANK.get(app.screening_recommendation or "", 0),
        "skill_overlap":            _skill_overlap(app.screening_strengths, required),
        "gap_ratio":                _gap_ratio(app.screening_gaps, required),

        # Process speed (faster = warmer candidate)
        "days_to_offer":            days_to_offer,
        "days_to_respond":          days_to_respond,

        # Interview depth
        "interview_rounds":         app.interview_rounds or 0,
        "interview_format_video":   1 if app.interview_format == "video" else 0,
        "interview_format_phone":   1 if app.interview_format == "phone" else 0,
        "interview_format_inperson":1 if app.interview_format == "in_person" else 0,

        # Role characteristics
        "seniority_tier":           _seniority_score(job.title),
        "required_skill_count":     len(required),
        "location_signal":          _location_match(job.location, app.cover_letter),

        # Candidate engagement
        "cover_letter_words":       _cover_letter_length(app.cover_letter),
        "has_cv":                   1 if app.cv_path else 0,

        # Label — None means offer outcome not yet recorded
        "label_accepted":           1 if app.offer_accepted is True else (0 if app.offer_accepted is False else None),
    }


# ── Bulk dataset export ───────────────────────────────────────────────────────

async def extract_dataset(db: AsyncSession) -> tuple[list[dict], list[dict]]:
    """
    Query the DB and return two lists of feature dicts:
      - fit_rows:  all applications with a recorded outcome (labelled for fit model)
      - join_rows: all applications where an offer was extended (labelled for join model)

    Convert to DataFrames with:
        import pandas as pd
        df_fit  = pd.DataFrame(fit_rows)
        df_join = pd.DataFrame(join_rows)
    """
    result = await db.execute(
        select(CandidateApplication, JDRequest).join(
            JDRequest, CandidateApplication.request_id == JDRequest.id
        )
    )
    rows = result.all()

    fit_rows: list[dict] = []
    join_rows: list[dict] = []

    for app, job in rows:
        f = fit_features(app, job)
        if f["label_hired"] is not None:
            fit_rows.append(f)

        j = join_features(app, job)
        if app.offer_extended and j["label_accepted"] is not None:
            join_rows.append(j)

    return fit_rows, join_rows