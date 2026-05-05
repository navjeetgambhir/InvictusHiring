import { useState, useRef, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { Bot, User, Info, DatabaseIcon } from 'lucide-react'
import type { Message } from '@/hooks/useJDSession'

function MarkdownText({ text }: { text: string }) {
  // Minimal inline markdown: **bold**, bullet lines, headings
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
        if (line === '') return <div key={i} className="h-2" />
        return <p key={i}>{line}</p>
      })}
    </div>
  )
}

function SqlBadge({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false)
  const [openUpward, setOpenUpward] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open || !btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    // popover is ~280px tall; flip up if less than 300px below the button
    setOpenUpward(window.innerHeight - rect.bottom < 300)
  }, [open])

  return (
    <div className="relative inline-block">
      <button
        ref={btnRef}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={() => setOpen(v => !v)}
        className="flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full bg-stone-100 border border-stone-200 text-[10px] font-medium text-stone-500 hover:bg-stone-200 hover:text-stone-700 transition-colors"
        title="View generated SQL"
      >
        <DatabaseIcon className="h-3 w-3" />
        SQL
      </button>
      {open && (
        <div className={`absolute left-0 z-50 w-80 rounded-xl border border-stone-200 bg-stone-950 shadow-xl ${openUpward ? 'bottom-full mb-1' : 'top-full mt-1'}`}>
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
      </div>
    </div>
  )
}