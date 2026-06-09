import { expect, test } from '@playwright/test'
import { openDashboardWithToken } from './fixtures'

test('token gate blocks API calls until token is saved', async ({ page }) => {
  await page.goto('/control/dashboard-v2/')
  await expect(page.getByRole('heading', { name: 'Bearer token required' })).toBeVisible()
  await expect(page.getByLabel('Bearer token')).toBeVisible()
})

test('overview hero renders after token is present', async ({ page }) => {
  await openDashboardWithToken(page, '#overview')
  await expect(page.getByText('Can I leave this running?')).toBeVisible()
})

test('hash navigation opens queue list', async ({ page }) => {
  await openDashboardWithToken(page, '#queue:queued')
  await expect(page.getByRole('heading', { name: 'Queue', exact: true })).toBeVisible()
})

test('detail hash opens structured run detail', async ({ page }) => {
  await openDashboardWithToken(page, '#run:run-e2e', {
    afterMocks: async (mockPage) => {
      await mockPage.route('**/control/api/v1/runs/run-e2e', async (route) => {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            run_id: 'run-e2e',
            run: { run_id: 'run-e2e', project_id: 'project-alpha', state: 'running', project_name: 'Alpha project' },
          }),
        })
      })
    },
  })
  await expect(page.getByRole('heading', { name: 'Alpha project' })).toBeVisible()
})

test('dispatch dry-run keeps raw JSON collapsed', async ({ page }) => {
  await openDashboardWithToken(page, '#overview')
  await expect(page.getByRole('region', { name: 'Readiness check' })).toContainText('Long-haul mode: READY')
  await page.getByRole('button', { name: 'Check dispatch' }).click()
  await expect(page.getByRole('heading', { name: 'Dispatch dry-run passed' })).toBeVisible()
  const raw = page.locator('details.command-result-raw')
  await expect(raw).toHaveCount(1)
  await expect(raw).not.toHaveAttribute('open')
})

test('resource briefing regions demote raw identifiers and internals to table/detail evidence', async ({ page }) => {
  await openDashboardWithToken(page, '#projects')
  const projectCards = page.getByLabel('Prioritized project workstreams')
  await expect(projectCards).toContainText('Alpha workstream')
  await expect(projectCards).not.toContainText('project-alpha-raw-id-20260609')
  await expect(page.getByRole('button', { name: 'Copy id project-alpha-raw-id-20260609' })).toBeVisible()

  await page.goto('/control/dashboard-v2/#runs')
  const runStories = page.getByLabel('Prioritized run stories')
  await expect(runStories).toContainText('Alpha run story')
  await expect(runStories).not.toContainText('run-alpha-raw-id-20260609T000000Z')
  await expect(runStories).not.toContainText('worker_callback')
  await expect(page.getByRole('button', { name: 'Copy run id run-alpha-raw-id-20260609T000000Z' })).toBeVisible()

  await page.goto('/control/dashboard-v2/#papers')
  const paperArtifacts = page.getByLabel('Prioritized publication artifacts')
  await expect(paperArtifacts).toContainText('Alpha publication artifact')
  await expect(paperArtifacts).not.toContainText('raw-paper-id:alpha-run:arxiv_draft')
  await expect(paperArtifacts).not.toContainText('/opt/enoch-control-plane/evidence/alpha/packet.json')
  await expect(page.getByRole('button', { name: 'Copy id raw-paper-id:alpha-run:arxiv_draft:/opt/enoch-control-plane/evidence/alpha/packet.json' })).toBeVisible()
})
