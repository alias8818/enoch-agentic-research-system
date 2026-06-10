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

type LlmModelHealthRow = {
  provider_id: string
  model_id: string
  status: string
  format_health?: string
  workflow_health?: string
  latest_checked_at?: string
  latest_failure_kind?: string
  latest_malformed_kind?: string
  latest_recoverable_json_shape?: boolean
  latest_latency_ms?: number
  latest_status_code?: number
  success_rate?: number
  format_success_rate?: number
  attempt_count?: number
  success_count?: number
  failure_count?: number
  consecutive_failures?: number
  recoverable_json_shape_count?: number
  latest?: Record<string, unknown> | null
}

type LlmModelHealth = {
  ok: boolean
  status: string
  model_count: number
  unhealthy_count: number
  models: LlmModelHealthRow[]
}

type LlmSettingsResponse = {
  ok: boolean
  path: string
  persisted: boolean
  settings: LlmSettings
  model_health?: LlmModelHealth
  generated_at: string
}

type LlmTestResponse = {
  ok: boolean
  provider_id: string
  model_id: string
  status_code: number
  latency_ms: number
  response_preview?: string
  error?: string
}

const API_KEY_ENV_RE = /^[A-Z][A-Z0-9_]{0,127}$/
const OPENROUTER_PROVIDER_ID = 'openrouter'

function updateAt<T>(items: T[], index: number, update: (item: T) => T): T[] {
  return items.map((item, itemIndex) => (itemIndex === index ? update(item) : item))
}

function toggleItem(items: string[], item: string, enabled: boolean): string[] {
  const next = items.filter((current) => current !== item)
  return enabled ? [...next, item] : next
}

function modelOptions(models: LlmModel[]): { value: string; label: string }[] {
  return models.map((model) => ({
    value: model.model_id,
    label: model.label ? `${model.label} (${model.model_id})` : model.model_id,
  }))
}

function providerStatus(provider: LlmProvider): string {
  if (!provider.enabled) return 'disabled'
  return provider.api_key_configured ? 'key present' : 'key missing'
}

function duplicateValues(values: string[]): string[] {
  const seen = new Set<string>()
  const duplicates = new Set<string>()
  for (const value of values) {
    if (seen.has(value)) duplicates.add(value)
    seen.add(value)
  }
  return Array.from(duplicates)
}

function sanitizeSettingsForSave(settings: LlmSettings): LlmSettings {
  return {
    ...settings,
    providers: settings.providers.map(({ api_key_configured: _ignored, ...provider }) => provider),
  }
}

function providerIdsForModels(models: LlmModel[], modelIds: string[]): string[] {
  const providerIds = new Set<string>()
  for (const modelId of modelIds) {
    const model = models.find((item) => item.model_id === modelId)
    if (model?.provider_id) providerIds.add(model.provider_id)
  }
  return Array.from(providerIds)
}

function canonicalModelId(model: LlmModel): string {
  const id = model.model_id.trim()
  const label = `${model.label} ${id}`.toLowerCase()
  if (model.provider_id !== OPENROUTER_PROVIDER_ID) return id
  if (label.includes('owl-alpha') || label.includes('owl alpha')) return 'openrouter/owl-alpha'
  if (label.includes('kimi') || label.includes('moonshot')) return 'moonshotai/kimi-k2.6'
  if (label.includes('deepseek')) return 'deepseek/deepseek-v4-pro'
  if (label.includes('mimo') || label.includes('xiaomi')) return 'xiaomi/mimo-v2.5-pro'
  if (label.includes('minimax')) return 'minimax/minimax-m2.7'
  if (label.includes('glm') || label.includes('z-ai')) return 'z-ai/glm-5.1'
  return id
}

function recommendedWeight(model: LlmModel): number {
  const text = `${model.label} ${model.model_id}`.toLowerCase()
  if (text.includes('glm-5.1')) return 92
  if (text.includes('kimi')) return 90
  if (text.includes('deepseek')) return 88
  if (text.includes('mimo')) return 84
  if (text.includes('minimax')) return 80
  if (text.includes('owl')) return 74
  return Math.max(35, Math.min(70, Number(model.weight) || 50))
}

function recommendedNotes(model: LlmModel): string {
  const text = `${model.label} ${model.model_id}`.toLowerCase()
  if (text.includes('glm-5.1')) return 'Recommended for long-horizon coding/review; OpenRouter lists ~203K context.'
  if (text.includes('kimi')) return 'Recommended for research generation and agentic coding; OpenRouter lists ~262K context.'
  if (text.includes('deepseek')) return 'Recommended for review/writing and low-cost long-context reasoning; OpenRouter lists ~1M context.'
  if (text.includes('mimo')) return 'Recommended as a low-cost long-context agent model; OpenRouter lists ~1M context.'
  if (text.includes('minimax')) return 'Recommended as a long-horizon agent/writing fallback; OpenRouter lists ~205K context.'
  if (text.includes('owl')) return 'Recommended as an OpenRouter agentic smoke-test/general fallback.'
  return model.notes || ''
}

function sortedEnabledModelIds(models: LlmModel[]): string[] {
  return [...models]
    .filter((model) => model.enabled)
    .sort((left, right) => (right.weight || 0) - (left.weight || 0) || left.model_id.localeCompare(right.model_id))
    .map((model) => model.model_id)
}

function firstAvailable(preferred: string[], fallback: string[]): string {
  return preferred.find((modelId) => fallback.includes(modelId)) || fallback[0] || ''
}

function preferredWorkflowModels(workflowId: LlmWorkflow['workflow_id']): string[] {
  const preferred: Record<LlmWorkflow['workflow_id'], string[]> = {
    research_generation: ['moonshotai/kimi-k2.6', 'hf:zai-org/GLM-5.1', 'deepseek/deepseek-v4-pro'],
    paper_writing: ['deepseek/deepseek-v4-pro', 'moonshotai/kimi-k2.6', 'hf:zai-org/GLM-5.1'],
    research_review: ['hf:zai-org/GLM-5.1', 'deepseek/deepseek-v4-pro', 'moonshotai/kimi-k2.6'],
    general_agent: ['openrouter/owl-alpha', 'xiaomi/mimo-v2.5-pro', 'minimax/minimax-m2.7'],
  }
  return preferred[workflowId]
}

function recommendedTemperature(workflowId: LlmWorkflow['workflow_id']): number {
  if (workflowId === 'research_generation') return 0.7
  if (workflowId === 'general_agent') return 0.3
  return 0.2
}

function applyRecommendedRouting(settings: LlmSettings): LlmSettings {
  const mergedModels = new Map<string, LlmModel>()
  for (const model of settings.models) {
    const modelId = canonicalModelId(model)
    const normalized = {
      ...model,
      model_id: modelId,
      enabled: true,
      weight: recommendedWeight({ ...model, model_id: modelId }),
      notes: recommendedNotes({ ...model, model_id: modelId }),
    }
    const existing = mergedModels.get(modelId)
    if (!existing || normalized.weight > existing.weight) mergedModels.set(modelId, normalized)
  }
  const models = Array.from(mergedModels.values())
  const allPool = sortedEnabledModelIds(models)
  const withDefault = (workflow: LlmWorkflow): LlmWorkflow => {
    const modelPool = workflow.workflow_id === 'general_agent' ? allPool.slice(0, 4) : allPool
    const defaultModel = firstAvailable(preferredWorkflowModels(workflow.workflow_id), modelPool)
    return {
      ...workflow,
      provider_ids: providerIdsForModels(models, modelPool),
      model_pool: modelPool,
      default_model: defaultModel,
      temperature: recommendedTemperature(workflow.workflow_id),
      max_tokens: workflow.workflow_id === 'paper_writing' ? 12000 : 8000,
    }
  }
  return {
    ...settings,
    providers: settings.providers.map((provider) => ({
      ...provider,
      enabled: provider.enabled || ['synthetic', OPENROUTER_PROVIDER_ID].includes(provider.provider_id),
    })),
    models,
    workflows: settings.workflows.map(withDefault),
  }
}

function pruneDeletedProvider(settings: LlmSettings, providerId: string): LlmSettings {
  const modelsToDelete = settings.models.filter((model) => model.provider_id === providerId).map((model) => model.model_id)
  const modelDeleteSet = new Set(modelsToDelete)
  const models = settings.models.filter((model) => model.provider_id !== providerId)
  return {
    ...settings,
    providers: settings.providers.filter((provider) => provider.provider_id !== providerId),
    models,
    workflows: settings.workflows.map((workflow) => {
      const modelPool = workflow.model_pool.filter((modelId) => !modelDeleteSet.has(modelId))
      return {
        ...workflow,
        provider_ids: workflow.provider_ids.filter((item) => item !== providerId),
        model_pool: modelPool,
        default_model: modelPool.includes(workflow.default_model) ? workflow.default_model : modelPool[0] || '',
      }
    }),
  }
}

function pruneDeletedModel(settings: LlmSettings, modelId: string): LlmSettings {
  const models = settings.models.filter((model) => model.model_id !== modelId)
  return {
    ...settings,
    models,
    workflows: settings.workflows.map((workflow) => {
      const modelPool = workflow.model_pool.filter((item) => item !== modelId)
      return {
        ...workflow,
        provider_ids: providerIdsForModels(models, modelPool),
        model_pool: modelPool,
        default_model: modelPool.includes(workflow.default_model) ? workflow.default_model : modelPool[0] || '',
      }
    }),
  }
}

function appendDuplicateErrors(errors: string[], label: string, values: string[]): void {
  for (const value of duplicateValues(values)) errors.push(`Duplicate ${label}: ${value}`)
}

function appendProviderValidationErrors(errors: string[], providers: LlmProvider[]): void {
  for (const provider of providers) {
    const envName = provider.api_key_env.trim()
    if (envName && !API_KEY_ENV_RE.test(envName)) {
      errors.push(`${provider.label || provider.provider_id} environment variable name is invalid. Save will store this value as a one-time provider secret and clear the env field.`)
    }
  }
}

function appendModelValidationErrors(errors: string[], models: LlmModel[], providerSet: Set<string>): void {
  for (const model of models) {
    if (model.provider_id && !providerSet.has(model.provider_id)) {
      errors.push(`${model.label || model.model_id} references unknown provider: ${model.provider_id}`)
    }
  }
}

function appendWorkflowValidationErrors(
  errors: string[],
  workflows: LlmWorkflow[],
  providerSet: Set<string>,
  modelSet: Set<string>,
): void {
  for (const workflow of workflows) {
    const label = workflow.label || workflow.workflow_id
    const missingProviders = workflow.provider_ids.filter((providerId) => !providerSet.has(providerId))
    if (missingProviders.length) errors.push(`${label} references providers not in the catalog: ${missingProviders.join(', ')}`)
    const missingModels = workflow.model_pool.filter((modelId) => !modelSet.has(modelId))
    if (missingModels.length) errors.push(`${label} references models not in the catalog: ${missingModels.join(', ')}`)
    if (workflow.default_model && !workflow.model_pool.includes(workflow.default_model)) {
      errors.push(`${label} default model is not in the model pool: ${workflow.default_model}`)
    }
    if (workflow.enabled && workflow.model_pool.length === 0) {
      errors.push(`${label} requires at least one model in its pool`)
    }
  }
}

function validateDraftSettings(settings: LlmSettings): string[] {
  const errors: string[] = []
  const providerIds = settings.providers.map((provider) => provider.provider_id.trim()).filter(Boolean)
  const modelIds = settings.models.map((model) => model.model_id.trim()).filter(Boolean)
  const providerSet = new Set(providerIds)
  const modelSet = new Set(modelIds)
  appendDuplicateErrors(errors, 'provider id', providerIds)
  appendProviderValidationErrors(errors, settings.providers)
  appendDuplicateErrors(errors, 'model id', modelIds)
  appendModelValidationErrors(errors, settings.models, providerSet)
  appendWorkflowValidationErrors(errors, settings.workflows, providerSet, modelSet)
  return errors
}

function SettingsValidationCard({ errors }: Readonly<{ errors: string[] }>) {
  if (!errors.length) return null
  return (
    <section className="state-card state-card--error state-card--compact" aria-label="Settings validation">
      <strong>Settings needs attention.</strong>
      <ul className="settings-validation-list">
        {errors.map((error) => <li key={error}>{error}</li>)}
      </ul>
    </section>
  )
}

function TestResult({ result }: Readonly<{ result?: LlmTestResponse | 'pending' }>) {
  if (!result) return null
  if (result === 'pending') return <span className="settings-test-result">testing...</span>
  return (
    <span className={`settings-test-result ${result.ok ? 'settings-test-result--ok' : 'settings-test-result--fail'}`}>
      {result.ok ? `ok ${result.latency_ms}ms` : `failed ${result.status_code || ''}`.trim()}
      {result.error ? `: ${result.error}` : ''}
    </span>
  )
}

function healthClass(status?: string): string {
  if (status === 'healthy') return 'settings-health settings-health--ok'
  if (status === 'unhealthy') return 'settings-health settings-health--fail'
  return 'settings-health settings-health--stale'
}

function formatHealthTimestamp(value?: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  const yyyy = String(date.getUTCFullYear()).padStart(4, '0')
  const mm = String(date.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(date.getUTCDate()).padStart(2, '0')
  const hh = String(date.getUTCHours()).padStart(2, '0')
  const min = String(date.getUTCMinutes()).padStart(2, '0')
  return `checked ${yyyy}-${mm}-${dd} ${hh}:${min} UTC`
}

function formatCheckCount(value?: number): string {
  const count = Number(value || 0)
  if (!Number.isFinite(count) || count <= 0) return ''
  return `${count} ${count === 1 ? 'check' : 'checks'}`
}

function formatSuccessRate(value?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return ''
  return `success ${Math.round(value * 100)}%`
}

function formatConsecutiveFailures(value?: number): string {
  const count = Number(value || 0)
  if (!Number.isFinite(count) || count <= 0) return ''
  return `${count} consecutive ${count === 1 ? 'failure' : 'failures'}`
}

function HealthResult({ health }: Readonly<{ health?: LlmModelHealthRow }>) {
  if (!health) {
    return (
      <span className={healthClass('stale')}>
        <span>stale</span>
        <span>no health checks</span>
      </span>
    )
  }
  const status = health.status || 'unknown'
  const details = [
    health.format_health ? `format ${health.format_health}` : '',
    health.workflow_health ? `workflow ${health.workflow_health}` : '',
    health.latest_recoverable_json_shape ? 'recoverable legacy JSON shape' : '',
    health.latest_malformed_kind || '',
    health.latest_latency_ms ? `${health.latest_latency_ms}ms` : '',
    health.latest_status_code ? `status ${health.latest_status_code}` : '',
    formatHealthTimestamp(health.latest_checked_at),
    formatCheckCount(health.attempt_count),
    formatSuccessRate(health.success_rate),
    health.latest_failure_kind || '',
    formatConsecutiveFailures(health.consecutive_failures),
  ].filter(Boolean)
  return (
    <span className={healthClass(status)}>
      <span>{status}</span>
      {details.map((detail) => <span key={detail}>{detail}</span>)}
    </span>
  )
}

function ProviderRow({
  settings,
  provider,
  index,
  providerSecrets,
  testResults,
  onChange,
  onSecretChange,
  onTestProvider,
}: Readonly<{
  settings: LlmSettings
  provider: LlmProvider
  index: number
  providerSecrets: Record<string, string>
  testResults: Record<string, LlmTestResponse | 'pending'>
  onChange: (settings: LlmSettings) => void
  onSecretChange: (providerId: string, value: string) => void
  onTestProvider: (providerId: string) => void
}>) {
  const providerName = provider.label || provider.provider_id || `Provider ${index + 1}`
  const testKey = `provider:${provider.provider_id}`
  const updateProvider = (update: Partial<LlmProvider>) => {
    onChange({
      ...settings,
      providers: updateAt(settings.providers, index, (item) => ({ ...item, ...update })),
    })
  }
  return (
    <article className="settings-row" key={`${provider.provider_id}-${index}`}>
      <label>
        <span>Provider id</span>
        <input
          aria-label={`${providerName} provider id`}
          value={provider.provider_id}
          onChange={(event) => updateProvider({ provider_id: event.target.value })}
        />
      </label>
      <label>
        <span>Label</span>
        <input
          aria-label={`${providerName} label`}
          value={provider.label}
          onChange={(event) => updateProvider({ label: event.target.value })}
        />
      </label>
      <label>
        <span>API format</span>
        <select
          aria-label={`${providerName} API format`}
          value={provider.api_format}
          onChange={(event) => updateProvider({ api_format: event.target.value as ProviderApiFormat })}
        >
          <option value="openai_compatible">OpenAI compatible</option>
          <option value="anthropic_messages">Anthropic messages</option>
        </select>
      </label>
      <label className="settings-field-wide">
        <span>Base URL</span>
        <input
          aria-label={`${providerName} base URL`}
          value={provider.base_url}
          onChange={(event) => updateProvider({ base_url: event.target.value })}
        />
      </label>
      <label>
        <span>Environment variable name</span>
        <input
          aria-label={`${providerName} API key environment variable`}
          placeholder={provider.api_key_env || 'OPENROUTER_API_KEY'}
          value={provider.api_key_env}
          onChange={(event) => updateProvider({ api_key_env: event.target.value })}
        />
      </label>
      <label>
        <span>API key secret</span>
        <input
          aria-label={`${providerName} API key secret`}
          type="password"
          autoComplete="off"
          placeholder={provider.api_key_configured ? 'Configured; paste to replace' : 'Paste key to store server-side'}
          value={providerSecrets[provider.provider_id] || ''}
          onChange={(event) => onSecretChange(provider.provider_id, event.target.value)}
        />
      </label>
      <label className="settings-checkbox">
        <input
          aria-label={`${providerName} enabled`}
          type="checkbox"
          checked={provider.enabled}
          onChange={(event) => updateProvider({ enabled: event.target.checked })}
        />
        <span>Enabled</span>
      </label>
      <div className="settings-actions">
        <span className="settings-status">{providerStatus(provider)}</span>
        <button className="secondary-button settings-small-button" type="button" onClick={() => onTestProvider(provider.provider_id)}>Test</button>
        <button className="danger-button settings-small-button" type="button" onClick={() => onChange(pruneDeletedProvider(settings, provider.provider_id))}>Delete</button>
        <TestResult result={testResults[testKey]} />
      </div>
    </article>
  )
}

function ProviderRows({
  settings,
  providerSecrets,
  testResults,
  onChange,
  onSecretChange,
  onTestProvider,
}: Readonly<{
  settings: LlmSettings
  providerSecrets: Record<string, string>
  testResults: Record<string, LlmTestResponse | 'pending'>
  onChange: (settings: LlmSettings) => void
  onSecretChange: (providerId: string, value: string) => void
  onTestProvider: (providerId: string) => void
}>) {
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
        {settings.providers.map((provider, index) => (
          <ProviderRow
            key={`${provider.provider_id}-${index}`}
            settings={settings}
            provider={provider}
            index={index}
            providerSecrets={providerSecrets}
            testResults={testResults}
            onChange={onChange}
            onSecretChange={onSecretChange}
            onTestProvider={onTestProvider}
          />
        ))}
      </div>
    </section>
  )
}

function ModelRow({
  settings,
  model,
  index,
  health,
  testResults,
  onChange,
  onTestModel,
}: Readonly<{
  settings: LlmSettings
  model: LlmModel
  index: number
  health?: LlmModelHealthRow
  testResults: Record<string, LlmTestResponse | 'pending'>
  onChange: (settings: LlmSettings) => void
  onTestModel: (model: LlmModel) => void
}>) {
  const modelName = model.label || model.model_id
  const testKey = `model:${model.provider_id}:${model.model_id}`
  const updateModel = (update: Partial<LlmModel>) => {
    onChange({
      ...settings,
      models: updateAt(settings.models, index, (item) => ({ ...item, ...update })),
    })
  }
  return (
    <article className="settings-row settings-row--model" key={`${model.model_id}-${index}`}>
      <label className="settings-field-wide">
        <span>Model id</span>
        <input
          aria-label={`${modelName} model id`}
          value={model.model_id}
          onChange={(event) => updateModel({ model_id: event.target.value })}
        />
      </label>
      <label>
        <span>Provider</span>
        <select
          aria-label={`${modelName} provider`}
          value={model.provider_id}
          onChange={(event) => updateModel({ provider_id: event.target.value })}
        >
          {settings.providers.map((provider) => (
            <option key={provider.provider_id} value={provider.provider_id}>
              {provider.label || provider.provider_id}
            </option>
          ))}
        </select>
      </label>
      <label>
        <span>Label</span>
        <input
          aria-label={`${modelName} label`}
          value={model.label}
          onChange={(event) => updateModel({ label: event.target.value })}
        />
      </label>
      <label>
        <span>Weight</span>
        <input
          aria-label={`${modelName} weight`}
          type="range"
          min={0}
          max={100}
          value={model.weight}
          onChange={(event) => updateModel({ weight: Number(event.target.value) })}
        />
        <span className="settings-range-value">{model.weight}</span>
      </label>
      <label className="settings-checkbox">
        <input
          aria-label={`${modelName} enabled`}
          type="checkbox"
          checked={model.enabled}
          onChange={(event) => updateModel({ enabled: event.target.checked })}
        />
        <span>Enabled</span>
      </label>
      <div className="settings-actions">
        <HealthResult health={health} />
        <button className="secondary-button settings-small-button" type="button" onClick={() => onTestModel(model)}>Test</button>
        <button className="danger-button settings-small-button" type="button" onClick={() => onChange(pruneDeletedModel(settings, model.model_id))}>Delete</button>
        <TestResult result={testResults[testKey]} />
      </div>
      {model.notes ? <p className="settings-note">{model.notes}</p> : null}
    </article>
  )
}

function ModelRows({
  settings,
  modelHealth,
  testResults,
  onChange,
  onTestModel,
}: Readonly<{
  settings: LlmSettings
  modelHealth?: LlmModelHealth
  testResults: Record<string, LlmTestResponse | 'pending'>
  onChange: (settings: LlmSettings) => void
  onTestModel: (model: LlmModel) => void
}>) {
  const healthByModel = useMemo(() => new Map(
    (modelHealth?.models || []).map((row) => [`${row.provider_id}:${row.model_id}`, row]),
  ), [modelHealth])
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
                weight: 35,
              },
            ],
          })}
        >
          Add model
        </button>
      </div>
      <div className="settings-table">
        {settings.models.map((model, index) => (
          <ModelRow
            key={`${model.model_id}-${index}`}
            settings={settings}
            model={model}
            index={index}
            health={healthByModel.get(`${model.provider_id}:${model.model_id}`)}
            testResults={testResults}
            onChange={onChange}
            onTestModel={onTestModel}
          />
        ))}
      </div>
    </section>
  )
}

function WorkflowCard({
  settings,
  workflow,
  index,
  options,
  onChange,
}: Readonly<{
  settings: LlmSettings
  workflow: LlmWorkflow
  index: number
  options: { value: string; label: string }[]
  onChange: (settings: LlmSettings) => void
}>) {
  const selectedModels = new Set(workflow.model_pool)
  const selectedProviders = new Set(workflow.provider_ids)
  const availableDefaults = options.filter((option) => selectedModels.has(option.value))
  const updateWorkflow = (update: (workflow: LlmWorkflow) => LlmWorkflow) => {
    onChange({
      ...settings,
      workflows: updateAt(settings.workflows, index, update),
    })
  }
  const updateModelPool = (modelId: string, enabled: boolean) => {
    updateWorkflow((item) => {
      const modelPool = toggleItem(item.model_pool, modelId, enabled)
      return {
        ...item,
        model_pool: modelPool,
        provider_ids: providerIdsForModels(settings.models, modelPool),
        default_model: modelPool.includes(item.default_model) ? item.default_model : modelPool[0] || '',
      }
    })
  }
  return (
    <article className="workflow-card" key={workflow.workflow_id}>
      <div className="workflow-card-head">
        <div>
          <p className="eyebrow">{workflow.workflow_id.replaceAll('_', ' ')}</p>
          <input
            className="workflow-title-input"
            value={workflow.label}
            onChange={(event) => updateWorkflow((item) => ({ ...item, label: event.target.value }))}
          />
        </div>
        <label className="settings-checkbox">
          <input
            aria-label={`${workflow.label} enabled`}
            type="checkbox"
            checked={workflow.enabled}
            onChange={(event) => updateWorkflow((item) => ({ ...item, enabled: event.target.checked }))}
          />
          <span>Enabled</span>
        </label>
      </div>
      <fieldset className="settings-choice-group">
        <legend>Providers</legend>
        {settings.providers.map((provider) => (
          <label className="settings-checkbox" key={provider.provider_id}>
            <input
              aria-label={`${workflow.label} provider ${provider.provider_id}`}
              type="checkbox"
              checked={selectedProviders.has(provider.provider_id)}
              onChange={(event) => updateWorkflow((item) => ({
                ...item,
                provider_ids: toggleItem(item.provider_ids, provider.provider_id, event.target.checked),
              }))}
            />
            <span>{provider.label || provider.provider_id}</span>
          </label>
        ))}
      </fieldset>
      <label>
        <span>Default model</span>
        <select
          aria-label={`${workflow.label} default model`}
          value={workflow.default_model}
          onChange={(event) => updateWorkflow((item) => ({ ...item, default_model: event.target.value }))}
        >
          {availableDefaults.map((model) => (
            <option key={model.value} value={model.value}>
              {model.label}
            </option>
          ))}
        </select>
      </label>
      <fieldset className="settings-choice-group">
        <legend>Model pool</legend>
        {settings.models.map((model) => (
          <label className="settings-checkbox" key={model.model_id}>
            <input
              aria-label={`${workflow.label} model ${model.model_id}`}
              type="checkbox"
              checked={selectedModels.has(model.model_id)}
              onChange={(event) => updateModelPool(model.model_id, event.target.checked)}
            />
            <span>{model.label || model.model_id}</span>
          </label>
        ))}
      </fieldset>
      <div className="settings-row settings-row--compact">
        <label>
          <span>Temperature</span>
          <input
            aria-label={`${workflow.label} temperature`}
            type="number"
            min={0}
            max={2}
            step={0.1}
            value={workflow.temperature}
            onChange={(event) => updateWorkflow((item) => ({ ...item, temperature: Number(event.target.value) }))}
          />
        </label>
        <label>
          <span>Max tokens</span>
          <input
            aria-label={`${workflow.label} max tokens`}
            type="number"
            min={512}
            value={workflow.max_tokens}
            onChange={(event) => updateWorkflow((item) => ({ ...item, max_tokens: Number(event.target.value) }))}
          />
        </label>
      </div>
    </article>
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
        <button className="secondary-button" type="button" onClick={() => onChange(applyRecommendedRouting(settings))}>
          Apply recommended routing
        </button>
      </div>
      <div className="workflow-grid">
        {settings.workflows.map((workflow, index) => (
          <WorkflowCard
            key={workflow.workflow_id}
            settings={settings}
            workflow={workflow}
            index={index}
            options={options}
            onChange={onChange}
          />
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
  const [providerSecrets, setProviderSecrets] = useState<Record<string, string>>({})
  const [testResults, setTestResults] = useState<Record<string, LlmTestResponse | 'pending'>>({})
  useEffect(() => {
    if (query.data?.settings) setDraft(query.data.settings)
  }, [query.data])
  const mutation = useMutation({
    mutationFn: (settings: LlmSettings) => {
      const secrets = Object.fromEntries(Object.entries(providerSecrets).filter(([, value]) => value.trim()))
      return apiPost<Record<string, unknown>>('/control/api/settings/llm', { requested_by: 'dashboard-v2', settings: sanitizeSettingsForSave(settings), provider_secrets: secrets })
    },
    onSuccess: () => {
      setProviderSecrets({})
      query.refetch()
    },
  })
  const testMutation = useMutation({
    mutationFn: (payload: { provider_id: string; model_id?: string }) => apiPost<LlmTestResponse>('/control/api/settings/llm/test', payload),
  })
  const runProviderTest = (providerId: string) => {
    const key = `provider:${providerId}`
    setTestResults((current) => ({ ...current, [key]: 'pending' }))
    testMutation.mutate(
      { provider_id: providerId },
      {
        onSuccess: (result) => setTestResults((current) => ({ ...current, [key]: result })),
        onError: (error) => setTestResults((current) => ({ ...current, [key]: { ok: false, provider_id: providerId, model_id: '', status_code: 0, latency_ms: 0, error: String(error) } })),
      },
    )
  }
  const runModelTest = (model: LlmModel) => {
    const key = `model:${model.provider_id}:${model.model_id}`
    setTestResults((current) => ({ ...current, [key]: 'pending' }))
    testMutation.mutate(
      { provider_id: model.provider_id, model_id: model.model_id },
      {
        onSuccess: (result) => setTestResults((current) => ({ ...current, [key]: result })),
        onError: (error) => setTestResults((current) => ({ ...current, [key]: { ok: false, provider_id: model.provider_id, model_id: model.model_id, status_code: 0, latency_ms: 0, error: String(error) } })),
      },
    )
  }
  if (query.isLoading) return <LoadingStateCard label="LLM settings" />
  if (query.error) return <InlineErrorStateCard prefix="Settings load failed" message={String(query.error)} />
  if (!draft) return <InlineErrorStateCard prefix="Settings unavailable" message="No settings payload returned." />
  const validationErrors = validateDraftSettings(draft)
  const blockingErrors = validationErrors.filter((error) => !error.includes('Save will store this value as a one-time provider secret'))

  return (
    <PageShell
      title="LLM settings"
      subtitle="Providers, model catalog, and workflow model pools"
      dataSource={`${displayText(query.data?.path, 'default settings')} ${query.data?.persisted ? 'persisted' : 'defaults'}`}
      action={(
        <button className="primary-button" type="button" disabled={mutation.isPending || blockingErrors.length > 0} onClick={() => mutation.mutate(draft)}>
          {mutation.isPending ? 'Saving settings' : 'Save settings'}
        </button>
      )}
    >
      {mutation.error ? <InlineErrorStateCard prefix="Settings save failed" message={String(mutation.error)} /> : null}
      {mutation.data ? <section className="state-card state-card--compact">Settings saved.</section> : null}
      <SettingsValidationCard errors={validationErrors} />
      <ProviderRows
        settings={draft}
        providerSecrets={providerSecrets}
        testResults={testResults}
        onChange={setDraft}
        onSecretChange={(providerId, value) => setProviderSecrets((current) => ({ ...current, [providerId]: value }))}
        onTestProvider={runProviderTest}
      />
      <ModelRows settings={draft} modelHealth={query.data?.model_health} testResults={testResults} onChange={setDraft} onTestModel={runModelTest} />
      <WorkflowRows settings={draft} onChange={setDraft} />
    </PageShell>
  )
}
