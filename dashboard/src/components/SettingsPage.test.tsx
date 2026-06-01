import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { fetchMockRequestBody } from '../test/fetchMockBody'
import { SettingsPage } from './SettingsPage'

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

const settingsPayload = {
  ok: true,
  path: '/var/lib/enoch-control-plane/llm-provider-settings.json',
  persisted: true,
  generated_at: '2026-06-01T16:55:00Z',
  settings: {
    schema_version: 1,
    updated_at: '2026-06-01T16:55:00Z',
    updated_by: 'test',
    providers: [
      {
        provider_id: 'synthetic',
        label: 'Synthetic',
        api_format: 'openai_compatible',
        base_url: 'https://synthetic.int.exe.xyz/openai/v1',
        api_key_env: 'SYNTHETIC_API_KEY',
        api_key_configured: true,
        enabled: true,
      },
      {
        provider_id: 'openrouter',
        label: 'OpenRouter',
        api_format: 'openai_compatible',
        base_url: 'https://openrouter.ai/api/v1',
        api_key_env: 'OPENROUTER_API_KEY',
        api_key_configured: false,
        enabled: false,
      },
    ],
    models: [
      {
        model_id: 'hf:moonshotai/Kimi-K2.6',
        provider_id: 'synthetic',
        label: 'Kimi K2.6',
        enabled: true,
        weight: 1,
      },
      {
        model_id: 'openrouter/anthropic/claude-sonnet-4.5',
        provider_id: 'openrouter',
        label: 'Claude Sonnet 4.5 via OpenRouter',
        enabled: false,
        weight: 1,
      },
    ],
    workflows: [
      {
        workflow_id: 'research_generation',
        label: 'Research agents',
        provider_ids: ['synthetic'],
        model_pool: ['hf:moonshotai/Kimi-K2.6'],
        default_model: 'hf:moonshotai/Kimi-K2.6',
        enabled: true,
        temperature: 0.7,
        max_tokens: 4096,
      },
      {
        workflow_id: 'paper_writing',
        label: 'Paper writing agents',
        provider_ids: ['synthetic'],
        model_pool: ['hf:moonshotai/Kimi-K2.6'],
        default_model: 'hf:moonshotai/Kimi-K2.6',
        enabled: true,
        temperature: 0.4,
        max_tokens: 8192,
      },
    ],
  },
}

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
})

it('edits provider endpoints, model catalog, and workflow pools through the settings API', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.click(screen.getByLabelText('OpenRouter enabled'))
  fireEvent.change(screen.getByLabelText('OpenRouter base URL'), {
    target: { value: 'https://openrouter.example/api/v1' },
  })
  fireEvent.click(screen.getByLabelText('Claude Sonnet 4.5 via OpenRouter enabled'))
  fireEvent.change(screen.getByLabelText('Research agents model pool'), {
    target: { value: 'hf:moonshotai/Kimi-K2.6\nopenrouter/anthropic/claude-sonnet-4.5' },
  })
  fireEvent.change(screen.getByLabelText('Research agents default model'), {
    target: { value: 'openrouter/anthropic/claude-sonnet-4.5' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
  expect(fetchMock).toHaveBeenNthCalledWith(
    1,
    '/control/api/settings/llm',
    expect.objectContaining({ headers: { Authorization: 'Bearer test-token' } }),
  )
  expect(fetchMock).toHaveBeenNthCalledWith(
    2,
    '/control/api/settings/llm',
    expect.objectContaining({ method: 'POST' }),
  )
  const body = JSON.parse(fetchMockRequestBody(fetchMock, 1))
  expect(body.requested_by).toBe('dashboard-v2')
  expect(body.settings.providers[1]).toMatchObject({
    provider_id: 'openrouter',
    base_url: 'https://openrouter.example/api/v1',
    enabled: true,
  })
  expect(body.settings.models[1]).toMatchObject({
    model_id: 'openrouter/anthropic/claude-sonnet-4.5',
    enabled: true,
  })
  expect(body.settings.workflows[0]).toMatchObject({
    workflow_id: 'research_generation',
    default_model: 'openrouter/anthropic/claude-sonnet-4.5',
    model_pool: ['hf:moonshotai/Kimi-K2.6', 'openrouter/anthropic/claude-sonnet-4.5'],
  })
})

it('blocks saves when a workflow references a model outside the catalog', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.change(screen.getByLabelText('Research agents model pool'), {
    target: { value: 'openrouter/missing-model' },
  })

  expect(await screen.findByText(/Research agents references models not in the catalog: openrouter\/missing-model/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save settings' })).toBeDisabled()
})
