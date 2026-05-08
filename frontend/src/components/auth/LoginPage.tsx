import { useState } from 'react'
import { LogIn, ArrowLeftIcon, MailIcon, CheckCircleIcon, FileTextIcon, BarChart2Icon, UsersIcon, SendIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { login, storeUser, type User } from '@/api/auth'

function InvictusLogo({ size = 36, className = '' }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" xmlns="frontend/public/tie-box-by-podvoodoo13-brandcrowd.png" className={className}>
      {/* Outer ring */}
      <circle cx="24" cy="24" r="22" stroke="white" strokeWidth="2" strokeOpacity="0.4" />
      {/* Person silhouette — head */}
      <circle cx="24" cy="17" r="6" fill="white" />
      {/* Person silhouette — body arc */}
      <path d="M10 38c0-7.732 6.268-14 14-14s14 6.268 14 14" stroke="white" strokeWidth="2.5" strokeLinecap="round" fill="none" />
      {/* Spark / bolt accent */}
      <path d="M32 10 L28.5 17 L31 17 L27 24 L30.5 24 L26 32" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
    </svg>
  )
}

interface Props {
  onLogin: (user: User) => void
}

const FEATURES = [
  { icon: <FileTextIcon className="h-4 w-4" />, label: 'AI JD Drafter',      desc: 'Draft UK-compliant job descriptions from plain English' },
  { icon: <SendIcon      className="h-4 w-4" />, label: 'Multi-platform Post', desc: 'Publish to LinkedIn, Indeed UK & Google Jobs in one click' },
  { icon: <UsersIcon     className="h-4 w-4" />, label: 'CV Screener',         desc: 'AI scores every applicant 0–100 against the role' },
  { icon: <BarChart2Icon className="h-4 w-4" />, label: 'Hiring Analytics',    desc: 'Ask questions about your data in plain English' },
]

// ── Forgot password view ──────────────────────────────────────────────────────

function ForgotPassword({ onBack }: { onBack: () => void }) {
  const [email, setEmail]     = useState('')
  const [loading, setLoading] = useState(false)
  const [sent, setSent]       = useState(false)
  const [error, setError]     = useState('')

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const res = await fetch('/api/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail ?? 'Request failed')
      }
      setSent(true)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  if (sent) {
    return (
      <div className="text-center space-y-4">
        <div className="flex justify-center">
          <div className="flex h-14 w-14 items-center justify-center rounded-full bg-violet-100">
            <CheckCircleIcon className="h-7 w-7 text-violet-600" />
          </div>
        </div>
        <div>
          <h2 className="text-lg font-semibold text-stone-900">Check your inbox</h2>
          <p className="text-sm text-stone-500 mt-1">
            If <span className="font-medium text-stone-700">{email}</span> is registered,
            a password reset link has been sent.
          </p>
        </div>
        <button onClick={onBack} className="text-sm text-violet-700 hover:underline font-medium">
          Back to sign in
        </button>
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div>
        <button onClick={onBack} className="flex items-center gap-1.5 text-xs text-stone-500 hover:text-stone-700 mb-5 transition-colors">
          <ArrowLeftIcon className="h-3.5 w-3.5" /> Back to sign in
        </button>
        <h2 className="text-xl font-semibold text-stone-900">Reset your password</h2>
        <p className="text-sm text-stone-500 mt-1">
          Enter your email and we'll send you a reset link.
        </p>
      </div>

      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="reset-email">Email address</Label>
          <div className="relative">
            <MailIcon className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-stone-400" />
            <Input
              id="reset-email"
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              className="pl-9"
              required
              autoFocus
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
        )}

        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? 'Sending…' : 'Send reset link'}
        </Button>
      </form>
    </div>
  )
}

// ── Main login view ───────────────────────────────────────────────────────────

export function LoginPage({ onLogin }: Props) {
  const [email, setEmail]         = useState('')
  const [password, setPassword]   = useState('')
  const [error, setError]         = useState('')
  const [loading, setLoading]     = useState(false)
  const [showForgot, setShowForgot] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const user = await login(email, password)
      storeUser(user)
      onLogin(user)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen flex">

      {/* ── Left panel ── */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between bg-gradient-to-br from-violet-700 via-purple-600 to-indigo-500 px-12 py-12 relative overflow-hidden">
        {/* Decorative blobs */}
        <div className="absolute -top-24 -left-24 h-96 w-96 rounded-full bg-white/5" />
        <div className="absolute -bottom-32 -right-20 h-[480px] w-[480px] rounded-full bg-white/5" />
        <div className="absolute top-1/3 right-0 h-48 w-48 rounded-full bg-white/5" />
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 h-64 w-64 rounded-full bg-white/[0.03] blur-2xl" />

        {/* Logo */}
        <div className="relative flex items-center gap-3">
          <InvictusLogo size={38} />
          <span className="text-xl font-semibold text-white tracking-tight">InvictusHiring</span>
        </div>

        {/* Hero copy */}
        <div className="relative space-y-6">
          <div>
            <h1 className="text-4xl font-bold text-white leading-tight tracking-tight">
              Hire smarter,<br />not harder.
            </h1>
            <p className="mt-3 text-purple-200 text-base leading-relaxed max-w-sm">
              AI-powered hiring automation with human-in-the-loop — from job description to published offer.
            </p>
          </div>

          <div className="space-y-3">
            {FEATURES.map(f => (
              <div key={f.label} className="flex items-start gap-3">
                <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white/15 text-white">
                  {f.icon}
                </div>
                <div>
                  <p className="text-sm font-semibold text-white">{f.label}</p>
                  <p className="text-xs text-purple-200 leading-relaxed">{f.desc}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Footer */}
        <p className="relative text-xs text-purple-300">© 2025 InvictusHiring. All rights reserved.</p>
      </div>

      {/* ── Right panel ── */}
      <div className="flex flex-1 flex-col items-center justify-center px-6 py-12 bg-violet-50">
        {/* Mobile logo */}
        <div className="lg:hidden flex items-center gap-2 mb-8">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600">
            <InvictusLogo size={22} />
          </div>
          <span className="text-lg font-semibold text-stone-900">InvictusHiring</span>
        </div>

        <div className="w-full max-w-sm">
          {showForgot ? (
            <ForgotPassword onBack={() => setShowForgot(false)} />
          ) : (
            <div className="space-y-6">
              <div>
                <h2 className="text-2xl font-semibold text-stone-900">Welcome back</h2>
                <p className="text-sm text-stone-500 mt-1">Sign in to your account to continue</p>
              </div>

              <form onSubmit={handleSubmit} className="space-y-4">
                <div className="space-y-1.5">
                  <Label htmlFor="email">Email</Label>
                  <Input
                    id="email"
                    type="email"
                    placeholder="you@company.com"
                    value={email}
                    onChange={e => setEmail(e.target.value)}
                    required
                    autoFocus
                  />
                </div>

                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <Label htmlFor="password">Password</Label>
                    <button
                      type="button"
                      onClick={() => setShowForgot(true)}
                      className="text-xs text-violet-700 hover:underline font-medium"
                    >
                      Forgot password?
                    </button>
                  </div>
                  <Input
                    id="password"
                    type="password"
                    placeholder="••••••••"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    required
                  />
                </div>

                {error && (
                  <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{error}</p>
                )}

                <Button type="submit" className="w-full bg-violet-600 hover:bg-violet-700" disabled={loading}>
                  {loading ? 'Signing in…' : <><LogIn className="h-4 w-4 mr-2" />Sign in</>}
                </Button>
              </form>

              {/* Demo credentials */}
              {/*<div className="rounded-xl bg-white/80 border border- -200 p-4 space-y-2">
                <p className="text-[10px] font-semibold text-stone-400 uppercase tracking-wider">Demo accounts</p>
                <div className="space-y-2">
                  {[
                    { email: 'hr@invictushiring.co', role: 'HR' },
                    { email: 'hm@invictushiring.co', role: 'Hiring Manager' },
                  ].map(a => (
                    <button
                      key={a.email}
                      type="button"
                      onClick={() => { setEmail(a.email); setPassword('password') }}
                      className="w-full flex items-center justify-between rounded-lg px-3 py-2 text-xs bg-stone-50 hover:bg-violet-50 hover:border-violet-200 border border-transparent transition-colors"
                    >
                      <span className="font-mono text-stone-700">{a.email}</span>
                      <span className="text-stone-400 font-sans">{a.role}</span>
                    </button>
                  ))}
                </div>
                <p className="text-[10px] text-stone-400">Click an account to auto-fill · password: <span className="font-mono">password</span></p>
              </div>*/}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}