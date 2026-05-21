import { FormEvent, useEffect, useState } from 'react'

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
}: {
  state: ListFilterState
  statusOptions: { label: string; value: string }[]
  statusLabel?: string
  onApply: (next: ListFilterState) => void
  onNext: () => void
  onReset: () => void
  page?: ListPageMeta
}) {
  const [draft, setDraft] = useState(state)
  useEffect(() => {
    setDraft(state)
  }, [state])

  function submit(event: FormEvent) {
    event.preventDefault()
    onApply({ ...draft, cursor: '' })
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
      <button className="secondary-button" type="button" onClick={() => { setDraft({ search: '', status: '', pageSize: '50', cursor: '' }); onReset() }}>Reset</button>
      <button className="secondary-button" type="button" disabled={!page?.has_more} onClick={onNext}>Next page</button>
      <span>Showing {page?.returned ?? 0}</span>
    </form>
  )
}
