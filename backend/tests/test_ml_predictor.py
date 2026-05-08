"""
Tests for ml_predictor.py — model loading and inference.

Models are mocked so tests run without trained .joblib files.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.services.ml_predictor import predict_fit, predict_join


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_app(**kwargs):
    app = MagicMock()
    app.id = uuid.uuid4()
    app.screening_score = kwargs.get("screening_score", 80)
    app.screening_recommendation = kwargs.get("screening_recommendation", "strong_match")
    app.screening_strengths = kwargs.get("screening_strengths", ["Python"])
    app.screening_gaps = kwargs.get("screening_gaps", [])
    app.cover_letter = kwargs.get("cover_letter", "Keen to join.")
    app.cv_path = kwargs.get("cv_path", "/cv.pdf")
    app.phone = kwargs.get("phone", "07700900000")
    app.shortlisted = kwargs.get("shortlisted", True)
    app.interview_status = kwargs.get("interview_status", "scheduled")
    app.interview_format = kwargs.get("interview_format", "video")
    app.interview_rounds = kwargs.get("interview_rounds", 2)
    app.days_to_respond = kwargs.get("days_to_respond", 3)
    app.offer_accepted = kwargs.get("offer_accepted", None)
    app.offer_date = kwargs.get("offer_date", None)
    from datetime import datetime, timezone
    app.applied_at = kwargs.get("applied_at", datetime(2024, 1, 1, tzinfo=timezone.utc))
    app.name = "Test Candidate"
    app.outcome = None
    return app


def _make_job(**kwargs):
    job = MagicMock()
    job.title = kwargs.get("title", "Senior Engineer")
    job.location = kwargs.get("location", "London, UK")
    job.required_skills = kwargs.get("required_skills", ["Python", "FastAPI"])
    job.nice_to_have_skills = kwargs.get("nice_to_have_skills", ["Docker"])
    return job


def _make_bundle(feature_cols: list) -> dict:
    """Fake model bundle as saved by ml_train.py."""
    pipeline = MagicMock()
    pipeline.predict_proba.return_value = [[0.2, 0.8]]
    return {"pipeline": pipeline, "features": feature_cols}


FIT_FEATURES = [
    "screening_score", "recommendation_rank", "skill_overlap", "gap_ratio",
    "nice_skill_overlap", "has_cv", "cover_letter_words", "has_phone",
    "seniority_tier", "required_skill_count", "nice_skill_count",
    "location_signal", "was_shortlisted", "reached_interview",
]

JOIN_FEATURES = [
    "screening_score", "recommendation_rank", "skill_overlap", "gap_ratio",
    "days_to_offer", "days_to_respond", "interview_rounds",
    "interview_format_video", "interview_format_phone", "interview_format_inperson",
    "seniority_tier", "required_skill_count", "location_signal",
    "cover_letter_words", "has_cv",
]


# ── predict_fit() ─────────────────────────────────────────────────────────────

class TestPredictFit:
    def test_returns_float_when_model_loaded(self):
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(FIT_FEATURES)
        with patch.object(pred_mod, "_fit_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_fit(_make_app(), _make_job())
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_returns_none_when_model_not_loaded(self):
        import app.services.ml_predictor as pred_mod
        with patch.object(pred_mod, "_fit_model", None), \
             patch.object(pred_mod, "_models_loaded", True):
            assert predict_fit(_make_app(), _make_job()) is None

    def test_probability_rounded_to_4_decimal_places(self):
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(FIT_FEATURES)
        bundle["pipeline"].predict_proba.return_value = [[0.123456789, 0.876543211]]
        with patch.object(pred_mod, "_fit_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_fit(_make_app(), _make_job())
        assert result == round(result, 4)

    def test_returns_none_on_prediction_error(self):
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(FIT_FEATURES)
        bundle["pipeline"].predict_proba.side_effect = RuntimeError("model corrupt")
        with patch.object(pred_mod, "_fit_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_fit(_make_app(), _make_job())
        assert result is None

    def test_low_screening_score_candidate(self):
        """Poor candidate should score lower — end-to-end feature alignment check."""
        import app.services.ml_predictor as pred_mod
        captured = {}

        def fake_predict_proba(vec):
            captured["vec"] = vec
            return [[0.9, 0.1]]

        bundle = _make_bundle(FIT_FEATURES)
        bundle["pipeline"].predict_proba.side_effect = fake_predict_proba

        with patch.object(pred_mod, "_fit_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_fit(_make_app(screening_score=10), _make_job())

        assert result == 0.1
        # Verify the feature vector length matches feature count
        assert len(captured["vec"][0]) == len(FIT_FEATURES)


# ── predict_join() ────────────────────────────────────────────────────────────

class TestPredictJoin:
    def test_returns_float_when_model_loaded(self):
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(JOIN_FEATURES)
        with patch.object(pred_mod, "_join_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_join(_make_app(), _make_job())
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_returns_none_when_model_not_loaded(self):
        import app.services.ml_predictor as pred_mod
        with patch.object(pred_mod, "_join_model", None), \
             patch.object(pred_mod, "_models_loaded", True):
            assert predict_join(_make_app(), _make_job()) is None

    def test_returns_none_on_prediction_error(self):
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(JOIN_FEATURES)
        bundle["pipeline"].predict_proba.side_effect = ValueError("bad input")
        with patch.object(pred_mod, "_join_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            assert predict_join(_make_app(), _make_job()) is None

    def test_feature_vector_length_matches_join_features(self):
        import app.services.ml_predictor as pred_mod
        captured = {}

        def fake_predict_proba(vec):
            captured["vec"] = vec
            return [[0.3, 0.7]]

        bundle = _make_bundle(JOIN_FEATURES)
        bundle["pipeline"].predict_proba.side_effect = fake_predict_proba

        with patch.object(pred_mod, "_join_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            predict_join(_make_app(), _make_job())

        assert len(captured["vec"][0]) == len(JOIN_FEATURES)


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_app_with_all_none_fields(self):
        """Gracefully handles an application with every optional field as None."""
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(FIT_FEATURES)
        with patch.object(pred_mod, "_fit_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_fit(
                _make_app(
                    screening_score=None,
                    screening_recommendation=None,
                    screening_strengths=None,
                    screening_gaps=None,
                    cover_letter=None,
                    cv_path=None,
                    phone=None,
                    interview_status=None,
                    interview_format=None,
                    interview_rounds=None,
                    days_to_respond=None,
                ),
                _make_job(required_skills=None, nice_to_have_skills=None),
            )
        # Should not raise — result is either float or None
        assert result is None or isinstance(result, float)

    def test_job_with_empty_skill_lists(self):
        import app.services.ml_predictor as pred_mod
        bundle = _make_bundle(FIT_FEATURES)
        with patch.object(pred_mod, "_fit_model", bundle), \
             patch.object(pred_mod, "_models_loaded", True):
            result = predict_fit(_make_app(), _make_job(required_skills=[], nice_to_have_skills=[]))
        assert result is None or isinstance(result, float)