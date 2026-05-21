export type SavedTableFilterTableId = 'queue' | 'projects'

export type SavedTableFilterPreset = {
  id: string
  name: string
  search: string
  status: string
  pageSize: string
}

export type SavedTableFilterDraft = Omit<SavedTableFilterPreset, 'id'>

export const SAVED_TABLE_FILTERS_STORAGE_KEY = 'enochDashboardSavedTableFilters'

type SavedTableFilterStore = Partial<Record<SavedTableFilterTableId, SavedTableFilterPreset[]>>

function readStore(): SavedTableFilterStore {
  const storage = globalThis.window?.localStorage
  const raw = storage?.getItem(SAVED_TABLE_FILTERS_STORAGE_KEY)
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw) as SavedTableFilterStore
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeStore(store: SavedTableFilterStore): void {
  globalThis.window?.localStorage?.setItem(SAVED_TABLE_FILTERS_STORAGE_KEY, JSON.stringify(store))
}

function normalizePreset(value: unknown): SavedTableFilterPreset | null {
  if (!value || typeof value !== 'object') return null
  const record = value as Record<string, unknown>
  const name = String(record.name || '').trim()
  if (!name) return null
  return {
    id: String(record.id || '').trim() || crypto.randomUUID(),
    name,
    search: String(record.search || ''),
    status: String(record.status || ''),
    pageSize: String(record.pageSize || '50'),
  }
}

function readTablePresetEntries(tableId: SavedTableFilterTableId): unknown[] {
  const presets = readStore()[tableId]
  return Array.isArray(presets) ? presets : []
}

export function loadSavedTableFilters(tableId: SavedTableFilterTableId): SavedTableFilterPreset[] {
  return readTablePresetEntries(tableId)
    .map(normalizePreset)
    .filter((preset): preset is SavedTableFilterPreset => Boolean(preset))
}

export function saveTableFilterPreset(tableId: SavedTableFilterTableId, draft: SavedTableFilterDraft): SavedTableFilterPreset[] {
  const store = readStore()
  const current = readTablePresetEntries(tableId)
    .map(normalizePreset)
    .filter((preset): preset is SavedTableFilterPreset => Boolean(preset))
  const nextPreset: SavedTableFilterPreset = {
    id: crypto.randomUUID(),
    name: draft.name.trim(),
    search: draft.search,
    status: draft.status,
    pageSize: draft.pageSize,
  }
  const next = [...current.filter((preset) => preset.name !== nextPreset.name), nextPreset]
  store[tableId] = next
  writeStore(store)
  return next
}

export function deleteTableFilterPreset(tableId: SavedTableFilterTableId, presetId: string): SavedTableFilterPreset[] {
  const store = readStore()
  const next = loadSavedTableFilters(tableId).filter((preset) => preset.id !== presetId)
  store[tableId] = next
  writeStore(store)
  return next
}
