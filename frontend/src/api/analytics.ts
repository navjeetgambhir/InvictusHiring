import { getToken } from './auth'

const BASE = '/api/analytics'

function authHeaders(): Record<string, string> {
  const token = getToken()
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

export type AnalyticsEvent =
  | { type: 'sql';   sql: string }
  | { type: 'chunk'; text: string }
  | { type: 'error'; message: string }
  | { type: 'done' }

export type Intent = 'jd_draft' | 'jd_chat' | 'jd_revise' | 'approve' | 'publish' | 'analytics' | 'ml_predict' | 'other'

export interface RoutingDecision {
  intent: Intent
  confidence: number
  reasoning: string
  suggested_action: string
  secondary_intent: Intent | null
}

export async function routeMessage(
  message: string,
  pipeline_state: string,
  has_draft: boolean,
  history: { role: string; content: string }[],
  sessionId?: string | null,
  jobTitle?: string | null,
  jobDepartment?: string | null,
): Promise<RoutingDecision> {
  const res = await fetch(`${BASE}/route`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({
      message, pipeline_state, has_draft, history,
      session_id: sessionId ?? null,
      job_title: jobTitle ?? null,
      job_department: jobDepartment ?? null,
    }),
  })
  if (!res.ok) return { intent: 'other', confidence: 0, reasoning: '', suggested_action: '', secondary_intent: null }
  return res.json()
}

export type MlEvent =
  | { type: 'results'; data: Record<string, unknown>[] }
  | { type: 'chunk';   text: string }
  | { type: 'error';   message: string }
  | { type: 'done' }

export async function streamMlQuery(
  question: string,
  onEvent: (event: MlEvent) => void,
  sessionId?: string | null,
): Promise<void> {
  const token = getToken()
  const res = await fetch('/api/ml/predict', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
  })
  if (!res.ok) { onEvent({ type: 'error', message: `Request failed: ${res.statusText}` }); return }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      try { onEvent(JSON.parse(line) as MlEvent) } catch { /* ignore */ }
    }
  }
}

// kept for backward compat
export async function classifyIntent(message: string): Promise<'jd_draft' | 'analytics' | 'other'> {
  const res = await fetch(`${BASE}/classify`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ message }),
  })
  if (!res.ok) return 'other'
  const data = await res.json()
  return data.intent ?? 'other'
}

export async function streamAnalyticsQuery(
  question: string,
  onEvent: (event: AnalyticsEvent) => void,
  sessionId?: string | null,
): Promise<void> {
  const res = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
  })
  if (!res.ok) {
    onEvent({ type: 'error', message: `Request failed: ${res.statusText}` })
    return
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.trim()) continue
      try {
        onEvent(JSON.parse(line) as AnalyticsEvent)
      } catch { /* ignore malformed line */ }
    }
  }
}