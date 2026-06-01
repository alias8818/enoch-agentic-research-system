import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { apiGet, apiPost } from '../api/client'
import { displayText } from '../displayText'
import { PageShell, InlineErrorStateCard, LoadingStateCard } from './ui'

type ProviderApiFormat = 'openai_compatible' | 'anthropic_messages'

type LlmProvider = {
  provider_id: string
  label: string
  api_format: ProviderApiFormat
  base_url: string
  api_key_env: string
  api_key_configured?: boolean
  enabled: boolean
  notes?: string
}

type LlmModel = {
  model_id: string
  provider_id: string
  label: string
  enabled: boolean
  weight: number
  notes?: string
}

type LlmWorkflow = {
  workflow_id: 'research_generation' | 'paper_writing' | 'research_review' | 'general_agent'
  label: string
  provider_ids: string[]
  model_pool: string[]
  default_model: string
  enabled: boolean
  temperature: number
  max_tokens: number
  notes?: string
}

type LlmSettings = {
  schema_version: number
  providers: LlmProvider[]
  models: LlmModel[]
  workflows: LlmWorkflow[]
  updated_at: string
  updated_by: string
}

type LlmSettingsResponse = {
  ok: boolean
  path: string
  persisted: boolean
  settings: LlmSettings
  generated_at: string
}

function updateAt<T>(items: T[], index: number, update: (item: T) => T): T[] {
  return items.map((item, itemIndex) => (itemIndex === index ? update(item) : item))
}

function splitList(value: string): string[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)
}

function listText(value: string[]): string {
  return value.join('\n')
}

function modelOptions(models: LlmModel[]): { value: string; label: string }[] {
  return models.map((model) => ({
    value: model.model_id,
    label: model.label ? `${model.label} (${model.model_id})` : model.model_id,
  }))
}

function providerStatus(provider: LlmProvider): string {
  if (!provider.enabled) return 'disabled'
  if (!provider.api_key_env) return 'no env key'
  return provider.api_key_configured ? 'key present' : 'key missing'
}

function ProviderRows({ settings, onChange }: Readonly<{ settings: LlmSettings; onChange: (settings: LlmSettings) => void }>) {
  return (
    <section className="settings-panel" aria-label="LLM providers">
      <div className="settings-panel-head">
        <div>
          <p className="eyebrow">Providers</p>
          <h2>Provider endpoints</h2>
        </div>
        <button
          className="secondary-button"
          type="button"
          onClick={() => onChange({
            ...settings,
            providers: [
              ...settings.providers,
              {
                provider_id: `provider_${settings.providers.length + 1}`,
                label: 'New provider',
                api_format: 'openai_compatible',
                base_url: 'https://example.invalid/v1',
                api_key_env: '',
                enabled: false,
              },
            ],
          })}
        >
          Add provider
        </button>
      </div>
      <div className="settings-table settings-table--providers">
        {settings.providers.map((provider, index) => {
          const providerName = provider.label || provider.provider_id || `Provider ${index + 1}`
          return (
          <article className="settings-row" key={`${provider.provider_id}-${index}`}>
            <label>
              Provider id
              <input aria-label={`${providerName} provider id`} value={provider.provider_id} onChange={(event) => onChange({ ...settings, providers: updateAt(settings.providers, index, (item) => ({ ...item, provider_id: event.target.value })) })} />
            </label>
            <label>
              Label
              <input aria-label={`${providerName} label`} value={provider.label} onChange={(event) => onChange({ ...settings, providers: updateAt(settings.providers, index, (item) => ({ ...item, label: event.target.value })) })} />
            </label>
            <label>
              API format
              <select aria-label={`${providerName} API format`} value={provider.api_format} onChange={(event) => onChange({ ...settings, providers: updateAt(settings.providers, index, (item) => ({ ...item, api_format: event.target.value as ProviderApiFormat })) })}>
                <option value="openai_compatible">OpenAI compatible</option>
                <option value="anthropic_messages">Anthropic messages</option>
              </select>
            </label>
            <label className="settings-field-wide">
              Base URL
              <input aria-label={`${providerName} base URL`} value={provider.base_url} onChange={(event) => onChange({ ...settings, providers: updateAt(settings.providers, index, (item) => ({ ...item, base_url: event.target.value })) })} />
            </label>
            <label>
              API key env
              <input aria-label={`${providerName} API key env`} value={provider.api_key_env} onChange={(event) => onChange({ ...settings, providers: updateAt(settings.providers, index, (item) => ({ ...item, api_key_env: event.target.value })) })} />
            </label>
            <label className="settings-checkbox">
              <input aria-label={`${providerName} enabled`} type="checkbox" checked={provider.enabled} onChange={(event) => onChange({ ...settings, providers: updateAt(settings.providers, index, (item) => ({ ...item, enabled: event.target.checked })) })} />
              Enabled
            </label>
            <span className="settings-status">{providerStatus(provider)}</span>
          </article>
          )
        })}
      </div>
    </section>
  )
}

function ModelRows({ settings, onChange }: Readonly<{ settings: LlmSettings; onChange: (settings: LlmSettings) => void }>) {
  return (
    <section className="settings-panel" aria-label="LLM models">
      <div className="settings-panel-head">
        <div>
          <p className="eyebrow">Models</p>
          <h2>Model catalog</h2>
        </div>
        <button
          className="secondary-button"
          type="button"
          onClick={() => onChange({
            ...settings,
            models: [
              ...settings.models,
              {
                model_id: `new-model-${settings.models.length + 1}`,
                provider_id: settings.providers[0]?.provider_id || 'synthetic',
                label: 'New model',
                enabled: false,
                weight: 1,
              },
            ],
          })}
        >
          Add model
        </button>
      </div>
      <div className="settings-table">
        {settings.models.map((model, index) => (
          <article className="settings-row settings-row--model" key={`${model.model_id}-${index}`}>
            <label className="settings-field-wide">
              Model id
              <input aria-label={`${model.label || model.model_id} model id`} value={model.model_id} onChange={(event) => onChange({ ...settings, models: updateAt(settings.models, index, (item) => ({ ...item, model_id: event.target.value })) })} />
            </label>
            <label>
              Provider
              <select aria-label={`${model.label || model.model_id} provider`} value={model.provider_id} onChange={(event) => onChange({ ...settings, models: updateAt(settings.models, index, (item) => ({ ...item, provider_id: event.target.value })) })}>
                {settings.providers.map((provider) => <option key={provider.provider_id} value={provider.provider_id}>{provider.label || provider.provider_id}</option>)}
              </select>
            </label>
            <label>
              Label
              <input aria-label={`${model.label || model.model_id} label`} value={model.label} onChange={(event) => onChange({ ...settings, models: updateAt(settings.models, index, (item) => ({ ...item, label: event.target.value })) })} />
            </label>
            <label>
              Weight
              <input aria-label={`${model.label || model.model_id} weight`} type="number" min={0} max={100} value={model.weight} onChange={(event) => onChange({ ...settings, models: updateAt(settings.models, index, (item) => ({ ...item, weight: Number(event.target.value) })) })} />
            </label>
            <label className="settings-checkbox">
              <input aria-label={`${model.label || model.model_id} enabled`} type="checkbox" checked={model.enabled} onChange={(event) => onChange({ ...settings, models: updateAt(settings.models, index, (item) => ({ ...item, enabled: event.target.checked })) })} />
              Enabled
            </label>
          </article>
        ))}
      </div>
    </section>
  )
}

function WorkflowRows({ settings, onChange }: Readonly<{ settings: LlmSettings; onChange: (settings: LlmSettings) => void }>) {
  const options = useMemo(() => modelOptions(settings.models), [settings.models])
  return (
    <section className="settings-panel" aria-label="LLM workflow pools">
      <div className="settings-panel-head">
        <div>
          <p className="eyebrow">Workflow pools</p>
          <h2>Agent routing</h2>
        </div>
      </div>
      <div className="workflow-grid">
        {settings.workflows.map((workflow, index) => (
          <article className="workflow-card" key={workflow.workflow_id}>
            <div className="workflow-card-head">
              <div>
                <p className="eyebrow">{workflow.workflow_id.replaceAll('_', ' ')}</p>
                <input
                  className="workflow-title-input"
                  value={workflow.label}
                  onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, label: event.target.value })) })}
                />
              </div>
              <label className="settings-checkbox">
                <input aria-label={`${workflow.label} enabled`} type="checkbox" checked={workflow.enabled} onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, enabled: event.target.checked })) })} />
                Enabled
              </label>
            </div>
            <label>
              Providers
              <textarea aria-label={`${workflow.label} providers`} value={listText(workflow.provider_ids)} onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, provider_ids: splitList(event.target.value) })) })} />
            </label>
            <label>
              Default model
              <select aria-label={`${workflow.label} default model`} value={workflow.default_model} onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, default_model: event.target.value })) })}>
                {options.map((model) => <option key={model.value} value={model.value}>{model.label}</option>)}
              </select>
            </label>
            <label>
              Model pool
              <textarea aria-label={`${workflow.label} model pool`} value={listText(workflow.model_pool)} onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, model_pool: splitList(event.target.value) })) })} />
            </label>
            <div className="settings-row settings-row--compact">
              <label>
                Temperature
                <input aria-label={`${workflow.label} temperature`} type="number" min={0} max={2} step={0.1} value={workflow.temperature} onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, temperature: Number(event.target.value) })) })} />
              </label>
              <label>
                Max tokens
                <input aria-label={`${workflow.label} max tokens`} type="number" min={512} value={workflow.max_tokens} onChange={(event) => onChange({ ...settings, workflows: updateAt(settings.workflows, index, (item) => ({ ...item, max_tokens: Number(event.target.value) })) })} />
              </label>
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

export function SettingsPage() {
  const query = useQuery({
    queryKey: ['llm-settings'],
    queryFn: () => apiGet<LlmSettingsResponse>('/control/api/settings/llm'),
  })
  const [draft, setDraft] = useState<LlmSettings | null>(null)
  useEffect(() => {
    if (query.data?.settings) setDraft(query.data.settings)
  }, [query.data])
  const mutation = useMutation({
    mutationFn: (settings: LlmSettings) => apiPost<Record<string, unknown>>('/control/api/settings/llm', { requested_by: 'dashboard-v2', settings }),
    onSuccess: () => query.refetch(),
  })
  if (query.isLoading) return <LoadingStateCard label="LLM settings" />
  if (query.error) return <InlineErrorStateCard prefix="Settings load failed" message={String(query.error)} />
  if (!draft) return <InlineErrorStateCard prefix="Settings unavailable" message="No settings payload returned." />

  return (
    <PageShell
      title="LLM settings"
      subtitle="Providers, model catalog, and workflow model pools"
      dataSource={`${displayText(query.data?.path, 'default settings')} ${query.data?.persisted ? 'persisted' : 'defaults'}`}
      action={(
        <button className="primary-button" type="button" disabled={mutation.isPending} onClick={() => mutation.mutate(draft)}>
          {mutation.isPending ? 'Saving settings' : 'Save settings'}
        </button>
      )}
    >
      {mutation.error ? <InlineErrorStateCard prefix="Settings save failed" message={String(mutation.error)} /> : null}
      {mutation.data ? <section className="state-card state-card--compact">Settings saved.</section> : null}
      <ProviderRows settings={draft} onChange={setDraft} />
      <ModelRows settings={draft} onChange={setDraft} />
      <WorkflowRows settings={draft} onChange={setDraft} />
    </PageShell>
  )
}
