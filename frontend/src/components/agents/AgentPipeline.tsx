import { useEffect, useState } from 'react'
import { ArrowRight, ChevronDown, ChevronUp, Loader2, CheckCircle, Clock, ExternalLink } from 'lucide-react'
import { fetchAgentCard, type AgentCard } from '@/api/agents'
import type { SessionStatus } from '@/hooks/useJDSession'

type CardState = 'waiting' | 'active' | 'done' | 'error'

const STATE_STYLES: Record<CardState, { border: string; bg: string; badge: string; icon: React.ReactNode; label: string }> = {
  waiting: {
    border: 'border-stone-200',
    bg:     'bg-white',
    badge:  'bg-stone-100 text-stone-500',
    icon:   <Clock className="h-3 w-3" />,
    label:  'Waiting',
  },
  active: {
    border: 'border-violet-300',
    bg:     'bg-violet-50',
    badge:  'bg-violet-100 text-violet-700',
    icon:   <Loader2 className="h-3 w-3 animate-spin" />,
    label:  'Active',
  },
  done: {
    border: 'border-violet-200',
    bg:     'bg-white',
    badge:  'bg-violet-100 text-violet-700',
    icon:   <CheckCircle className="h-3 w-3" />,
    label:  'Done',
  },
  error: {
    border: 'border-red-200',
    bg:     'bg-red-50',
    badge:  'bg-red-100 text-red-700',
    icon:   <Clock className="h-3 w-3" />,
    label:  'Error',
  },
}

interface AgentCardProps {
  number: number
  cardState: CardState
  card: AgentCard | null
  loading: boolean
}

function AgentCardUI({ number, cardState, card, loading }: AgentCardProps) {
  const [expanded, setExpanded] = useState(false)
  const s = STATE_STYLES[cardState]

  return (
    <div className={`flex-1 rounded-xl border transition-colors shadow-sm ${s.border} ${s.bg}`}>
      {/* Header row */}
      <div className="flex items-start justify-between gap-2 px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-stone-900 text-white text-xs font-bold">
            {number}
          </div>
          <div className="min-w-0">
            {loading ? (
              <div className="h-4 w-24 animate-pulse rounded bg-stone-200" />
            ) : (
              <p className="text-sm font-semibold text-stone-900 leading-tight">{card?.name ?? `Agent ${number}`}</p>
            )}
            {loading ? (
              <div className="mt-1 h-3 w-40 animate-pulse rounded bg-stone-100" />
            ) : (
              <p className="text-xs text-stone-500 mt-0.5 line-clamp-1">{card?.description}</p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <span className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${s.badge}`}>
            {s.icon}
            {s.label}
          </span>
          {card && (
            <button
              onClick={() => setExpanded(v => !v)}
              className="rounded-full p-1 text-stone-400 hover:bg-stone-100 hover:text-stone-600 transition-colors"
              title={expanded ? 'Hide details' : 'Show details'}
            >
              {expanded ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
            </button>
          )}
        </div>
      </div>

      {/* Expanded detail panel */}
      {expanded && card && (
        <div className="border-t border-stone-100 px-4 pb-3 pt-2.5">
          {/* Meta row */}
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500 mb-2.5">
            <span><span className="font-medium text-stone-700">v</span>{card.version}</span>
            <span><span className="font-medium text-stone-700">Streaming: </span>{card.capabilities.streaming ? 'yes' : 'no'}</span>
            <span><span className="font-medium text-stone-700">In: </span>{card.defaultInputModes.join(', ')}</span>
            <span><span className="font-medium text-stone-700">Out: </span>{card.defaultOutputModes.join(', ')}</span>
            {card.documentationUrl && (
              <a
                href={card.documentationUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center gap-0.5 text-violet-700 hover:underline"
              >
                Docs <ExternalLink className="h-2.5 w-2.5" />
              </a>
            )}
          </div>

          {/* Skills */}
          <p className="text-xs font-semibold text-stone-700 mb-1.5">Skills</p>
          <div className="flex flex-col gap-1.5">
            {card.skills.map(skill => (
              <div key={skill.id} className="rounded-lg bg-stone-50 border border-stone-100 px-3 py-2">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-xs font-medium text-stone-800">{skill.name}</span>
                  {skill.endpoint !== 'internal' && (
                    <code className="text-[10px] text-stone-400 font-mono shrink-0">{skill.endpoint}</code>
                  )}
                </div>
                <p className="text-xs text-stone-500 mt-0.5">{skill.description}</p>
              </div>
            ))}
          </div>

          {/* A2A card URL */}
          <p className="mt-2.5 text-[10px] text-stone-400 font-mono">
            card: {card.url.replace('/api/jd', '').replace('/api/jobs', '')}/.well-known/{number === 1 ? 'jd-drafter' : 'job-poster'}/agent-card.json
          </p>
        </div>
      )}
    </div>
  )
}

interface Props {
  status: SessionStatus
}

export function AgentPipeline({ status }: Props) {
  const [jdCard, setJdCard] = useState<AgentCard | null>(null)
  const [jobCard, setJobCard] = useState<AgentCard | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([fetchAgentCard('jd-drafter'), fetchAgentCard('job-poster')])
      .then(([jd, job]) => { setJdCard(jd); setJobCard(job) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const agent1State: CardState =
    status === 'idle'             ? 'waiting'
    : status === 'drafting'       ? 'active'
    : status === 'pending_approval' ? 'active'
    : status === 'error'          ? 'error'
    : 'done'

  const agent2State: CardState =
    status === 'publishing' ? 'active'
    : status === 'published' ? 'done'
    : status === 'error'     ? 'error'
    : 'waiting'

  return (
    <div className="flex items-start gap-3">
      <AgentCardUI number={1} cardState={agent1State} card={jdCard} loading={loading} />
      <ArrowRight className="h-4 w-4 shrink-0 text-stone-400 mt-3.5" />
      <AgentCardUI number={2} cardState={agent2State} card={jobCard} loading={loading} />
    </div>
  )
}