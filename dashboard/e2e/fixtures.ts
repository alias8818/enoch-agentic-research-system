import type { Page } from '@playwright/test'
import { TOKEN_STORAGE_KEY } from '../src/api/client'
import { SAVED_TABLE_FILTERS_STORAGE_KEY } from '../src/savedTableFilters'

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
  primary_operator_action: {
    kind: 'dispatch_next',
    title: 'Start next queued item',
    summary: 'Dry-run dispatch before live dispatch.',
    action_label: 'Check dispatch',
    action_hash: '#queue:queued',
  },
}

const statusPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  worker_lanes: [
    {
      lane_key: 'cpu',
      machine_target: 'cpu-proxmox-1',
      label: 'CPU lane',
      status: 'active',
      queued_count: 14,
      dispatch_available: false,
      dispatch_blocker: 'lane active',
      active_item: { project_id: 'project-alpha', project_name: 'Alpha study' },
      feed_pressure: { desired_queue_depth: 25, queue_deficit: 11 },
    },
    {
      lane_key: 'gb10',
      machine_target: 'gb10-worker-1',
      label: 'GB10 lane',
      status: 'idle',
      queued_count: 14,
      dispatch_available: true,
      dispatch_blocker: null,
      next_candidate: { project_id: 'project-beta', project_name: 'Beta follow-up' },
      feed_pressure: { desired_queue_depth: 25, queue_deficit: 11 },
    },
  ],
  flags: { queue_paused: false, maintenance_mode: false },
}

const readinessPayload = {
  ok: true,
  label: 'Long-haul mode: READY',
  blockers: [],
  checks: [{ name: 'queue_unpaused', ok: true }],
  summary: { queued: 1, active: 0, queue_paused: false, maintenance_mode: false },
}

const dispatchDryRunPayload = {
  ok: true,
  dry_run: true,
  action: 'dry_run_dispatch',
  reason: 'lane open',
  project_id: 'project-alpha',
  candidate: { project_id: 'project-alpha', lane: 'cpu', machine_target: 'cpu-proxmox-1' },
}

const queueListPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  rows: [
    {
      project_id: 'project-beta',
      project_name: 'Beta follow-up',
      title: 'Beta follow-up',
      status: 'queued',
      machine_target: 'gb10-worker-1',
      age_seconds: 1800,
      next_action_hint: 'Dry-run before dispatch',
    },
    {
      project_id: 'project-gamma',
      project_name: 'Gamma calibration',
      title: 'Gamma calibration',
      status: 'queued',
      machine_target: 'cpu-proxmox-1',
      age_seconds: 7200,
      blocked_reason: 'lane busy',
    },
  ],
  page: { returned: 2, has_more: false },
}

const projectsListPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  rows: [
    {
      project_id: 'project-alpha-raw-id-20260609',
      project_name: 'Alpha workstream',
      title: 'Alpha workstream',
      queue_status: 'queued',
      operator_stage_label: 'Ready',
      operator_tone: 'info',
      operator_explanation: 'The workstream is queued and waiting for lane capacity.',
      operator_next_step: 'Open the row and dry-run dispatch when a lane is idle.',
      related_artifact_paths_present: { evidence_bundle_path: true },
    },
  ],
  page: { returned: 1, has_more: false },
}

const runsListPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  rows: [
    {
      run_id: 'run-alpha-raw-id-20260609T000000Z',
      project_id: 'project-alpha-raw-id-20260609',
      project_name: 'Alpha run story',
      state: 'running',
      gate_state: 'running',
      current_activity: 'worker_callback',
      operator_stage_label: 'Running',
      operator_tone: 'info',
      operator_explanation: 'Worker is active; callback evidence is not complete yet.',
      operator_next_step: 'Wait for the callback before acting on this run.',
      started_at: '2026-05-21T11:59:00Z',
      related_artifact_paths_present: {},
    },
  ],
  page: { returned: 1, has_more: false },
}

const papersListPayload = {
  generated_at: '2026-05-21T12:00:00Z',
  rows: [
    {
      paper_id: 'raw-paper-id:alpha-run:arxiv_draft:/opt/enoch-control-plane/evidence/alpha/packet.json',
      project_id: 'project-alpha-raw-id-20260609',
      project_name: 'Alpha publication artifact',
      paper_status: 'publication_draft',
      review_status: 'draft_review',
      operator_stage_label: 'Needs Evidence',
      operator_tone: 'warn',
      operator_explanation: 'Draft exists but publication evidence is still incomplete.',
      operator_next_step: 'Collect the evidence bundle before publication review.',
      artifact_paths_present: { draft_markdown_path: true },
    },
  ],
  page: { returned: 1, has_more: false },
}

export async function installDashboardApiMocks(page: Page): Promise<void> {
  await page.route('**/control/dashboard-v2/session', async (route) => {
    const method = route.request().method()
    if (method === 'GET') {
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'invalid bearer token' }) })
      return
    }
    if (method === 'POST' || method === 'DELETE') {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
      return
    }
    await route.fallback()
  })

  await page.route('**/control/api/v1/**', async (route) => {
    const url = new URL(route.request().url())
    const path = url.pathname

    if (path.endsWith('/overview')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(overviewPayload) })
      return
    }
    if (path.endsWith('/queue')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(queueListPayload) })
      return
    }
    if (path.endsWith('/projects')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(projectsListPayload) })
      return
    }
    if (path.endsWith('/runs')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(runsListPayload) })
      return
    }
    if (path.endsWith('/papers')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(papersListPayload) })
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
    if (path.endsWith('/automation-readiness')) {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(readinessPayload) })
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
  await page.addInitScript(({ savedFiltersKey }) => {
    globalThis.localStorage.removeItem(savedFiltersKey)
  }, { savedFiltersKey: SAVED_TABLE_FILTERS_STORAGE_KEY })
  await page.goto(`/control/dashboard-v2/${hash}`)
  await page.getByLabel('Bearer token').fill('playwright-token')
  await page.getByRole('button', { name: 'Save token' }).click()
  const storedToken = await page.evaluate((storageKey) => globalThis.sessionStorage.getItem(storageKey), TOKEN_STORAGE_KEY)
  if (storedToken !== null) {
    throw new Error('dashboard bearer token was persisted to sessionStorage')
  }
  const cookieToken = await page.evaluate(() => globalThis.document.cookie.includes('enoch_dashboard_token='))
  if (cookieToken) {
    throw new Error('dashboard bearer token was persisted to a script-readable cookie')
  }
}
