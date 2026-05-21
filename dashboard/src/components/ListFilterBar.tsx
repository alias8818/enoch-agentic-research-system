import { FormEvent, useEffect, useState } from 'react'
import {
  deleteTableFilterPreset,
  loadSavedTableFilters,
  saveTableFilterPreset,
  type SavedTableFilterTableId,
} from '../savedTableFilters'

export type ListFilterState = { search: string; status: string; pageSize: string; cursor: string }
export type ListPageMeta = { next_cursor?: string; has_more?: boolean; returned?: number; page_size?: number }

export function hashQuery(entries: [string, string][]): string {
  const params = new URLSearchParams()
  entries.forEach(([key, value]) => {
    if (value) params.set(key, value)
  })
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function ListFilterBar({
  state,
  statusOptions,
  statusLabel = 'Status',
  onApply,
  onNext,
  onReset,
  page,
  savedFiltersTableId,
}: {
  state: ListFilterState
  statusOptions: { label: string; value: string }[]
  statusLabel?: string
  onApply: (next: ListFilterState) => void
  onNext: () => void
  onReset: () => void
  page?: ListPageMeta
  savedFiltersTableId?: SavedTableFilterTableId
}) {
  const [draft, setDraft] = useState(state)
  const [savedPresets, setSavedPresets] = useState(() => (savedFiltersTableId ? loadSavedTableFilters(savedFiltersTableId) : []))
  const [selectedPresetId, setSelectedPresetId] = useState('')
  const [saveName, setSaveName] = useState('')
  const [showSaveInput, setShowSaveInput] = useState(false)
  useEffect(() => {
    setDraft(state)
  }, [state])
  useEffect(() => {
    if (!savedFiltersTableId) return
    setSavedPresets(loadSavedTableFilters(savedFiltersTableId))
    setSelectedPresetId('')
  }, [savedFiltersTableId])

  function submit(event: FormEvent) {
    event.preventDefault()
    onApply({ ...draft, cursor: '' })
  }

  function applyPreset(presetId: string) {
    setSelectedPresetId(presetId)
    const preset = savedPresets.find((entry) => entry.id === presetId)
    if (!preset) return
    const next = { search: preset.search, status: preset.status, pageSize: preset.pageSize, cursor: '' }
    setDraft(next)
    onApply(next)
  }

  function handleSavePreset() {
    if (!savedFiltersTableId) return
    const trimmed = saveName.trim()
    if (!trimmed) return
    const next = saveTableFilterPreset(savedFiltersTableId, {
      name: trimmed,
      search: draft.search,
      status: draft.status,
      pageSize: draft.pageSize,
    })
    setSavedPresets(next)
    setSaveName('')
    setShowSaveInput(false)
    const saved = next.find((entry) => entry.name === trimmed)
    if (saved) setSelectedPresetId(saved.id)
  }

  function handleDeletePreset() {
    if (!savedFiltersTableId || !selectedPresetId) return
    const next = deleteTableFilterPreset(savedFiltersTableId, selectedPresetId)
    setSavedPresets(next)
    setSelectedPresetId('')
  }

  return (
    <form className="filter-bar" onSubmit={submit}>
      <label>Search
        <input value={draft.search} onChange={(event) => setDraft({ ...draft, search: event.target.value })} placeholder="Search" />
      </label>
      <label>{statusLabel}
        <select value={draft.status} onChange={(event) => setDraft({ ...draft, status: event.target.value })}>
          {statusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
        </select>
      </label>
      <label>Size
        <select value={draft.pageSize} onChange={(event) => setDraft({ ...draft, pageSize: event.target.value })}>
          {['25', '50', '100', '200'].map((value) => <option key={value} value={value}>{value}</option>)}
        </select>
      </label>
      <button className="primary-button" type="submit">Apply filters</button>
      <button className="secondary-button" type="button" onClick={() => { setDraft({ search: '', status: '', pageSize: '50', cursor: '' }); setSelectedPresetId(''); onReset() }}>Reset</button>
      <button className="secondary-button" type="button" disabled={!page?.has_more} onClick={onNext}>Next page</button>
      {savedFiltersTableId ? (
        <div className="filter-bar-saved">
          <label>Saved filters
            <select value={selectedPresetId} onChange={(event) => applyPreset(event.target.value)}>
              <option value="">Choose saved filter</option>
              {savedPresets.map((preset) => <option key={preset.id} value={preset.id}>{preset.name}</option>)}
            </select>
          </label>
          {showSaveInput ? (
            <div className="filter-bar-save-form">
              <label className="filter-bar-save-label">Preset name
                <input value={saveName} onChange={(event) => setSaveName(event.target.value)} placeholder="Queued GB10 watch" />
              </label>
              <button className="secondary-button" type="button" disabled={!saveName.trim()} onClick={handleSavePreset}>Save preset</button>
              <button className="secondary-button" type="button" onClick={() => { setShowSaveInput(false); setSaveName('') }}>Cancel</button>
            </div>
          ) : (
            <button className="secondary-button" type="button" onClick={() => setShowSaveInput(true)}>Save current</button>
          )}
          <button className="secondary-button" type="button" disabled={!selectedPresetId} onClick={handleDeletePreset}>Delete saved</button>
        </div>
      ) : null}
      <span>Showing {page?.returned ?? 0}</span>
    </form>
  )
}
