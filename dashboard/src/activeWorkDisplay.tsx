import type { ReactNode } from 'react'
import { displayText } from './displayText'
import { dashboardV2Href } from './routes'

export type ActiveWorkRow = {
  key: string
  label: string
  machine: string
  href: string
  runLabel: string
  linkLabel: string
}

export function activeWorkRow(item: Record<string, unknown>, index: number): ActiveWorkRow {
  const projectId = displayText(item.project_id, '')
  const runId = displayText(item.current_run_id ?? item.run_id, '')
  const fallbackLabel = projectId || runId || 'Active work'
  const label = displayText(item.project_name, fallbackLabel)
  const machine = displayText(item.machine_target ?? item.lane, 'unknown lane')
  const key = runId || projectId || String(index)
  let hash = '#runs'
  if (runId) hash = `#run:${encodeURIComponent(runId)}`
  else if (projectId) hash = `#project:${encodeURIComponent(projectId)}`
  const href = dashboardV2Href(hash)
  let runLabel = 'no run id'
  if (runId) runLabel = runId
  else if (projectId) runLabel = projectId
  let linkLabel = 'Open project'
  if (runId) linkLabel = 'Open run'
  return { key, label, machine, href, runLabel, linkLabel }
}

export function ActiveWorkItem({ row }: Readonly<{ row: ActiveWorkRow }>) {
  return (
    <li>
      <div>
        <strong>{row.label}</strong>
        <span>{row.machine} · {row.runLabel}</span>
      </div>
      <a href={row.href}>{row.linkLabel}</a>
    </li>
  )
}

export function ActiveWorkList({ activeItems }: Readonly<{ activeItems: Record<string, unknown>[] }>): ReactNode {
  if (activeItems.length === 0) {
    return <p>No active work returned in the bounded overview snapshot.</p>
  }
  const rows = activeItems.slice(0, 6).map((item, index) => activeWorkRow(item, index))
  return (
    <ol>
      {rows.map((row) => (
        <ActiveWorkItem key={row.key} row={row} />
      ))}
    </ol>
  )
}
