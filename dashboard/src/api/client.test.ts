import { afterEach, expect, it, vi } from 'vitest'
import { apiGet, apiPost, saveToken } from './client'

afterEach(() => {
  vi.restoreAllMocks()
  saveToken('')
})

it('includes API error detail from failed writes', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    detail: "workflow 'research_generation' references unknown models: openrouter/auto",
  }), { status: 400 }))

  await expect(apiPost('/control/api/settings/llm', { settings: {} })).rejects.toThrow(
    "/control/api/settings/llm -> 400: workflow 'research_generation' references unknown models: openrouter/auto",
  )
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
