import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { WorkbenchCountsFold, WorkbenchOperatorSummary } from './WorkbenchSummary'

const dashboardSrc = resolve(dirname(fileURLToPath(import.meta.url)), '..')

afterEach(() => {
  cleanup()
})

describe('WorkbenchSummary', () => {
  it('renders one operator sentence when summary text is present', () => {
    render(<WorkbenchOperatorSummary summary="3 idea(s) queued for operator review." />)
    expect(screen.getByText('3 idea(s) queued for operator review.')).toHaveClass('workbench-operator-summary')
  })

  it('hides empty summaries and collapses non-zero ledger counts', () => {
    const { container } = render(
      <>
        <WorkbenchOperatorSummary summary="" />
        <WorkbenchCountsFold counts={{ admitted: 2, needs_review: 0, queued: 1 }} label="Research counts" />
      </>,
    )
    expect(container.querySelector('.workbench-operator-summary')).toBeNull()
    expect(screen.getByText('Research counts')).toBeInTheDocument()
    expect(screen.getByText('admitted')).toBeInTheDocument()
    expect(screen.queryByText('needs review')).not.toBeInTheDocument()
  })
})

describe('workbench page KPI guard', () => {
  it('does not render decorative count-grid on intake, research, or automation pages', () => {
    const research = readFileSync(resolve(dashboardSrc, 'components/ResearchPage.tsx'), 'utf8')
    const automation = readFileSync(resolve(dashboardSrc, 'components/AutomationPage.tsx'), 'utf8')
    const resourcePages = readFileSync(resolve(dashboardSrc, 'components/ResourcePages.tsx'), 'utf8')
    const intakeSection = resourcePages.slice(resourcePages.indexOf('export function IntakePage'))

    expect(research.includes('count-grid'), 'ResearchPage should not use count-grid').toBe(false)
    expect(automation.includes('count-grid'), 'AutomationPage should not use count-grid').toBe(false)
    expect(intakeSection.includes('count-grid'), 'IntakePage should not use count-grid').toBe(false)
    expect(research.includes('WorkbenchOperatorSummary')).toBe(true)
    expect(automation.includes('WorkbenchOperatorSummary')).toBe(true)
    expect(intakeSection.includes('WorkbenchOperatorSummary')).toBe(true)
    expect(research.includes('WorkbenchCountsFold')).toBe(true)
    expect(automation.includes('WorkbenchCountsFold')).toBe(true)
    expect(intakeSection.includes('WorkbenchCountsFold')).toBe(true)
  })
})
