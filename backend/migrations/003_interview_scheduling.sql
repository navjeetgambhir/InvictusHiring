-- 003_interview_scheduling.sql
-- Adds interview scheduling fields to candidate_applications
-- and creates the interview_invitations table.
--
-- Run once against the target database:
--   psql $DATABASE_URL -f backend/migrations/003_interview_scheduling.sql

ALTER TABLE candidate_applications
  ADD COLUMN IF NOT EXISTS shortlisted          BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS interview_status     VARCHAR(20),
  ADD COLUMN IF NOT EXISTS interview_scheduled_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS interview_format     VARCHAR(20),
  ADD COLUMN IF NOT EXISTS interview_location   VARCHAR(500),
  ADD COLUMN IF NOT EXISTS interview_notes      TEXT;

CREATE TABLE IF NOT EXISTS interview_invitations (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  application_id      UUID NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
  email_subject       VARCHAR(500) NOT NULL,
  email_body          TEXT NOT NULL,
  interview_questions JSONB NOT NULL DEFAULT '[]',
  -- HR-approved final version
  final_recipient     VARCHAR(255),
  final_subject       VARCHAR(500),
  final_body          TEXT,
  email_approved_at   TIMESTAMPTZ,
  email_sent_at       TIMESTAMPTZ,
  email_send_error    TEXT,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_interview_invitations_application_id
  ON interview_invitations(application_id);