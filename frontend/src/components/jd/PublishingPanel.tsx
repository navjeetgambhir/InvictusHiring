import { Briefcase, CheckCircle, ExternalLink, Loader2, Send, XCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { SessionStatus, PlatformPosting } from '@/hooks/useJDSession'

const PLATFORM_META: Record<string, { label: string; color: string }> = {
  linkedin:    { label: 'LinkedIn',     color: 'text-blue-700 bg-blue-50 border-blue-200'   },
  indeed:      { label: 'Indeed UK',    color: 'text-amber-700 bg-amber-50 border-amber-200' },
  google_jobs: { label: 'Google Jobs',  color: 'text-violet-700 bg-violet-50 border-violet-200' },
}

interface Props {
  status: SessionStatus
  postings: PlatformPosting[]
  onPublish: () => void
}

export function PublishingPanel({ status, postings, onPublish }: Props) {
  if (status === 'approved') {
    return (
      <div className="flex flex-col gap-3 rounded-xl border border-violet-200 bg-violet-50 p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <CheckCircle className="h-4 w-4 text-violet-600" />
            <span className="text-sm font-medium text-violet-800">JD Approved</span>
          </div>
          <Button size="sm" onClick={onPublish}>
            <Send className="h-3.5 w-3.5" />
            Publish to Job Boards
          </Button>
        </div>
        <p className="text-xs text-violet-700">
          Click publish to post to LinkedIn, Indeed UK, and Google Jobs.
          Agent 2 will reformat and optimise the JD for each platform.
        </p>
      </div>
    )
  }

  if (status === 'publishing' || status === 'published') {
    return (
      <div className="flex flex-col gap-3 rounded-xl border border-violet-200 bg-white p-4 shadow-sm">
        <div className="flex items-center gap-2">
          {status === 'publishing' ? (
            <Loader2 className="h-4 w-4 animate-spin text-violet-600" />
          ) : (
            <CheckCircle className="h-4 w-4 text-violet-600" />
          )}
          <span className="text-sm font-semibold text-stone-800">
            {status === 'publishing' ? 'Publishing to job boards…' : 'Published successfully'}
          </span>
        </div>

        <div className="flex flex-col gap-2">
          {postings.map(p => {
            const meta = PLATFORM_META[p.platform_id] ?? { label: p.platform, color: 'text-stone-700 bg-stone-50 border-stone-200' }
            return (
              <div
                key={p.platform}
                className={`flex items-center justify-between rounded-lg border px-3 py-2 text-sm ${meta.color}`}
              >
                <div className="flex items-center gap-2">
                  {p.status === 'posting' && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {p.status === 'posted'  && <CheckCircle className="h-3.5 w-3.5" />}
                  {p.status === 'error'   && <XCircle className="h-3.5 w-3.5 text-red-500" />}
                  <span className="font-medium">{meta.label}</span>
                  {p.status === 'posting' && <span className="text-xs opacity-70">formatting…</span>}
                  {p.status === 'error'   && <span className="text-xs text-red-600">failed</span>}
                </div>
                {p.status === 'posted' && p.url && (
                  <a
                    href={p.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="flex items-center gap-1 text-xs underline underline-offset-2 opacity-80 hover:opacity-100"
                  >
                    View post <ExternalLink className="h-3 w-3" />
                  </a>
                )}
              </div>
            )
          })}

          {/* Pending platforms not yet started */}
          {status === 'publishing' && postings.length < 3 && (
            <div className="flex items-center gap-2 rounded-lg border border-violet-100 bg-violet-50 px-3 py-2 text-xs text-violet-400">
              <Briefcase className="h-3.5 w-3.5" />
              More platforms queued…
            </div>
          )}
        </div>
      </div>
    )
  }

  return null
}