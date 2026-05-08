-- Migration 005: ML outcome fields for fit and join prediction models
--
-- Run once:
--   docker compose exec postgres psql -U hiring_user -d hiring_db \
--     -f backend/migrations/005_ml_outcome_fields.sql

ALTER TABLE candidate_applications
  -- Hiring outcome (target label for fit model)
  ADD COLUMN IF NOT EXISTS outcome              VARCHAR(20),     -- hired | rejected | withdrew | no_hire
  ADD COLUMN IF NOT EXISTS outcome_recorded_at TIMESTAMPTZ,

  -- Offer stage (target labels for join prediction model)
  ADD COLUMN IF NOT EXISTS offer_extended      BOOLEAN,
  ADD COLUMN IF NOT EXISTS offer_amount        VARCHAR(100),    -- free-text, e.g. "£55,000"
  ADD COLUMN IF NOT EXISTS offer_date          TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS offer_accepted      BOOLEAN,
  ADD COLUMN IF NOT EXISTS offer_declined_reason VARCHAR(50),   -- competing_offer | salary | role_fit | location | other

  -- Extra signal for join prediction features
  ADD COLUMN IF NOT EXISTS interview_rounds    SMALLINT,        -- total number of interview rounds completed
  ADD COLUMN IF NOT EXISTS days_to_respond     SMALLINT;        -- calendar days between invite sent and candidate reply

CREATE INDEX IF NOT EXISTS ix_candidate_applications_outcome
  ON candidate_applications (outcome)
  WHERE outcome IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_candidate_applications_offer_accepted
  ON candidate_applications (offer_accepted)
  WHERE offer_accepted IS NOT NULL;