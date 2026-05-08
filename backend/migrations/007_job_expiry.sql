-- Migration 007: job post expiry date and application cap
ALTER TABLE jd_requests
    ADD COLUMN IF NOT EXISTS expires_at       TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS max_applications INTEGER,
    ADD COLUMN IF NOT EXISTS published_at     TIMESTAMPTZ;