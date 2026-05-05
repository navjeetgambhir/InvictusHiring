export interface JobRequirements {
  submitted_by: string
  role: 'hr' | 'hm'
  title: string
  department: string
  location: string
  salary_band: string
  required_skills: string[]
  nice_to_have_skills: string[]
  company_description: string
  additional_context?: string
}

export interface SessionState {
  session_id: string
  status: 'drafting' | 'pending_approval' | 'approved' | 'rejected' | 'published'
  title: string
  submitted_by: string
  latest_draft: string | null
  draft_version: number
  chat_history: { role: 'user' | 'assistant'; content: string }[]
}

import { getToken } from './auth'

const BASE = '/api/jd'

function authHeaders(): Record<string, string> {
  const token = getToken()
  return token
    ? { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` }
    : { 'Content-Type': 'application/json' }
}

/** POST free-text requirements → streams JD text chunks; resolves with the session_id */
export async function submitFreetextDraft(
  submitted_by: string,
  role: 'hr' | 'hm',
  text: string,
  onChunk: (chunk: string) => void
): Promise<string> {
  const res = await fetch(`${BASE}/draft-freetext`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ submitted_by, role, text }),
  })
  if (!res.ok) throw new Error(`Draft failed: ${res.statusText}`)

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let sessionId = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value, { stream: true })
    const sessionMatch = text.match(/__SESSION_ID__([a-f0-9-]{36})/)
    if (sessionMatch) {
      sessionId = sessionMatch[1]
      const before = text.replace(/__SESSION_ID__[a-f0-9-]{36}/, '')
      if (before) onChunk(before)
    } else {
      onChunk(text)
    }
  }
  return sessionId
}

/** POST requirements → streams JD text chunks; resolves with the session_id */
export async function submitDraft(
  requirements: JobRequirements,
  onChunk: (chunk: string) => void
): Promise<string> {
  const res = await fetch(`${BASE}/draft`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify(requirements),
  })
  if (!res.ok) throw new Error(`Draft failed: ${res.statusText}`)

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let sessionId = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    const text = decoder.decode(value, { stream: true })

    const sessionMatch = text.match(/__SESSION_ID__([a-f0-9-]{36})/)
    if (sessionMatch) {
      sessionId = sessionMatch[1]
      const before = text.replace(/__SESSION_ID__[a-f0-9-]{36}/, '')
      if (before) onChunk(before)
    } else {
      onChunk(text)
    }
  }

  return sessionId
}

/** POST a chat message → streams reply chunks */
export async function sendChat(
  sessionId: string,
  message: string,
  onChunk: (chunk: string) => void
): Promise<void> {
  const res = await fetch(`${BASE}/chat`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId, message }),
  })
  if (!res.ok) throw new Error(`Chat failed: ${res.statusText}`)

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
}

/** Approve the current draft */
export async function approveDraft(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/approve`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId, approved: true }),
  })
  if (!res.ok) throw new Error(`Approval failed: ${res.statusText}`)
}

/** Reject with feedback → streams revised draft chunks */
export async function rejectDraft(
  sessionId: string,
  feedback: string,
  onChunk: (chunk: string) => void
): Promise<void> {
  const res = await fetch(`${BASE}/approve`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId, approved: false, feedback }),
  })
  if (!res.ok) throw new Error(`Rejection failed: ${res.statusText}`)

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    onChunk(decoder.decode(value, { stream: true }))
  }
}

export interface SessionSummary {
  session_id: string
  title: string
  status: string
  department: string
  created_at: string
  last_message_preview: string
  last_message_role: 'user' | 'assistant' | null
}

/** List all sessions for the current user */
export async function fetchSessions(): Promise<SessionSummary[]> {
  const res = await fetch(`${BASE}/sessions`, { headers: authHeaders() })
  if (!res.ok) throw new Error('Failed to fetch sessions')
  return res.json()
}

/** Fetch full session state */
export async function getSession(sessionId: string): Promise<SessionState> {
  const res = await fetch(`${BASE}/session/${sessionId}`, { headers: authHeaders() })
  if (!res.ok) throw new Error(`Session fetch failed: ${res.statusText}`)
  return res.json()
}

// ── Job Poster (Agent 2) ───────────────────────────────────────────────────────

export type PostingEvent =
  | { type: 'start';  platform: string }
  | { type: 'chunk';  platform: string; text: string }
  | { type: 'posted'; platform: string; platform_id: string; url: string; content: string }
  | { type: 'error';  platform: string; message: string }
  | { type: 'done' }

/** POST to /api/jobs/post/:sessionId — streams NDJSON posting events */
export async function publishJD(
  sessionId: string,
  onEvent: (event: PostingEvent) => void
): Promise<void> {
  const res = await fetch(`/api/jobs/post/${sessionId}`, {
    method: 'POST',
    headers: authHeaders(),
  })
  if (!res.ok) throw new Error(`Publish failed: ${res.statusText}`)

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
      const trimmed = line.trim()
      if (!trimmed) continue
      try {
        onEvent(JSON.parse(trimmed) as PostingEvent)
      } catch {
        // ignore malformed lines
      }
    }
  }
}