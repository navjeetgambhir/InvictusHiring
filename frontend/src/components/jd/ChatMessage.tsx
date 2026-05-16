import { useState, useRef, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { Bot, User, Info, DatabaseIcon, TrendingUp, TrendingDown } from 'lucide-react'
import type { Message, MlResult, MlFactor } from '@/hooks/useJDSession'

// Hoisted to module scope — stable reference, no re-allocation per render.
// Matches *italic* but not **bold**: negative lookahead/lookbehind prevents
// matching the inner *word* of **word**.
function renderInline(line: string) {
  const parts = line.split(/((?<!\*)\*(?!\*)[^*]+(?<!\*)\*(?!\*))/)
  return parts.map((part, j) =>
    part.startsWith('*') && part.endsWith('*') && part.length > 2
      ? <em key={j} className="text-stone-500 not-italic text-sm">{part.slice(1, -1)}</em>
      : part
  )
}

function MarkdownText({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <div className="flex flex-col gap-0.5">
      {lines.map((line, i) => {
        if (line.startsWith('## ')) return <p key={i} className="font-semibold text-stone-800 mt-2">{line.slice(3)}</p>
        if (line.startsWith('# ')) return <p key={i} className="font-bold text-stone-900 text-base mt-3">{line.slice(2)}</p>
        if (line.startsWith('- ') || line.startsWith('• ')) {
          return <p key={i} className="pl-4 before:content-['•'] before:mr-2 before:text-violet-600">{line.slice(2)}</p>
        }
        if (line.startsWith('**') && line.endsWith('**')) {
          return <p key={i} className="font-semibold text-stone-800">{line.slice(2, -2)}</p>
        }
        if (line.trim() === '---') return <hr key={i} className="border-stone-200 my-2" />
        if (line === '') return <div key={i} className="h-2" />
        return <p key={i}>{renderInline(line)}</p>
      })}
    </div>
  )
}

function SqlBadge({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false)
  const [style, setStyle] = useState<React.CSSProperties>({})
  const btnRef = useRef<HTMLButtonElement>(null)

  function computePosition() {
    if (!btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const openUpward = window.innerHeight - rect.bottom < 300
    setStyle(
      openUpward
        ? { position: 'fixed', bottom: window.innerHeight - rect.top + 4, left: rect.left, zIndex: 9999 }
        : { position: 'fixed', top: rect.bottom + 4, left: rect.left, zIndex: 9999 },
    )
  }

  function handleOpen() { computePosition(); setOpen(true) }
  function handleClose() { setOpen(false) }

  useEffect(() => {
    if (open) {
      window.addEventListener('scroll', handleClose, true)
      return () => window.removeEventListener('scroll', handleClose, true)
    }
  }, [open])

  return (
    <div className="relative inline-block">
      <button
        ref={btnRef}
        onMouseEnter={handleOpen}
        onMouseLeave={handleClose}
        onClick={() => { if (!open) { handleOpen() } else { handleClose() } }}
        className="flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full bg-stone-100 border border-stone-200 text-[10px] font-medium text-stone-500 hover:bg-stone-200 hover:text-stone-700 transition-colors"
        title="View generated SQL"
      >
        <DatabaseIcon className="h-3 w-3" />
        SQL
      </button>
      {open && (
        <div style={style} className="w-80 rounded-xl border border-stone-200 bg-stone-950 shadow-xl"
          onMouseEnter={handleOpen}
          onMouseLeave={handleClose}
        >
          <div className="flex items-center justify-between px-3 py-2 border-b border-stone-800">
            <span className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider">Generated SQL</span>
            <button
              onClick={() => navigator.clipboard.writeText(sql)}
              className="text-[10px] text-stone-500 hover:text-stone-300 transition-colors"
            >
              copy
            </button>
          </div>
          <pre className="px-3 py-3 text-[11px] text-green-400 font-mono whitespace-pre-wrap break-all leading-relaxed max-h-60 overflow-y-auto">
            {sql}
          </pre>
        </div>
      )}
    </div>
  )
}

function ScoreGauge({ label, value, color }: { label: string; value: number | null | undefined; color: string }) {
  if (value == null) return null
  return (
    <div className="flex items-center gap-2">
      <span className="text-[10px] text-stone-500 w-8 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded-full bg-stone-100 overflow-hidden">
        <div className={cn('h-full rounded-full transition-all', color)} style={{ width: `${value}%` }} />
      </div>
      <span className="text-[11px] font-semibold text-stone-700 w-9 text-right">{value.toFixed(0)}%</span>
    </div>
  )
}

function FactorBar({ factor }: { factor: MlFactor }) {
  const maxContrib = 1.5  // cap for visual scale
  const pct = Math.min(Math.abs(factor.contribution) / maxContrib * 100, 100)
  const isPos = factor.direction === 'positive'
  const isAbsent = factor.raw_value === 0
  const tooltip = `${factor.label}: ${isAbsent ? 'not submitted / absent' : factor.raw_value}`
  return (
    <div className="flex items-center gap-2">
      <span className={cn('text-[10px] flex-1 min-w-0 truncate', isAbsent ? 'text-stone-400 italic' : 'text-stone-600')} title={tooltip}>
        {factor.label}{isAbsent && <span className="ml-1 text-[9px] text-stone-400">(absent)</span>}
      </span>
      <div className="w-20 h-1.5 rounded-full bg-stone-100 overflow-hidden shrink-0">
        <div
          className={cn('h-full rounded-full', isPos ? 'bg-emerald-400' : 'bg-rose-400')}
          style={{ width: `${pct}%` }}
        />
      </div>
      {isPos
        ? <TrendingUp className="h-3 w-3 text-emerald-500 shrink-0" />
        : <TrendingDown className="h-3 w-3 text-rose-400 shrink-0" />
      }
    </div>
  )
}

function MlCandidateCard({ result }: { result: MlResult }) {
  const [open, setOpen] = useState(false)
  const hasExplanation = (result.fit_explanation?.length ?? 0) > 0 || (result.join_explanation?.length ?? 0) > 0
  const rec = result.screening_recommendation?.replace(/_/g, ' ')

  return (
    <div className="border border-stone-200 rounded-xl bg-stone-50 p-3 space-y-2">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-sm font-semibold text-stone-800">{result.candidate_name}</p>
          {rec && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 font-medium capitalize">
              {rec}
            </span>
          )}
        </div>
        {result.shortlisted && (
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 font-medium shrink-0">
            Shortlisted
          </span>
        )}
      </div>

      <div className="space-y-1">
        {result.screening_score != null && (
          <ScoreGauge label="Screen" value={result.screening_score} color="bg-stone-400" />
        )}
        <ScoreGauge label="Fit" value={result.fit_probability} color="bg-violet-500" />
        <ScoreGauge label="Join" value={result.join_probability} color="bg-emerald-500" />
      </div>

      {hasExplanation && (
        <button
          onClick={() => setOpen(o => !o)}
          className="text-[10px] text-violet-600 hover:text-violet-800 font-medium transition-colors"
        >
          {open ? 'Hide factors ↑' : 'Why this score? ↓'}
        </button>
      )}

      {open && (
        <div className="space-y-3 pt-1 border-t border-stone-200">
          {(result.fit_explanation?.length ?? 0) > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-stone-500 uppercase tracking-wider mb-1">Fit factors</p>
              <div className="space-y-1">
                {result.fit_explanation!.map(f => <FactorBar key={f.feature} factor={f} />)}
              </div>
            </div>
          )}
          {(result.join_explanation?.length ?? 0) > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-stone-500 uppercase tracking-wider mb-1">Join factors</p>
              <div className="space-y-1">
                {result.join_explanation!.map(f => <FactorBar key={f.feature} factor={f} />)}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MlResultCard({ data }: { data: MlResult[] }) {
  if (!data.length) return null
  return (
    <div className="mt-3 space-y-2 w-full">
      {data.map(r => <MlCandidateCard key={r.application_id} result={r} />)}
    </div>
  )
}

export function ChatMessageBubble({ message }: { message: Message }) {
  if (message.role === 'system') {
    return (
      <div className="flex items-center justify-center gap-2 py-2">
        <Info className="h-3.5 w-3.5 text-stone-400 shrink-0" />
        <span className="text-xs text-stone-500 italic"
          dangerouslySetInnerHTML={{
            __html: message.content.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
          }}
        />
      </div>
    )
  }

  const isUser = message.role === 'user'

  return (
    <div className={cn('flex gap-3 items-start', isUser && 'flex-row-reverse')}>
      <div className={cn(
        'flex h-8 w-8 shrink-0 items-center justify-center rounded-full',
        isUser ? 'bg-violet-600' : 'bg-stone-100 border border-stone-200'
      )}>
        {isUser
          ? <User className="h-4 w-4 text-white" />
          : <Bot className="h-4 w-4 text-stone-600" />
        }
      </div>

      <div className={cn(
        'max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed',
        isUser
          ? 'bg-violet-600 text-white rounded-tr-sm'
          : 'bg-white border border-stone-200 text-stone-800 rounded-tl-sm shadow-sm'
      )}>
        {message.streaming && message.content === ''
          ? <span className="flex gap-1 items-center h-5">
              <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:0ms]" />
              <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 rounded-full bg-stone-400 animate-bounce [animation-delay:300ms]" />
            </span>
          : isUser
            ? message.content
            : <MarkdownText text={message.content} />
        }
        {message.streaming && message.content !== '' && (
          <span className="inline-block h-3.5 w-0.5 bg-stone-400 animate-pulse ml-0.5 align-middle" />
        )}
        {!isUser && message.sql && <SqlBadge sql={message.sql} />}
        {!isUser && message.mlData && message.mlData.length > 0 && (
          <MlResultCard data={message.mlData} />
        )}
      </div>
    </div>
  )
}