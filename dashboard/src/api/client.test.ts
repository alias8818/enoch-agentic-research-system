import { afterEach, expect, it, vi } from 'vitest'
import { apiGet, saveToken } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  saveToken('')
})

it('sends the saved bearer token on API reads', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ ok: true }), { status: 200 }))

  await apiGet('/control/api/v1/overview')

  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/overview', expect.objectContaining({
    cache: 'no-store',
    headers: { Authorization: 'Bearer test-token' },
  }))
})
