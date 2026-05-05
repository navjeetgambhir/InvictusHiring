-- Migration 004: agent_runs table for eval metrics and traceability

CREATE TABLE IF NOT EXISTS agent_runs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_name      VARCHAR(50)  NOT NULL,
    operation       VARCHAR(50)  NOT NULL,
    prompt_version  VARCHAR(50)  NOT NULL,
    model           VARCHAR(100) NOT NULL,
    status          VARCHAR(20)  NOT NULL,   -- success | error

    session_id      UUID,
    application_id  UUID,

    latency_ms      INTEGER,
    input_tokens    INTEGER,
    output_tokens   INTEGER,

    metrics         JSONB,
    error_message   TEXT,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_agent_runs_session_id  ON agent_runs (session_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_created_at  ON agent_runs (created_at);
CREATE INDEX IF NOT EXISTS ix_agent_runs_agent_name  ON agent_runs (agent_name);