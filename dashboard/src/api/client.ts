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

export async function apiGet<T>(path: string, token = getSavedToken()): Promise<T> {
  const response = await fetch(path, {
    cache: 'no-store',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status}`)
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
    throw new Error(`${path} -> ${response.status}`)
  }
  return response.json() as Promise<T>
}
