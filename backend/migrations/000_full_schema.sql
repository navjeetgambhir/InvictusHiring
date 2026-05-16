-- Full schema creation for fresh database deployments.
-- Run this instead of migrations 002–008 on a brand-new database.
-- Always run 001_init.sql first (creates pgvector extension).

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_hash VARCHAR(64) UNIQUE NOT NULL,
    email_encrypted TEXT NOT NULL,
    name VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS past_jds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title VARCHAR(255) NOT NULL,
    department VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS jd_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id UUID NOT NULL,
    submitted_by VARCHAR(255) NOT NULL,
    role VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,
    department VARCHAR(255) NOT NULL,
    location VARCHAR(255) NOT NULL,
    salary_band VARCHAR(100) NOT NULL,
    required_skills JSONB NOT NULL,
    nice_to_have_skills JSONB NOT NULL,
    company_description TEXT NOT NULL,
    additional_context TEXT,
    status VARCHAR(50) NOT NULL DEFAULT 'drafting',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    max_applications INTEGER
);
CREATE INDEX IF NOT EXISTS ix_jd_requests_session_id ON jd_requests(session_id);

CREATE TABLE IF NOT EXISTS jd_drafts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES jd_requests(id),
    version INTEGER NOT NULL DEFAULT 1,
    content TEXT NOT NULL,
    rejection_feedback TEXT,
    prompt_version VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES jd_requests(id),
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS job_postings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES jd_requests(id),
    platform VARCHAR(50) NOT NULL,
    formatted_content TEXT NOT NULL,
    post_url VARCHAR(500),
    status VARCHAR(20) NOT NULL DEFAULT 'posted',
    posted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS candidate_applications (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL REFERENCES jd_requests(id),
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255) NOT NULL,
    phone VARCHAR(50),
    cover_letter TEXT,
    cover_letter_filename VARCHAR(255),
    cv_filename VARCHAR(500),
    cv_path VARCHAR(500),
    screening_status VARCHAR(20) NOT NULL DEFAULT 'pending',
    screening_score INTEGER,
    screening_summary TEXT,
    screening_strengths JSONB,
    screening_gaps JSONB,
    screening_recommendation VARCHAR(50),
    screening_prompt_version VARCHAR(50),
    shortlisted BOOLEAN NOT NULL DEFAULT FALSE,
    interview_status VARCHAR(20),
    interview_scheduled_at TIMESTAMPTZ,
    interview_format VARCHAR(20),
    interview_location VARCHAR(500),
    interview_notes TEXT,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    outcome VARCHAR(20),
    outcome_recorded_at TIMESTAMPTZ,
    offer_extended BOOLEAN,
    offer_amount VARCHAR(100),
    offer_date TIMESTAMPTZ,
    offer_accepted BOOLEAN,
    offer_declined_reason VARCHAR(50),
    interview_rounds SMALLINT,
    days_to_respond SMALLINT
);

CREATE TABLE IF NOT EXISTS interview_invitations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id UUID NOT NULL REFERENCES candidate_applications(id) ON DELETE CASCADE,
    email_subject VARCHAR(500) NOT NULL,
    email_body TEXT NOT NULL,
    interview_questions JSONB NOT NULL DEFAULT '[]',
    final_recipient VARCHAR(255),
    final_subject VARCHAR(500),
    final_body TEXT,
    email_approved_at TIMESTAMPTZ,
    email_sent_at TIMESTAMPTZ,
    email_send_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_interview_invitations_application_id ON interview_invitations(application_id);

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name VARCHAR(50) NOT NULL,
    operation VARCHAR(50) NOT NULL,
    prompt_version VARCHAR(50) NOT NULL,
    model VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL,
    session_id UUID,
    application_id UUID,
    latency_ms INTEGER,
    input_tokens INTEGER,
    output_tokens INTEGER,
    metrics JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_runs_session_id ON agent_runs(session_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_created_at ON agent_runs(created_at);
CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_name ON agent_runs(agent_name);