import { useEffect, useState } from 'react'
import {
  Calendar, ChevronDown, ChevronUp, Download, Loader2,
  Mail, MessageSquare, Sparkles, CheckCircle2,
} from 'lucide-react'
import { PanelWrapper } from './PanelWrapper'
import { getToken } from '@/api/auth'
import {
  fetchSessionInterviews,
  generateInvitation,
  approveAndSendEmail,
  scheduleInterview,
  icsDownloadUrl,
  type InterviewRecord,
  type InterviewInvitation,
  type InterviewFormat,
} from '@/api/candidates'
import { downloadBlob } from '@/lib/download'

interface Props {
  sessionId: string
  refreshTrigger?: number
}

const FORMAT_LABELS: Record<InterviewFormat, string> = {
  phone: 'Phone Call',
  video: 'Video Call',
  in_person: 'In Person',
}

type BadgeState = 'scheduled' | 'invite_sent' | 'invite_approved' | 'awaiting_approval' | 'shortlisted'

function statusBadge(scheduled: boolean, invitation: InterviewInvitation | null): BadgeState {
  if (scheduled) return 'scheduled'
  if (!invitation) return 'shortlisted'
  if (invitation.email_approved_at) return invitation.email_sent_at ? 'invite_sent' : 'invite_approved'
  return 'awaiting_approval'
}

const BADGE_STYLES: Record<BadgeState, { label: string; className: string }> = {
  scheduled:        { label: 'Scheduled',        className: 'text-violet-600 bg-violet-50 border-violet-200' },
  invite_sent:      { label: 'Invite sent',       className: 'text-green-700 bg-green-50 border-green-200'   },
  invite_approved:  { label: 'Invite approved',   className: 'text-green-700 bg-green-50 border-green-200'   },
  awaiting_approval:{ label: 'Awaiting approval', className: 'text-amber-700 bg-amber-50 border-amber-200'   },
  shortlisted:      { label: 'Shortlisted',       className: 'text-stone-400 bg-transparent border-transparent' },
}

function QuestionList({ questions }: { questions: string[] }) {
  return (
    <ol className="flex flex-col gap-1.5 list-decimal list-inside">
      {questions.map((q, i) => (
        <li key={i} className="text-xs text-stone-700 leading-relaxed">{q}</li>
      ))}
    </ol>
  )
}

function EmailApprovalForm({
  invitation,
  candidateEmail,
  token,
  scheduled,
  onApproved,
}: {
  invitation: InterviewInvitation
  candidateEmail: string
  token: string
  scheduled: boolean
  onApproved: (updated: InterviewInvitation) => void
}) {
  const alreadySent = !!invitation.email_approved_at
  const [recipient, setRecipient] = useState(invitation.final_recipient ?? candidateEmail)
  const [subject, setSubject] = useState(invitation.final_subject ?? invitation.email_subject)
  const [body, setBody] = useState(invitation.final_body ?? invitation.email_body)
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleApprove() {
    setSending(true)
    setError(null)
    try {
      const result = await approveAndSendEmail(invitation.id, { recipient, subject, body }, token)
      onApproved(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to approve')
    } finally {
      setSending(false)
    }
  }

  if (alreadySent) {
    const sentAt = invitation.email_sent_at
      ? new Date(invitation.email_sent_at).toLocaleString('en-GB', {
          day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
        })
      : null
    return (
      <div className="rounded-lg border border-green-200 bg-green-50 p-3 flex flex-col gap-2">
        <div className="flex items-center gap-1.5">
          <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
          <span className="text-xs font-semibold text-green-800">
            {invitation.email_sent_at
              ? `Email sent to ${invitation.final_recipient}`
              : 'Approved — email not sent (SMTP not configured)'}
          </span>
        </div>
        {sentAt && <p className="text-xs text-green-700">Sent {sentAt}</p>}
        {invitation.email_send_error && (
          <p className="text-xs text-red-600">Send error: {invitation.email_send_error}</p>
        )}
        <div className="border-t border-green-200 pt-2 flex flex-col gap-1">
          <p className="text-xs text-stone-500">To: {invitation.final_recipient}</p>
          <p className="text-xs text-stone-600 font-medium">Subject: {invitation.final_subject}</p>
          <p className="text-xs text-stone-600 whitespace-pre-wrap leading-relaxed mt-1">{invitation.final_body}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-violet-200 bg-white p-3 flex flex-col gap-2.5">
      <div className="flex items-center gap-1.5">
        <Mail className="h-3.5 w-3.5 text-violet-500" />
        <span className="text-xs font-semibold text-stone-700">Review & Approve Email</span>
        <span className="ml-auto text-xs text-stone-400">Edit before sending</span>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-stone-500">To</label>
        <input
          type="email"
          value={recipient}
          onChange={e => setRecipient(e.target.value)}
          className="rounded border border-stone-200 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-stone-500">Subject</label>
        <input
          type="text"
          value={subject}
          onChange={e => setSubject(e.target.value)}
          className="rounded border border-stone-200 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-stone-500">Body</label>
        <textarea
          value={body}
          onChange={e => setBody(e.target.value)}
          rows={10}
          className="rounded border border-stone-200 px-2 py-1.5 text-xs resize-y leading-relaxed focus:outline-none focus:ring-1 focus:ring-violet-400 font-mono"
        />
      </div>

      {!scheduled && (
        <div className="flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2">
          <Calendar className="h-3.5 w-3.5 shrink-0 text-amber-500" />
          <p className="text-xs text-amber-700">Schedule the interview date &amp; time below before sending the invite.</p>
        </div>
      )}

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        onClick={handleApprove}
        disabled={sending || !recipient || !subject || !body || !scheduled}
        className="flex items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
      >
        {sending
          ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Sending…</>
          : <><CheckCircle2 className="h-3.5 w-3.5" /> Approve &amp; Send</>}
      </button>
    </div>
  )
}

function ScheduleForm({
  applicationId,
  token,
  onScheduled,
}: {
  applicationId: string
  token: string
  onScheduled: (result: { interview_scheduled_at: string; interview_format: InterviewFormat; interview_location: string | null }) => void
}) {
  const [scheduledAt, setScheduledAt] = useState('')
  const [format, setFormat] = useState<InterviewFormat>('video')
  const [location, setLocation] = useState('')
  const [notes, setNotes] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!scheduledAt) { setError('Please select a date and time'); return }
    setSaving(true)
    setError(null)
    try {
      const result = await scheduleInterview(applicationId, {
        scheduled_at: new Date(scheduledAt).toISOString(),
        format,
        location,
        notes,
      }, token)
      onScheduled({
        interview_scheduled_at: result.interview_scheduled_at,
        interview_format: format,
        interview_location: result.interview_location,
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to schedule')
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2.5 rounded-lg border border-stone-200 bg-white p-3">
      <p className="text-xs font-semibold text-stone-700 flex items-center gap-1.5">
        <Calendar className="h-3.5 w-3.5 text-violet-500" /> Schedule Interview
      </p>

      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs text-stone-500">Date & Time</label>
          <input
            type="datetime-local"
            value={scheduledAt}
            onChange={e => setScheduledAt(e.target.value)}
            className="rounded border border-stone-200 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-stone-500">Format</label>
          <select
            value={format}
            onChange={e => setFormat(e.target.value as InterviewFormat)}
            className="rounded border border-stone-200 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400"
          >
            <option value="video">Video Call</option>
            <option value="phone">Phone Call</option>
            <option value="in_person">In Person</option>
          </select>
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-stone-500">
          {format === 'video' ? 'Video Link' : format === 'in_person' ? 'Address' : 'Phone number (optional)'}
        </label>
        <input
          type="text"
          value={location}
          onChange={e => setLocation(e.target.value)}
          placeholder={format === 'video' ? 'https://meet.google.com/...' : format === 'in_person' ? '123 Main St, London' : ''}
          className="rounded border border-stone-200 px-2 py-1.5 text-xs focus:outline-none focus:ring-1 focus:ring-violet-400"
        />
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs text-stone-500">Notes (optional)</label>
        <textarea
          value={notes}
          onChange={e => setNotes(e.target.value)}
          rows={2}
          placeholder="Any additional notes for the candidate or internal team..."
          className="rounded border border-stone-200 px-2 py-1.5 text-xs resize-none focus:outline-none focus:ring-1 focus:ring-violet-400"
        />
      </div>

      {error && <p className="text-xs text-red-500">{error}</p>}

      <button
        type="submit"
        disabled={saving}
        className="flex items-center justify-center gap-1.5 rounded-lg bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-700 disabled:opacity-50 transition-colors"
      >
        {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Calendar className="h-3.5 w-3.5" />}
        Confirm Interview
      </button>
    </form>
  )
}

function InterviewRow({ record, token, onUpdated }: {
  record: InterviewRecord
  token: string
  onUpdated: (updated: Partial<InterviewRecord> & { id: string }) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [invitation, setInvitation] = useState<InterviewInvitation | null>(record.invitation)
  const [genError, setGenError] = useState<string | null>(null)

  const scheduled = !!record.interview_scheduled_at
  const badge = BADGE_STYLES[statusBadge(scheduled, invitation)]

  const scheduledDate = record.interview_scheduled_at
    ? new Date(record.interview_scheduled_at).toLocaleString('en-GB', {
        weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : null

  async function handleGenerate() {
    setGenerating(true)
    setGenError(null)
    try {
      const inv = await generateInvitation(record.id, token)
      setInvitation(inv)
      setExpanded(true)
    } catch (err) {
      setGenError(err instanceof Error ? err.message : 'Generation failed')
    } finally {
      setGenerating(false)
    }
  }

  function handleScheduled(result: { interview_scheduled_at: string; interview_format: InterviewFormat; interview_location: string | null }) {
    onUpdated({
      id: record.id,
      interview_status: 'scheduled',
      interview_scheduled_at: result.interview_scheduled_at,
      interview_format: result.interview_format,
      interview_location: result.interview_location,
    })

    // Replace [DATE/TIME] and [FORMAT] placeholders in the invitation body
    if (invitation && !invitation.email_approved_at) {
      const formattedDate = new Date(result.interview_scheduled_at).toLocaleString('en-GB', {
        weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
      const formatLabel = FORMAT_LABELS[result.interview_format]
      setInvitation(prev => prev ? {
        ...prev,
        email_body: prev.email_body
          .replace(/\[DATE\/TIME\]/gi, formattedDate)
          .replace(/\[FORMAT\]/gi, formatLabel),
      } : prev)
    }
  }

  return (
    <div className="rounded-lg border border-stone-200 bg-white overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-stone-50 transition-colors text-left"
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-amber-100 text-sm font-semibold text-amber-700">
            {record.name.charAt(0).toUpperCase()}
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium text-stone-900 truncate">{record.name}</p>
            <p className="text-xs text-stone-500 truncate">{record.email}</p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 ml-3">
          {record.screening_score !== null && (
            <span className="text-xs text-stone-500 font-medium">{record.screening_score}/100</span>
          )}
          <span className={`text-xs font-medium border px-2 py-0.5 rounded-full ${badge.className}`}>
            {badge.label}
          </span>
          {expanded ? <ChevronUp className="h-4 w-4 text-stone-400" /> : <ChevronDown className="h-4 w-4 text-stone-400" />}
        </div>
      </button>

      {expanded && (
        <div className="border-t border-stone-100 px-4 py-4 flex flex-col gap-3 bg-stone-50">
          {record.screening_summary && (
            <p className="text-xs text-stone-600 leading-relaxed italic">{record.screening_summary}</p>
          )}

          {scheduled && scheduledDate && (
            <div className="flex items-start justify-between rounded-lg border border-violet-200 bg-violet-50 p-3">
              <div className="flex flex-col gap-0.5">
                <p className="text-xs font-semibold text-violet-800">Interview Confirmed</p>
                <p className="text-xs text-violet-700">{scheduledDate}</p>
                {record.interview_format && (
                  <p className="text-xs text-violet-600">{FORMAT_LABELS[record.interview_format]}</p>
                )}
                {record.interview_location && (
                  <p className="text-xs text-stone-600">{record.interview_location}</p>
                )}
              </div>
              <button
                onClick={e => { e.stopPropagation(); downloadBlob(icsDownloadUrl(record.id), `interview_${record.name.replace(/\s+/g, '_').toLowerCase()}.ics`, token) }}
                className="flex items-center gap-1 text-xs text-violet-700 hover:underline shrink-0 ml-3"
              >
                <Download className="h-3.5 w-3.5" /> .ics
              </button>
            </div>
          )}

          {invitation && (
            <>
              <EmailApprovalForm
                key={record.interview_scheduled_at ?? 'unscheduled'}
                invitation={invitation}
                candidateEmail={record.email}
                token={token}
                scheduled={scheduled}
                onApproved={updated => setInvitation(updated)}
              />
              <div className="rounded-lg border border-stone-200 bg-white p-3 flex flex-col gap-2">
                <div className="flex items-center gap-1.5">
                  <MessageSquare className="h-3.5 w-3.5 text-violet-500" />
                  <span className="text-xs font-semibold text-stone-700">Interview Questions</span>
                </div>
                <QuestionList questions={invitation.interview_questions} />
              </div>
            </>
          )}

          {!invitation && (
            <div className="flex flex-col gap-1.5">
              <button
                onClick={handleGenerate}
                disabled={generating}
                className="flex items-center justify-center gap-1.5 rounded-lg border border-violet-300 bg-white px-3 py-2 text-xs font-semibold text-violet-700 hover:bg-violet-50 disabled:opacity-50 transition-colors"
              >
                {generating
                  ? <><Loader2 className="h-3.5 w-3.5 animate-spin" /> Generating…</>
                  : <><Sparkles className="h-3.5 w-3.5" /> Generate AI Invitation</>}
              </button>
              {genError && <p className="text-xs text-red-500">{genError}</p>}
            </div>
          )}

          {invitation && (
            <button
              onClick={handleGenerate}
              disabled={generating}
              className="self-start flex items-center gap-1 text-xs text-stone-400 hover:text-violet-600 transition-colors"
            >
              {generating ? <Loader2 className="h-3 w-3 animate-spin" /> : <Sparkles className="h-3 w-3" />}
              Regenerate
            </button>
          )}

          {!scheduled && (
            <ScheduleForm
              applicationId={record.id}
              token={token}
              onScheduled={handleScheduled}
            />
          )}
        </div>
      )}
    </div>
  )
}

export function InterviewPanel({ sessionId, refreshTrigger }: Props) {
  const [records, setRecords] = useState<InterviewRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const token = getToken() ?? ''

  useEffect(() => {
    if (!token) return

    let cancelled = false

    async function refresh() {
      try {
        const data = await fetchSessionInterviews(sessionId, token)
        if (!cancelled) {
          setRecords(prev => {
            const changed = data.length !== prev.length || data.some(d => {
              const p = prev.find(p => p.id === d.id)
              return !p
                || p.interview_status !== d.interview_status
                || p.interview_scheduled_at !== d.interview_scheduled_at
                || !!d.invitation !== !!p.invitation
            })
            return changed ? data : prev
          })
        }
      } catch { /* ignore polling errors */ }
    }

    fetchSessionInterviews(sessionId, token)
      .then(data => { if (!cancelled) { setRecords(data); setLoading(false) } })
      .catch(e => { if (!cancelled) { setError(e.message); setLoading(false) } })

    const interval = setInterval(refresh, 5_000)
    return () => { cancelled = true; clearInterval(interval) }
  }, [sessionId, token, refreshTrigger])

  function handleUpdated(updated: Partial<InterviewRecord> & { id: string }) {
    setRecords(prev => prev.map(r => r.id === updated.id ? { ...r, ...updated } : r))
  }

  const scheduledCount = records.filter(r => r.interview_status === 'scheduled').length

  const metaText = !loading
    ? `${records.length} shortlisted${scheduledCount > 0 ? ` · ${scheduledCount} scheduled` : ''}`
    : undefined

  return (
    <PanelWrapper
      icon={<Calendar className="h-4 w-4 text-amber-500" />}
      title="Interview Scheduling"
      meta={metaText}
      borderColor="border-amber-200"
      headerBg="bg-white"
      headerHover="hover:bg-amber-50"
    >
      <div className="flex flex-col gap-2">
        {loading && (
          <div className="flex items-center gap-2 text-xs text-stone-400 py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
          </div>
        )}
        {error && <p className="text-xs text-red-500">{error}</p>}

        {!loading && !error && records.length === 0 && (
          <p className="text-xs text-stone-400 py-2">
            No shortlisted candidates yet. Star candidates in the Applications panel to shortlist them.
          </p>
        )}

        {records.length > 0 && records.map(r => (
          <InterviewRow key={r.id} record={r} token={token} onUpdated={handleUpdated} />
        ))}
      </div>
    </PanelWrapper>
  )
}