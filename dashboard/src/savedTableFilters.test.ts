import { afterEach, expect, it } from 'vitest'
import {
  deleteTableFilterPreset,
  loadSavedTableFilters,
  saveTableFilterPreset,
  SAVED_TABLE_FILTERS_STORAGE_KEY,
} from './savedTableFilters'

afterEach(() => {
  window.localStorage.removeItem(SAVED_TABLE_FILTERS_STORAGE_KEY)
})

it('persists queue filter presets in localStorage', () => {
  saveTableFilterPreset('queue', {
    name: 'Queued watch',
    search: 'oracle',
    status: 'queued',
    pageSize: '25',
  })

  const presets = loadSavedTableFilters('queue')
  expect(presets).toHaveLength(1)
  expect(presets[0]?.name).toBe('Queued watch')
  expect(presets[0]?.search).toBe('oracle')
  expect(presets[0]?.status).toBe('queued')
  expect(presets[0]?.pageSize).toBe('25')
})

it('replaces queue presets with the same name', () => {
  saveTableFilterPreset('queue', { name: 'Active lane', search: '', status: 'active', pageSize: '50' })
  saveTableFilterPreset('queue', { name: 'Active lane', search: 'gb10', status: 'active', pageSize: '25' })

  const presets = loadSavedTableFilters('queue')
  expect(presets).toHaveLength(1)
  expect(presets[0]?.search).toBe('gb10')
  expect(presets[0]?.pageSize).toBe('25')
})

it('deletes saved queue presets by id', () => {
  saveTableFilterPreset('queue', { name: 'One', search: 'a', status: '', pageSize: '50' })
  const [preset] = loadSavedTableFilters('queue')
  const next = deleteTableFilterPreset('queue', preset.id)
  expect(next).toHaveLength(0)
  expect(loadSavedTableFilters('queue')).toHaveLength(0)
})
