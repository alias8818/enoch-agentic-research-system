export const TOKEN_STORAGE_KEY = 'enochControlToken'

let fallbackToken = ''

function browserStorage(): Pick<Storage, 'getItem' | 'setItem'> | undefined {
  const storage = globalThis.window?.localStorage
  if (typeof storage?.getItem === 'function' && typeof storage?.setItem === 'function') {
    return storage
  }
  return undefined
}

export function getSavedToken(): string {
  return browserStorage()?.getItem(TOKEN_STORAGE_KEY) || fallbackToken
}

export function saveToken(token: string): void {
  fallbackToken = token.trim()
  browserStorage()?.setItem(TOKEN_STORAGE_KEY, fallbackToken)
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
    return `${value}`
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
    headers: { Authorization: `Bearer ${token}` },
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
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error(await errorMessageForResponse(path, response))
  }
  return response.json() as Promise<T>
}
