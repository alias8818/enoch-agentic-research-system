import { afterEach, expect, it, vi } from 'vitest'
import { apiGet, apiPost, getSavedToken, saveToken, TOKEN_STORAGE_KEY } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  saveToken('')
  globalThis.window?.sessionStorage?.clear()
})

it('keeps saved bearer tokens in memory and scrubs stale session storage', () => {
  globalThis.window.sessionStorage.setItem(TOKEN_STORAGE_KEY, 'stale-session-token')

  expect(getSavedToken()).toBe('')

  saveToken('  operator-token  ')

  expect(getSavedToken()).toBe('operator-token')
  expect(globalThis.window.sessionStorage.getItem(TOKEN_STORAGE_KEY)).toBeNull()
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
