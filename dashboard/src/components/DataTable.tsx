import { MouseEvent, ReactNode, useState } from 'react'

type Row = Record<string, unknown>

function formatValue(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="muted-value">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return <code className="json-inline">{JSON.stringify(value)}</code>
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
  if (!isCopyableColumn(column)) return <span className="cell-truncate" title={text}>{text}</span>
  async function copy(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    await copyToClipboard(text)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }
  return (
    <span className="copy-cell">
      <span className="cell-truncate" title={text}>{text}</span>
      <button className="copy-button" type="button" onClick={copy} aria-label={`Copy ${column.replaceAll('_', ' ')} ${text}`}>{copied ? 'Copied' : 'Copy'}</button>
    </span>
  )
}

function rowKey(row: Row, index: number): string {
  return String(row.project_id || row.run_id || row.paper_id || row.event_id || row.id || index)
}

export function DataTable({ rows, columns, empty, onSelectRow }: { rows: Row[]; columns: string[]; empty: string; onSelectRow?: (row: Row) => void }) {
  if (!rows.length) {
    return <div className="empty-table">{empty}</div>
  }
  return (
    <div className="data-table-wrap">
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>{columns.map((column) => <th key={column}>{column.replaceAll('_', ' ')}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={rowKey(row, index)} className={onSelectRow ? 'selectable-row' : ''} onClick={() => onSelectRow?.(row)}>
                {columns.map((column) => <td key={column} title={typeof row[column] === 'string' ? String(row[column]) : undefined}><CellValue column={column} value={row[column]} /></td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
