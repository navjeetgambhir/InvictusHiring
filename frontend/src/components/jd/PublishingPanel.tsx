import { useState } from 'react'
import { Briefcase, CheckCircle, ExternalLink, Loader2, Send, XCircle, Calendar, Users, Pencil, Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { PanelWrapper } from './PanelWrapper'
import type { SessionStatus, PlatformPosting } from '@/hooks/useJDSession'
import type { PublishOptions } from '@/api/jd'

const PLATFORM_META: Record<string, { label: string; color: string }> = {
  linkedin:    { label: 'LinkedIn',     color: 'text-blue-700 bg-blue-50 border-blue-200'   },
  indeed:      { label: 'Indeed UK',    color: 'text-amber-700 bg-amber-50 border-amber-200' },
  google_jobs: { label: 'Google Jobs',  color: 'text-violet-700 bg-violet-50 border-violet-200' },
}

interface Props {
  status: SessionStatus
  postings: PlatformPosting[]
  onPublish: (options: PublishOptions) => void
  onRevert?: () => void
}

export function PublishingPanel({ status, postings, onPublish, onRevert }: Props) {
  const [expiresAt, setExpiresAt] = useState('')
  const [maxApps, setMaxApps] = useState('')

  function handlePublish() {
    const options: PublishOptions = {}
    if (expiresAt) {
      options.expires_at = new Date(expiresAt).toISOString()
    }
    if (maxApps && parseInt(maxApps) > 0) {
      options.max_applications = parseInt(maxApps)
    }
    onPublish(options)
  }

  if (status === 'approved') {
    // Minimum date = today
    const today = new Date().toISOString().split('T')[0]

    return (
      <PanelWrapper
        icon={<CheckCircle className="h-4 w-4 text-violet-600" />}
        title="JD Approved"
        borderColor="border-violet-200"
        headerBg="bg-violet-50"
        headerHover="hover:bg-violet-100"
      >
        <div className="flex flex-col gap-4">
          <p className="text-xs text-violet-700">
            Click publish to post to the internal job board, LinkedIn, Indeed UK, and Google Jobs.
            Agent 2 will reformat and optimise the JD for each external platform.
          </p>

          {/* Expiry date */}
          <div className="flex flex-col gap-1.5">
            <Label className="flex items-center gap-1.5 text-xs text-stone-600">
              <Calendar className="h-3.5 w-3.5" />
              Close date <span className="text-stone-400 font-normal">(optional)</span>
            </Label>
            <Input
              type="date"
              min={today}
              value={expiresAt}
              onChange={e => setExpiresAt(e.target.value)}
              className="text-xs h-8"
            />
            <p className="text-[10px] text-stone-400">Job will stop accepting applications after this date.</p>
          </div>

          {/* Max applications */}
          <div className="flex flex-col gap-1.5">
            <Label className="flex items-center gap-1.5 text-xs text-stone-600">
              <Users className="h-3.5 w-3.5" />
              Max applications <span className="text-stone-400 font-normal">(optional)</span>
            </Label>
            <Input
              type="number"
              min={1}
              placeholder="e.g. 50"
              value={maxApps}
              onChange={e => setMaxApps(e.target.value)}
              className="text-xs h-8"
            />
            <p className="text-[10px] text-stone-400">Job closes automatically when this many applications are received.</p>
          </div>

          <Button size="sm" onClick={handlePublish} className="self-start">
            <Send className="h-3.5 w-3.5" />
            Publish to Job Boards
          </Button>
        </div>
      </PanelWrapper>
    )
  }

  if (status === 'publishing' || status === 'published') {
    const icon = status === 'publishing'
      ? <Loader2 className="h-4 w-4 animate-spin text-violet-600" />
      : <CheckCircle className="h-4 w-4 text-violet-600" />
    const title = status === 'publishing' ? 'Publishing to job boards…' : 'Published successfully'

    return (
      <PanelWrapper
        icon={icon}
        title={title}
        borderColor="border-violet-200"
        headerBg="bg-white"
        headerHover="hover:bg-violet-50"
      >
        <div className="flex flex-col gap-2">
          {/* Internal job board — always live once published */}
          <div className="flex items-center justify-between rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
            <div className="flex items-center gap-2">
              <Building2 className="h-3.5 w-3.5" />
              <span className="font-medium">Internal Job Board</span>
            </div>
            <a
              href="/jobs"
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs underline underline-offset-2 opacity-80 hover:opacity-100"
            >
              View <ExternalLink className="h-3 w-3" />
            </a>
          </div>

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

          {status === 'publishing' && postings.length < 3 && (
            <div className="flex items-center gap-2 rounded-lg border border-violet-100 bg-violet-50 px-3 py-2 text-xs text-violet-400">
              <Briefcase className="h-3.5 w-3.5" />
              More platforms queued…
            </div>
          )}

          {status === 'published' && onRevert && (
            <div className="border-t border-stone-100 pt-3 mt-1">
              <p className="text-[11px] text-stone-400 mb-2">Not getting enough applications? Update the JD and republish.</p>
              <Button
                size="sm"
                variant="outline"
                onClick={onRevert}
                className="w-full text-xs border-stone-200 text-stone-600 hover:border-violet-400 hover:text-violet-700"
              >
                <Pencil className="h-3.5 w-3.5" />
                Revise JD &amp; Republish
              </Button>
            </div>
          )}
        </div>
      </PanelWrapper>
    )
  }

  return null
}