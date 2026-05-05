import { useNavigate } from 'react-router-dom'
import { Briefcase } from 'lucide-react'

interface Props {
  children: React.ReactNode
  maxWidth?: 'max-w-4xl' | 'max-w-5xl'
}

export function PageShell({ children, maxWidth = 'max-w-5xl' }: Props) {
  const navigate = useNavigate()

  return (
    <div className="min-h-screen bg-violet-50">
      <header className="border-b border-violet-200 bg-white px-6 py-4">
        <div className={`${maxWidth} mx-auto flex items-center`}>
          <button
            onClick={() => navigate('/jobs')}
            className="flex items-center gap-3 hover:opacity-80 transition-opacity"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600">
              <Briefcase className="h-4 w-4 text-white" />
            </div>
            <span className="font-semibold text-stone-900">InvictusHiring</span>
          </button>
        </div>
      </header>
      <main className={`${maxWidth} mx-auto px-6 py-8`}>{children}</main>
    </div>
  )
}