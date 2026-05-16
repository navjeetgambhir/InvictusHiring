-- Migration 003: add prompt_version tracking to jd_drafts and candidate_applications

ALTER TABLE jd_drafts
    ADD COLUMN IF NOT EXISTS prompt_version VARCHAR(50);

ALTER TABLE candidate_applications
    ADD COLUMN IF NOT EXISTS screening_prompt_version VARCHAR(50);