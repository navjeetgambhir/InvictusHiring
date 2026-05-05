import { useState, useCallback, useEffect, useRef } from 'react'
import { submitFreetextDraft, sendChat, approveDraft, rejectDraft, publishJD, getSession } from '@/api/jd'
import { routeMessage, streamAnalyticsQuery } from '@/api/analytics'

export type MessageRole = 'user' | 'assistant' | 'system'

export interface Message {
  id: string
  role: MessageRole
  content: string
  streaming?: boolean
  sql?: string        // set on analytics assistant messages
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

const WELCOME: Message = {
  id: 'welcome',
  role: 'assistant',
  content: `Hi! I'm your hiring assistant. I can help with two things:\n\nDraft a job description: describe the role in plain English and I'll write a full JD for you.\nExample: "We need a Senior Python Engineer in London, £70k-£90k, must know FastAPI and PostgreSQL."\n\nAnswer hiring data questions: ask about applications, candidates, job statuses, or any other data.\nExample: "How many candidates applied in the last 7 days?" or "Which JDs are pending approval?"`,
  streaming: false,
}

export function useJDSession(submittedBy: string, role: 'hr' | 'hm') {
  const [messages, setMessages] = useState<Message[]>([WELCOME])
  const _historyRef = useRef<{ role: string; content: string }[]>([])
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [status, setStatus] = useState<SessionStatus>('idle')
  const [error, setError] = useState<string | null>(null)
  const [postings, setPostings] = useState<PlatformPosting[]>([])

  // Reset when user identity changes
  useEffect(() => {
    setMessages([WELCOME])
    setSessionId(null)
    setStatus('idle')
    setError(null)
    setPostings([])
  }, [submittedBy, role])

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

    // Context-aware routing — passes pipeline state + history to supervisor
    const decision = await routeMessage(
      text,
      status,
      !!sessionId,
      _historyRef.current,
    )
    const intent = decision.intent

    if (intent === 'analytics') {
      const assistantId = pushMessage('assistant', '', true)
      try {
        await streamAnalyticsQuery(text, event => {
          if (event.type === 'sql')        attachSql(assistantId, event.sql)
          else if (event.type === 'chunk') appendToMessage(assistantId, event.text)
          else if (event.type === 'error') appendToMessage(assistantId, `\n\n_Error: ${event.message}_`)
        })
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
      pushMessage('assistant', decision.suggested_action || "I can **draft job descriptions** or **answer questions about your hiring data** — try one of those!")
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

  const publish = useCallback(async () => {
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
      })
    } catch (e) {
      setError((e as Error).message)
      setStatus('approved') // fall back so user can retry
    }
  }, [sessionId])

  const reset = useCallback(() => {
    setMessages([WELCOME])
    setSessionId(null)
    setStatus('idle')
    setError(null)
    setPostings([])
  }, [])

  const loadSession = useCallback(async (sid: string) => {
    try {
      const state = await getSession(sid)
      const restored: Message[] = state.chat_history.map(m => ({
        id: crypto.randomUUID(),
        role: m.role as MessageRole,
        content: m.content,
        streaming: false,
      }))
      setMessages(restored.length ? restored : [WELCOME])
      setSessionId(sid)
      setStatus(state.status as SessionStatus)
      setError(null)
      setPostings([])
    } catch {
      setError('Failed to load session')
    }
  }, [])

  return { messages, sessionId, status, error, postings, sendMessage, approve, reject, publish, reset, loadSession }
}