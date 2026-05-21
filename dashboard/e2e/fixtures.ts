import type { Page } from '@playwright/test'
import { TOKEN_STORAGE_KEY } from '../src/api/client'

const overviewPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  counts: { queued: 1, active: 0 },
  queue: { queued: 1, active: 0 },
  paper_counts: {},
  paper_pipeline: {
    publish_ready: 0,
    published_imported: 0,
    publication_ready_total: 0,
    missing_from_corpus: 0,
  },
  movement_diagnosis: {
    status: 'actionable',
    primary_reason: 'Dry-run dispatch before live dispatch.',
    blockers: [],
  },
  flags: { queue_paused: false, maintenance_mode: false },
  events: [],
  recent_events: [],
  active_items: [],
  top_actions: [{
    kind: 'dispatch_next',
    priority: 1,
    title: 'Start next queued item',
    summary: 'Dry-run dispatch before live dispatch.',
    action_label: 'Check dispatch',
  }],
}

const statusPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  worker_lanes: [],
  flags: { queue_paused: false, maintenance_mode: false },
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

  await page.route('**/control/api/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(statusPayload) })
  })

  await page.route('**/control/dispatch-next', async (route) => {
    if (route.request().method() !== 'POST') {
      await route.fallback()
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(dispatchDryRunPayload) })
  })
}

export async function openDashboardWithToken(
  page: Page,
  hash = '#overview',
  options?: { afterMocks?: (page: Page) => Promise<void> },
): Promise<void> {
  await installDashboardApiMocks(page)
  if (options?.afterMocks) await options.afterMocks(page)
  await page.addInitScript((storageKey) => {
    window.localStorage.setItem(storageKey, 'playwright-token')
  }, TOKEN_STORAGE_KEY)
  await page.goto(`/control/dashboard-v2/${hash}`)
}
