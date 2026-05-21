import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'
import { PageHeader } from './PageHeader'

it('renders compact page headers with operator subtitle and collapsed data source', () => {
  const { container } = render(
    <PageHeader
      title="Projects"
      subtitle="Search projects and open structured detail."
      dataSource="/control/api/v1/projects"
      action={<button type="button">Refresh rows</button>}
    />,
  )

  expect(container.querySelector('.page-header--compact')).not.toBeNull()
  expect(container.querySelector('.page-hero')).toBeNull()
  expect(screen.getByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
  expect(screen.getByText('Search projects and open structured detail.')).toBeInTheDocument()
  expect(screen.queryByText('/control/api/v1/projects')).not.toBeVisible()
  expect(screen.getByText('Data source')).toBeInTheDocument()
})
