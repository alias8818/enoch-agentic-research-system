import { afterEach, expect, it, vi } from 'vitest'
import { apiGet, apiPost, getSavedToken, saveToken, TOKEN_STORAGE_KEY } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  saveToken('')
  globalThis.window?.localStorage?.clear()
  globalThis.window?.sessionStorage?.clear()
  globalThis.document.cookie = 'enoch_dashboard_token=; Max-Age=0; Path=/control; SameSite=Strict'
})

it('keeps saved bearer tokens in memory only and scrubs script-readable storage', () => {
  globalThis.history.pushState(null, '', '/control/dashboard-v2')
  globalThis.window.localStorage.setItem(TOKEN_STORAGE_KEY, 'stale-local-token')
  globalThis.window.sessionStorage.setItem(TOKEN_STORAGE_KEY, 'stale-session-token')
  globalThis.document.cookie = 'enoch_dashboard_token=stale-cookie-token; Path=/control; SameSite=Strict'

  expect(getSavedToken()).toBe('')

  saveToken('  operator-token  ')

  expect(getSavedToken()).toBe('operator-token')
  expect(globalThis.window.localStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  expect(globalThis.window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
  expect(globalThis.document.cookie).not.toContain('enoch_dashboard_token=')
})

it('does not load bearer tokens from script-readable dashboard cookies after reload', () => {
  globalThis.history.pushState(null, '', '/control/dashboard-v2')
  globalThis.document.cookie = 'enoch_dashboard_token=operator-token; Path=/control; SameSite=Strict'

  expect(getSavedToken()).toBe('')

  saveToken('replacement-token')
  expect(getSavedToken()).toBe('replacement-token')
  expect(globalThis.document.cookie).not.toContain('enoch_dashboard_token=')

  saveToken('')
  expect(getSavedToken()).toBe('')
  expect(globalThis.document.cookie).not.toContain('enoch_dashboard_token=')
})

it('omits Authorization instead of sending a bogus bearer when token is missing', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))

  await apiGet('/control/api/v1/overview', '')
  await apiPost('/control/api/preflight', {}, '   ')

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/overview', {
    cache: 'no-store',
    headers: {},
  })
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/preflight', {
    method: 'POST',
    cache: 'no-store',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({}),
  })
})

it('trims token before building the Authorization header', async () => {
  const fetchMock = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))

  await apiGet('/control/api/v1/overview', '  operator-token  ')
  await apiPost('/control/api/preflight', { dry_run: true }, '  operator-token  ')

  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/overview', {
    cache: 'no-store',
    headers: { Authorization: 'Bearer operator-token' },
  })
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/preflight', {
    method: 'POST',
    cache: 'no-store',
    headers: { Authorization: 'Bearer operator-token', 'Content-Type': 'application/json' },
    body: JSON.stringify({ dry_run: true }),
  })
})
