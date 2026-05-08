"""
Kaggle bootstrap data preparation for the fit and join-prediction ML models.

Downloads the IBM HR Analytics Employee Attrition dataset from Kaggle, maps its
columns to the Invictus Hiring feature schema, then appends synthetic negative
examples to balance the dataset.

Why synthetic negatives are needed
───────────────────────────────────
The IBM dataset is heavily skewed: ~84% of employees have high performance
(label_hired=1) and ~84% stayed (label_accepted=1). A model trained on this
distribution would simply predict "hired" and "accepted" for every candidate.

Synthetic negatives are generated as four distinct realistic personas per model,
each with internally consistent feature values (e.g. a skill-mismatch candidate
has low skill_overlap AND high gap_ratio AND low screening_score simultaneously).

Final target distribution: ~60% positive / 40% negative for both labels.

Usage
─────
  # 1. Set up Kaggle API credentials at ~/.kaggle/kaggle.json
  #    (Kaggle → Account → API → Create New Token, chmod 600 ~/.kaggle/kaggle.json)

  python Data/prepare_kaggle_data.py

  # Output: Data/training_data.csv  (~2,400 rows, balanced labels)

  # 2. Train:
  PYTHONPATH=backend python backend/ml_train.py --source csv --csv-path Data/training_data.csv
"""

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent
OUT_CSV  = DATA_DIR / "training_data.csv"
RAW_CSV  = DATA_DIR / "WA_Fn-UseC_-HR-Employee-Attrition.csv"

KAGGLE_DATASET = "pavansubhasht/ibm-hr-analytics-attrition-dataset"

# Target: add this many synthetic negatives for each label
_N_FIT_NEGATIVES  = 700   # brings fit label to ~37% negative
_N_JOIN_NEGATIVES = 700   # brings join label to ~37% negative


# ── Download ──────────────────────────────────────────────────────────────────

def _download():
    if RAW_CSV.exists():
        print(f"Raw dataset already present: {RAW_CSV}")
        return
    try:
        import kaggle  # noqa: F401 — triggers credential check
    except OSError:
        print(
            "\nKaggle credentials not found.\n"
            "Setup:\n"
            "  1. kaggle.com → Account → API → Create New Token\n"
            "  2. mv ~/Downloads/kaggle.json ~/.kaggle/kaggle.json\n"
            "  3. chmod 600 ~/.kaggle/kaggle.json\n"
            "  4. Re-run this script\n"
            "\nOr download manually:\n"
            f"  https://www.kaggle.com/datasets/{KAGGLE_DATASET}\n"
            f"  Unzip → place WA_Fn-UseC_-HR-Employee-Attrition.csv in {DATA_DIR}/\n"
        )
        sys.exit(1)

    print(f"Downloading {KAGGLE_DATASET} ...")
    os.system(f"kaggle datasets download -d {KAGGLE_DATASET} -p {DATA_DIR} --unzip")

    if not RAW_CSV.exists():
        candidates = list(DATA_DIR.glob("*.csv"))
        if candidates:
            candidates[0].rename(RAW_CSV)
        else:
            print("Download failed. Please download manually.")
            sys.exit(1)

    print(f"Downloaded: {RAW_CSV}")


# ── Real-data mapping ─────────────────────────────────────────────────────────

def _map_features(df: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Map IBM HR Analytics columns → Invictus Hiring feature schema."""
    n    = len(df)
    perf = df["PerformanceRating"].clip(1, 4)
    edu  = df["Education"].clip(1, 5)

    screening_score = (perf / 4 * 75 + edu / 5 * 15 + rng.normal(0, 3, n)).clip(0, 100).round().astype(int)
    recommendation_rank = perf.astype(int)
    skill_overlap       = (df["JobInvolvement"].clip(1, 4) / 4).round(2)
    gap_ratio           = (1 - skill_overlap).round(2)
    nice_skill_overlap  = (df["RelationshipSatisfaction"].clip(1, 4) / 4).round(2)
    cover_letter_words  = (edu * 60 + df["JobInvolvement"].clip(1, 4) * 20 + rng.normal(0, 15, n)).clip(0).round().astype(int)
    seniority_tier      = df["JobLevel"].clip(1, 4).astype(int)
    location_signal     = (df["DistanceFromHome"] <= 10).astype(int)
    was_shortlisted     = (perf >= 3).astype(int)
    reached_interview   = (df["JobLevel"] >= 2).astype(int)
    days_to_offer       = (df["YearsAtCompany"].clip(0, 20) * 5 + 20 + rng.normal(0, 5, n)).clip(5).round().astype(int)
    interview_rounds    = df["NumCompaniesWorked"].clip(1, 5).astype(int)
    fmt = rng.choice(["phone", "video", "in_person"], n, p=[0.2, 0.5, 0.3])

    return pd.DataFrame({
        "screening_score":           screening_score,
        "recommendation_rank":       recommendation_rank,
        "skill_overlap":             skill_overlap,
        "gap_ratio":                 gap_ratio,
        "nice_skill_overlap":        nice_skill_overlap,
        "has_cv":                    1,
        "cover_letter_words":        cover_letter_words,
        "has_phone":                 1,
        "seniority_tier":            seniority_tier,
        "required_skill_count":      rng.integers(3, 9, n),
        "nice_skill_count":          rng.integers(1, 5, n),
        "location_signal":           location_signal,
        "was_shortlisted":           was_shortlisted,
        "reached_interview":         reached_interview,
        "days_to_offer":             days_to_offer,
        "days_to_respond":           rng.integers(1, 15, n),
        "interview_rounds":          interview_rounds,
        "interview_format_video":    (fmt == "video").astype(int),
        "interview_format_phone":    (fmt == "phone").astype(int),
        "interview_format_inperson": (fmt == "in_person").astype(int),
        "label_hired":               (perf >= 3).astype(int),
        "label_accepted":            (df["Attrition"] == "No").astype(int),
    })


# ── Synthetic negative generation ─────────────────────────────────────────────

def _make_fit_negatives(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """
    Generate n synthetic candidates who would NOT be hired.

    Four personas — each has internally consistent, realistic features:

    1. Underqualified (35%)
       Skills don't match the role at all. Applied speculatively.
       Low screening score, very high gap ratio, no shortlisting.

    2. Wrong seniority (25%)
       Junior candidate for a senior role (or vice versa).
       Seniority tier mismatch is the primary signal.

    3. Poor engagement (20%)
       No CV, one-line cover letter, no phone number.
       Signals low commitment to the application.

    4. Skill mismatch despite experience (20%)
       Experienced but in the wrong domain.
       Moderate score, high gap ratio, low skill overlap.
    """
    sizes = _split(n, [0.35, 0.25, 0.20, 0.20])
    parts = []

    # ── Persona 1: Underqualified ─────────────────────────────────────────────
    k = sizes[0]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(5, 40, k),
        "recommendation_rank":   rng.choice([1, 2], k, p=[0.6, 0.4]),
        "skill_overlap":         rng.uniform(0.0, 0.25, k).round(2),
        "gap_ratio":             rng.uniform(0.7, 1.0, k).round(2),
        "nice_skill_overlap":    rng.uniform(0.0, 0.3, k).round(2),
        "has_cv":                rng.choice([0, 1], k, p=[0.3, 0.7]),
        "cover_letter_words":    rng.integers(0, 80, k),
        "has_phone":             rng.choice([0, 1], k, p=[0.4, 0.6]),
        "seniority_tier":        rng.integers(1, 3, k),
        "required_skill_count":  rng.integers(5, 9, k),
        "nice_skill_count":      rng.integers(2, 5, k),
        "location_signal":       rng.integers(0, 2, k),
        "was_shortlisted":       0,
        "reached_interview":     0,
        "days_to_offer":         rng.integers(5, 20, k),
        "days_to_respond":       rng.integers(1, 7, k),
        "interview_rounds":      rng.integers(0, 2, k),
        **_fmt_cols(k, rng, p=[0.5, 0.3, 0.2]),
        "label_hired":    0,
        "label_accepted": rng.choice([0, 1], k, p=[0.5, 0.5]),
    }))

    # ── Persona 2: Wrong seniority ────────────────────────────────────────────
    k = sizes[1]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(30, 60, k),
        "recommendation_rank":   rng.choice([1, 2], k, p=[0.5, 0.5]),
        "skill_overlap":         rng.uniform(0.2, 0.5, k).round(2),
        "gap_ratio":             rng.uniform(0.5, 0.8, k).round(2),
        "nice_skill_overlap":    rng.uniform(0.1, 0.4, k).round(2),
        "has_cv":                1,
        "cover_letter_words":    rng.integers(50, 200, k),
        "has_phone":             1,
        "seniority_tier":        rng.choice([1, 4], k),   # mismatch: too junior or too senior
        "required_skill_count":  rng.integers(4, 8, k),
        "nice_skill_count":      rng.integers(1, 4, k),
        "location_signal":       rng.integers(0, 2, k),
        "was_shortlisted":       0,
        "reached_interview":     rng.choice([0, 1], k, p=[0.7, 0.3]),
        "days_to_offer":         rng.integers(10, 30, k),
        "days_to_respond":       rng.integers(1, 10, k),
        "interview_rounds":      rng.integers(1, 3, k),
        **_fmt_cols(k, rng),
        "label_hired":    0,
        "label_accepted": rng.choice([0, 1], k, p=[0.4, 0.6]),
    }))

    # ── Persona 3: Poor engagement ────────────────────────────────────────────
    k = sizes[2]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(10, 50, k),
        "recommendation_rank":   rng.choice([1, 2], k, p=[0.7, 0.3]),
        "skill_overlap":         rng.uniform(0.0, 0.3, k).round(2),
        "gap_ratio":             rng.uniform(0.6, 1.0, k).round(2),
        "nice_skill_overlap":    rng.uniform(0.0, 0.25, k).round(2),
        "has_cv":                0,       # no CV uploaded
        "cover_letter_words":    rng.integers(0, 30, k),  # near-empty cover letter
        "has_phone":             0,
        "seniority_tier":        rng.integers(1, 3, k),
        "required_skill_count":  rng.integers(3, 8, k),
        "nice_skill_count":      rng.integers(1, 4, k),
        "location_signal":       rng.integers(0, 2, k),
        "was_shortlisted":       0,
        "reached_interview":     0,
        "days_to_offer":         rng.integers(5, 15, k),
        "days_to_respond":       rng.integers(1, 5, k),
        "interview_rounds":      0,
        **_fmt_cols(k, rng, p=[0.6, 0.3, 0.1]),
        "label_hired":    0,
        "label_accepted": rng.choice([0, 1], k, p=[0.6, 0.4]),
    }))

    # ── Persona 4: Domain mismatch (experienced, wrong field) ─────────────────
    k = sizes[3]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(35, 65, k),
        "recommendation_rank":   rng.choice([2, 3], k, p=[0.6, 0.4]),
        "skill_overlap":         rng.uniform(0.1, 0.35, k).round(2),
        "gap_ratio":             rng.uniform(0.55, 0.85, k).round(2),
        "nice_skill_overlap":    rng.uniform(0.1, 0.4, k).round(2),
        "has_cv":                1,
        "cover_letter_words":    rng.integers(100, 350, k),  # they tried
        "has_phone":             1,
        "seniority_tier":        rng.integers(2, 4, k),
        "required_skill_count":  rng.integers(5, 9, k),
        "nice_skill_count":      rng.integers(2, 5, k),
        "location_signal":       rng.integers(0, 2, k),
        "was_shortlisted":       rng.choice([0, 1], k, p=[0.8, 0.2]),
        "reached_interview":     rng.choice([0, 1], k, p=[0.6, 0.4]),
        "days_to_offer":         rng.integers(15, 40, k),
        "days_to_respond":       rng.integers(2, 12, k),
        "interview_rounds":      rng.integers(1, 3, k),
        **_fmt_cols(k, rng),
        "label_hired":    0,
        "label_accepted": rng.choice([0, 1], k, p=[0.45, 0.55]),
    }))

    return pd.concat(parts, ignore_index=True)


def _make_join_negatives(n: int, rng: np.random.Generator) -> pd.DataFrame:
    """
    Generate n synthetic candidates who would NOT accept an offer.

    Four personas:

    1. Counter-offer accepted (30%)
       Strong candidate who got a better offer while waiting.
       High screening score, good fit — but the process took too long.

    2. Salary / location deal-breaker (30%)
       Candidate liked the role but couldn't make it work.
       Good scores, bad location signal, quick decline.

    3. Speculative applicant (25%)
       Applied while not seriously looking. Slow to respond,
       dropped out after first interview.

    4. Multiple competing offers (15%)
       High-value candidate with several options. Short process but
       declined immediately — had a better offer in hand.
    """
    sizes = _split(n, [0.30, 0.30, 0.25, 0.15])
    parts = []

    # ── Persona 1: Counter-offer accepted ────────────────────────────────────
    k = sizes[0]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(65, 95, k),   # strong candidate
        "recommendation_rank":   rng.choice([3, 4], k, p=[0.5, 0.5]),
        "skill_overlap":         rng.uniform(0.6, 0.95, k).round(2),
        "gap_ratio":             rng.uniform(0.0, 0.3, k).round(2),
        "days_to_offer":         rng.integers(60, 120, k),  # process dragged on
        "days_to_respond":       rng.integers(1, 3, k),     # quick decline
        "interview_rounds":      rng.integers(3, 5, k),
        "seniority_tier":        rng.integers(2, 5, k),
        "required_skill_count":  rng.integers(4, 8, k),
        "location_signal":       rng.integers(0, 2, k),
        "cover_letter_words":    rng.integers(150, 400, k),
        "has_cv":                1,
        **_fmt_cols(k, rng, p=[0.1, 0.6, 0.3]),
        "label_hired":    1,   # they WERE a fit — they just didn't join
        "label_accepted": 0,
    }))

    # ── Persona 2: Salary / location deal-breaker ─────────────────────────────
    k = sizes[1]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(55, 85, k),
        "recommendation_rank":   rng.choice([2, 3], k, p=[0.4, 0.6]),
        "skill_overlap":         rng.uniform(0.5, 0.85, k).round(2),
        "gap_ratio":             rng.uniform(0.1, 0.4, k).round(2),
        "days_to_offer":         rng.integers(25, 55, k),
        "days_to_respond":       rng.integers(2, 6, k),
        "interview_rounds":      rng.integers(2, 4, k),
        "seniority_tier":        rng.integers(2, 4, k),
        "required_skill_count":  rng.integers(4, 8, k),
        "location_signal":       0,   # bad location every time — that's the reason
        "cover_letter_words":    rng.integers(100, 300, k),
        "has_cv":                1,
        **_fmt_cols(k, rng),
        "label_hired":    rng.choice([0, 1], k, p=[0.3, 0.7]),
        "label_accepted": 0,
    }))

    # ── Persona 3: Speculative applicant ─────────────────────────────────────
    k = sizes[2]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(30, 65, k),
        "recommendation_rank":   rng.choice([1, 2], k, p=[0.4, 0.6]),
        "skill_overlap":         rng.uniform(0.2, 0.55, k).round(2),
        "gap_ratio":             rng.uniform(0.4, 0.75, k).round(2),
        "days_to_offer":         rng.integers(30, 70, k),
        "days_to_respond":       rng.integers(8, 20, k),   # slow — not engaged
        "interview_rounds":      rng.integers(1, 3, k),
        "seniority_tier":        rng.integers(1, 3, k),
        "required_skill_count":  rng.integers(3, 7, k),
        "location_signal":       rng.integers(0, 2, k),
        "cover_letter_words":    rng.integers(0, 100, k),  # minimal effort
        "has_cv":                rng.choice([0, 1], k, p=[0.2, 0.8]),
        **_fmt_cols(k, rng, p=[0.5, 0.3, 0.2]),
        "label_hired":    rng.choice([0, 1], k, p=[0.6, 0.4]),
        "label_accepted": 0,
    }))

    # ── Persona 4: Multiple competing offers ──────────────────────────────────
    k = sizes[3]
    parts.append(pd.DataFrame({
        "screening_score":       rng.integers(75, 100, k),  # top-tier candidate
        "recommendation_rank":   4,
        "skill_overlap":         rng.uniform(0.75, 1.0, k).round(2),
        "gap_ratio":             rng.uniform(0.0, 0.2, k).round(2),
        "days_to_offer":         rng.integers(20, 45, k),
        "days_to_respond":       rng.integers(1, 2, k),    # immediate decline
        "interview_rounds":      rng.integers(2, 4, k),
        "seniority_tier":        rng.integers(3, 5, k),
        "required_skill_count":  rng.integers(5, 9, k),
        "location_signal":       rng.integers(0, 2, k),
        "cover_letter_words":    rng.integers(200, 500, k),
        "has_cv":                1,
        **_fmt_cols(k, rng, p=[0.1, 0.5, 0.4]),
        "label_hired":    1,
        "label_accepted": 0,
    }))

    return pd.concat(parts, ignore_index=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _split(n: int, proportions: list[float]) -> list[int]:
    """Split n into chunks according to proportions, ensuring sum == n."""
    sizes = [int(n * p) for p in proportions]
    sizes[-1] += n - sum(sizes)
    return sizes


def _fmt_cols(n: int, rng: np.random.Generator, p: list | None = None) -> dict:
    """Return the three interview_format_* one-hot columns."""
    if p is None:
        p = [0.2, 0.5, 0.3]
    fmt = rng.choice(["phone", "video", "in_person"], n, p=p)
    return {
        "interview_format_phone":    (fmt == "phone").astype(int),
        "interview_format_video":    (fmt == "video").astype(int),
        "interview_format_inperson": (fmt == "in_person").astype(int),
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    _download()

    print(f"Loading {RAW_CSV} ...")
    raw = pd.read_csv(RAW_CSV)
    print(f"  Raw rows: {len(raw)}")

    required_cols = {
        "PerformanceRating", "Education", "JobInvolvement", "RelationshipSatisfaction",
        "JobLevel", "DistanceFromHome", "NumCompaniesWorked", "YearsAtCompany", "Attrition",
    }
    missing = required_cols - set(raw.columns)
    if missing:
        print(f"ERROR: missing columns: {missing}")
        sys.exit(1)

    rng = np.random.default_rng(seed=42)

    # ── Map real data ─────────────────────────────────────────────────────────
    real = _map_features(raw, rng)
    print(f"  Real data — label_hired=1: {real['label_hired'].sum()} ({real['label_hired'].mean():.1%})  "
          f"label_accepted=1: {real['label_accepted'].sum()} ({real['label_accepted'].mean():.1%})")

    # ── Generate synthetic negatives ──────────────────────────────────────────
    print(f"\nGenerating {_N_FIT_NEGATIVES} fit negatives across 4 personas ...")
    fit_negs = _make_fit_negatives(_N_FIT_NEGATIVES, rng)

    print(f"Generating {_N_JOIN_NEGATIVES} join negatives across 4 personas ...")
    join_negs = _make_join_negatives(_N_JOIN_NEGATIVES, rng)

    # Combine: real data + both negative sets
    combined = pd.concat([real, fit_negs, join_negs], ignore_index=True)

    # Ensure all expected columns are present and correctly typed
    combined = combined.fillna(0)
    for col in ["has_cv", "has_phone", "was_shortlisted", "reached_interview",
                "interview_format_video", "interview_format_phone", "interview_format_inperson",
                "label_hired", "label_accepted"]:
        combined[col] = combined[col].astype(int)

    combined.to_csv(OUT_CSV, index=False)

    # ── Report ─────────────────────────────────────────────────────────────────
    total = len(combined)
    print(f"\n{'─'*55}")
    print(f"Output: {OUT_CSV}")
    print(f"  Total rows:        {total}")
    print(f"  label_hired=1:     {combined['label_hired'].sum():>4}  ({combined['label_hired'].mean():.1%})")
    print(f"  label_hired=0:     {(combined['label_hired']==0).sum():>4}  ({(combined['label_hired']==0).mean():.1%})")
    print(f"  label_accepted=1:  {combined['label_accepted'].sum():>4}  ({combined['label_accepted'].mean():.1%})")
    print(f"  label_accepted=0:  {(combined['label_accepted']==0).sum():>4}  ({(combined['label_accepted']==0).mean():.1%})")
    print(f"{'─'*55}")


if __name__ == "__main__":
    main()