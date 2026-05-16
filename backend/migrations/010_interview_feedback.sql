CREATE TABLE IF NOT EXISTS interview_feedback (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id       UUID NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
    submitted_by         VARCHAR(255) NOT NULL,
    round                SMALLINT NOT NULL DEFAULT 1,
    overall_rating       SMALLINT NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
    technical_score      SMALLINT CHECK (technical_score BETWEEN 1 AND 5),
    communication_score  SMALLINT CHECK (communication_score BETWEEN 1 AND 5),
    cultural_fit_score   SMALLINT CHECK (cultural_fit_score BETWEEN 1 AND 5),
    strengths            TEXT,
    concerns             TEXT,
    recommendation       VARCHAR(20) NOT NULL,   -- strong_hire | hire | no_hire | strong_no_hire
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_interview_feedback_application ON interview_feedback(application_id);