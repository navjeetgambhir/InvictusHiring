import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, MapPin, DollarSign, Building2, Briefcase, CheckCircle2, Paperclip, X, FileText, Clock, Users, AlertCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { PageShell } from '@/components/layout/PageShell'
import { fetchJob, submitApplication, type JobListing } from '@/api/candidates'

export function JobDetailPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const navigate = useNavigate()
  const [job, setJob] = useState<JobListing | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!sessionId) return
    fetchJob(sessionId)
      .then(setJob)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [sessionId])

  if (loading) {
    return (
      <PageShell>
        <div className="text-center text-stone-400 py-24">Loading job details…</div>
      </PageShell>
    )
  }

  if (error || !job) {
    return (
      <PageShell>
        <div className="text-center py-24">
          <p className="text-red-500 mb-4">{error ?? 'Job not found'}</p>
          <Button variant="outline" onClick={() => navigate('/jobs')}>Back to jobs</Button>
        </div>
      </PageShell>
    )
  }

  return (
    <PageShell>
      {/* Back */}
      <button
        onClick={() => navigate('/jobs')}
        className="flex items-center gap-1.5 text-sm text-stone-500 hover:text-stone-800 transition-colors mb-6"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to all jobs
      </button>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left: JD content */}
        <div className="lg:col-span-2 flex flex-col gap-6">
          {/* Job header */}
          <div className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
            <div className="flex items-start gap-3 mb-4">
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-violet-600">
                <Briefcase className="h-5 w-5 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-stone-900">{job.title}</h1>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-sm text-stone-500">
                  <Badge variant="secondary">{job.department}</Badge>
                  <span className="flex items-center gap-1">
                    <MapPin className="h-3.5 w-3.5" />{job.location}
                  </span>
                  {job.salary_band && (
                    <span className="flex items-center gap-1">
                      <DollarSign className="h-3.5 w-3.5" />{job.salary_band}
                    </span>
                  )}
                  {job.expires_at && (
                    <span className="flex items-center gap-1 text-amber-600">
                      <Clock className="h-3.5 w-3.5" />
                      Closes {new Date(job.expires_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
                    </span>
                  )}
                  {job.max_applications != null && (
                    <span className={`flex items-center gap-1 ${job.max_applications - job.application_count <= 5 ? 'text-red-500' : 'text-stone-500'}`}>
                      <Users className="h-3.5 w-3.5" />
                      {Math.max(0, job.max_applications - job.application_count)} spot{job.max_applications - job.application_count !== 1 ? 's' : ''} left
                    </span>
                  )}
                </div>
              </div>
            </div>

            {job.company_description && (
              <div className="flex items-start gap-2 text-sm text-stone-600 border-t border-stone-100 pt-4">
                <Building2 className="h-4 w-4 mt-0.5 shrink-0 text-stone-400" />
                <p>{job.company_description}</p>
              </div>
            )}
          </div>

          {/* Skills */}
          {(job.required_skills.length > 0 || job.nice_to_have_skills.length > 0) && (
            <div className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
              {job.required_skills.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-semibold text-stone-700 mb-2">Required Skills</h3>
                  <div className="flex flex-wrap gap-2">
                    {job.required_skills.map((s) => (
                      <span key={s} className="rounded-full bg-violet-50 px-3 py-1 text-sm font-medium text-violet-700">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {job.nice_to_have_skills.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold text-stone-700 mb-2">Nice to Have</h3>
                  <div className="flex flex-wrap gap-2">
                    {job.nice_to_have_skills.map((s) => (
                      <span key={s} className="rounded-full bg-stone-100 px-3 py-1 text-sm text-stone-600">
                        {s}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Full JD content */}
          {job.content && (
            <div className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
              <h2 className="text-base font-semibold text-stone-800 mb-4">Full Job Description</h2>
              <div className="prose prose-stone prose-sm max-w-none whitespace-pre-wrap text-stone-700 leading-relaxed text-sm">
                {job.content}
              </div>
            </div>
          )}
        </div>

        {/* Right: Apply form or closed notice */}
        <div className="lg:col-span-1">
          <div className="sticky top-6">
            {job.is_accepting
              ? <ApplyForm sessionId={sessionId!} jobTitle={job.title} />
              : (
                <div className="rounded-xl border border-stone-200 bg-stone-50 p-6 text-center shadow-sm">
                  <AlertCircle className="h-8 w-8 text-stone-400 mx-auto mb-3" />
                  <h3 className="font-semibold text-stone-700 mb-1">Applications Closed</h3>
                  <p className="text-sm text-stone-500">
                    {job.expires_at && new Date(job.expires_at) <= new Date()
                      ? 'This job posting has expired.'
                      : 'This job has reached its maximum number of applications.'}
                  </p>
                </div>
              )
            }
          </div>
        </div>
      </div>
    </PageShell>
  )
}

function ApplyForm({ sessionId, jobTitle }: { sessionId: string; jobTitle: string }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [phone, setPhone] = useState('')
  const [clMode, setClMode] = useState<'type' | 'upload'>('type')
  const [coverLetter, setCoverLetter] = useState('')
  const [clFile, setClFile] = useState<File | null>(null)
  const [cvFile, setCvFile] = useState<File | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const cvRef = useRef<HTMLInputElement>(null)
  const clRef = useRef<HTMLInputElement>(null)

  // keep fileRef alias for the existing CV input
  const fileRef = cvRef

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await submitApplication(sessionId, {
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim() || undefined,
        cover_letter: clMode === 'type' ? coverLetter.trim() || undefined : undefined,
        cover_letter_file: clMode === 'upload' ? clFile ?? undefined : undefined,
        cv: cvFile ?? undefined,
      })
      setSubmitted(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setSubmitting(false)
    }
  }

  if (submitted) {
    return (
      <div className="rounded-xl border border-violet-200 bg-violet-50 p-6 text-center shadow-sm">
        <CheckCircle2 className="h-10 w-10 text-violet-500 mx-auto mb-3" />
        <h3 className="font-semibold text-stone-900 mb-1">Application Submitted</h3>
        <p className="text-sm text-stone-500">
          Thanks for applying for <span className="font-medium">{jobTitle}</span>. We'll be in touch soon.
        </p>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm">
      <h2 className="text-base font-semibold text-stone-900 mb-4">Apply for this role</h2>
      <form onSubmit={handleSubmit} className="flex flex-col gap-4">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="name">Full Name <span className="text-red-400">*</span></Label>
          <Input
            id="name"
            placeholder="Jane Smith"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="email">Email <span className="text-red-400">*</span></Label>
          <Input
            id="email"
            type="email"
            placeholder="jane@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <Label htmlFor="phone">Phone <span className="text-stone-400 text-xs font-normal">(optional)</span></Label>
          <Input
            id="phone"
            type="tel"
            placeholder="+44 7700 000000"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
        </div>

        {/* CV upload */}
        <div className="flex flex-col gap-1.5">
          <Label>CV / Resume <span className="text-stone-400 text-xs font-normal">(PDF, DOCX — max 5 MB)</span></Label>
          {cvFile ? (
            <div className="flex items-center justify-between rounded-lg border border-violet-200 bg-violet-50 px-3 py-2">
              <div className="flex items-center gap-2 text-sm text-violet-800 truncate">
                <Paperclip className="h-4 w-4 shrink-0" />
                <span className="truncate">{cvFile.name}</span>
              </div>
              <button
                type="button"
                onClick={() => { setCvFile(null); if (fileRef.current) fileRef.current.value = '' }}
                className="ml-2 shrink-0 text-violet-600 hover:text-red-500 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex items-center justify-center gap-2 rounded-lg border border-dashed border-violet-300 bg-violet-50/50 px-4 py-3 text-sm text-stone-500 hover:border-violet-500 hover:bg-violet-50 hover:text-violet-700 transition-colors"
            >
              <Paperclip className="h-4 w-4" />
              Upload your CV
            </button>
          )}
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.doc,.txt"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) setCvFile(file)
            }}
          />
        </div>

        {/* Cover letter — type or upload */}
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <Label>Cover Letter <span className="text-stone-400 text-xs font-normal">(optional)</span></Label>
            <div className="flex rounded-md overflow-hidden border border-stone-200 text-xs">
              <button
                type="button"
                onClick={() => { setClMode('type'); setClFile(null); if (clRef.current) clRef.current.value = '' }}
                className={`px-2.5 py-1 transition-colors ${clMode === 'type' ? 'bg-violet-600 text-white' : 'bg-white text-stone-500 hover:bg-stone-50'}`}
              >
                Write
              </button>
              <button
                type="button"
                onClick={() => { setClMode('upload'); setCoverLetter('') }}
                className={`px-2.5 py-1 transition-colors border-l border-stone-200 ${clMode === 'upload' ? 'bg-violet-600 text-white' : 'bg-white text-stone-500 hover:bg-stone-50'}`}
              >
                Upload
              </button>
            </div>
          </div>

          {clMode === 'type' ? (
            <Textarea
              id="cover-letter"
              placeholder="Tell us why you're a great fit…"
              value={coverLetter}
              onChange={(e) => setCoverLetter(e.target.value)}
              rows={4}
            />
          ) : clFile ? (
            <div className="flex items-center justify-between rounded-lg border border-violet-200 bg-violet-50 px-3 py-2">
              <div className="flex items-center gap-2 text-sm text-violet-800 truncate">
                <FileText className="h-4 w-4 shrink-0" />
                <span className="truncate">{clFile.name}</span>
              </div>
              <button
                type="button"
                onClick={() => { setClFile(null); if (clRef.current) clRef.current.value = '' }}
                className="ml-2 shrink-0 text-violet-600 hover:text-red-500 transition-colors"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={() => clRef.current?.click()}
              className="flex items-center justify-center gap-2 rounded-lg border border-dashed border-violet-300 bg-violet-50/50 px-4 py-3 text-sm text-stone-500 hover:border-violet-500 hover:bg-violet-50 hover:text-violet-700 transition-colors"
            >
              <FileText className="h-4 w-4" />
              Upload cover letter (PDF, DOCX, TXT)
            </button>
          )}
          <input
            ref={clRef}
            type="file"
            accept=".pdf,.docx,.doc,.txt"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) setClFile(file)
            }}
          />
        </div>

        {error && <p className="text-sm text-red-500">{error}</p>}

        <Button type="submit" disabled={submitting} className="bg-violet-600 hover:bg-violet-700 text-white">
          {submitting ? 'Submitting…' : 'Submit Application'}
        </Button>
      </form>
    </div>
  )
}
