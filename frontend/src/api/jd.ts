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
  department: string
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

const SENTINEL = '__SESSION_ID__'
const SENTINEL_LEN = SENTINEL.length + 36  // "__SESSION_ID__" + UUID

/**
 * Read a streaming draft response, extract the __SESSION_ID__ sentinel that
 * arrives at the very end, and forward only visible content to onChunk.
 * Buffers the tail of the stream so a sentinel split across two raw TCP chunks
 * never appears in the displayed message.
 */
async function readDraftStream(
  body: ReadableStream<Uint8Array>,
  onChunk: (chunk: string) => void,
): Promise<string> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let pending = ''
  let sessionId = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    pending += decoder.decode(value, { stream: true })

    const sentinelIdx = pending.indexOf(SENTINEL)
    if (sentinelIdx !== -1) {
      // Sentinel arrived — flush everything before it, extract ID
      const before = pending.slice(0, sentinelIdx)
      if (before) onChunk(before)
      const match = pending.slice(sentinelIdx).match(/__SESSION_ID__([a-f0-9-]{36})/)
      if (match) sessionId = match[1]
      pending = ''
    } else {
      // Safe to flush everything except the last SENTINEL_LEN chars
      // which might be a partial sentinel split across chunks
      if (pending.length > SENTINEL_LEN) {
        onChunk(pending.slice(0, -SENTINEL_LEN))
        pending = pending.slice(-SENTINEL_LEN)
      }
    }
  }
  // Flush any remainder (should be empty after sentinel extraction)
  if (pending && !pending.includes(SENTINEL)) onChunk(pending)
  return sessionId
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
  return readDraftStream(res.body!, onChunk)
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
  return readDraftStream(res.body!, onChunk)
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

/** Revert a published/approved JD back to pending_approval for re-editing */
export async function revertToPendingApproval(sessionId: string): Promise<void> {
  const res = await fetch(`${BASE}/revert`, {
    method: 'POST',
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId }),
  })
  if (!res.ok) throw new Error(`Revert failed: ${res.statusText}`)
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

export interface PublishOptions {
  expires_at?: string | null    // ISO8601 datetime string, or null for no expiry
  max_applications?: number | null
}

/** POST to /api/jobs/post/:sessionId — streams NDJSON posting events */
export async function publishJD(
  sessionId: string,
  onEvent: (event: PostingEvent) => void,
  options?: PublishOptions,
): Promise<void> {
  const res = await fetch(`/api/jobs/post/${sessionId}`, {
    method: 'POST',
    headers: { ...authHeaders(), 'Content-Type': 'application/json' },
    body: JSON.stringify(options ?? {}),
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