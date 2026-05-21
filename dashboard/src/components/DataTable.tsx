import { MouseEvent, ReactNode, useState } from 'react'
import type { ComposedEmptyStateCopy } from '../resourceStatePresentation'
import { columnLinkHref, resolveColumnTone, resolveColumnValue, shortTableId, type TableColumnSpec } from '../tablePresentation'
import { ComposedEmptyState } from './ResourceStateCards'

type Row = Record<string, unknown>

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

function formatFallback(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="muted-value">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return <code className="json-inline">{JSON.stringify(value)}</code>
  return String(value)
}

function IdCell({ column, idValue, href }: { column: TableColumnSpec; idValue: string; href?: string }) {
  const [copied, setCopied] = useState(false)
  async function copy(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    await copyToClipboard(idValue)
    setCopied(true)
    window.setTimeout(() => setCopied(false), 1200)
  }
  return (
    <span className="table-id-chip" title={idValue}>
      {href
        ? <a className="cell-link" href={href} onClick={(event) => event.stopPropagation()}>{shortTableId(idValue)}</a>
        : <span>{shortTableId(idValue)}</span>}
      <button className="copy-button copy-button--subtle" type="button" onClick={copy} aria-label={`Copy ${column.label} ${idValue}`}>
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  )
}

function CellValue({
  column,
  row,
  href,
}: {
  column: TableColumnSpec
  row: Row
  href?: string
}) {
  const raw = resolveColumnValue(row, column)
  const tone = resolveColumnTone(row, column)
  const text = raw === null || raw === undefined || raw === '' ? '—' : String(raw)

  if (column.kind === 'id') {
    const idValue = String(row[column.key] || (text === '—' ? '' : text))
    if (!idValue || idValue === '—') return <span className="muted-value">—</span>
    return <IdCell column={column} idValue={idValue} href={href} />
  }

  if (column.kind === 'primary') {
    const content = text === '—' ? formatFallback(raw) : text
    return href
      ? <a className="cell-link cell-primary cell-truncate" href={href} onClick={(event) => event.stopPropagation()} title={text}>{content}</a>
      : <span className="cell-primary cell-truncate" title={text}>{content}</span>
  }

  if (column.kind === 'link') {
    if (text === '—') return <span className="muted-value">—</span>
    return href
      ? <a className="cell-link cell-truncate" href={href} onClick={(event) => event.stopPropagation()} title={text}>{text}</a>
      : <span className="cell-truncate" title={text}>{text}</span>
  }

  if (column.kind === 'status' || tone) {
    const toneClass = tone ? ` table-status--${tone}` : ''
    return <span className={`table-status${toneClass}`}>{text}</span>
  }

  const formatted = formatFallback(raw)
  return href
    ? <a className="cell-link cell-truncate" href={href} onClick={(event) => event.stopPropagation()} title={text}>{formatted}</a>
    : <span className="cell-truncate" title={text}>{formatted}</span>
}

function rowKey(row: Row, index: number): string {
  return String(row.project_id || row.run_id || row.paper_id || row.event_id || row.id || index)
}

export function DataTable({
  rows,
  columns,
  empty,
  onSelectRow,
  cellHref,
}: {
  rows: Row[]
  columns: TableColumnSpec[]
  empty: string | ComposedEmptyStateCopy
  onSelectRow?: (row: Row) => void
  cellHref?: (row: Row, column: string) => string | undefined
}) {
  if (!rows.length) {
    if (typeof empty === 'string') {
      return <div className="empty-table">{empty}</div>
    }
    return <ComposedEmptyState state={empty} />
  }
  return (
    <div className="data-table-wrap">
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>{columns.map((column) => <th key={column.key} className={column.kind === 'primary' ? 'data-table-col--primary' : undefined}>{column.label}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={rowKey(row, index)} className={onSelectRow ? 'selectable-row' : ''} onClick={() => onSelectRow?.(row)}>
                {columns.map((column) => {
                  const allowLink = !onSelectRow || column.kind === 'id' || column.kind === 'link'
                  const href = allowLink ? (cellHref?.(row, column.key) ?? columnLinkHref(row, column)) : undefined
                  const value = resolveColumnValue(row, column)
                  return (
                    <td key={column.key} className={column.kind === 'primary' ? 'data-table-col--primary' : undefined} title={typeof value === 'string' ? value : undefined}>
                      <CellValue column={column} row={row} href={href} />
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
