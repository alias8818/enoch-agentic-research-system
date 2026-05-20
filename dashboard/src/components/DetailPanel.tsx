import { apiGet } from '../api/client'
import { useQuery } from '@tanstack/react-query'

type DetailKind = 'project' | 'paper' | 'event'

type DetailSelection = {
  kind: DetailKind
  id: string
  row?: Record<string, unknown>
}

function endpoint(selection: DetailSelection): string | null {
  if (selection.kind === 'project') return `/control/api/v1/projects/${encodeURIComponent(selection.id)}`
  if (selection.kind === 'paper') return `/control/api/v1/papers/${encodeURIComponent(selection.id)}`
  return null
}

function DetailBody({ selection }: { selection: DetailSelection }) {
  const url = endpoint(selection)
  const query = useQuery({
    queryKey: ['detail', selection.kind, selection.id],
    queryFn: () => apiGet<Record<string, unknown>>(url || ''),
    enabled: Boolean(url),
    retry: false,
  })
  if (!url) {
    return <pre className="mt-4 max-h-[70vh] overflow-auto rounded-2xl bg-black/40 p-4 text-xs text-zinc-300">{JSON.stringify(selection.row || {}, null, 2)}</pre>
  }
  if (query.isLoading) return <div className="mt-4 rounded-2xl border border-zinc-800 bg-black/20 p-4 text-zinc-400">Loading detail…</div>
  if (query.isError) return <div className="mt-4 rounded-2xl border border-red-900 bg-red-950/40 p-4 text-red-100">Detail unavailable: {String(query.error.message)}</div>
  return <pre className="mt-4 max-h-[70vh] overflow-auto rounded-2xl bg-black/40 p-4 text-xs text-zinc-300">{JSON.stringify(query.data, null, 2)}</pre>
}

export function DetailPanel({ selection, onClose }: { selection: DetailSelection | null; onClose: () => void }) {
  if (!selection) return null
  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-full max-w-2xl flex-col border-l border-zinc-800 bg-zinc-950 p-5 shadow-2xl shadow-black/60" aria-label="Dashboard detail panel">
      <div className="flex items-start justify-between gap-4 border-b border-zinc-800 pb-4">
        <div>
          <p className="text-xs font-bold uppercase tracking-[0.24em] text-sky-300">{selection.kind} detail</p>
          <h2 className="mt-2 text-xl font-black text-white">{selection.id}</h2>
        </div>
        <button className="rounded-lg border border-zinc-700 px-3 py-2 text-sm font-bold text-white" type="button" onClick={onClose}>Close</button>
      </div>
      <DetailBody selection={selection} />
    </aside>
  )
}
