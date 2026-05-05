import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { Briefcase, LogOut, LayoutDashboard } from 'lucide-react'
import { JDChat } from '@/components/jd/JDChat'
import { SessionSidebar } from '@/components/jd/SessionSidebar'
import { DashboardHome } from '@/components/dashboard/DashboardHome'
import { LoginPage } from '@/components/auth/LoginPage'
import { useJDSession } from '@/hooks/useJDSession'
import { getStoredUser, getToken, clearUser, type User } from '@/api/auth'
import { JobBoardPage } from '@/pages/JobBoardPage'
import { JobDetailPage } from '@/pages/JobDetailPage'

type Role = 'hr' | 'hm'
type View = 'dashboard' | 'jd-chat'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/jobs" element={<JobBoardPage />} />
        <Route path="/jobs/:sessionId" element={<JobDetailPage />} />
        <Route path="/*" element={<HRApp />} />
      </Routes>
    </BrowserRouter>
  )
}

function HRApp() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    const stored = getStoredUser()
    if (!stored) { setChecking(false); return }

    fetch('/api/auth/me', { headers: { Authorization: `Bearer ${getToken()}` } })
      .then(r => { if (!r.ok) throw new Error('invalid'); return r.json() })
      .then(() => setUser(stored))
      .catch(() => clearUser())
      .finally(() => setChecking(false))
  }, [])

  if (checking) return null
  if (!user) return <LoginPage onLogin={setUser} />
  return <AuthenticatedApp user={user} onLogout={() => { clearUser(); setUser(null) }} />
}

function AuthenticatedApp({ user, onLogout }: { user: User; onLogout: () => void }) {
  const session = useJDSession(user.email, user.role as Role)
  const [view, setView] = useState<View>('dashboard')
  const [sidebarRefresh, setSidebarRefresh] = useState(0)

  // Refresh sidebar whenever a new session is saved
  useEffect(() => {
    if (session.sessionId) setSidebarRefresh(n => n + 1)
  }, [session.sessionId])

  function handleNavigate(destination: string) {
    if (destination === 'job-board') {
      window.open('/jobs', '_blank')
      return
    }
    setView('jd-chat')
  }

  function handleSend(message: string) {
    setView('jd-chat')
    // Small delay so the chat view is mounted before the message fires
    setTimeout(() => session.sendMessage(message), 50)
  }

  function goToDashboard() {
    setView('dashboard')
  }

  return (
    <div className="h-screen bg-violet-50 flex flex-col overflow-hidden">
      {/* Nav */}
      <header className="border-b border-violet-200 bg-white px-6 py-3.5 shrink-0">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={goToDashboard}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600 hover:bg-violet-700 transition-colors"
              title="Dashboard"
            >
              <Briefcase className="h-4 w-4 text-white" />
            </button>
            <span className="font-semibold text-stone-900">InvictusHiring</span>
            {view === 'jd-chat' && (
              <>
                <span className="text-stone-300">|</span>
                <button
                  onClick={goToDashboard}
                  className="flex items-center gap-1 text-sm text-stone-400 hover:text-stone-700 transition-colors"
                >
                  <LayoutDashboard className="h-3.5 w-3.5" />
                  Dashboard
                </button>
                <span className="text-stone-300">/</span>
                <span className="text-sm text-stone-600 font-medium">JD Drafter</span>
              </>
            )}
          </div>
          <div className="flex items-center gap-3 text-sm text-stone-500">
            <a href="/jobs" target="_blank" className="text-xs text-stone-500 hover:text-violet-700 transition-colors">
              Job Board
            </a>
            <span className="rounded-full bg-violet-100 px-3 py-1 text-xs font-medium text-violet-700">
              {user.role === 'hm' ? 'Hiring Manager' : 'HR'}
            </span>
            <span className="text-stone-700">{user.name}</span>
            <button
              onClick={onLogout}
              className="flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-medium text-stone-500 hover:bg-violet-100 hover:text-violet-700 transition-colors"
              title="Sign out"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </button>
          </div>
        </div>
      </header>

      {/* Body */}
      {view === 'dashboard' ? (
        <DashboardHome user={user} onNavigate={handleNavigate} onSend={handleSend} />
      ) : (
        <div className="flex flex-1 overflow-hidden">
          <SessionSidebar
            activeSessionId={session.sessionId}
            onSelect={session.loadSession}
            onNew={session.reset}
            refreshTrigger={sidebarRefresh}
          />
          <main className="flex-1 p-4 overflow-hidden">
            <div className="rounded-2xl border border-violet-200 bg-white shadow-sm overflow-hidden h-full">
              <JDChat session={session} onReset={session.reset} />
            </div>
          </main>
        </div>
      )}
    </div>
  )
}