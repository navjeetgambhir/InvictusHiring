import { FileTextIcon, BarChart2Icon, UsersIcon, BriefcaseIcon, ArrowRightIcon, SendIcon, SearchIcon, CalendarIcon } from 'lucide-react'
import type { User } from '@/api/auth'
import { QualityPanel } from './QualityPanel'

const CARDS = [
  { id: 'jd-draft',   icon: <FileTextIcon  className="h-5 w-5" />, title: 'JD Drafter',          description: 'Draft a UK-compliant job description from plain English.',          iconBg: 'bg-violet-50 text-violet-700',  border: 'hover:border-violet-400' },
  { id: 'publish',    icon: <SendIcon       className="h-5 w-5" />, title: 'Job Publisher',        description: 'Publish an approved JD to LinkedIn, Indeed & Google Jobs.',          iconBg: 'bg-blue-50 text-blue-700',      border: 'hover:border-blue-400'   },
  { id: 'cv-screen',  icon: <UsersIcon      className="h-5 w-5" />, title: 'CV Screener',          description: 'AI scores candidates 0–100 against job requirements.',                iconBg: 'bg-purple-50 text-purple-700',  border: 'hover:border-purple-400' },
  { id: 'interviews', icon: <CalendarIcon   className="h-5 w-5" />, title: 'Interview Scheduler',  description: 'Shortlist candidates and generate AI-drafted interview invitations.',  iconBg: 'bg-amber-50 text-amber-700',    border: 'hover:border-amber-400'  },
  { id: 'analytics',  icon: <BarChart2Icon  className="h-5 w-5" />, title: 'Analytics',            description: 'Ask questions about hiring data in plain English.',                   iconBg: 'bg-rose-50 text-rose-700',      border: 'hover:border-rose-400'   },
  { id: 'job-board',  icon: <SearchIcon     className="h-5 w-5" />, title: 'Job Board',            description: 'Public board where candidates browse and apply to roles.',            iconBg: 'bg-green-50 text-green-700',    border: 'hover:border-green-400'  },
  { id: 'sessions',   icon: <BriefcaseIcon  className="h-5 w-5" />, title: 'Session History',      description: 'Resume any previous drafting session with full chat history.',        iconBg: 'bg-violet-100 text-violet-600', border: 'hover:border-violet-400' },
]

interface Props {
  user: User
  onNavigate: (destination: 'jd-draft' | 'analytics' | 'publish' | 'cv-screen' | 'job-board' | 'sessions' | 'interviews') => void
  onSend: (message: string) => void
}

export function DashboardHome({ user, onNavigate }: Props) {
  const hour = new Date().getHours()
  const greeting = hour < 12 ? 'Good morning' : hour < 17 ? 'Good afternoon' : 'Good evening'

  return (
    <div className="flex-1 overflow-y-auto bg-violet-50">
      <div className="max-w-4xl mx-auto px-6 py-10">

        {/* Greeting */}
        <div className="mb-6">
          <h1 className="text-2xl font-semibold text-stone-900 tracking-tight">
            {greeting}, {user.name.split(' ')[0]}
          </h1>
          <p className="text-sm text-stone-500 mt-1">What would you like to do today?</p>
        </div>

        {/* Cards */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          {CARDS.map(card => (
            <button
              key={card.id}
              onClick={() => onNavigate(card.id as Parameters<Props['onNavigate']>[0])}
              className={`group text-left bg-white rounded-xl border border-violet-200 ${card.border} p-4 flex flex-col gap-3 transition-all duration-150 shadow-sm hover:shadow-md`}
            >
              <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ${card.iconBg}`}>
                {card.icon}
              </div>
              <div className="min-w-0">
                <div className="flex items-center justify-between gap-1 mb-1">
                  <h2 className="text-sm font-semibold text-stone-900 leading-snug">{card.title}</h2>
                  <ArrowRightIcon className="h-3.5 w-3.5 text-stone-300 group-hover:text-violet-600 group-hover:translate-x-0.5 transition-all shrink-0" />
                </div>
                <p className="text-xs text-stone-500 leading-relaxed">{card.description}</p>
              </div>
            </button>
          ))}
        </div>

        {/* Agent quality panel */}
        <div className="mt-6">
          <QualityPanel />
        </div>

      </div>
    </div>
  )
}