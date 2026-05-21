import { expect, test } from '@playwright/test'
import { openDashboardWithToken } from './fixtures'

/**
 * Narrow visual-regression foundation for operator-critical surfaces.
 *
 * Scope is intentionally limited to fixture-driven, deterministic views.
 * Full route coverage waits until copy polish (hero/movement panels) settles.
 */
test('token gate matches baseline screenshot @visual', async ({ page }) => {
  await page.goto('/control/dashboard-v2/')
  await expect(page.getByRole('heading', { name: 'Bearer token required' })).toBeVisible()
  await expect(page.locator('main')).toHaveScreenshot('token-gate.png')
})

test('command center overview matches baseline screenshot @visual', async ({ page }) => {
  await openDashboardWithToken(page, '#overview')
  await expect(page.getByText('Can I leave this running?')).toBeVisible()
  await expect(page.getByLabel('Worker lanes')).toBeVisible()
  await expect(page.locator('.command-stack')).toHaveScreenshot('command-center-overview.png')
})
