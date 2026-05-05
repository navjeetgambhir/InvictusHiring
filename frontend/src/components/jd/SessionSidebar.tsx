import { useEffect, useState, useRef } from 'react'
import {
  PlusIcon, FolderPlusIcon, FolderIcon, FolderOpenIcon,
  MessageSquareIcon, ChevronRightIcon, MoreHorizontalIcon,
  PencilIcon, TrashIcon, FolderInputIcon, CheckIcon,
} from 'lucide-react'
import { fetchSessions, type SessionSummary } from '@/api/jd'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Folder {
  id: string
  name: string
  sessionIds: string[]
  collapsed: boolean
}

const FOLDERS_KEY = 'invictus_folders'

function loadFolders(): Folder[] {
  try { return JSON.parse(localStorage.getItem(FOLDERS_KEY) || '[]') } catch { return [] }
}
function saveFolders(folders: Folder[]) {
  localStorage.setItem(FOLDERS_KEY, JSON.stringify(folders))
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const STATUS_DOT: Record<string, string> = {
  drafting:         'bg-yellow-400',
  pending_approval: 'bg-blue-400',
  approved:         'bg-green-400',
  publishing:       'bg-purple-400',
  published:        'bg-emerald-400',
}

function relativeDate(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins  = Math.floor(diff / 60_000)
  const hours = Math.floor(diff / 3_600_000)
  const days  = Math.floor(diff / 86_400_000)
  if (mins  < 1)  return 'just now'
  if (mins  < 60) return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  if (days  < 7)  return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
}

// ── Session row ───────────────────────────────────────────────────────────────

function SessionRow({
  session, active, folders, onSelect, onMoveToFolder,
}: {
  session: SessionSummary
  active: boolean
  folders: Folder[]
  onSelect: () => void
  onMoveToFolder: (folderId: string | null) => void
}) {
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const close = (e: MouseEvent) => { if (!menuRef.current?.contains(e.target as Node)) setMenuOpen(false) }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [menuOpen])

  const currentFolder = folders.find(f => f.sessionIds.includes(session.session_id))

  return (
    <div
      className={`group relative flex items-start gap-2.5 px-3 py-2.5 cursor-pointer transition-colors border-l-2 ${
        active ? 'bg-violet-50 border-violet-500' : 'hover:bg-violet-50/50 border-transparent'
      }`}
      onClick={onSelect}
    >
      {/* Status dot */}
      <div className="mt-1 shrink-0">
        <span className={`block h-2 w-2 rounded-full ${STATUS_DOT[session.status] ?? 'bg-stone-300'}`} />
      </div>

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-stone-800 truncate leading-snug">
          {session.title || 'Untitled'}
        </p>
        {session.last_message_preview && (
          <p className="text-xs text-stone-400 truncate mt-0.5 leading-relaxed">
            {session.last_message_preview}
          </p>
        )}
        <p className="text-[10px] text-stone-400 mt-1">{relativeDate(session.created_at)}</p>
      </div>

      {/* Overflow menu */}
      <div
        className="shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
        onClick={e => { e.stopPropagation(); setMenuOpen(v => !v) }}
      >
        <MoreHorizontalIcon className="h-4 w-4 text-stone-400 hover:text-stone-600" />
      </div>

      {menuOpen && (
        <div
          ref={menuRef}
          className="absolute right-2 top-8 z-50 w-44 rounded-xl bg-white border border-stone-200 shadow-lg py-1 text-xs"
          onClick={e => e.stopPropagation()}
        >
          <p className="px-3 py-1.5 text-[10px] font-semibold uppercase tracking-wider text-stone-400">Move to folder</p>
          {folders.map(f => (
            <button
              key={f.id}
              onClick={() => { onMoveToFolder(f.id); setMenuOpen(false) }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-stone-50 text-stone-700"
            >
              <FolderIcon className="h-3.5 w-3.5 text-stone-400" />
              <span className="truncate">{f.name}</span>
              {currentFolder?.id === f.id && <CheckIcon className="h-3 w-3 text-violet-600 ml-auto" />}
            </button>
          ))}
          {currentFolder && (
            <button
              onClick={() => { onMoveToFolder(null); setMenuOpen(false) }}
              className="w-full flex items-center gap-2 px-3 py-1.5 hover:bg-stone-50 text-stone-500"
            >
              <FolderInputIcon className="h-3.5 w-3.5" />
              Remove from folder
            </button>
          )}
          {folders.length === 0 && (
            <p className="px-3 py-1.5 text-stone-400 italic">No folders yet</p>
          )}
        </div>
      )}
    </div>
  )
}

// ── Folder section ────────────────────────────────────────────────────────────

function FolderSection({
  folder, sessions, activeSessionId, onSelect, onMoveToFolder,
  onRename, onDelete, onToggle, folders,
}: {
  folder: Folder
  sessions: SessionSummary[]
  activeSessionId: string | null
  onSelect: (id: string) => void
  onMoveToFolder: (sessionId: string, folderId: string | null) => void
  onRename: (id: string, name: string) => void
  onDelete: (id: string) => void
  onToggle: (id: string) => void
  folders: Folder[]
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(folder.name)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { if (editing) inputRef.current?.focus() }, [editing])

  function commitRename() {
    if (draft.trim()) onRename(folder.id, draft.trim())
    setEditing(false)
  }

  const folderSessions = sessions.filter(s => folder.sessionIds.includes(s.session_id))

  return (
    <div>
      {/* Folder header */}
      <div className="group flex items-center gap-1.5 px-3 py-2 hover:bg-stone-50 cursor-pointer"
        onClick={() => !editing && onToggle(folder.id)}
      >
        <ChevronRightIcon className={`h-3 w-3 text-stone-400 transition-transform shrink-0 ${folder.collapsed ? '' : 'rotate-90'}`} />
        {folder.collapsed
          ? <FolderIcon className="h-4 w-4 text-amber-500 shrink-0" />
          : <FolderOpenIcon className="h-4 w-4 text-amber-500 shrink-0" />
        }
        {editing ? (
          <input
            ref={inputRef}
            value={draft}
            onChange={e => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={e => { if (e.key === 'Enter') commitRename(); if (e.key === 'Escape') setEditing(false) }}
            className="flex-1 text-sm font-medium text-stone-800 bg-transparent outline-none border-b border-violet-500"
            onClick={e => e.stopPropagation()}
          />
        ) : (
          <span className="flex-1 text-sm font-medium text-stone-700 truncate">{folder.name}</span>
        )}
        <span className="text-[10px] text-stone-400 shrink-0">{folderSessions.length}</span>
        <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity ml-1"
          onClick={e => e.stopPropagation()}
        >
          <button onClick={() => setEditing(true)} className="p-0.5 rounded hover:bg-stone-200">
            <PencilIcon className="h-3 w-3 text-stone-400" />
          </button>
          <button onClick={() => onDelete(folder.id)} className="p-0.5 rounded hover:bg-red-50">
            <TrashIcon className="h-3 w-3 text-red-400" />
          </button>
        </div>
      </div>

      {/* Sessions inside folder */}
      {!folder.collapsed && (
        <div className="pl-4 border-l border-stone-100 ml-4">
          {folderSessions.length === 0 && (
            <p className="px-3 py-2 text-xs text-stone-400 italic">Empty folder</p>
          )}
          {folderSessions.map(s => (
            <SessionRow
              key={s.session_id}
              session={s}
              active={s.session_id === activeSessionId}
              folders={folders}
              onSelect={() => onSelect(s.session_id)}
              onMoveToFolder={fId => onMoveToFolder(s.session_id, fId)}
            />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Main sidebar ──────────────────────────────────────────────────────────────

interface Props {
  activeSessionId: string | null
  onSelect: (sessionId: string) => void
  onNew: () => void
  refreshTrigger?: number
}

export function SessionSidebar({ activeSessionId, onSelect, onNew, refreshTrigger }: Props) {
  const [sessions, setSessions] = useState<SessionSummary[]>([])
  const [loading, setLoading]   = useState(true)
  const [folders, setFolders]   = useState<Folder[]>(loadFolders)

  useEffect(() => {
    setLoading(true)
    fetchSessions()
      .then(setSessions)
      .catch(() => setSessions([]))
      .finally(() => setLoading(false))
  }, [refreshTrigger])

  function persist(next: Folder[]) { setFolders(next); saveFolders(next) }

  function addFolder() {
    const name = `Folder ${folders.length + 1}`
    persist([...folders, { id: crypto.randomUUID(), name, sessionIds: [], collapsed: false }])
  }

  function renameFolder(id: string, name: string) {
    persist(folders.map(f => f.id === id ? { ...f, name } : f))
  }

  function deleteFolder(id: string) {
    persist(folders.filter(f => f.id !== id))
  }

  function toggleFolder(id: string) {
    persist(folders.map(f => f.id === id ? { ...f, collapsed: !f.collapsed } : f))
  }

  function moveToFolder(sessionId: string, folderId: string | null) {
    persist(folders.map(f => ({
      ...f,
      sessionIds: folderId === f.id
        ? [...new Set([...f.sessionIds, sessionId])]
        : f.sessionIds.filter(id => id !== sessionId),
    })))
  }

  const folderSessionIds = new Set(folders.flatMap(f => f.sessionIds))
  const ungrouped = sessions.filter(s => !folderSessionIds.has(s.session_id))

  return (
    <aside className="w-60 shrink-0 flex flex-col bg-white border-r border-violet-200 h-full">
      {/* Header */}
      <div className="px-3 py-3 border-b border-violet-100 flex items-center justify-between gap-1">
        <div className="flex items-center gap-1.5">
          <MessageSquareIcon className="h-4 w-4 text-stone-400" />
          <span className="text-sm font-semibold text-stone-700">Chats</span>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={addFolder} title="New folder"
            className="p-1 rounded-lg text-stone-400 hover:bg-violet-100 hover:text-amber-600 transition-colors">
            <FolderPlusIcon className="h-4 w-4" />
          </button>
          <button onClick={onNew} title="New chat"
            className="p-1 rounded-lg text-stone-400 hover:bg-violet-100 hover:text-violet-600 transition-colors">
            <PlusIcon className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* List */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="px-4 py-6 text-xs text-stone-400 text-center">Loading…</div>
        )}

        {!loading && sessions.length === 0 && (
          <div className="px-4 py-8 text-center">
            <MessageSquareIcon className="mx-auto h-6 w-6 text-stone-200 mb-2" />
            <p className="text-xs text-stone-400">No chats yet.</p>
            <p className="text-xs text-stone-400">Describe a role to start.</p>
          </div>
        )}

        {/* Folders */}
        {!loading && folders.map(folder => (
          <FolderSection
            key={folder.id}
            folder={folder}
            sessions={sessions}
            activeSessionId={activeSessionId}
            folders={folders}
            onSelect={onSelect}
            onMoveToFolder={moveToFolder}
            onRename={renameFolder}
            onDelete={deleteFolder}
            onToggle={toggleFolder}
          />
        ))}

        {/* Ungrouped sessions */}
        {!loading && ungrouped.length > 0 && (
          <div>
            {folders.length > 0 && (
              <p className="px-3 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-wider text-stone-400">
                Other chats
              </p>
            )}
            {ungrouped.map(s => (
              <SessionRow
                key={s.session_id}
                session={s}
                active={s.session_id === activeSessionId}
                folders={folders}
                onSelect={() => onSelect(s.session_id)}
                onMoveToFolder={fId => moveToFolder(s.session_id, fId)}
              />
            ))}
          </div>
        )}
      </div>
    </aside>
  )
}