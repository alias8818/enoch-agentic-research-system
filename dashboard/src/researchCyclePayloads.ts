export const dryRunCyclePayload = {
  enabled: false,
  dry_run: true,
  requested_by: 'dashboard-v2',
  max_provider_requests_per_run: 1,
  max_promotions_per_run: 2,
  max_dispatches_per_run: 0,
  wait_for_completion: false,
  max_wait_seconds: 0,
  max_paper_drafts_per_run: 0,
  max_publication_rewrites_per_run: 0,
  generation_max_tokens: 8000,
  generation_attempts: 2,
  temperature: 0.6,
}

export const liveCyclePayload = {
  ...dryRunCyclePayload,
  enabled: true,
  dry_run: false,
}
