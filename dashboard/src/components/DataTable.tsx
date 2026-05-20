import { ReactNode } from 'react'

type Row = Record<string, unknown>

function formatValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="text-zinc-600">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return <code className="text-xs text-zinc-400">{JSON.stringify(value)}</code>
  return String(value)
}

function rowKey(row: Row, index: number): string {
  return String(row.project_id || row.run_id || row.paper_id || row.event_id || row.id || index)
}

export function DataTable({ rows, columns, empty, onSelectRow }: { rows: Row[]; columns: string[]; empty: string; onSelectRow?: (row: Row) => void }) {
  if (!rows.length) {
    return <div className="rounded-2xl border border-dashed border-zinc-800 bg-black/20 p-8 text-center text-sm text-zinc-500">{empty}</div>
  }
  return (
    <div className="overflow-hidden rounded-2xl border border-zinc-800">
      <div className="max-h-[60vh] overflow-auto">
        <table className="min-w-full divide-y divide-zinc-800 text-sm">
          <thead className="sticky top-0 bg-zinc-950 text-left text-xs uppercase tracking-[0.16em] text-zinc-500">
            <tr>{columns.map((column) => <th key={column} className="px-4 py-3 font-bold">{column.replaceAll('_', ' ')}</th>)}</tr>
          </thead>
          <tbody className="divide-y divide-zinc-900 bg-black/20 text-zinc-300">
            {rows.map((row, index) => (
              <tr key={rowKey(row, index)} className={onSelectRow ? 'cursor-pointer hover:bg-zinc-900/60' : 'hover:bg-zinc-900/60'} onClick={() => onSelectRow?.(row)}>
                {columns.map((column) => <td key={column} className="max-w-[24rem] truncate px-4 py-3 align-top tabular-nums" title={typeof row[column] === 'string' ? String(row[column]) : undefined}>{formatValue(row[column])}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
