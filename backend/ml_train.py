"""
ML training script — fit model and join-prediction model.

Run from the project root after applying migration 005:

    PYTHONPATH=backend python backend/ml_train.py [--source db|csv] [--csv-path path/to/data.csv]

Data sources
------------
  db   — pulls labelled rows live from Postgres (requires DATABASE_URL in backend/.env)
  csv  — loads a CSV exported from the DB or a Kaggle bootstrap dataset

The CSV must have the same column names as the feature dicts produced by
ml_features.py, plus 'label_hired' and 'label_accepted'.

Outputs
-------
  ml_models/fit_model.joblib   — GradientBoostingClassifier for candidate-to-role fit
  ml_models/join_model.joblib  — GradientBoostingClassifier for offer acceptance
  ml_models/fit_report.txt     — classification report + feature importances
  ml_models/join_report.txt    — classification report + feature importances
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import classification_report, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ── Bootstrap: add backend/ to path so app.* imports work ────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from dotenv import load_dotenv
load_dotenv(ROOT / "backend" / ".env")

MODEL_DIR = ROOT / "ml_models"
MODEL_DIR.mkdir(exist_ok=True)

# Features used by each model (must match ml_features.py — label columns excluded)
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


# ── Data loading ──────────────────────────────────────────────────────────────

async def _load_from_db() -> pd.DataFrame:
    from app.core.database import AsyncSessionLocal
    from app.services.ml_features import extract_dataset

    async with AsyncSessionLocal() as db:
        fit_rows, join_rows = await extract_dataset(db)

    if not fit_rows and not join_rows:
        print("No labelled rows found in DB. Record outcomes via POST /api/candidates/applications/{id}/outcome first.")
        sys.exit(1)

    # Merge into one wide DataFrame; join columns will be NaN for non-offer rows
    fit_df  = pd.DataFrame(fit_rows)
    join_df = pd.DataFrame(join_rows)
    print(f"DB export: {len(fit_df)} fit rows, {len(join_df)} join rows")
    return fit_df, join_df


def _load_from_csv(path: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    df = pd.read_csv(path)
    print(f"Loaded {len(df)} rows from {path}")

    fit_df  = df[df["label_hired"].notna()].copy()
    join_df = df[df["label_accepted"].notna()].copy()
    print(f"  → {len(fit_df)} fit rows, {len(join_df)} join rows (after dropping nulls)")
    return fit_df, join_df


# ── Training ──────────────────────────────────────────────────────────────────

def _train(df: pd.DataFrame, feature_cols: list[str], label_col: str, name: str) -> Pipeline:
    df = df[feature_cols + [label_col]].dropna(subset=[label_col]).copy()
    df[feature_cols] = df[feature_cols].fillna(0)

    X = df[feature_cols].values
    y = df[label_col].astype(int).values

    pos = y.sum()
    neg = len(y) - pos
    print(f"\n── {name} ──────────────────────────────────")
    print(f"  Samples: {len(y)} total  |  {pos} positive  |  {neg} negative")

    if len(np.unique(y)) < 2:
        print("  WARNING: only one class present — cannot train. Collect more labelled data.")
        sys.exit(1)

    if len(y) < 30:
        print(f"  WARNING: only {len(y)} samples — model will be unreliable. Use a Kaggle bootstrap dataset.")

    # Scale + GBM pipeline (GBM is robust to scale, but StandardScaler helps with
    # the few numeric features that have very different ranges, e.g. cover_letter_words)
    pipeline = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", GradientBoostingClassifier(
            n_estimators=200,
            max_depth=3,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )),
    ])

    # Cross-validation (stratified 5-fold; fall back to 3-fold on small datasets)
    n_splits = min(5, pos, neg)
    if n_splits >= 2:
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        auc_scores = cross_val_score(pipeline, X, y, cv=cv, scoring="roc_auc")
        print(f"  CV ROC-AUC: {auc_scores.mean():.3f} ± {auc_scores.std():.3f}")
    else:
        print("  CV skipped — too few samples per class")

    # Final fit on full dataset
    pipeline.fit(X, y)

    # Evaluation report (in-sample — treat as a sanity check, not held-out perf)
    y_pred = pipeline.predict(X)
    y_prob = pipeline.predict_proba(X)[:, 1]
    print("\n  In-sample classification report:")
    print(classification_report(y, y_pred, target_names=["negative", "positive"], zero_division=0))
    print(f"  In-sample ROC-AUC: {roc_auc_score(y, y_prob):.3f}")

    # Feature importances
    clf = pipeline.named_steps["clf"]
    importances = sorted(
        zip(feature_cols, clf.feature_importances_),
        key=lambda x: x[1],
        reverse=True,
    )
    print("\n  Feature importances:")
    for feat, imp in importances:
        bar = "█" * int(imp * 40)
        print(f"    {feat:<30} {imp:.4f}  {bar}")

    # Return a bundle so the predictor can align columns at inference time
    bundle = {"pipeline": pipeline, "features": feature_cols}
    return bundle, importances


def _save_report(name: str, bundle: dict, importances: list) -> None:
    report_path = MODEL_DIR / f"{name}_report.txt"
    clf = bundle["pipeline"].named_steps["clf"]
    lines = [
        f"Model: {name}",
        f"Estimator: {type(clf).__name__}",
        f"n_estimators={clf.n_estimators}  max_depth={clf.max_depth}  "
        f"learning_rate={clf.learning_rate}  subsample={clf.subsample}",
        "",
        "Feature importances (descending):",
    ]
    for feat, imp in importances:
        lines.append(f"  {feat:<30} {imp:.6f}")
    report_path.write_text("\n".join(lines))
    print(f"\n  Report saved → {report_path}")


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Train fit and join-prediction models")
    parser.add_argument("--source", choices=["db", "csv"], default="db",
                        help="Data source: 'db' (live Postgres) or 'csv' (file)")
    parser.add_argument("--csv-path", default=None,
                        help="Path to CSV file when --source=csv")
    args = parser.parse_args()

    if args.source == "db":
        fit_df, join_df = asyncio.run(_load_from_db())
    else:
        if not args.csv_path:
            print("--csv-path required when --source=csv")
            sys.exit(1)
        fit_df, join_df = _load_from_csv(args.csv_path)

    # ── Fit model ─────────────────────────────────────────────────────────────
    fit_bundle, fit_importances = _train(fit_df, FIT_FEATURES, "label_hired", "Candidate-to-Role Fit")
    fit_model_path = MODEL_DIR / "fit_model.joblib"
    joblib.dump(fit_bundle, fit_model_path)
    print(f"\n  Fit model saved → {fit_model_path}")
    _save_report("fit", fit_bundle, fit_importances)

    # ── Join model ────────────────────────────────────────────────────────────
    if len(join_df) == 0:
        print("\n── Join Prediction ─────────────────────────────────────────────")
        print("  No offer rows found — skipping join model training.")
        print("  Record offer outcomes via POST /api/candidates/applications/{id}/outcome")
    else:
        join_bundle, join_importances = _train(join_df, JOIN_FEATURES, "label_accepted", "Join Prediction (Offer Acceptance)")
        join_model_path = MODEL_DIR / "join_model.joblib"
        joblib.dump(join_bundle, join_model_path)
        print(f"\n  Join model saved → {join_model_path}")
        _save_report("join", join_bundle, join_importances)

    print("\nDone. Restart the backend to load the updated models.")


if __name__ == "__main__":
    main()