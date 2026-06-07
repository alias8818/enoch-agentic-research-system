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
