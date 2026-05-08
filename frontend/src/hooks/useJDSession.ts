import { useState, useCallback, useEffect, useRef } from 'react'
import { submitFreetextDraft, sendChat, approveDraft, rejectDraft, publishJD, revertToPendingApproval, getSession, type PublishOptions } from '@/api/jd'
import { routeMessage, streamAnalyticsQuery, streamMlQuery } from '@/api/analytics'

// ── localStorage message cache ────────────────────────────────────────────────
const _MSG_TTL_MS = 7 * 24 * 60 * 60 * 1000 // 7 days

function _saveMessages(sid: string, msgs: Message[]) {
  try {
    localStorage.setItem(`chat_${sid}`, JSON.stringify({ ts: Date.now(), messages: msgs }))
  } catch {}
}

function _loadMessages(sid: string): Message[] | null {
  try {
    const raw = localStorage.getItem(`chat_${sid}`)
    if (!raw) return null
    const parsed = JSON.parse(raw) as { ts: number; messages: Message[] }
    if (Date.now() - parsed.ts > _MSG_TTL_MS) { localStorage.removeItem(`chat_${sid}`); return null }
    return parsed.messages
  } catch { return null }
}

function _clearMessages(sid: string) {
  try { localStorage.removeItem(`chat_${sid}`) } catch {}
}

export type MessageRole = 'user' | 'assistant' | 'system'

export interface MlFactor {
  feature: string
  label: string
  contribution: number
  direction: 'positive' | 'negative'
  raw_value: number
}

export interface MlResult {
  application_id: string
  candidate_name: string
  job_title: string
  session_id: string
  screening_score: number | null
  screening_recommendation: string | null
  shortlisted: boolean
  fit_probability?: number | null
  join_probability?: number | null
  fit_explanation?: MlFactor[]
  join_explanation?: MlFactor[]
}

export interface Message {
  id: string
  role: MessageRole
  content: string
  streaming?: boolean
  sql?: string        // set on analytics assistant messages
  mlData?: MlResult[] // set on ml_predict assistant messages
}

export type SessionStatus =
  | 'idle'
  | 'drafting'
  | 'pending_approval'
  | 'approved'
  | 'publishing'
  | 'published'
  | 'error'

export interface PlatformPosting {
  platform: string
  platform_id: string
  url: string
  content: string
  status: 'pending' | 'posting' | 'posted' | 'error'
}

const _ENTRY_WELCOMES: Record<string, string> = {
  'jd-draft':   `Let's draft a job description. Describe the role in plain English and I'll write a full, structured JD for you.\n\nExample: *"Senior Python Engineer in London, £70k–£90k, must know FastAPI and PostgreSQL"*`,
  'analytics':  `Ask me anything about your hiring data — applications, candidates, pipeline status, or trends.\n\nExample: *"How many candidates applied this week?"* or *"Which roles have the most strong-match candidates?"*`,
  'cv-screen':  `I can help you review screened candidates. Ask about screening scores, recommendations, or specific applicants.\n\nExample: *"Show me all strong-match candidates for this role"* or *"Who has the highest screening score?"*`,
  'interviews': `Let's look at interview scheduling. Ask about shortlisted candidates or interview status across your open roles.\n\nExample: *"Which shortlisted candidates haven't been invited yet?"*`,
  'publish':    `Ready to publish? Once a JD is approved I can post it to LinkedIn, Indeed, and Google Jobs.\n\nOpen a session from the sidebar or start by drafting a new JD.`,
  'sessions':   `Pick up where you left off — select a session from the sidebar on the left, or start a new JD.\n\nYou can also ask me questions about your hiring data at any time.`,
  'ml-predict': `Ask for ML-powered candidate predictions — fit scores, offer-acceptance probabilities, and the key factors driving each score.\n\nExample: *"Which shortlisted candidates are most likely to accept an offer?"*`,
}

const _DEFAULT_WELCOME = `Hi! I'm your AI hiring assistant. I can help you:\n\n- **Draft job descriptions** — describe a role and I'll write it\n- **Answer hiring data questions** — applications, candidates, pipeline status\n- **Predict candidate fit** — ML scores with explainability\n\nWhat would you like to do?`

function _makeWelcome(content: string): Message {
  return { id: 'welcome', role: 'assistant', content, streaming: false }
}

const WELCOME: Message = _makeWelcome(_DEFAULT_WELCOME)

export function useJDSession(submittedBy: string, role: 'hr' | 'hm') {
  const [messages, setMessages] = useState<Message[]>([WELCOME])
  const _historyRef = useRef<{ role: string; content: string }[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [sessionTitle, setSessionTitle] = useState<string | null>(null)
  const [sessionDepartment, setSessionDepartment] = useState<string | null>(null)
  const [status, setStatus] = useState<SessionStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [postings, setPostings] = useState<PlatformPosting[]>([])

  // Reset when user identity changes
  useEffect(() => {
    setMessages([WELCOME])
    setSessionId(null)
    setSessionTitle(null)
    setSessionDepartment(null)
    setStatus('idle')
    setError(null)
    setPostings([])
  }, [submittedBy, role])

  // Persist messages to localStorage whenever they change and no message is streaming
  useEffect(() => {
    if (sessionId && messages.length > 1 && !messages.some(m => m.streaming)) {
      _saveMessages(sessionId, messages)
    }
  }, [messages, sessionId])

  const pushMessage = (msgRole: MessageRole, content: string, streaming = false): string => {
    const id = crypto.randomUUID()
    setMessages(prev => [...prev, { id, msgRole, role: msgRole, content, streaming }])
    return id
  }

  const appendToMessage = (id: string, chunk: string) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, content: m.content + chunk } : m))
  }

  const finaliseMessage = (id: string) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, streaming: false } : m))
  }

  const attachSql = (id: string, sql: string) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, sql } : m))
  }

  const attachMlData = (id: string, data: MlResult[]) => {
    setMessages(prev => prev.map(m => m.id === id ? { ...m, mlData: data } : m))
  }

  const sendMessage = useCallback(async (text: string) => {
    if (!text.trim()) return
    setError(null)
    pushMessage('user', text)

    // Build history snapshot for routing context
    setMessages(prev => {
      _historyRef.current = prev
        .filter(m => m.role !== 'system')
        .slice(-6)
        .map(m => ({ role: m.role, content: m.content }))
      return prev
    })

    // Context-aware routing — passes full session context to supervisor
    const decision = await routeMessage(
      text,
      status,
      !!sessionId,
      _historyRef.current,
      sessionId,
      sessionTitle,
      sessionDepartment,
    )
    const intent = decision.intent

    if (intent === 'analytics') {
      const assistantId = pushMessage('assistant', '', true)
      try {
        await streamAnalyticsQuery(text, event => {
          if (event.type === 'sql')        attachSql(assistantId, event.sql)
          else if (event.type === 'chunk') appendToMessage(assistantId, event.text)
          else if (event.type === 'error') appendToMessage(assistantId, `\n\n_Error: ${event.message}_`)
        }, sessionId)
        finaliseMessage(assistantId)
      } catch (e) {
        appendToMessage(assistantId, `\n\n_Error: ${(e as Error).message}_`)
        finaliseMessage(assistantId)
      }
      return
    }

    if (intent === 'ml_predict') {
      const assistantId = pushMessage('assistant', '', true)
      try {
        await streamMlQuery(text, event => {
          if (event.type === 'chunk')   appendToMessage(assistantId, event.text)
          else if (event.type === 'results') attachMlData(assistantId, event.data as unknown as MlResult[])
          else if (event.type === 'error')   appendToMessage(assistantId, `\n\n_Error: ${event.message}_`)
        }, sessionId)
        finaliseMessage(assistantId)
      } catch (e) {
        appendToMessage(assistantId, `\n\n_Error: ${(e as Error).message}_`)
        finaliseMessage(assistantId)
      }
      return
    }

    if (intent === 'approve') {
      if (sessionId) {
        try {
          await approveDraft(sessionId)
          setStatus('approved')
          pushMessage('system', 'JD approved ✓ — ready to publish to job boards.')
        } catch (e) { setError((e as Error).message) }
      }
      return
    }

    if (intent === 'other') {
      const isGreeting = /^(hi|hello|hey|howdy|hiya|good\s+(morning|afternoon|evening)|how are|how's|what'?s up|sup|yo)\b/i.test(text.trim())
      const reply = isGreeting
        ? `Hi! I'm your hiring assistant — great to hear from you.\n\nI can help you with two things:\n- **Draft a job description** — just describe the role in plain English, e.g. *"We need a Senior Python Engineer in London, £70k–£90k"*\n- **Answer hiring data questions** — e.g. *"How many candidates applied this week?"*\n\nWhat would you like to do?`
        : "I can **draft job descriptions** or **answer questions about your hiring data**. Try describing a role you want to hire for, or ask me a question about your candidates."
      pushMessage('assistant', reply)
      return
    }

    if (intent === 'jd_draft') {
      setStatus('drafting')
      const assistantId = pushMessage('assistant', '', true)
      try {
        const sid = await submitFreetextDraft(submittedBy, role, text, chunk => appendToMessage(assistantId, chunk))
        finaliseMessage(assistantId)
        setSessionId(sid)
        setStatus('pending_approval')
        // Fetch session to populate title/department context
        getSession(sid).then(s => { setSessionTitle(s.title); setSessionDepartment(s.department ?? null) }).catch(() => {})
        pushMessage('system', 'Draft complete. Review above and **Approve** or **Reject with feedback**.')
      } catch (e) {
        setError((e as Error).message)
        setStatus('error')
        finaliseMessage(assistantId)
      }
      return
    }

    // jd_chat | jd_revise | publish — need an active session
    if (sessionId) {
      const assistantId = pushMessage('assistant', '', true)
      try {
        await sendChat(sessionId, text, chunk => appendToMessage(assistantId, chunk))
        finaliseMessage(assistantId)
      } catch (e) {
        setError((e as Error).message)
        finaliseMessage(assistantId)
      }
    }
  }, [status, sessionId, submittedBy, role])

  const approve = useCallback(async () => {
    if (!sessionId) return
    try {
      await approveDraft(sessionId)
      setStatus('approved')
      pushMessage('system', 'JD approved ✓  — ready to publish to job boards.')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [sessionId])

  const reject = useCallback(async (feedback: string) => {
    if (!sessionId) return
    setError(null)
    pushMessage('user', `Feedback: ${feedback}`)
    const assistantId = pushMessage('assistant', '', true)
    setStatus('drafting')
    try {
      await rejectDraft(sessionId, feedback, chunk => appendToMessage(assistantId, chunk))
      finaliseMessage(assistantId)
      setStatus('pending_approval')
      pushMessage('system', 'Revised draft ready. Review and approve or provide more feedback.')
    } catch (e) {
      setError((e as Error).message)
      setStatus('error')
      finaliseMessage(assistantId)
    }
  }, [sessionId])

  const publish = useCallback(async (options?: PublishOptions) => {
    if (!sessionId) return
    setError(null)
    setStatus('publishing')
    setPostings([])

    try {
      await publishJD(sessionId, event => {
        if (event.type === 'start') {
          setPostings(prev => [
            ...prev,
            { platform: event.platform, platform_id: '', url: '', content: '', status: 'posting' },
          ])
        } else if (event.type === 'posted') {
          setPostings(prev => prev.map(p =>
            p.platform === event.platform
              ? { platform: event.platform, platform_id: event.platform_id, url: event.url, content: event.content, status: 'posted' }
              : p
          ))
        } else if (event.type === 'error') {
          setPostings(prev => prev.map(p =>
            p.platform === event.platform ? { ...p, status: 'error' } : p
          ))
        } else if (event.type === 'done') {
          setStatus('published')
          pushMessage('system', 'JD published to all job boards successfully.')
        }
      }, options)
    } catch (e) {
      setError((e as Error).message)
      setStatus('approved') // fall back so user can retry
    }
  }, [sessionId])

  const revertForRevision = useCallback(async () => {
    if (!sessionId) return
    try {
      await revertToPendingApproval(sessionId)
      setStatus('pending_approval')
      setPostings([])
      pushMessage('system', 'JD reverted to draft — make your changes and approve to republish.')
    } catch (e) {
      setError((e as Error).message)
    }
  }, [sessionId])

  const setEntryPoint = useCallback((destination: string) => {
    const content = _ENTRY_WELCOMES[destination] ?? _DEFAULT_WELCOME
    setSessionId(prev => { if (prev) _clearMessages(prev); return null })
    setMessages([_makeWelcome(content)])
    setSessionTitle(null)
    setSessionDepartment(null)
    setStatus('idle')
    setError(null)
    setPostings([])
  }, [])

  const reset = useCallback(() => {
    setSessionId(prev => { if (prev) _clearMessages(prev); return null })
    setMessages([WELCOME])
    setSessionTitle(null)
    setSessionDepartment(null)
    setStatus('idle')
    setError(null)
    setPostings([])
  }, [])

  const loadSession = useCallback(async (sid: string) => {
    try {
      // Restore from localStorage immediately (includes analytics/ML messages)
      const cached = _loadMessages(sid)
      if (cached?.length) {
        setMessages(cached)
      }

      const state = await getSession(sid)
      setSessionId(sid)
      setSessionTitle(state.title ?? null)
      setSessionDepartment(state.department ?? null)
      setStatus(state.status as SessionStatus)
      setError(null)
      setPostings([])

      // Only fall back to backend history if localStorage was empty
      if (!cached?.length) {
        const restored: Message[] = state.chat_history.map(m => ({
          id: crypto.randomUUID(),
          role: m.role as MessageRole,
          content: m.content,
          streaming: false,
        }))
        setMessages(restored.length ? restored : [WELCOME])
      }
    } catch {
      setError('Failed to load session')
    }
  }, [])

  return { messages, sessionId, sessionTitle, sessionDepartment, status, error, postings, sendMessage, approve, reject, publish, revertForRevision, reset, loadSession, setEntryPoint }
}