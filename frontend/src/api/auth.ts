const BASE = '/api/auth'

export interface User {
  email: string
  name: string
  role: 'hr' | 'hm'
}

interface LoginResponse {
  access_token: string
  token_type: string
  email: string
  name: string
  role: 'hr' | 'hm'
}

const USER_KEY  = 'invictushiring_user'
const TOKEN_KEY = 'invictushiring_token'

export async function login(email: string, password: string): Promise<User> {
  const res = await fetch(`${BASE}/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail ?? 'Login failed')
  }
  const data: LoginResponse = await res.json()
  const user: User = { email: data.email, name: data.name, role: data.role }
  storeUser(user)
  storeToken(data.access_token)
  return user
}

export function getStoredUser(): User | null {
  try {
    const raw = localStorage.getItem(USER_KEY)
    return raw ? (JSON.parse(raw) as User) : null
  } catch {
    return null
  }
}

export function storeUser(user: User): void {
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token)
}

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function clearUser(): void {
  localStorage.removeItem(USER_KEY)
  localStorage.removeItem(TOKEN_KEY)
}

function authHeaders(): Record<string, string> {
  const token = getToken()
  const h: Record<string, string> = { 'Content-Type': 'application/json' }
  if (token) h['Authorization'] = `Bearer ${token}`
  return h
}

export async function saveActiveSession(sessionId: string): Promise<void> {
  await fetch(`${BASE}/active-session`, {
    method: 'PUT',
    headers: authHeaders(),
    body: JSON.stringify({ session_id: sessionId }),
  }).catch(() => {})
}

export async function loadActiveSession(): Promise<string | null> {
  try {
    const res = await fetch(`${BASE}/active-session`, { headers: authHeaders() })
    if (!res.ok) return null
    const data = await res.json()
    return data.session_id ?? null
  } catch {
    return null
  }
}

export async function clearActiveSession(): Promise<void> {
  await fetch(`${BASE}/active-session`, {
    method: 'DELETE',
    headers: authHeaders(),
  }).catch(() => {})
}