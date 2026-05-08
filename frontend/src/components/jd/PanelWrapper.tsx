import { useState } from 'react'
import { ChevronDown, Maximize2, X } from 'lucide-react'

export type PanelState = 'normal' | 'minimized' | 'maximized'

interface Props {
  icon: React.ReactNode
  title: string
  meta?: React.ReactNode
  borderColor: string
  headerBg: string
  headerHover: string
  children: React.ReactNode
}

export function PanelWrapper({ icon, title, meta, borderColor, headerBg, headerHover, children }: Props) {
  const [state, setState] = useState<PanelState>('normal')

  const isMinimized = state === 'minimized'

  if (state === 'maximized') {
    return (
      <div className="fixed inset-0 z-50 bg-white flex flex-col">
        <div className={`border-b ${borderColor} shrink-0`}>
          <div className={`flex items-center gap-2 px-4 py-3 ${headerBg}`}>
            <span className="shrink-0">{icon}</span>
            <span className="text-sm font-semibold text-stone-800">{title}</span>
            {meta && <span className="text-xs text-stone-400">{meta}</span>}
            <button
              onClick={() => setState('normal')}
              title="Exit fullscreen"
              className="ml-auto p-1.5 rounded-lg hover:bg-stone-100 text-stone-400 hover:text-stone-600 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-6">
          {children}
        </div>
      </div>
    )
  }

  return (
    <div className={`flex flex-col rounded-xl border ${borderColor} bg-white shadow-sm overflow-hidden`}>
      {/* div not button — avoids invalid nested <button><button> HTML */}
      <div
        role="button"
        tabIndex={0}
        onClick={() => setState(isMinimized ? 'normal' : 'minimized')}
        onKeyDown={e => e.key === 'Enter' || e.key === ' ' ? setState(isMinimized ? 'normal' : 'minimized') : undefined}
        className={`flex items-center gap-2 px-4 py-3 cursor-pointer select-none ${headerBg} ${headerHover} transition-colors`}
      >
        <span className="shrink-0">{icon}</span>
        <span className="text-sm font-semibold text-stone-800">{title}</span>
        {meta && <span className="text-xs text-stone-400">{meta}</span>}

        <div className="ml-auto flex items-center gap-1">
          {!isMinimized && (
            <button
              onClick={e => { e.stopPropagation(); setState('maximized') }}
              title="Expand"
              className={`p-1.5 rounded-lg ${headerHover} text-stone-400 hover:text-stone-600 transition-colors`}
            >
              <Maximize2 className="h-3.5 w-3.5" />
            </button>
          )}
          <ChevronDown
            className={`h-4 w-4 text-stone-400 transition-transform duration-200 ${isMinimized ? '-rotate-90' : ''}`}
          />
        </div>
      </div>

      {!isMinimized && (
        <div className={`border-t ${borderColor} px-4 pb-4 pt-3`}>
          {children}
        </div>
      )}
    </div>
  )
}