import { MouseEvent, ReactNode, useState } from 'react'

type Row = Record<string, unknown>

function formatValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="text-zinc-600">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return <code className="text-xs text-zinc-400">{JSON.stringify(value)}</code>
  return String(value)
}


function isCopyableColumn(column: string): boolean {
  return column === 'id' || column.endsWith('_id') || column === 'run_id'
}

async function copyToClipboard(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text)
    return
  }
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', 'true')
  textarea.style.position = 'fixed'
  textarea.style.opacity = '0'
  document.body.appendChild(textarea)
  textarea.select()
  document.execCommand('copy')
  document.body.removeChild(textarea)
}

function CellValue({ column, value }: { column: string; value: unknown }) {
  const [copied, setCopied] = useState(false)
  if (typeof value !== 'string' || !value) return formatValue(value)
  const text = value
  if (!isCopyableColumn(column)) return <span className="block truncate" title={text}>{text}</span>
  async function copy(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    await copyToClipboard(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }
  return (
    <span className="inline-flex max-w-full items-center gap-2">
      <span className="min-w-0 truncate" title={text}>{text}</span>
      <button className="rounded-md border border-zinc-700 px-1.5 py-0.5 text-[0.65rem] font-bold uppercase tracking-wide text-zinc-300 hover:border-sky-500 hover:text-white" type="button" onClick={copy} aria-label={`Copy ${column.replaceAll('_', ' ')} ${text}`}>{copied ? 'Copied' : 'Copy'}</button>
    </span>
  )
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
                {columns.map((column) => <td key={column} className="max-w-[24rem] px-4 py-3 align-top tabular-nums" title={typeof row[column] === 'string' ? String(row[column]) : undefined}><CellValue column={column} value={row[column]} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
