import { useEffect, useState } from 'react'
import { Users, Download, ChevronDown, ChevronUp, Loader2, AlertCircle, Star } from 'lucide-react'
import { getToken } from '@/api/auth'
import { fetchApplications, toggleShortlist, cvDownloadUrl, type CandidateApplicationRecord, type ScreeningRecommendation } from '@/api/candidates'
import { downloadBlob } from '@/lib/download'

interface Props {
  sessionId: string
}

const RECOMMENDATION_META: Record<ScreeningRecommendation, { label: string; color: string }> = {
  strong_match:   { label: 'Strong Match',   color: 'bg-green-100 text-green-800 border-green-200' },
  good_match:     { label: 'Good Match',     color: 'bg-blue-100 text-blue-800 border-blue-200'   },
  partial_match:  { label: 'Partial Match',  color: 'bg-amber-100 text-amber-800 border-amber-200' },
  poor_match:     { label: 'Poor Match',     color: 'bg-red-100 text-red-800 border-red-200'       },
}

function ScoreBadge({ score, recommendation }: { score: number | null; recommendation: ScreeningRecommendation | null }) {
  if (score === null || !recommendation) return <span className="text-xs text-stone-400">—</span>
  const meta = RECOMMENDATION_META[recommendation]
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${meta.color}`}>
      {score}/100 · {meta.label}
    </span>
  )
}

function ApplicationRow({ app, sessionId, token, onShortlistToggled }: {
  app: CandidateApplicationRecord
  sessionId: string
  token: string
  onShortlistToggled: (id: string, shortlisted: boolean) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [shortlisting, setShortlisting] = useState(false)

  const appliedDate = new Date(app.applied_at).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })

  async function handleShortlist(e: React.MouseEvent) {
    e.stopPropagation()
    setShortlisting(true)
    try {
      const result = await toggleShortlist(app.id, token)
      onShortlistToggled(app.id, result.shortlisted)
    } finally {
      setShortlisting(false)
    }
  }

  function downloadCV() {
    downloadBlob(cvDownloadUrl(sessionId, app.id), app.cv_filename!, token)
  }

  return (
    <div className="rounded-lg border border-stone-200 bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-stone-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-stone-100 text-sm font-semibold text-stone-600">
            {app.name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-stone-900 truncate">{app.name}</p>
            <p className="text-xs text-stone-500 truncate">{app.email}</p>
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0 ml-3">
          {app.screening_status === 'pending' && (
            <span className="flex items-center gap-1 text-xs text-stone-400">
              <Loader2 className="h-3 w-3 animate-spin" /> Screening…
            </span>
          )}
          {app.screening_status === 'failed' && !app.has_cv && (
            <span className="text-xs text-stone-400">No CV</span>
          )}
          {app.screening_status === 'failed' && app.has_cv && (
            <span className="flex items-center gap-1 text-xs text-red-500">
              <AlertCircle className="h-3 w-3" /> Screen failed
            </span>
          )}
          {app.screening_status === 'screened' && (
            <ScoreBadge score={app.screening_score} recommendation={app.screening_recommendation} />
          )}
          {app.screening_status === 'screened' && (
            <button
              onClick={handleShortlist}
              disabled={shortlisting}
              title={app.shortlisted ? 'Remove from shortlist' : 'Add to shortlist'}
              className={`rounded-full p-1 transition-colors ${app.shortlisted ? 'text-amber-500 hover:text-stone-400' : 'text-stone-300 hover:text-amber-400'}`}
            >
              {shortlisting
                ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                : <Star className={`h-3.5 w-3.5 ${app.shortlisted ? 'fill-amber-400' : ''}`} />}
            </button>
          )}
          {app.interview_status === 'scheduled' && (
            <span className="text-xs font-medium text-violet-600 bg-violet-50 border border-violet-200 px-2 py-0.5 rounded-full">
              Interview scheduled
            </span>
          )}
          <span className="text-xs text-stone-400">{appliedDate}</span>
          {expanded ? <ChevronUp className="h-4 w-4 text-stone-400" /> : <ChevronDown className="h-4 w-4 text-stone-400" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-stone-100 px-4 py-4 flex flex-col gap-3 bg-stone-50">
          <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-stone-600">
            {app.phone && <span>Phone: {app.phone}</span>}
            {app.cv_filename && (
              <button
                onClick={downloadCV}
                className="flex items-center gap-1 text-violet-700 hover:underline"
              >
                <Download className="h-3.5 w-3.5" />
                {app.cv_filename}
              </button>
            )}
          </div>

          {app.cover_letter && (
            <div>
              <p className="text-xs font-semibold text-stone-500 mb-1">Cover Letter</p>
              <p className="text-xs text-stone-700 whitespace-pre-wrap leading-relaxed">{app.cover_letter}</p>
            </div>
          )}

          {app.screening_status === 'screened' && (
            <div className="rounded-lg border border-stone-200 bg-white p-3 flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <p className="text-xs font-semibold text-stone-700">AI Screening</p>
                <ScoreBadge score={app.screening_score} recommendation={app.screening_recommendation} />
              </div>
              {app.screening_summary && (
                <p className="text-xs text-stone-600 leading-relaxed">{app.screening_summary}</p>
              )}
              <div className="grid grid-cols-2 gap-2">
                {app.screening_strengths && app.screening_strengths.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-violet-700 mb-1">Strengths</p>
                    <ul className="flex flex-col gap-0.5">
                      {app.screening_strengths.map((s, i) => (
                        <li key={i} className="text-xs text-stone-600 before:content-['✓_'] before:text-violet-500">{s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {app.screening_gaps && app.screening_gaps.length > 0 && (
                  <div>
                    <p className="text-xs font-medium text-red-600 mb-1">Gaps</p>
                    <ul className="flex flex-col gap-0.5">
                      {app.screening_gaps.map((g, i) => (
                        <li key={i} className="text-xs text-stone-600 before:content-['✗_'] before:text-red-400">{g}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function ApplicationsPanel({ sessionId }: Props) {
  const [apps, setApps] = useState<CandidateApplicationRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const token = getToken() ?? ''

  useEffect(() => {
    if (!token) return

    let interval: ReturnType<typeof setInterval> | null = null

    fetchApplications(sessionId, token)
      .then((initial) => {
        setApps(initial)
        setLoading(false)

        if (!initial.some(a => a.screening_status === 'pending')) return

        interval = setInterval(async () => {
          try {
            const updated = await fetchApplications(sessionId, token)
            setApps(prev => {
              const changed = updated.length !== prev.length || updated.some(u => {
                const p = prev.find(p => p.id === u.id)
                return !p || p.screening_status !== u.screening_status || p.screening_score !== u.screening_score
              })
              return changed ? updated : prev
            })
            if (!updated.some(a => a.screening_status === 'pending')) clearInterval(interval!)
          } catch { /* ignore polling errors */ }
        }, 10_000)
      })
      .catch((e) => {
        setError(e.message)
        setLoading(false)
      })

    return () => { if (interval) clearInterval(interval) }
  }, [sessionId, token])

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-violet-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-violet-500" />
        <span className="text-sm font-semibold text-stone-800">Applications</span>
        {!loading && <span className="ml-auto text-xs text-stone-400">{apps.length} received</span>}
      </div>

      {loading && (
        <div className="flex items-center gap-2 text-xs text-stone-400 py-2">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
        </div>
      )}
      {error && <p className="text-xs text-red-500">{error}</p>}

      {!loading && !error && apps.length === 0 && (
        <p className="text-xs text-stone-400 py-2">No applications yet. Share the job board link with candidates.</p>
      )}

      {apps.length > 0 && (
        <div className="flex flex-col gap-2">
          {apps.map(app => (
            <ApplicationRow
              key={app.id}
              app={app}
              sessionId={sessionId}
              token={token}
              onShortlistToggled={(id, shortlisted) =>
                setApps(prev => prev.map(a => a.id === id ? { ...a, shortlisted } : a))
              }
            />
          ))}
        </div>
      )}
    </div>
  )
}