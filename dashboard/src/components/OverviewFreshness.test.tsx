import { fireEvent, render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'
import { OverviewFreshness } from './OverviewFreshness'

it('shows backend freshness timestamps and triggers manual refresh', () => {
  const onRefresh = vi.fn()
  render(<OverviewFreshness generatedAt="2026-05-20T12:34:56Z" laneGeneratedAt="not-a-date" onRefresh={onRefresh} />)

  expect(screen.getByLabelText('Dashboard data freshness')).toHaveTextContent('overview ')
  expect(screen.getByLabelText('Dashboard data freshness')).toHaveTextContent('lanes not-a-date')
  fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
  expect(onRefresh).toHaveBeenCalledTimes(1)
})

it('disables refresh while queries are already fetching', () => {
  render(<OverviewFreshness isFetching onRefresh={() => undefined} />)
  expect(screen.getByRole('button', { name: 'Refreshing…' })).toBeDisabled()
})
