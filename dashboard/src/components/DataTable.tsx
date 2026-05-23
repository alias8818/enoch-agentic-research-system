import { MouseEvent, ReactNode, useState } from 'react'
import { displayText } from '../displayText'
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
  textarea.remove()
}

function formatFallback(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="muted-value">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return <code className="json-inline">{JSON.stringify(value)}</code>
  return displayText(value)
}

function IdCell({ column, idValue, href }: Readonly<{ column: TableColumnSpec; idValue: string; href?: string }>) {
  const [copied, setCopied] = useState(false)
  async function copy(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    await copyToClipboard(idValue)
    setCopied(true)
    globalThis.setTimeout(() => setCopied(false), 1200)
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

function cellDisplayText(raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '—'
  return displayText(raw)
}

function CellLinkWrap({
  href,
  className,
  title,
  children,
}: Readonly<{ href?: string; className: string; title: string; children: ReactNode }>) {
  if (href) {
    return (
      <a className={className} href={href} onClick={(event) => event.stopPropagation()} title={title}>
        {children}
      </a>
    )
  }
  return <span className={className} title={title}>{children}</span>
}

function IdColumnCell({
  column,
  row,
  href,
  text,
}: Readonly<{ column: TableColumnSpec; row: Row; href?: string; text: string }>) {
  const fallbackId = text === '—' ? '' : text
  const idValue = displayText(row[column.key], fallbackId)
  if (!idValue || idValue === '—') return <span className="muted-value">—</span>
  return <IdCell column={column} idValue={idValue} href={href} />
}

function PrimaryColumnCell({
  raw,
  href,
  text,
}: Readonly<{ raw: unknown; href?: string; text: string }>) {
  let content: ReactNode = text
  if (text === '—') content = formatFallback(raw)
  const className = href ? 'cell-link cell-primary cell-truncate' : 'cell-primary cell-truncate'
  return <CellLinkWrap href={href} className={className} title={text}>{content}</CellLinkWrap>
}

function LinkColumnCell({ href, text }: Readonly<{ href?: string; text: string }>) {
  if (text === '—') return <span className="muted-value">—</span>
  const className = href ? 'cell-link cell-truncate' : 'cell-truncate'
  return <CellLinkWrap href={href} className={className} title={text}>{text}</CellLinkWrap>
}

function StatusColumnCell({ text, tone }: Readonly<{ text: string; tone?: string }>) {
  const toneClass = tone ? ` table-status--${tone}` : ''
  return <span className={`table-status${toneClass}`}>{text}</span>
}

function DefaultColumnCell({
  raw,
  href,
  text,
}: Readonly<{ raw: unknown; href?: string; text: string }>) {
  const formatted = formatFallback(raw)
  const className = href ? 'cell-link cell-truncate' : 'cell-truncate'
  return <CellLinkWrap href={href} className={className} title={text}>{formatted}</CellLinkWrap>
}

function CellValue({
  column,
  row,
  href,
}: Readonly<{
  column: TableColumnSpec
  row: Row
  href?: string
}>) {
  const raw = resolveColumnValue(row, column)
  const tone = resolveColumnTone(row, column)
  const text = cellDisplayText(raw)

  if (column.kind === 'id') return <IdColumnCell column={column} row={row} href={href} text={text} />
  if (column.kind === 'primary') return <PrimaryColumnCell raw={raw} href={href} text={text} />
  if (column.kind === 'link') return <LinkColumnCell href={href} text={text} />
  if (column.kind === 'status' || tone) return <StatusColumnCell text={text} tone={tone} />
  return <DefaultColumnCell raw={raw} href={href} text={text} />
}

function rowKey(row: Row, index: number): string {
  for (const candidate of [row.project_id, row.run_id, row.paper_id, row.event_id, row.id]) {
    const key = displayText(candidate)
    if (key) return key
  }
  return String(index)
}

export function DataTable({
  rows,
  columns,
  empty,
  onSelectRow,
  cellHref,
}: Readonly<{
  rows: Row[]
  columns: TableColumnSpec[]
  empty: string | ComposedEmptyStateCopy
  onSelectRow?: (row: Row) => void
  cellHref?: (row: Row, column: string) => string | undefined
}>) {
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
              <tr
                key={rowKey(row, index)}
                className={onSelectRow ? 'selectable-row' : undefined}
                tabIndex={onSelectRow ? 0 : undefined}
                onClick={() => onSelectRow?.(row)}
                onKeyDown={(event) => {
                  if (!onSelectRow) return
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    onSelectRow(row)
                  }
                }}
              >
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
