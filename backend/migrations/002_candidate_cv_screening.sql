-- Migration 002: Add CV upload and AI screening fields to candidate_applications

ALTER TABLE candidate_applications
  ADD COLUMN IF NOT EXISTS cv_filename              VARCHAR(500),
  ADD COLUMN IF NOT EXISTS cv_path                  VARCHAR(500),
  ADD COLUMN IF NOT EXISTS screening_status         VARCHAR(20) NOT NULL DEFAULT 'pending',
  ADD COLUMN IF NOT EXISTS screening_score          INTEGER,
  ADD COLUMN IF NOT EXISTS screening_summary        TEXT,
  ADD COLUMN IF NOT EXISTS screening_strengths      JSONB,
  ADD COLUMN IF NOT EXISTS screening_gaps           JSONB,
  ADD COLUMN IF NOT EXISTS screening_recommendation VARCHAR(50);