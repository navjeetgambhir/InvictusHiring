import { useEffect, useState } from 'react'
import { ActivityIcon, CheckCircleIcon, AlertCircleIcon, ZapIcon, BarChart2Icon } from 'lucide-react'
import { fetchQualityMetrics, type QualityMetrics } from '@/api/telemetry'
import { cn } from '@/lib/utils'

function StatCard({ label, value, sub, accent }: { label: string; value: string | number; sub?: string; accent?: string }) {
  return (
    <div className="bg-white rounded-xl border border-violet-100 px-4 py-3 flex flex-col gap-0.5">
      <span className={cn('text-xl font-bold', accent ?? 'text-stone-800')}>{value}</span>
      <span className="text-xs font-medium text-stone-600">{label}</span>
      {sub && <span className="text-[10px] text-stone-400">{sub}</span>}
    </div>
  )
}

function BarRow({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-stone-600 w-28 shrink-0 truncate capitalize">{label.replace(/_/g, ' ')}</span>
      <div className="flex-1 h-1.5 rounded-full bg-stone-100 overflow-hidden">
        <div className={cn('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-medium text-stone-700 w-8 text-right">{value}</span>
    </div>
  )
}

export function QualityPanel() {
  const [data, setData] = useState<QualityMetrics | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchQualityMetrics(30).then(d => { setData(d); setLoading(false) })
  }, [])

  if (loading) return (
    <div className="rounded-2xl border border-violet-200 bg-white shadow-sm p-5 animate-pulse">
      <div className="h-4 w-40 bg-violet-100 rounded mb-4" />
      <div className="grid grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => <div key={i} className="h-16 rounded-xl bg-violet-50" />)}
      </div>
    </div>
  )

  if (!data) return null

  const totalRuns = data.errors.reduce((s, e) => s + e.total, 0)
  const totalErrors = data.errors.reduce((s, e) => s + e.errors, 0)
  const errorRate = totalRuns > 0 ? ((totalErrors / totalRuns) * 100).toFixed(1) : '0'
  const avgConfidence = data.routing.length > 0
    ? (data.routing.reduce((s, r) => s + r.avg_confidence * r.count, 0) /
       data.routing.reduce((s, r) => s + r.count, 0) * 100).toFixed(0)
    : '—'

  const sqlPassRate = data.analytics.total_queries > 0
    ? ((data.analytics.passed / data.analytics.total_queries) * 100).toFixed(0)
    : '—'

  const maxRouteCount = Math.max(...data.routing.map(r => r.count), 1)
  const maxScreenCount = Math.max(...data.screening.by_recommendation.map(r => r.count), 1)

  const routeColors: Record<string, string> = {
    jd_draft: 'bg-violet-400', jd_chat: 'bg-violet-300', jd_revise: 'bg-amber-400',
    approve: 'bg-emerald-400', publish: 'bg-blue-400', analytics: 'bg-rose-400',
    ml_predict: 'bg-purple-400', other: 'bg-stone-300',
  }
  const recColors: Record<string, string> = {
    strong_match: 'bg-emerald-500', good_match: 'bg-emerald-300',
    partial_match: 'bg-amber-400', poor_match: 'bg-rose-400',
  }

  return (
    <div className="rounded-2xl border border-violet-200 bg-white shadow-sm p-5 space-y-5">
      <div className="flex items-center gap-2">
        <ActivityIcon className="h-4 w-4 text-violet-600" />
        <h2 className="text-sm font-semibold text-stone-800">Agent Quality — last {data.period_days} days</h2>
      </div>

      {/* Top-line stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <StatCard label="Total agent runs" value={totalRuns.toLocaleString()} />
        <StatCard
          label="Error rate"
          value={`${errorRate}%`}
          sub={`${totalErrors} errors`}
          accent={parseFloat(errorRate) > 5 ? 'text-rose-600' : 'text-emerald-600'}
        />
        <StatCard
          label="Routing confidence"
          value={`${avgConfidence}%`}
          sub="avg across all intents"
          accent={parseFloat(avgConfidence) < 70 ? 'text-amber-600' : 'text-stone-800'}
        />
        <StatCard
          label="SQL pass rate"
          value={`${sqlPassRate}%`}
          sub={`${data.analytics.total_queries} queries`}
          accent={parseFloat(sqlPassRate) < 80 ? 'text-amber-600' : 'text-stone-800'}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
        {/* Routing intent distribution */}
        {data.routing.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider mb-2 flex items-center gap-1">
              <BarChart2Icon className="h-3 w-3" /> Routing intents
            </p>
            <div className="space-y-1.5">
              {data.routing.map(r => (
                <BarRow
                  key={r.intent}
                  label={r.intent}
                  value={r.count}
                  max={maxRouteCount}
                  color={routeColors[r.intent] ?? 'bg-stone-400'}
                />
              ))}
            </div>
          </div>
        )}

        {/* Screening recommendations */}
        {data.screening.by_recommendation.length > 0 && (
          <div>
            <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider mb-2 flex items-center gap-1">
              <CheckCircleIcon className="h-3 w-3" /> CV screening outcomes
            </p>
            <div className="space-y-1.5">
              {data.screening.by_recommendation.map(r => (
                <BarRow
                  key={r.recommendation}
                  label={r.recommendation}
                  value={r.count}
                  max={maxScreenCount}
                  color={recColors[r.recommendation] ?? 'bg-stone-400'}
                />
              ))}
            </div>
            {data.screening.score_buckets.length > 0 && (
              <div className="mt-3 flex gap-1.5 flex-wrap">
                {data.screening.score_buckets.map(b => (
                  <span key={b.bucket} className="text-[10px] px-2 py-0.5 rounded-full bg-stone-100 text-stone-600">
                    {b.bucket}: <strong>{b.count}</strong>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Latency + error per agent */}
        <div>
          <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider mb-2 flex items-center gap-1">
            <ZapIcon className="h-3 w-3" /> Latency &amp; errors
          </p>
          <div className="space-y-1.5">
            {data.errors.map(e => {
              const latencyRow = data.latency.find(l => l.agent_name === e.agent_name)
              const isHighError = e.error_rate_pct > 5
              return (
                <div key={e.agent_name} className="flex items-center justify-between gap-2">
                  <span className="text-xs text-stone-600 truncate flex-1">{e.agent_name.replace(/_/g, ' ')}</span>
                  {latencyRow && (
                    <span className="text-[10px] text-stone-400">{latencyRow.avg_ms}ms</span>
                  )}
                  <span className={cn(
                    'text-[10px] font-medium px-1.5 py-0.5 rounded-full',
                    isHighError ? 'bg-rose-100 text-rose-600' : 'bg-emerald-100 text-emerald-700'
                  )}>
                    {e.error_rate_pct ?? 0}% err
                  </span>
                </div>
              )
            })}
          </div>

          {/* Drafting efficiency */}
          {data.drafting.avg_versions_to_approve != null && (
            <div className="mt-3 pt-3 border-t border-stone-100 space-y-1">
              <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider">
                JD draft efficiency
              </p>
              <div className="flex items-center justify-between">
                <span className="text-xs text-stone-600">Avg revisions to approve</span>
                <span className={cn(
                  'text-xs font-semibold',
                  data.drafting.avg_versions_to_approve > 2 ? 'text-amber-600' : 'text-emerald-600'
                )}>
                  {data.drafting.avg_versions_to_approve ?? '—'}
                </span>
              </div>
              {data.drafting.chat_block_stats?.total > 0 && (
                <div className="flex items-center justify-between">
                  <span className="text-xs text-stone-600">Off-topic blocks</span>
                  <span className="text-xs font-semibold text-stone-700">
                    {data.drafting.chat_block_stats.blocked} / {data.drafting.chat_block_stats.total}
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {totalRuns === 0 && (
        <div className="flex items-center gap-2 text-xs text-stone-400 pt-1">
          <AlertCircleIcon className="h-3.5 w-3.5 shrink-0" />
          No agent runs recorded yet — metrics will appear after the platform is used.
        </div>
      )}
    </div>
  )
}
