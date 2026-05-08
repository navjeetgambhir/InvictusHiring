"""
Agent quality aggregation API.

GET /api/telemetry/quality  — returns quality metrics aggregated from agent_runs,
                              jd_drafts, jd_requests, and candidate_applications.

All queries are read-only and use raw SQL for performance.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import get_current_user, CurrentUser

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])


@router.get("/quality")
async def get_quality_metrics(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    _user: CurrentUser = Depends(get_current_user),
):
    """
    Aggregate quality metrics across all agents for the past `days` days.

    Returns:
      routing      — intent distribution + confidence trend (supervisor)
      drafting     — avg revisions per session, off-topic block rate (jd_drafter)
      screening    — score distribution, recommendation breakdown (cv_screener)
      analytics    — SQL pass rate, avg rows returned (analytics agent)
      ml           — avg candidate count, prediction type mix (ml_predictor)
      errors       — error rate per agent
      latency      — avg latency per agent
    """

    # ── Routing quality ──────────────────────────────────────────────────────
    routing_rows = await db.execute(text("""
        SELECT
            metrics->>'intent'          AS intent,
            COUNT(*)                    AS count,
            ROUND(AVG((metrics->>'confidence')::float)::numeric, 3) AS avg_confidence,
            SUM(CASE WHEN (metrics->>'confidence')::float < 0.7 THEN 1 ELSE 0 END) AS low_confidence_count
        FROM agent_runs
        WHERE agent_name = 'supervisor'
          AND created_at >= NOW() - (:days || ' days')::interval
          AND status != 'error'
          AND metrics->>'intent' IS NOT NULL
        GROUP BY metrics->>'intent'
        ORDER BY count DESC
    """), {"days": days})
    routing = [dict(r._mapping) for r in routing_rows]

    # ── Drafting quality: revisions per session ──────────────────────────────
    drafting_rows = await db.execute(text("""
        SELECT
            COUNT(DISTINCT session_id)                     AS sessions_with_revisions,
            ROUND(AVG(max_version)::numeric, 2)            AS avg_versions_to_approve,
            MAX(max_version)                               AS max_versions,
            SUM(off_topic_blocks)                          AS total_off_topic_blocks
        FROM (
            SELECT
                d.session_id,
                MAX(dr.version)  AS max_version,
                COUNT(ar.id)     AS off_topic_blocks
            FROM agent_runs ar
            JOIN jd_requests d ON d.session_id = ar.session_id
            JOIN jd_drafts dr  ON dr.request_id = d.id
            WHERE ar.agent_name = 'jd_drafter'
              AND ar.created_at >= NOW() - (:days || ' days')::interval
            GROUP BY d.session_id
        ) sub
    """), {"days": days})
    drafting_raw = drafting_rows.one_or_none()
    drafting = dict(drafting_raw._mapping) if drafting_raw else {}

    # Off-topic block rate separately (simpler query)
    block_rows = await db.execute(text("""
        SELECT
            COUNT(*) FILTER (WHERE (metrics->>'blocked')::boolean = true)  AS blocked,
            COUNT(*) FILTER (WHERE (metrics->>'on_topic')::boolean = true)  AS on_topic,
            COUNT(*)                                                         AS total
        FROM agent_runs
        WHERE agent_name = 'jd_drafter'
          AND operation = 'chat'
          AND created_at >= NOW() - (:days || ' days')::interval
    """), {"days": days})
    block_raw = block_rows.one_or_none()
    drafting["chat_block_stats"] = dict(block_raw._mapping) if block_raw else {}

    # ── Screening quality ────────────────────────────────────────────────────
    screening_rows = await db.execute(text("""
        SELECT
            metrics->>'recommendation'                                      AS recommendation,
            COUNT(*)                                                        AS count,
            ROUND(AVG((metrics->>'score')::float)::numeric, 1)             AS avg_score,
            ROUND(MIN((metrics->>'score')::float)::numeric, 1)             AS min_score,
            ROUND(MAX((metrics->>'score')::float)::numeric, 1)             AS max_score
        FROM agent_runs
        WHERE agent_name = 'cv_screener'
          AND created_at >= NOW() - (:days || ' days')::interval
          AND status = 'success'
          AND metrics->>'recommendation' IS NOT NULL
        GROUP BY metrics->>'recommendation'
        ORDER BY avg_score DESC NULLS LAST
    """), {"days": days})
    screening = [dict(r._mapping) for r in screening_rows]

    # Score bucket distribution
    score_buckets = await db.execute(text("""
        SELECT
            CASE
                WHEN (metrics->>'score')::int >= 80 THEN '80-100'
                WHEN (metrics->>'score')::int >= 60 THEN '60-79'
                WHEN (metrics->>'score')::int >= 40 THEN '40-59'
                ELSE '0-39'
            END AS bucket,
            COUNT(*) AS count
        FROM agent_runs
        WHERE agent_name = 'cv_screener'
          AND created_at >= NOW() - (:days || ' days')::interval
          AND status = 'success'
          AND metrics->>'score' IS NOT NULL
        GROUP BY bucket
        ORDER BY bucket DESC
    """), {"days": days})

    # ── Analytics quality ────────────────────────────────────────────────────
    analytics_rows = await db.execute(text("""
        SELECT
            COUNT(*)                                                                      AS total_queries,
            SUM(CASE WHEN (metrics->>'sql_passed_validation')::boolean THEN 1 ELSE 0 END) AS passed,
            SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END)                           AS blocked,
            SUM(CASE WHEN status = 'sql_error' THEN 1 ELSE 0 END)                         AS sql_errors,
            ROUND(AVG((metrics->>'rows_returned')::float)::numeric, 1)                    AS avg_rows_returned
        FROM agent_runs
        WHERE agent_name = 'analytics'
          AND created_at >= NOW() - (:days || ' days')::interval
    """), {"days": days})
    analytics_raw = analytics_rows.one_or_none()
    analytics = dict(analytics_raw._mapping) if analytics_raw else {}

    # ── ML quality ───────────────────────────────────────────────────────────
    ml_rows = await db.execute(text("""
        SELECT
            metrics->>'prediction_type'                                    AS prediction_type,
            COUNT(*)                                                       AS count,
            ROUND(AVG((metrics->>'candidate_count')::float)::numeric, 1)  AS avg_candidates,
            SUM((metrics->>'shap_explanations')::int)                     AS total_shap_explanations
        FROM agent_runs
        WHERE agent_name = 'ml_predictor'
          AND created_at >= NOW() - (:days || ' days')::interval
          AND status = 'success'
          AND metrics->>'prediction_type' IS NOT NULL
        GROUP BY metrics->>'prediction_type'
    """), {"days": days})
    ml = [dict(r._mapping) for r in ml_rows]

    # ── Error rates per agent ────────────────────────────────────────────────
    error_rows = await db.execute(text("""
        SELECT
            agent_name,
            COUNT(*)                                                          AS total,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END)                AS errors,
            ROUND(
                100.0 * SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END)
                / NULLIF(COUNT(*), 0), 1
            )                                                                 AS error_rate_pct
        FROM agent_runs
        WHERE created_at >= NOW() - (:days || ' days')::interval
        GROUP BY agent_name
        ORDER BY error_rate_pct DESC NULLS LAST
    """), {"days": days})
    errors = [dict(r._mapping) for r in error_rows]

    # ── Latency per agent ────────────────────────────────────────────────────
    latency_rows = await db.execute(text("""
        SELECT
            agent_name,
            operation,
            ROUND(AVG(latency_ms)::numeric, 0)    AS avg_ms,
            ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms)::numeric, 0) AS p95_ms,
            COUNT(*)                               AS sample_count
        FROM agent_runs
        WHERE created_at >= NOW() - (:days || ' days')::interval
          AND status = 'success'
          AND latency_ms IS NOT NULL
        GROUP BY agent_name, operation
        ORDER BY avg_ms DESC
    """), {"days": days})
    latency = [dict(r._mapping) for r in latency_rows]

    # ── Daily volume trend (last 14 days regardless of `days` param) ─────────
    trend_rows = await db.execute(text("""
        SELECT
            DATE_TRUNC('day', created_at)::date  AS day,
            agent_name,
            COUNT(*)                             AS runs,
            SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS errors
        FROM agent_runs
        WHERE created_at >= NOW() - INTERVAL '14 days'
        GROUP BY day, agent_name
        ORDER BY day DESC, agent_name
    """))
    trend = [dict(r._mapping) for r in trend_rows]

    return {
        "period_days": days,
        "routing": routing,
        "drafting": drafting,
        "screening": {
            "by_recommendation": screening,
            "score_buckets": [dict(r._mapping) for r in score_buckets],
        },
        "analytics": analytics,
        "ml": ml,
        "errors": errors,
        "latency": latency,
        "daily_trend": trend,
    }