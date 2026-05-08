import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Briefcase, MapPin, DollarSign, Building2, Search, ArrowRight, Clock, Users, ChevronLeft, ChevronRight } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { fetchJobs, type JobListing } from '@/api/candidates'

const PAGE_SIZE = 10

export function JobBoardPage() {
  const [jobs, setJobs] = useState<JobListing[]>([])
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const navigate = useNavigate()

  useEffect(() => {
    setLoading(true)
    setError(null)
    fetchJobs(page, PAGE_SIZE)
      .then((data) => {
        setJobs(data.jobs)
        setTotal(data.total)
        setTotalPages(data.total_pages)
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false))
  }, [page])

  // Reset to page 1 when search changes
  useEffect(() => {
    setPage(1)
  }, [search])

  const filtered = search
    ? jobs.filter((j) => {
        const q = search.toLowerCase()
        return (
          j.title.toLowerCase().includes(q) ||
          j.department.toLowerCase().includes(q) ||
          j.location.toLowerCase().includes(q)
        )
      })
    : jobs

  return (
    <div className="min-h-screen bg-violet-50">
      <header className="border-b border-violet-200 bg-white px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600">
            <Briefcase className="h-4 w-4 text-white" />
          </div>
          <span className="font-semibold text-stone-900">InvictusHiring</span>
          <span className="text-stone-300">|</span>
          <span className="text-sm text-stone-500">Open Roles</span>
        </div>
      </header>

      <div className="bg-white border-b border-violet-200 py-10 px-6">
        <div className="max-w-4xl mx-auto">
          <h1 className="text-3xl font-bold text-stone-900 mb-2">Find Your Next Role</h1>
          <p className="text-stone-500 mb-6">Browse open positions and apply directly.</p>
          <div className="relative max-w-lg">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
            <Input
              placeholder="Search by title, department, or location…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="pl-9"
            />
          </div>
        </div>
      </div>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {loading && <div className="text-center text-stone-400 py-16">Loading open positions…</div>}
        {error && <div className="text-center text-red-500 py-16">{error}</div>}
        {!loading && !error && filtered.length === 0 && (
          <div className="text-center text-stone-400 py-16">
            {search ? 'No roles match your search.' : 'No open positions right now. Check back soon.'}
          </div>
        )}

        <div className="flex flex-col gap-4">
          {filtered.map((job) => (
            <JobCard key={job.session_id} job={job} onClick={() => navigate(`/jobs/${job.session_id}`)} />
          ))}
        </div>

        {!loading && !error && totalPages > 1 && (
          <div className="flex items-center justify-between mt-8 pt-6 border-t border-violet-100">
            <p className="text-sm text-stone-400">
              Showing {(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, total)} of {total} role{total !== 1 ? 's' : ''}
            </p>
            <div className="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page === 1}
                className="h-8 w-8 p-0"
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>

              {Array.from({ length: totalPages }, (_, i) => i + 1)
                .filter((p) => p === 1 || p === totalPages || Math.abs(p - page) <= 1)
                .reduce<(number | '…')[]>((acc, p, idx, arr) => {
                  if (idx > 0 && p - (arr[idx - 1] as number) > 1) acc.push('…')
                  acc.push(p)
                  return acc
                }, [])
                .map((p, idx) =>
                  p === '…' ? (
                    <span key={`ellipsis-${idx}`} className="px-1 text-stone-400 text-sm">…</span>
                  ) : (
                    <Button
                      key={p}
                      variant={p === page ? 'default' : 'outline'}
                      size="sm"
                      onClick={() => setPage(p as number)}
                      className="h-8 w-8 p-0 text-xs"
                    >
                      {p}
                    </Button>
                  )
                )}

              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="h-8 w-8 p-0"
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function JobCard({ job, onClick }: { job: JobListing; onClick: () => void }) {
  const postedDate = new Date(job.posted_at).toLocaleDateString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
  })

  const expiryLabel = job.expires_at
    ? new Date(job.expires_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
    : null

  const spotsLeft = job.max_applications != null
    ? Math.max(0, job.max_applications - job.application_count)
    : null

  return (
    <button
      onClick={onClick}
      className="w-full text-left rounded-xl border border-violet-200 bg-white p-5 shadow-sm hover:border-violet-400 hover:shadow-md transition-all group"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h2 className="text-lg font-semibold text-stone-900 group-hover:text-violet-700 transition-colors truncate">
              {job.title}
            </h2>
            <Badge variant="secondary" className="shrink-0 text-xs">{job.department}</Badge>
          </div>

          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-stone-500 mb-3">
            <span className="flex items-center gap-1 max-w-[200px]">
              <Building2 className="h-3.5 w-3.5 shrink-0" />
              <span className="truncate">{job.company_description}</span>
            </span>
            <span className="flex items-center gap-1">
              <MapPin className="h-3.5 w-3.5" />
              {job.location}
            </span>
            {job.salary_band && (
              <span className="flex items-center gap-1">
                <DollarSign className="h-3.5 w-3.5" />
                {job.salary_band}
              </span>
            )}
          </div>

          {job.required_skills.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {job.required_skills.slice(0, 5).map((skill) => (
                <span key={skill} className="rounded-full bg-violet-50 px-2.5 py-0.5 text-xs font-medium text-violet-700">
                  {skill}
                </span>
              ))}
              {job.required_skills.length > 5 && (
                <span className="rounded-full bg-stone-100 px-2.5 py-0.5 text-xs text-stone-500">
                  +{job.required_skills.length - 5} more
                </span>
              )}
            </div>
          )}
        </div>

        <div className="flex flex-col items-end gap-2 shrink-0">
          <span className="text-xs text-stone-400">{postedDate}</span>
          {expiryLabel && (
            <span className="flex items-center gap-1 text-[11px] text-amber-600 bg-amber-50 border border-amber-200 rounded-full px-2 py-0.5">
              <Clock className="h-3 w-3" />
              Closes {expiryLabel}
            </span>
          )}
          {spotsLeft !== null && (
            <span className={`flex items-center gap-1 text-[11px] rounded-full px-2 py-0.5 border ${spotsLeft <= 5 ? 'text-red-600 bg-red-50 border-red-200' : 'text-stone-500 bg-stone-50 border-stone-200'}`}>
              <Users className="h-3 w-3" />
              {spotsLeft} spot{spotsLeft !== 1 ? 's' : ''} left
            </span>
          )}
          <ArrowRight className="h-4 w-4 text-stone-300 group-hover:text-violet-500 group-hover:translate-x-0.5 transition-all" />
        </div>
      </div>
    </button>
  )
}