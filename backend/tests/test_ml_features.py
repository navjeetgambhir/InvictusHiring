"""
Tests for ml_features.py — feature engineering for fit and join prediction.

All tests are pure (no DB, no OpenAI) since both functions take model objects directly.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.ml_features import (
    fit_features,
    join_features,
    _seniority_score,
    _skill_overlap,
    _gap_ratio,
    _cover_letter_length,
    _location_match,
    _days_between,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app(**kwargs) -> MagicMock:
    app = MagicMock()
    app.id = uuid.uuid4()
    app.screening_score = kwargs.get("screening_score", 75)
    app.screening_recommendation = kwargs.get("screening_recommendation", "strong_match")
    app.screening_strengths = kwargs.get("screening_strengths", ["Python", "FastAPI"])
    app.screening_gaps = kwargs.get("screening_gaps", [])
    app.cover_letter = kwargs.get("cover_letter", "I am excited to apply for this role.")
    app.cv_path = kwargs.get("cv_path", "/uploads/cv.pdf")
    app.phone = kwargs.get("phone", "+44 7911 123456")
    app.shortlisted = kwargs.get("shortlisted", False)
    app.interview_status = kwargs.get("interview_status", None)
    app.interview_format = kwargs.get("interview_format", None)
    app.interview_rounds = kwargs.get("interview_rounds", None)
    app.days_to_respond = kwargs.get("days_to_respond", None)
    app.offer_extended = kwargs.get("offer_extended", None)
    app.offer_accepted = kwargs.get("offer_accepted", None)
    app.offer_date = kwargs.get("offer_date", None)
    app.applied_at = kwargs.get("applied_at", datetime(2024, 1, 1, tzinfo=timezone.utc))
    app.name = kwargs.get("name", "Alice Smith")
    return app


def _make_job(**kwargs) -> MagicMock:
    job = MagicMock()
    job.title = kwargs.get("title", "Senior Software Engineer")
    job.department = kwargs.get("department", "Engineering")
    job.location = kwargs.get("location", "London, UK")
    job.required_skills = kwargs.get("required_skills", ["Python", "FastAPI", "PostgreSQL"])
    job.nice_to_have_skills = kwargs.get("nice_to_have_skills", ["Docker", "Kubernetes"])
    return job


# ── Seniority scoring ─────────────────────────────────────────────────────────

class TestSeniorityScore:
    def test_junior_keywords(self):
        assert _seniority_score("Junior Developer") == 1
        assert _seniority_score("Graduate Engineer") == 1
        assert _seniority_score("Entry Level Analyst") == 1

    def test_mid_keywords(self):
        assert _seniority_score("Associate Engineer") == 2
        assert _seniority_score("Mid-level Developer") == 2

    def test_senior_keywords(self):
        assert _seniority_score("Senior Software Engineer") == 3
        assert _seniority_score("Lead Developer") == 3
        assert _seniority_score("Principal Architect") == 3

    def test_executive_keywords(self):
        assert _seniority_score("Head of Engineering") == 4
        assert _seniority_score("VP of Product") == 4
        assert _seniority_score("Chief Technology Officer") == 4

    def test_unknown_title_returns_zero(self):
        assert _seniority_score("Wizard of Craft") == 0
        assert _seniority_score(None) == 0
        assert _seniority_score("") == 0

    def test_case_insensitive(self):
        assert _seniority_score("SENIOR ENGINEER") == 3


# ── Skill overlap ─────────────────────────────────────────────────────────────

class TestSkillOverlap:
    def test_full_overlap(self):
        assert _skill_overlap(["Python", "FastAPI"], ["Python", "FastAPI"]) == 1.0

    def test_partial_overlap(self):
        result = _skill_overlap(["Python", "Django"], ["Python", "FastAPI", "PostgreSQL"])
        assert result == pytest.approx(1 / 3)

    def test_no_overlap(self):
        assert _skill_overlap(["Java", "Spring"], ["Python", "FastAPI"]) == 0.0

    def test_empty_strengths_returns_zero(self):
        assert _skill_overlap([], ["Python"]) == 0.0
        assert _skill_overlap(None, ["Python"]) == 0.0

    def test_empty_required_returns_zero(self):
        assert _skill_overlap(["Python"], []) == 0.0
        assert _skill_overlap(["Python"], None) == 0.0

    def test_case_insensitive_matching(self):
        assert _skill_overlap(["PYTHON", "fastapi"], ["python", "FastAPI"]) == 1.0


# ── Gap ratio ─────────────────────────────────────────────────────────────────

class TestGapRatio:
    def test_all_required_are_gaps(self):
        assert _gap_ratio(["No SQL", "No Docker"], ["Python", "FastAPI"]) == 0.0

    def test_one_of_two_required_is_gap(self):
        result = _gap_ratio(["Missing Python"], ["Python", "FastAPI"])
        assert result == pytest.approx(0.5)

    def test_empty_gaps_returns_zero(self):
        assert _gap_ratio([], ["Python"]) == 0.0
        assert _gap_ratio(None, ["Python"]) == 0.0


# ── Cover letter length ───────────────────────────────────────────────────────

class TestCoverLetterLength:
    def test_counts_words(self):
        assert _cover_letter_length("I am excited to apply") == 5

    def test_empty_string_returns_zero(self):
        assert _cover_letter_length("") == 0
        assert _cover_letter_length(None) == 0


# ── Location match ────────────────────────────────────────────────────────────

class TestLocationMatch:
    def test_city_found_in_cover_letter(self):
        assert _location_match("London, UK", "I am based in London and can commute easily.") == 1

    def test_city_not_found(self):
        assert _location_match("Manchester, UK", "I am based in London.") == 0

    def test_none_location_returns_zero(self):
        assert _location_match(None, "I am in London.") == 0

    def test_none_cover_letter_returns_zero(self):
        assert _location_match("London, UK", None) == 0


# ── Days between ─────────────────────────────────────────────────────────────

class TestDaysBetween:
    def test_exact_days(self):
        early = datetime(2024, 1, 1, tzinfo=timezone.utc)
        late  = datetime(2024, 1, 31, tzinfo=timezone.utc)
        assert _days_between(early, late) == 30

    def test_none_returns_none(self):
        assert _days_between(None, datetime.now(timezone.utc)) is None
        assert _days_between(datetime.now(timezone.utc), None) is None

    def test_same_day_returns_zero(self):
        d = datetime(2024, 6, 1, tzinfo=timezone.utc)
        assert _days_between(d, d) == 0


# ── fit_features() ────────────────────────────────────────────────────────────

class TestFitFeatures:
    def test_returns_all_expected_keys(self):
        expected = {
            "screening_score", "recommendation_rank", "skill_overlap", "gap_ratio",
            "nice_skill_overlap", "has_cv", "cover_letter_words", "has_phone",
            "seniority_tier", "required_skill_count", "nice_skill_count",
            "location_signal", "was_shortlisted", "reached_interview", "label_hired",
        }
        result = fit_features(_make_app(), _make_job())
        assert set(result.keys()) == expected

    def test_label_hired_is_1_when_outcome_hired(self):
        app = _make_app()
        app.outcome = "hired"
        assert fit_features(app, _make_job())["label_hired"] == 1

    def test_label_hired_is_0_when_outcome_rejected(self):
        app = _make_app()
        app.outcome = "rejected"
        assert fit_features(app, _make_job())["label_hired"] == 0

    def test_label_hired_is_none_when_no_outcome(self):
        app = _make_app()
        app.outcome = None
        assert fit_features(app, _make_job())["label_hired"] is None

    def test_has_cv_is_1_when_cv_path_present(self):
        assert fit_features(_make_app(cv_path="/path/cv.pdf"), _make_job())["has_cv"] == 1

    def test_has_cv_is_0_when_no_cv(self):
        assert fit_features(_make_app(cv_path=None), _make_job())["has_cv"] == 0

    def test_has_phone_is_0_when_missing(self):
        assert fit_features(_make_app(phone=None), _make_job())["has_phone"] == 0

    def test_shortlisted_flag(self):
        assert fit_features(_make_app(shortlisted=True), _make_job())["was_shortlisted"] == 1
        assert fit_features(_make_app(shortlisted=False), _make_job())["was_shortlisted"] == 0

    def test_reached_interview_when_scheduled(self):
        assert fit_features(_make_app(interview_status="scheduled"), _make_job())["reached_interview"] == 1

    def test_reached_interview_false_when_none(self):
        assert fit_features(_make_app(interview_status=None), _make_job())["reached_interview"] == 0

    def test_recommendation_rank_mapping(self):
        ranks = {
            "strong_match": 4, "good_match": 3, "partial_match": 2, "poor_match": 1
        }
        for rec, expected_rank in ranks.items():
            app = _make_app(screening_recommendation=rec)
            assert fit_features(app, _make_job())["recommendation_rank"] == expected_rank

    def test_unknown_recommendation_maps_to_zero(self):
        app = _make_app(screening_recommendation="unknown_value")
        assert fit_features(app, _make_job())["recommendation_rank"] == 0

    def test_required_skill_count_matches_job(self):
        job = _make_job(required_skills=["Python", "Go", "Rust"])
        assert fit_features(_make_app(), job)["required_skill_count"] == 3

    def test_empty_required_skills(self):
        job = _make_job(required_skills=[])
        result = fit_features(_make_app(), job)
        assert result["required_skill_count"] == 0
        assert result["skill_overlap"] == 0.0

    def test_none_screening_score_defaults_to_zero(self):
        assert fit_features(_make_app(screening_score=None), _make_job())["screening_score"] == 0


# ── join_features() ───────────────────────────────────────────────────────────

class TestJoinFeatures:
    def test_returns_all_expected_keys(self):
        expected = {
            "screening_score", "recommendation_rank", "skill_overlap", "gap_ratio",
            "days_to_offer", "days_to_respond", "interview_rounds",
            "interview_format_video", "interview_format_phone", "interview_format_inperson",
            "seniority_tier", "required_skill_count", "location_signal",
            "cover_letter_words", "has_cv", "label_accepted",
        }
        result = join_features(_make_app(), _make_job())
        assert set(result.keys()) == expected

    def test_label_accepted_is_1_when_offer_accepted(self):
        app = _make_app(offer_accepted=True)
        assert join_features(app, _make_job())["label_accepted"] == 1

    def test_label_accepted_is_0_when_offer_declined(self):
        app = _make_app(offer_accepted=False)
        assert join_features(app, _make_job())["label_accepted"] == 0

    def test_label_accepted_is_none_when_not_recorded(self):
        app = _make_app(offer_accepted=None)
        assert join_features(app, _make_job())["label_accepted"] is None

    def test_days_to_offer_calculated_from_dates(self):
        app = _make_app(
            applied_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            offer_date=datetime(2024, 2, 1, tzinfo=timezone.utc),
        )
        assert join_features(app, _make_job())["days_to_offer"] == 31

    def test_days_to_offer_none_when_no_offer_date(self):
        app = _make_app(offer_date=None)
        assert join_features(app, _make_job())["days_to_offer"] is None

    def test_interview_format_video_one_hot(self):
        app = _make_app(interview_format="video")
        result = join_features(app, _make_job())
        assert result["interview_format_video"] == 1
        assert result["interview_format_phone"] == 0
        assert result["interview_format_inperson"] == 0

    def test_interview_format_phone_one_hot(self):
        app = _make_app(interview_format="phone")
        result = join_features(app, _make_job())
        assert result["interview_format_phone"] == 1
        assert result["interview_format_video"] == 0
        assert result["interview_format_inperson"] == 0

    def test_interview_format_inperson_one_hot(self):
        app = _make_app(interview_format="in_person")
        result = join_features(app, _make_job())
        assert result["interview_format_inperson"] == 1
        assert result["interview_format_video"] == 0
        assert result["interview_format_phone"] == 0

    def test_interview_format_none_gives_all_zeros(self):
        app = _make_app(interview_format=None)
        result = join_features(app, _make_job())
        assert result["interview_format_video"] == 0
        assert result["interview_format_phone"] == 0
        assert result["interview_format_inperson"] == 0

    def test_interview_rounds_none_defaults_to_zero(self):
        app = _make_app(interview_rounds=None)
        assert join_features(app, _make_job())["interview_rounds"] == 0

    def test_days_to_respond_passed_through(self):
        app = _make_app(days_to_respond=5)
        assert join_features(app, _make_job())["days_to_respond"] == 5