import { KeyboardEvent, MouseEvent, ReactNode, useState } from 'react'
import { displayText } from '../displayText'
import type { ComposedEmptyStateCopy } from '../resourceStatePresentation'
import { columnLinkHref, resolveColumnTone, resolveColumnValue, shortTableId, type TableColumnSpec } from '../tablePresentation'
import { ComposedEmptyState } from './ResourceStateCards'

type Row = Record<string, unknown>

async function copyToClipboard(text: string): Promise<void> {
  if (!navigator.clipboard?.writeText) return
  await navigator.clipboard.writeText(text)
}

function formatObjectPreview(value: object): ReactNode {
  try {
    return <code className="json-inline">{JSON.stringify(value)}</code>
  } catch {
    return <span className="muted-value">—</span>
  }
}

function formatFallback(value: unknown): ReactNode {
  if (value === null || value === undefined || value === '') return <span className="muted-value">—</span>
  if (typeof value === 'boolean') return value ? 'yes' : 'no'
  if (typeof value === 'object') return formatObjectPreview(value)
  return displayText(value)
}

function IdCellLabel({ idValue, href }: Readonly<{ idValue: string; href?: string }>) {
  const label = shortTableId(idValue)
  if (href) {
    return (
      <a className="cell-link" href={href} onClick={(event) => event.stopPropagation()}>
        {label}
      </a>
    )
  }
  return <span>{label}</span>
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
      <IdCellLabel idValue={idValue} href={href} />
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
  if (idValue === '' || idValue === '—') return <span className="muted-value">—</span>
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

function defaultColumnCell(
  column: TableColumnSpec,
  raw: unknown,
  href: string | undefined,
  text: string,
  tone: string | undefined,
): ReactNode {
  if (column.kind === 'status' || tone) return <StatusColumnCell text={text} tone={tone} />
  return <DefaultColumnCell raw={raw} href={href} text={text} />
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

  switch (column.kind) {
    case 'id':
      return <IdColumnCell column={column} row={row} href={href} text={text} />
    case 'primary':
      return <PrimaryColumnCell raw={raw} href={href} text={text} />
    case 'link':
      return <LinkColumnCell href={href} text={text} />
    default:
      return defaultColumnCell(column, raw, href, text, tone)
  }
}

function rowKey(row: Row, index: number): string {
  for (const candidate of [row.project_id, row.run_id, row.paper_id, row.event_id, row.id]) {
    const key = displayText(candidate)
    if (key) return key
  }
  return `${index}`
}

function primaryColumnClass(column: TableColumnSpec): string | undefined {
  return column.kind === 'primary' ? 'data-table-col--primary' : undefined
}

function cellTitle(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function rowAllowsColumnLink(onSelectRow: ((row: Row) => void) | undefined, column: TableColumnSpec): boolean {
  if (onSelectRow === undefined) return true
  return column.kind === 'id' || column.kind === 'link'
}

function resolveDataCellHref(
  row: Row,
  column: TableColumnSpec,
  onSelectRow: ((row: Row) => void) | undefined,
  cellHref: ((row: Row, column: string) => string | undefined) | undefined,
): string | undefined {
  if (!rowAllowsColumnLink(onSelectRow, column)) return undefined
  return cellHref?.(row, column.key) ?? columnLinkHref(row, column)
}

function handleSelectableRowKeyDown(
  event: KeyboardEvent<HTMLTableRowElement>,
  onSelectRow: (row: Row) => void,
  row: Row,
): void {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  onSelectRow(row)
}

function DataTableCell({
  row,
  column,
  onSelectRow,
  cellHref,
}: Readonly<{
  row: Row
  column: TableColumnSpec
  onSelectRow?: (row: Row) => void
  cellHref?: (row: Row, column: string) => string | undefined
}>) {
  const value = resolveColumnValue(row, column)
  const href = resolveDataCellHref(row, column, onSelectRow, cellHref)
  return (
    <td className={primaryColumnClass(column)} title={cellTitle(value)}>
      <CellValue column={column} row={row} href={href} />
    </td>
  )
}

function DataTableRow({
  row,
  columns,
  onSelectRow,
  cellHref,
}: Readonly<{
  row: Row
  columns: TableColumnSpec[]
  onSelectRow?: (row: Row) => void
  cellHref?: (row: Row, column: string) => string | undefined
}>) {
  return (
    <tr
      className={onSelectRow ? 'selectable-row' : undefined}
      tabIndex={onSelectRow ? 0 : undefined}
      onClick={() => onSelectRow?.(row)}
      onKeyDown={onSelectRow ? (event) => handleSelectableRowKeyDown(event, onSelectRow, row) : undefined}
    >
      {columns.map((column) => (
        <DataTableCell key={column.key} row={row} column={column} onSelectRow={onSelectRow} cellHref={cellHref} />
      ))}
    </tr>
  )
}

function EmptyDataTable({ empty }: Readonly<{ empty: string | ComposedEmptyStateCopy }>) {
  if (typeof empty === 'string') {
    return <div className="empty-table">{empty}</div>
  }
  return <ComposedEmptyState state={empty} />
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
  if (!rows.length) return <EmptyDataTable empty={empty} />
  return (
    <div className="data-table-wrap">
      <div className="data-table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              {columns.map((column) => (
                <th key={column.key} className={primaryColumnClass(column)}>{column.label}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <DataTableRow
                key={rowKey(row, index)}
                row={row}
                columns={columns}
                onSelectRow={onSelectRow}
                cellHref={cellHref}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
