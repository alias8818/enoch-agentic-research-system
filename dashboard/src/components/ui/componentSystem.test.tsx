import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { EntityLinkChips, OperatorDetailSummary, RawJsonDetails, StateCard } from './index'

const uiDir = dirname(fileURLToPath(import.meta.url))
const srcDir = resolve(uiDir, '../..')
const REQUIRED_UI_EXPORTS = ['ActionRow','EntityLinkChips','Eyebrow','InlineErrorStateCard','LoadingStateCard','OperatorDetailSummary','OperatorQuestionSections','PageShell','RawDetails','RawJsonDetails','StateCard']
const PAGE_FILES_USING_UI = ['components/DetailPanel.tsx','components/ResourcePages.tsx','components/ResearchPage.tsx']

describe('dashboard ui component system', () => {
  it('exports the documented shared primitives from components/ui', () => {
    const barrel = readFileSync(resolve(uiDir, 'index.ts'), 'utf8')
    for (const name of REQUIRED_UI_EXPORTS) expect(barrel).toContain(name)
  })
  it('defines one ui module per primitive file', () => {
    const files = readdirSync(uiDir).filter((file) => file.endsWith('.tsx'))
    expect(files.length).toBeGreaterThanOrEqual(8)
  })
  it('keeps raw JSON inside details.raw-details via RawJsonDetails', () => {
    const { container } = render(<RawJsonDetails summary="Raw payload" payload={{ ok: true }} />)
    expect(container.querySelector('.json-block')?.closest('details.raw-details')).not.toBeNull()
  })
  it('renders operator detail summary with current state and next action', () => {
    render(<OperatorDetailSummary state="Queued" context="Lane gb10 owns dispatch." next="Review queue row before dispatch." />)
    expect(screen.getByText('Current state')).toBeInTheDocument()
    expect(screen.getByText('Next safe action')).toBeInTheDocument()
  })
  it('styles error state cards consistently', () => {
    const { container } = render(<StateCard variant="error">Detail unavailable</StateCard>)
    expect(container.querySelector('.state-card.state-card--error')).not.toBeNull()
  })
  it('renders entity link chips with dashboard hashes', () => {
    render(<EntityLinkChips links={[{ kind: 'project', id: 'project-1', label: 'Alpha study' }]} />)
    expect(screen.getByRole('link', { name: 'project: Alpha study' }).getAttribute('href')).toContain('#project:project-1')
  })
  it('requires list/detail pages to import from components/ui', () => {
    for (const relativePath of PAGE_FILES_USING_UI) {
      const source = readFileSync(resolve(srcDir, relativePath), 'utf8')
      expect(source).toMatch(/from '\.\/ui'|from "\.\/ui"/)
    }
  })
})
