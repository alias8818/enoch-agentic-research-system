import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from '../api/client'
import { fetchMockCallUrl, fetchMockRequestBody } from '../test/fetchMockBody'
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
  model_health: {
    ok: false,
    status: 'needs_attention',
    model_count: 2,
    unhealthy_count: 1,
    models: [
      {
        provider_id: 'synthetic',
        model_id: 'hf:moonshotai/Kimi-K2.6',
        status: 'healthy',
        latest_checked_at: '2026-06-01T19:00:00Z',
        latest_failure_kind: '',
        latest_latency_ms: 42,
        latest_status_code: 200,
        success_rate: 1,
        attempt_count: 1,
        success_count: 1,
        failure_count: 0,
        consecutive_failures: 0,
        latest: { ok: true },
      },
      {
        provider_id: 'openrouter',
        model_id: 'openrouter/anthropic/claude-sonnet-4.5',
        status: 'unhealthy',
        latest_checked_at: '2026-06-01T19:01:00Z',
        latest_failure_kind: 'model_not_found',
        latest_latency_ms: 120,
        latest_status_code: 404,
        success_rate: 1 / 3,
        attempt_count: 3,
        success_count: 1,
        failure_count: 2,
        consecutive_failures: 2,
        latest: { ok: false },
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
  fireEvent.click(screen.getByLabelText('Research agents model openrouter/anthropic/claude-sonnet-4.5'))
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
  expect(body.settings.providers[1]).not.toHaveProperty('api_key_configured')
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

it('sends one-time provider secrets separately from persisted settings', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.change(screen.getByLabelText('OpenRouter API key secret'), {
    target: { value: 'or-secret-value' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
  const body = JSON.parse(fetchMockRequestBody(fetchMock, 1))
  expect(body.provider_secrets).toEqual({ openrouter: 'or-secret-value' })
  expect(JSON.stringify(body.settings)).not.toContain('or-secret-value')
})

it('blocks saves when an API key is entered into the environment variable field', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValue(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.change(screen.getByLabelText('OpenRouter API key environment variable'), {
    target: { value: 'or-secret-value' },
  })

  expect(await screen.findByText(/OpenRouter environment variable name is invalid/)).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save settings' })).not.toBeDisabled()
  expect(fetchMock).toHaveBeenCalledTimes(1)
})

it('deletes models and prunes workflow references before save', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.click(screen.getByLabelText('Research agents model openrouter/anthropic/claude-sonnet-4.5'))
  fireEvent.click(screen.getAllByRole('button', { name: 'Delete' })[1])
  fireEvent.click(screen.getByRole('button', { name: 'Save settings' }))

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
  const body = JSON.parse(fetchMockRequestBody(fetchMock, 1))
  expect(body.settings.models.map((model: { model_id: string }) => model.model_id)).not.toContain('openrouter/anthropic/claude-sonnet-4.5')
  expect(body.settings.workflows[0].model_pool).not.toContain('openrouter/anthropic/claude-sonnet-4.5')
})

it('tests an exact model id through the settings API', async () => {
  saveToken('test-token')
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify(settingsPayload), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, provider_id: 'synthetic', model_id: 'hf:moonshotai/Kimi-K2.6', status_code: 200, latency_ms: 42 }), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.click(screen.getAllByRole('button', { name: 'Test' })[2])

  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
  expect(fetchMockCallUrl(fetchMock, 1)).toBe('/control/api/settings/llm/test')
  const body = JSON.parse(fetchMockRequestBody(fetchMock, 1))
  expect(body).toEqual({ provider_id: 'synthetic', model_id: 'hf:moonshotai/Kimi-K2.6' })
  expect(await screen.findByText('ok 42ms')).toBeInTheDocument()
})

it('renders persisted model health beside catalog rows', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')

  expect(screen.getByText('healthy')).toBeInTheDocument()
  expect(screen.getByText('42ms')).toBeInTheDocument()
  expect(screen.getByText('status 200')).toBeInTheDocument()
  expect(screen.getByText('checked 2026-06-01 19:00 UTC')).toBeInTheDocument()
  expect(screen.getByText('1 check')).toBeInTheDocument()
  expect(screen.getByText('success 100%')).toBeInTheDocument()
  expect(screen.getByText('unhealthy')).toBeInTheDocument()
  expect(screen.getByText('model_not_found')).toBeInTheDocument()
  expect(screen.getByText('status 404')).toBeInTheDocument()
  expect(screen.getByText('3 checks')).toBeInTheDocument()
  expect(screen.getByText('success 33%')).toBeInTheDocument()
  expect(screen.getByText('2 consecutive failures')).toBeInTheDocument()
})

it('applies recommended routing with checkboxes instead of typed workflow pools', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(settingsPayload), { status: 200 }))

  renderWithClient(<SettingsPage />)

  await screen.findByDisplayValue('https://openrouter.ai/api/v1')
  fireEvent.click(screen.getByRole('button', { name: 'Apply recommended routing' }))

  expect(screen.getByLabelText('Research agents model openrouter/anthropic/claude-sonnet-4.5')).toBeChecked()
  expect(screen.queryByLabelText('Research agents model pool')).not.toBeInTheDocument()
})
