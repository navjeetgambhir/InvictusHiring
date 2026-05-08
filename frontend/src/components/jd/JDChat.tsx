import { useEffect, useRef, useState } from 'react'
import { Send, RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { Badge } from '@/components/ui/badge'
import { ChatMessageBubble } from './ChatMessage'
import { ApprovalBar } from './ApprovalBar'
import type { useJDSession, Message } from '@/hooks/useJDSession'
import type { SessionStatus } from '@/hooks/useJDSession'

type Session = ReturnType<typeof useJDSession>

interface Props {
  session: Session
  onReset: () => void
}

const STATUS_LABEL: Record<string, { label: string; variant: 'default' | 'secondary' | 'warning' | 'destructive' }> = {
  idle:             { label: 'Ready',            variant: 'secondary'   },
  drafting:         { label: 'Generating…',      variant: 'warning'     },
  pending_approval: { label: 'Awaiting Approval', variant: 'warning'    },
  approved:         { label: 'Approved',          variant: 'default'    },
  publishing:       { label: 'Publishing…',       variant: 'warning'    },
  published:        { label: 'Published',         variant: 'default'    },
  error:            { label: 'Error',             variant: 'destructive' },
}

const FOLLOW_UPS: Record<SessionStatus, string[]> = {
  idle: [
    'We need a Senior Python Engineer in London, £70k–£90k',
    'Draft a Product Manager JD for a fintech startup',
    'How many applications did we receive this week?',
  ],
  drafting: [],
  pending_approval: [
    'Make the tone more formal',
    'Add a remote-first clause',
    'Expand the responsibilities section',
    'Make the salary band more competitive',
    'Add diversity and inclusion statement',
  ],
  approved: [],
  publishing: [],
  published: [
    'How many candidates have applied?',
    'Show me the top-scoring applicants',
    'Which candidates are a strong match?',
  ],
  error: [
    'Try again',
    'Start a new JD',
  ],
}

function FollowUpChips({ status, onSend }: { status: SessionStatus; onSend: (msg: string) => void }) {
  const chips = FOLLOW_UPS[status] ?? []
  if (!chips.length) return null

  return (
    <div className="flex flex-wrap gap-2 px-6 pb-3">
      {chips.map(chip => (
        <button
          key={chip}
          onClick={() => onSend(chip)}
          className="text-xs text-violet-700 bg-violet-50 border border-violet-200 rounded-full px-3 py-1.5 hover:bg-violet-100 hover:border-violet-400 transition-colors text-left"
        >
          {chip}
        </button>
      ))}
    </div>
  )
}

export function JDChat({ session, onReset }: Props) {
  const { messages, status, error, sendMessage, approve, reject } = session
  const [input, setInput] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const isStreaming = status === 'drafting' || status === 'publishing'

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const send = (msg?: string) => {
    const text = (msg ?? input).trim()
    if (!text || isStreaming) return
    setInput('')
    sendMessage(text)
  }

  const statusInfo = STATUS_LABEL[status] ?? STATUS_LABEL.idle

  const inputDisabled = isStreaming || status === 'approved'
  const placeholder =
    status === 'idle'               ? 'Describe the role you\'re hiring for…'
    : isStreaming                   ? 'Please wait…'
    : status === 'pending_approval' ? 'Ask to refine the JD, e.g. "Make the tone more formal"'
    : status === 'published'        ? 'Ask about applicants, scores, or hiring data…'
    : 'JD has been finalised'

  // Show follow-ups only after the last assistant message has finished streaming
  const lastMessage = messages[messages.length - 1]
  const showFollowUps = !isStreaming && !inputDisabled && lastMessage?.role === 'assistant'

  return (
    <div className="flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-violet-200 bg-white shrink-0">
        <div className="flex items-center gap-3">
          <h2 className="font-semibold text-stone-900">JD Drafter</h2>
          <Badge variant={statusInfo.variant}>{statusInfo.label}</Badge>
        </div>
        <Button variant="ghost" size="sm" onClick={onReset}>
          <RotateCcw className="h-4 w-4" />
          New JD
        </Button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto chat-scroll px-6 py-6 flex flex-col gap-4">
        {messages.map((m: Message) => <ChatMessageBubble key={m.id} message={m} />)}
        {error && (
          <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Follow-up suggestions */}
      {showFollowUps && <FollowUpChips status={status} onSend={send} />}

      {/* Bottom action area */}
      <div className="px-6 pb-3 overflow-y-auto flex flex-col gap-3 max-h-72 shrink-0">
        <ApprovalBar status={status} onApprove={approve} onReject={reject} />
      </div>

      {/* Chat input — hidden once finalised */}
      {!inputDisabled && (
        <div className="px-6 pb-6 shrink-0">
          <div className="flex gap-3 items-end rounded-xl border border-violet-200 bg-white px-4 py-3 shadow-sm focus-within:ring-2 focus-within:ring-violet-500">
            <Textarea
              value={input}
              onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setInput(e.target.value)}
              onKeyDown={(e: React.KeyboardEvent<HTMLTextAreaElement>) => {
                if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send() }
              }}
              placeholder={placeholder}
              disabled={isStreaming}
              rows={2}
              className="border-0 shadow-none focus:ring-0 p-0 resize-none"
            />
            <Button size="icon" onClick={() => send()} disabled={!input.trim() || isStreaming}>
              <Send className="h-4 w-4" />
            </Button>
          </div>
          <p className="text-xs text-violet-400 mt-1.5 text-right">Shift+Enter for new line · Enter to send</p>
        </div>
      )}
    </div>
  )
}
