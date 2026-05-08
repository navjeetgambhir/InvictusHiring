import { getToken } from './auth'

function authHeaders(): Record<string, string> {
  const token = getToken()
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

export interface RoutingMetric {
  intent: string
  count: number
  avg_confidence: number
  low_confidence_count: number
}

export interface RecommendationMetric {
  recommendation: string
  count: number
  avg_score: number
  min_score: number
  max_score: number
}

export interface ScoreBucket {
  bucket: string
  count: number
}

export interface AgentError {
  agent_name: string
  total: number
  errors: number
  error_rate_pct: number
}

export interface AgentLatency {
  agent_name: string
  operation: string
  avg_ms: number
  p95_ms: number
  sample_count: number
}

export interface QualityMetrics {
  period_days: number
  routing: RoutingMetric[]
  drafting: {
    sessions_with_revisions: number
    avg_versions_to_approve: number
    max_versions: number
    total_off_topic_blocks: number
    chat_block_stats: { blocked: number; on_topic: number; total: number }
  }
  screening: {
    by_recommendation: RecommendationMetric[]
    score_buckets: ScoreBucket[]
  }
  analytics: {
    total_queries: number
    passed: number
    blocked: number
    sql_errors: number
    avg_rows_returned: number
  }
  ml: { prediction_type: string; count: number; avg_candidates: number; total_shap_explanations: number }[]
  errors: AgentError[]
  latency: AgentLatency[]
  daily_trend: { day: string; agent_name: string; runs: number; errors: number }[]
}

export async function fetchQualityMetrics(days = 30): Promise<QualityMetrics | null> {
  try {
    const res = await fetch(`/api/telemetry/quality?days=${days}`, { headers: authHeaders() })
    if (!res.ok) return null
    return res.json()
  } catch {
    return null
  }
}