import type { Page } from '@playwright/test'

const overviewPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  queue: { queued: 1, active: 0 },
  paper_pipeline: {
    publish_ready: 0,
    published_imported: 0,
    publication_ready_total: 0,
    missing_from_corpus: 0,
  },
  events: [],
  top_actions: [{
    kind: 'dispatch_next',
    priority: 1,
    title: 'Start next queued item',
    summary: 'Dry-run dispatch before live dispatch.',
    action_label: 'Check dispatch',
  }],
}

const dispatchDryRunPayload = {
  ok: true,
  dry_run: true,
  reason: 'lane open',
  project_id: 'project-alpha',
  candidate: { project_id: 'project-alpha', lane: 'cpu', machine_target: 'cpu-proxmox-1' },
}

export async function installDashboardApiMocks(page: Page): Promise<void> {
  await page.route('**/control/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (path.endsWith('/overview')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overviewPayload) })
      return
    }
    if (path.endsWith('/queue')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rows: [], page: { returned: 0, has_more: false } }) })
      return
    }
    if (path.endsWith('/runs')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rows: [], page: { returned: 0, has_more: false } }) })
      return
    }
    if (path.endsWith('/papers')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rows: [], page: { returned: 0, has_more: false } }) })
      return
    }
    if (path.endsWith('/events')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ rows: [], page: { returned: 0, has_more: false } }) })
      return
    }
    if (path.endsWith('/observability/health')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
      return
    }

    await route.fallback()
  })

  await page.route('**/control/dispatch-next', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback()
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dispatchDryRunPayload) })
  })
}

export async function openDashboardWithToken(page: Page, hash = '#overview'): Promise<void> {
  await installDashboardApiMocks(page)
  await page.addInitScript(() => {
    window.localStorage.setItem('enoch-dashboard-v2-token', 'playwright-token')
  })
  await page.goto(`/control/dashboard-v2/${hash}`)
}
