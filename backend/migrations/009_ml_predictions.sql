CREATE TABLE IF NOT EXISTS ml_predictions (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id   UUID REFERENCES candidate_applications(id) ON DELETE CASCADE,
    session_id       UUID,                          -- denormalised for easy querying after jd_requests are deleted
    candidate_name   VARCHAR(255),
    job_title        VARCHAR(255),
    prediction_type  VARCHAR(10) NOT NULL,          -- fit | join | both
    fit_score        SMALLINT,                      -- 0-100, NULL if prediction_type = join
    join_score       SMALLINT,                      -- 0-100, NULL if prediction_type = fit
    fit_explanation  JSONB,                         -- top-5 SHAP factors for fit model
    join_explanation JSONB,                         -- top-5 SHAP factors for join model
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ml_predictions_application ON ml_predictions(application_id);
CREATE INDEX IF NOT EXISTS idx_ml_predictions_session     ON ml_predictions(session_id);