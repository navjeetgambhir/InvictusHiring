"""
ML predictor — loads trained models from disk and exposes predict_fit() / predict_join().

Models are trained by ml_train.py and saved to backend/ml_models/.
On first call the models are loaded once and cached in module-level globals.
If a model file is missing, predictions return None rather than raising.

Usage in routes
---------------
    from app.services.ml_predictor import predict_fit, predict_join

    fit_prob   = predict_fit(app, job)    # float 0–1 or None
    join_prob  = predict_join(app, job)   # float 0–1 or None
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import joblib
import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from app.db.models import CandidateApplication, JDRequest

from app.services.ml_features import fit_features, join_features

# ── Human-readable labels for SHAP output ─────────────────────────────────────

_FIT_LABELS: dict[str, str] = {
    "screening_score":      "AI screening score",
    "recommendation_rank":  "AI recommendation level",
    "skill_overlap":        "Required skills matched",
    "gap_ratio":            "Skill gaps identified",
    "nice_skill_overlap":   "Nice-to-have skills matched",
    "has_cv":               "CV submitted",
    "cover_letter_words":   "Cover letter length",
    "has_phone":            "Phone provided",
    "seniority_tier":       "Seniority match",
    "required_skill_count": "Number of required skills",
    "nice_skill_count":     "Number of nice-to-have skills",
    "location_signal":      "Location match",
    "was_shortlisted":      "Shortlisted by HR",
    "reached_interview":    "Reached interview stage",
}

_JOIN_LABELS: dict[str, str] = {
    "screening_score":           "AI screening score",
    "recommendation_rank":       "AI recommendation level",
    "skill_overlap":             "Required skills matched",
    "gap_ratio":                 "Skill gaps",
    "days_to_offer":             "Days to receive offer",
    "days_to_respond":           "Days to respond",
    "interview_rounds":          "Interview rounds completed",
    "interview_format_video":    "Video interview",
    "interview_format_phone":    "Phone interview",
    "interview_format_inperson": "In-person interview",
    "seniority_tier":            "Seniority level",
    "required_skill_count":      "Number of required skills",
    "location_signal":           "Location match",
    "cover_letter_words":        "Cover letter length",
    "has_cv":                    "CV submitted",
}

_MODEL_DIR = Path(__file__).resolve().parents[3] / "ml_models"

_fit_model = None
_join_model = None
_models_loaded = False


def _load_models() -> None:
    global _fit_model, _join_model, _models_loaded
    if _models_loaded:
        return

    fit_path = _MODEL_DIR / "fit_model.joblib"
    join_path = _MODEL_DIR / "join_model.joblib"

    if fit_path.exists():
        _fit_model = joblib.load(fit_path)   # {"pipeline": ..., "features": [...]}
        logger.info(f"Fit model loaded from {fit_path}")
    else:
        logger.warning(f"Fit model not found at {fit_path} — run ml_train.py first")

    if join_path.exists():
        _join_model = joblib.load(join_path)
        logger.info(f"Join model loaded from {join_path}")
    else:
        logger.warning(f"Join model not found at {join_path} — run ml_train.py first")

    _models_loaded = True


def _feature_vector(features: dict, bundle: dict) -> list:
    """Extract values in the same column order the model was trained on."""
    return [features.get(col, 0) or 0 for col in bundle["features"]]


def predict_fit(app: CandidateApplication, job: JDRequest) -> float | None:
    """Return probability (0–1) that this candidate is a fit for the role, or None if model unavailable."""
    _load_models()
    if _fit_model is None:
        return None
    try:
        features = fit_features(app, job)
        features.pop("label_hired", None)
        vec = [_feature_vector(features, _fit_model)]
        prob = _fit_model["pipeline"].predict_proba(vec)[0][1]
        return round(float(prob*100), 2)
    except Exception as exc:
        logger.warning(f"predict_fit failed for application {app.id}: {exc}")
        return None


def predict_join(app: CandidateApplication, job: JDRequest) -> float | None:
    """Return probability (0–1) that this candidate will accept an offer, or None if model unavailable."""
    _load_models()
    if _join_model is None:
        return None
    try:
        features = join_features(app, job)
        features.pop("label_accepted", None)
        vec = [_feature_vector(features, _join_model)]
        prob = _join_model["pipeline"].predict_proba(vec)[0][1]
        return round(float(prob*100), 2)
    except Exception as exc:
        logger.warning(f"predict_join failed for application {app.id}: {exc}")
        return None


# ── SHAP explainability ────────────────────────────────────────────────────────

def _shap_factors(
    bundle: dict,
    feature_names: list[str],
    raw_vec: list,
    labels: dict[str, str],
    top_n: int = 5,
) -> list[dict]:
    """
    Compute SHAP values for a single prediction and return the top_n factors.

    Returns a list of dicts:
      {"feature": str, "label": str, "contribution": float, "direction": "positive"|"negative", "raw_value": float}

    Positive contribution = pushed the score UP; negative = pushed it DOWN.
    """
    try:
        import shap  # lazy import — not required for core predictions

        pipeline = bundle["pipeline"]
        # Transform input through all steps except the final estimator
        X = np.array([raw_vec])
        if len(pipeline) > 1:
            X_transformed = pipeline[:-1].transform(X)
        else:
            X_transformed = X

        clf = pipeline[-1]
        explainer = shap.TreeExplainer(clf)
        shap_values = explainer.shap_values(X_transformed)

        # GBC returns a single array (log-odds contribution for positive class)
        values = np.array(shap_values[0] if isinstance(shap_values, list) else shap_values[0])

        factors = []
        for i, (name, shap_val) in enumerate(zip(feature_names, values)):
            factors.append({
                "feature": name,
                "label": labels.get(name, name.replace("_", " ").title()),
                "contribution": round(float(shap_val), 4),
                "direction": "positive" if shap_val >= 0 else "negative",
                "raw_value": round(float(raw_vec[i]), 4),
            })

        # Sort by absolute contribution and return top_n
        factors.sort(key=lambda f: abs(f["contribution"]), reverse=True)
        return factors[:top_n]

    except Exception as exc:
        logger.warning(f"SHAP explanation failed: {exc}")
        return []


def explain_fit(app: CandidateApplication, job: JDRequest, top_n: int = 5) -> list[dict]:
    """Return top SHAP feature contributions for the fit prediction."""
    _load_models()
    if _fit_model is None:
        return []
    try:
        features = fit_features(app, job)
        features.pop("label_hired", None)
        raw_vec = _feature_vector(features, _fit_model)
        return _shap_factors(_fit_model, _fit_model["features"], raw_vec, _FIT_LABELS, top_n)
    except Exception as exc:
        logger.warning(f"explain_fit failed for application {app.id}: {exc}")
        return []


def explain_join(app: CandidateApplication, job: JDRequest, top_n: int = 5) -> list[dict]:
    """Return top SHAP feature contributions for the join prediction."""
    _load_models()
    if _join_model is None:
        return []
    try:
        features = join_features(app, job)
        features.pop("label_accepted", None)
        raw_vec = _feature_vector(features, _join_model)
        return _shap_factors(_join_model, _join_model["features"], raw_vec, _JOIN_LABELS, top_n)
    except Exception as exc:
        logger.warning(f"explain_join failed for application {app.id}: {exc}")
        return []