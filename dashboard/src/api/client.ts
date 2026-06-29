export const TOKEN_STORAGE_KEY = 'enochControlToken'
const TOKEN_COOKIE_NAME = 'enoch_dashboard_token'
const DASHBOARD_SESSION_PATH = '/control/dashboard-v2/session'

let currentToken = ''

function removeStoredToken(storage: Storage | undefined): void {
  if (typeof storage?.removeItem === 'function') {
    storage.removeItem(TOKEN_STORAGE_KEY)
  }
}

function scrubStoredToken(): void {
  removeStoredToken(globalThis.window?.localStorage)
  removeStoredToken(globalThis.window?.sessionStorage)
  expireTokenCookie()
}

function cookieAttributes(): string {
  const secure = globalThis.location?.protocol === 'https:' ? '; Secure' : ''
  return `; Path=/control; SameSite=Strict${secure}`
}

function expireTokenCookie(): void {
  if (!globalThis.document) return
  globalThis.document.cookie = `${TOKEN_COOKIE_NAME}=; Max-Age=0${cookieAttributes()}`
}

export function getSavedToken(): string {
  return currentToken
}

export function saveToken(token: string): void {
  currentToken = token.trim()
  scrubStoredToken()
}

function authHeaders(token: string): { Authorization?: string } {
  const trimmed = token.trim()
  if (!trimmed) {
    return {}
  }
  return { Authorization: `Bearer ${trimmed}` }
}

async function fetchDashboardSession(method: 'GET' | 'POST' | 'DELETE', token?: string): Promise<Response> {
  const headers: HeadersInit = token === undefined ? {} : { 'Content-Type': 'application/json' }
  return fetch(DASHBOARD_SESSION_PATH, {
    method,
    cache: 'no-store',
    credentials: 'same-origin',
    headers,
    body: token === undefined ? undefined : JSON.stringify({ token }),
  })
}

export async function hasDashboardSession(): Promise<boolean> {
  const response = await fetchDashboardSession('GET')
  if (response.ok) {
    try {
      const payload = await response.json() as { ok?: unknown }
      return payload.ok === true
    } catch {
      return false
    }
  }
  if (response.status === 401) return false
  throw new Error(await errorMessageForResponse(DASHBOARD_SESSION_PATH, response))
}

export async function establishDashboardSession(token: string): Promise<void> {
  const trimmed = token.trim()
  if (!trimmed) {
    saveToken('')
    throw new Error('Bearer token required')
  }
  const response = await fetchDashboardSession('POST', trimmed)
  if (!response.ok) {
    saveToken('')
    throw new Error(await errorMessageForResponse(DASHBOARD_SESSION_PATH, response))
  }
  saveToken(trimmed)
}

export async function clearDashboardSession(): Promise<void> {
  saveToken('')
  try {
    await fetchDashboardSession('DELETE')
  } catch {
    // Clearing in-memory/script-readable storage is the critical local action;
    // the server cookie will expire naturally if the network is unavailable.
  }
}

function stringifyApiDetail(value: unknown): string {
  if (typeof value === 'string') return value
  if (value === null || value === undefined) return ''
  try {
    return JSON.stringify(value)
  } catch {
    if (typeof value === 'object') return '[unserializable object]'
    if (typeof value === 'function') return '[function]'
    if (typeof value === 'symbol') return value.description ? `Symbol(${value.description})` : 'Symbol()'
    return '[unserializable value]'
  }
}

async function errorMessageForResponse(path: string, response: Response): Promise<string> {
  let detail = ''
  try {
    const text = await response.text()
    if (text) {
      try {
        const parsed = JSON.parse(text) as { detail?: unknown; message?: unknown }
        detail = stringifyApiDetail(parsed.detail ?? parsed.message ?? parsed)
      } catch {
        detail = text
      }
    }
  } catch {
    detail = ''
  }
  return detail ? `${path} -> ${response.status}: ${detail}` : `${path} -> ${response.status}`
}

export async function apiGet<T>(path: string, token = getSavedToken()): Promise<T> {
  const response = await fetch(path, {
    cache: 'no-store',
    credentials: 'same-origin',
    headers: authHeaders(token),
  })
  if (!response.ok) {
    throw new Error(await errorMessageForResponse(path, response))
  }
  return response.json() as Promise<T>
}

export async function apiPost<T>(path: string, payload: unknown, token = getSavedToken()): Promise<T> {
  const response = await fetch(path, {
    method: 'POST',
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { ...authHeaders(token), 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await errorMessageForResponse(path, response))
  }
  return response.json() as Promise<T>
}
