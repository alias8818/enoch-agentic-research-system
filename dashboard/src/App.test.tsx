import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { saveToken } from './api/client'
import { fetchMockCallUrl } from './test/fetchMockBody'
import { App } from './App'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  saveToken('')
  globalThis.location.hash = ''
})

it('keeps overview secondary links in V2 and exposes data freshness', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, generated_at: '2026-05-20T12:00:00Z', counts: { active: 0, queued: 0 }, paper_counts: {}, movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] }, flags: {} }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({ ok: true, generated_at: '2026-05-20T12:01:00Z', counts: { active: 0, queued: 0 }, paper_counts: {}, movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] }, flags: {} }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  expect(screen.getByLabelText('Dashboard data freshness')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument()
  fireEvent.click(screen.getByText('More'))
  expect(screen.getByRole('link', { name: 'Events' })).toHaveAttribute('href', '/control/dashboard-v2#events')
  expect(screen.queryByRole('link', { name: 'Legacy dashboard' })).not.toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getAllByRole('link', { name: 'Runs' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#runs')).toBe(true)
  expect(screen.getAllByRole('link', { name: 'Papers' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#papers')).toBe(true)
  expect(screen.getByRole('link', { name: 'Recent activity' })).toHaveAttribute('href', '/control/dashboard-v2#events')

  fireEvent.click(screen.getByRole('button', { name: 'Refresh now' }))
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(5))
})


it('requests live worker refresh for overview lane status', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 1, queued: 4 },
      paper_counts: {},
      movement_diagnosis: { status: 'blocked', primary_reason: 'Worker lane state is being verified.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-20T12:00:05Z',
      worker_lanes: [
        {
          lane_key: 'gb10',
          label: 'GB10 lane',
          machine_target: 'gb10',
          status: 'active',
          queued_count: 4,
          dispatch_available: false,
          active_confirmation: { state: 'active_confirmed', matched: true, reason: 'matched worker run/session marker' },
        },
      ],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
  expect(fetchMockCallUrl(vi.mocked(globalThis.fetch), 1)).toBe('/control/api/status?refresh_worker=true')
  expect(screen.getByText('Worker confirmed active run.')).toBeInTheDocument()
  expect(screen.queryByText('Stale active: worker reports no matching live run.')).not.toBeInTheDocument()
})

it('shows research signal quality in the overview side rail', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      research_signal_quality: {
        status: 'warnings',
        ok: true,
        decisions_checked: 20,
        weak_evidence_count: 2,
        malformed_provider_response_count: 7,
        useful_adjacent_followup_delta: -4,
        report_age_hours: 120,
        report_stale_after_hours: 48,
        report_is_stale: true,
        freshness_summary: 'quality report stale: 120.0h old; refresh before relying on unattended automation',
        refresh_ok: false,
        refresh_action: 'research_quality_refresh_skipped',
        refresh_reason: 'missing database URL',
        refresh_operator_action: 'configure the Research Quality database URL so the read-only refresh can update the report',
        signal_verdict: 'stale',
        signal_label: 'Research signal: stale',
        signal_operator_action: 'refresh the Research Quality report before relying on unattended automation',
        signal_reasons: [{
          code: 'quality_report_stale',
          severity: 'blocked',
          message: 'quality report is stale',
          operator_action: 'refresh the Research Quality report before relying on unattended automation',
        }],
        malformed_provider_model_counts: { 'hf:model-a': 2 },
        recent_malformed_provider_responses: [{
          checked_at: '2026-05-30T03:00:30Z',
          recorded_at: '2026-05-30T03:04:45Z',
          provider_model: 'hf:model-a',
          malformed_provider_response_count: 2,
          generated_count: 0,
          promoted_count: 0,
          dispatched_count: 2,
          operator_action: 'inspect provider-generation output for this tick before trusting new idea volume',
        }],
        post_prompt_warning_details: [{
          code: 'malformed_provider_responses',
          severity: 'warning',
          message: '2 malformed provider responses across 1 recent tick',
          operator_action: 'inspect provider-generation output for the listed ticks before trusting new idea volume',
        }],
        provider_generation_health: {
          available: true,
          rows_checked: 4,
          malformed_provider_response_count: 2,
          malformed_provider_response_ticks: 1,
          clean_tick_count: 3,
          consecutive_clean_ticks: 2,
          malformed_history_status: 'recovered',
          active_malformed_warning: false,
          last_checked_at: '2026-05-30T04:00:30Z',
          last_malformed_at: '2026-05-30T03:00:30Z',
          malformed_provider_model_counts: { 'hf:model-a': 2 },
          latest_tick: {
            checked_at: '2026-05-30T04:00:30Z',
            recorded_at: '2026-05-30T04:04:45Z',
            trace_id: 'research-cycle-trace-b',
            run_cycle_id: 'run-cycle-b',
            provider_model: 'hf:model-b',
            malformed_provider_response_count: 0,
            generated_count: 3,
            promoted_count: 1,
            dispatched_count: 0,
            status: 'clean',
            operator_action: 'provider generation is currently clean; keep monitoring before widening automation',
          },
          last_malformed_tick: {
            checked_at: '2026-05-30T03:00:30Z',
            recorded_at: '2026-05-30T03:04:45Z',
            trace_id: 'research-cycle-trace-a',
            run_cycle_id: 'run-cycle-a',
            provider_model: 'hf:model-a',
            malformed_provider_response_count: 2,
            generated_count: 0,
            promoted_count: 0,
            dispatched_count: 2,
            status: 'malformed',
            operator_action: 'inspect provider-generation output for this tick before trusting new idea volume',
          },
          operator_action: 'provider generation has 2 clean ticks since the last malformed response; review the last malformed model before widening automation',
        },
        useful_adjacent_followup_evidence: {
          current: [{
            case_id: 'useful_adjacent_followup:post-run',
            case_type: 'useful_adjacent_followup',
            severity: 'info',
            title: 'Current follow-up',
            project_id: 'post-project',
            project_name: 'Current Project',
            run_id: 'post-run',
            followup_title: 'Current follow-up',
            followup_depth: 1,
            expected_behavior: 'Prefer bounded follow-up.',
          }],
          previous: [{
            case_id: 'useful_adjacent_followup:pre-run',
            case_type: 'useful_adjacent_followup',
            severity: 'info',
            title: 'Previous follow-up',
            project_id: 'pre-project',
            project_name: 'Previous Project',
            run_id: 'pre-run',
            followup_title: 'Previous follow-up',
            followup_depth: 0,
            expected_behavior: 'Prefer bounded follow-up.',
          }],
          delta: -4,
        },
        candidate_status_counts: {
          admitted: 45,
          needs_review: 53,
          rejected: 2,
        },
        decision_outcome_counts: [{
          decision: 'finalize_negative',
          hypothesis_status: 'mixed',
          count: 50,
        }],
        top_candidate_categories: [{
          category: 'home-training',
          count: 22,
        }],
        candidate_status_samples: {
          admitted: [{
            candidate_id: 'candidate-admitted',
            title: 'Admitted candidate',
            status: 'admitted',
            deterministic_total_score: 76.4,
            contract_quality_score: 1,
            problems: [],
          }],
          needs_review: [{
            candidate_id: 'candidate-needs-review',
            title: 'Needs review candidate',
            status: 'needs_review',
            deterministic_total_score: 64.2,
            contract_quality_score: 0.5,
            problems: ['thin_expected_artifacts'],
          }],
        },
        decision_outcome_samples: [{
          decision: 'finalize_negative',
          hypothesis_status: 'mixed',
          samples: [{
            project_id: 'project-mixed',
            project_name: 'Mixed project',
            run_id: 'run-mixed',
            links: {
              project: '/control/api/v1/projects/project-mixed',
              run: '/control/api/v1/runs/run-mixed',
            },
            decision: 'finalize_negative',
            hypothesis_status: 'mixed',
            evidence_strength: 'moderate',
            research_outcome: 'useful_signal',
            followup_title: 'Mixed follow-up',
            problems: [],
            }],
        }],
        quality_floor: {
          available: true,
          threshold: 0.7,
          posture: 'review_required',
          candidates_checked: 45,
          decisions_checked: 50,
          candidate_below_floor_count: 1,
          decision_below_floor_count: 1,
          below_floor_count: 2,
          candidate_samples: [{
            candidate_id: 'candidate-low',
            title: 'Thin candidate',
            status: 'needs_review',
            score: 0.55,
            problems: ['thin_expected_artifacts'],
          }],
          decision_samples: [{
            project_id: 'project-low',
            project_name: 'Thin decision',
            run_id: 'run-low',
            decision: 'blocked',
            hypothesis_status: 'unknown',
            score: 0.4,
            problems: ['weak_or_missing_evidence_strength'],
          }],
          operator_action: 'review 2 below-floor Research Quality artifacts before widening automation or treating outputs as externally useful',
        },
        decision_posture: {
          available: true,
          decisions_checked: 3,
          useful_signal_count: 2,
          negative_count: 1,
          bounded_paper_ready_count: 0,
          followup_recommended_count: 2,
          compute_scale_blocked_count: 0,
          publication_posture: 'followup_only',
          research_outcome_counts: { useful_signal: 2, negative: 1 },
          hypothesis_status_counts: { mixed: 1, supported: 1, unsupported: 1 },
          evidence_strength_counts: { moderate: 3 },
          decision_counts: {
            'finalize_negative:mixed': 1,
            'finalize_negative:supported': 1,
            'finalize_negative:unsupported': 1,
          },
          paper_readiness_blockers: {
            available: true,
            decisions_checked: 3,
            paper_ready_count: 0,
            blocker_counts: {
              not_bounded_paper_ready: 3,
              non_strong_evidence: 3,
              mixed_or_unsupported_hypothesis: 2,
              negative_outcome: 1,
              followup_required: 2,
            },
            samples: [{
              project_id: 'project-mixed',
              project_name: 'Mixed project',
              run_id: 'run-mixed',
              hypothesis_status: 'mixed',
              evidence_strength: 'moderate',
              research_outcome: 'useful_signal',
              bounded_paper_ready: false,
              followup_recommended: true,
              followup_title: 'Mixed follow-up',
              recommended_next_action: 'Run the mixed follow-up before treating this as paper-ready.',
              blocker_reasons: [
                'not_bounded_paper_ready',
                'non_strong_evidence',
                'mixed_or_unsupported_hypothesis',
                'followup_required',
              ],
            }],
            operator_action: 'no paper-ready decisions; dominant blocker is non-strong evidence across 3 decisions',
          },
          representative_useful_signals: [{
            project_id: 'project-mixed',
            project_name: 'Mixed project',
            run_id: 'run-mixed',
            links: {
              project: '/control/api/v1/projects/project-mixed',
              run: '/control/api/v1/runs/run-mixed',
            },
            decision: 'finalize_negative',
            hypothesis_status: 'mixed',
            evidence_strength: 'moderate',
            research_outcome: 'useful_signal',
            bounded_paper_ready: false,
            followup_recommended: true,
            followup_title: 'Mixed follow-up',
            recommended_next_action: 'Run the mixed follow-up before treating this as paper-ready.',
          }],
          operator_action: 'useful signals are present but none are bounded-paper-ready; run or review the listed follow-ups before treating this as publication output',
        },
        followup_readiness: {
          available: true,
          recommended_count: 2,
          bounded_ready_count: 1,
          underspecified_count: 1,
          missing_title_count: 0,
          missing_success_threshold_count: 0,
          missing_stop_condition_count: 1,
          thin_required_evidence_count: 0,
          followup_type_counts: { deepen: 2 },
          ready_followups: [{
            project_id: 'project-mixed',
            project_name: 'Mixed project',
            run_id: 'run-mixed',
            links: {
              project: '/control/api/v1/projects/project-mixed',
              run: '/control/api/v1/runs/run-mixed',
            },
            followup_type: 'deepen',
            followup_title: 'Mixed follow-up',
            followup_required_evidence_count: 4,
            followup_success_threshold: 'Mixed follow-up must improve accuracy by 5 points.',
            followup_stop_condition: 'Stop mixed follow-up if accuracy does not improve.',
            recommended_next_action: 'Run the mixed follow-up before treating this as paper-ready.',
          }],
          prioritized_followups: [{
            project_id: 'project-mixed',
            project_name: 'Mixed project',
            run_id: 'run-mixed',
            links: {
              project: '/control/api/v1/projects/project-mixed',
              run: '/control/api/v1/runs/run-mixed',
            },
            followup_type: 'deepen',
            followup_title: 'Mixed follow-up',
            followup_required_evidence_count: 4,
            followup_success_threshold: 'Mixed follow-up must improve accuracy by 5 points.',
            followup_stop_condition: 'Stop mixed follow-up if accuracy does not improve.',
            recommended_next_action: 'Run the mixed follow-up before treating this as paper-ready.',
            hypothesis_status: 'mixed',
            evidence_strength: 'moderate',
            priority_score: 75,
            priority_reasons: [
              'mixed_hypothesis',
              'moderate_evidence',
              'deepen_followup',
              '4_required_evidence_items',
              'explicit_success_and_stop_bounds',
            ],
          }],
          underspecified_followups: [{
            project_id: 'project-supported',
            project_name: 'Supported project',
            run_id: 'run-supported',
            followup_type: 'deepen',
            followup_title: 'Supported follow-up',
            followup_required_evidence_count: 4,
            followup_success_threshold: 'Supported follow-up must reproduce the effect.',
            followup_stop_condition: '',
            recommended_next_action: 'Run the supported follow-up before treating this as paper-ready.',
            missing_fields: ['missing_stop_condition'],
          }],
          operator_action: '1 recommended follow-up is underspecified; fill missing readiness fields before queueing it',
        },
        followup_scope_alignment: {
          available: true,
          global_ready_count: 733,
          same_project: false,
          same_run: false,
          global_candidate: {
            project_id: 'global-project',
            project_name: 'Global Follow-up Project',
            run_id: 'global-run',
            followup_title: 'Global ranked follow-up',
          },
          quality_window_candidate: {
            project_id: 'project-mixed',
            project_name: 'Mixed project',
            run_id: 'run-mixed',
            followup_title: 'Mixed follow-up',
          },
          operator_action: 'Global ranked follow-up and Research Quality window priority are different scopes; use the global action for queue selection and the quality-window sample for quality review.',
        },
        window_comparison: {
          cutoff: '2026-05-11T09:58:00Z',
          limit: 20,
          delta: {
            admitted_rate_delta: 0.1,
            proxy_only_positive_delta: -4,
            useful_adjacent_followup_delta: -4,
            moonshot_avg_score_delta: 1.426,
          },
          current: {
            candidate_count: 20,
            decision_count: 20,
            admitted_rate: 0.6,
            avg_total_score: 73.093,
            status_counts: { admitted: 12, rejected: 4 },
            category_counts: { 'home-training': 3, 'long-context': 4 },
            generation_mode_counts: { fresh_grounded: 9, moonshot: 10 },
            eval_case_counts: { proxy_only_positive: 6, useful_adjacent_followup: 2 },
            high_similarity_pair_count: 0,
          },
          previous: {
            candidate_count: 20,
            decision_count: 20,
            admitted_rate: 0.5,
            avg_total_score: 71.82,
            status_counts: { admitted: 10, rejected: 2 },
            category_counts: { 'home-training': 4, 'spec-decoding': 4 },
            generation_mode_counts: { fresh_grounded: 7, moonshot: 7 },
            eval_case_counts: { proxy_only_positive: 8, useful_adjacent_followup: 6 },
            high_similarity_pair_count: 0,
          },
        },
        operator_summary: 'quality=warnings; quality floor=review 2 below 0.70; quality-window posture=followup only (2 useful; 0 paper-ready); quality-window follow-ups=1 ready / 2 recommended; weak evidence=2; provider malformed=active (7 responses across 4 recent ticks); useful follow-up=active decline -4.0 (2 current vs 6 previous)',
        operator_recommendations: ['inspect provider-generation failures before trusting new idea volume'],
        recommendations: ['No critical quality-layer warnings from the read-only audit heuristics.'],
        top_problem_details: [{
          severity: 'warning',
          problem: 'weak_or_missing_evidence_strength',
          project_id: 'project-1',
          run_id: 'run-1',
          title: 'Weak Evidence Project',
          operator_action: 'inspect Weak Evidence Project before resuming unattended automation',
        }],
      },
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  const quality = await screen.findByLabelText('Research signal quality')
  expect(within(quality).getByText('warnings')).toBeInTheDocument()
  expect(within(quality).getByText('Weak evidence')).toBeInTheDocument()
  expect(within(quality).getByText('2')).toBeInTheDocument()
  expect(within(quality).getByText('Malformed provider')).toBeInTheDocument()
  expect(within(quality).getByText('7')).toBeInTheDocument()
  expect(within(quality).getByText('Useful trend')).toBeInTheDocument()
  expect(within(quality).getByText('-4')).toBeInTheDocument()
  expect(within(quality).getByText('quality=warnings; quality floor=review 2 below 0.70; quality-window posture=followup only (2 useful; 0 paper-ready); quality-window follow-ups=1 ready / 2 recommended; weak evidence=2; provider malformed=active (7 responses across 4 recent ticks); useful follow-up=active decline -4.0 (2 current vs 6 previous)')).toBeInTheDocument()
  expect(within(quality).getByText('Report age')).toBeInTheDocument()
  expect(within(quality).getByText('120.0h')).toBeInTheDocument()
  expect(within(quality).getByText('Signal verdict')).toBeInTheDocument()
  expect(within(quality).getByText('Research signal: stale')).toBeInTheDocument()
  expect(within(quality).getByText('quality report is stale')).toBeInTheDocument()
  expect(within(quality).getByText('refresh the Research Quality report before relying on unattended automation')).toBeInTheDocument()
  expect(within(quality).getByText('Provider warning evidence')).toBeInTheDocument()
  expect(within(quality).getByText('hf:model-a')).toBeInTheDocument()
  expect(within(quality).getByText('2 malformed responses at 2026-05-30T03:00:30Z')).toBeInTheDocument()
  expect(within(quality).getByText('inspect provider-generation output for this tick before trusting new idea volume')).toBeInTheDocument()
  expect(within(quality).getByText('Provider recovery')).toBeInTheDocument()
  expect(within(quality).getByText('provider warning recovered')).toBeInTheDocument()
  expect(within(quality).getByText('2 clean ticks since last malformed')).toBeInTheDocument()
  expect(within(quality).getByText('latest hf:model-b clean at 2026-05-30T04:00:30Z')).toBeInTheDocument()
  expect(within(quality).getByText('last malformed hf:model-a 2 at 2026-05-30T03:00:30Z')).toBeInTheDocument()
  expect(within(quality).getByText('provider generation has 2 clean ticks since the last malformed response; review the last malformed model before widening automation')).toBeInTheDocument()
  expect(within(quality).getByText('Follow-up trend evidence')).toBeInTheDocument()
  expect(within(quality).getByText('Current: Current follow-up')).toBeInTheDocument()
  expect(within(quality).getByText('Previous: Previous follow-up')).toBeInTheDocument()
  expect(within(quality).getByText('post-project / post-run')).toBeInTheDocument()
  expect(within(quality).getByText('Portfolio composition')).toBeInTheDocument()
  expect(within(quality).getByText('admitted 45')).toBeInTheDocument()
  expect(within(quality).getByText('needs review 53')).toBeInTheDocument()
  expect(within(quality).getByText('finalize negative / mixed 50')).toBeInTheDocument()
  expect(within(quality).getByText('home-training 22')).toBeInTheDocument()
  expect(within(quality).getByText('Portfolio evidence')).toBeInTheDocument()
  expect(within(quality).getByText('admitted: Admitted candidate')).toBeInTheDocument()
  expect(within(quality).getByText('candidate-admitted')).toBeInTheDocument()
  expect(within(quality).getByText('needs review: Needs review candidate')).toBeInTheDocument()
  expect(within(quality).getByText('candidate-needs-review')).toBeInTheDocument()
  expect(within(quality).getByText('finalize negative / mixed: Mixed project')).toBeInTheDocument()
  expect(within(quality).getByText('project-mixed / run-mixed')).toBeInTheDocument()
  expect(within(quality).getByText('Quality floor')).toBeInTheDocument()
  expect(within(quality).getByText('floor review required at 0.70')).toBeInTheDocument()
  expect(within(quality).getByText('below floor 2 / 95 checked')).toBeInTheDocument()
  expect(within(quality).getByText('candidate Thin candidate 0.55')).toBeInTheDocument()
  expect(within(quality).getByText('decision Thin decision 0.40')).toBeInTheDocument()
  expect(within(quality).getByText('review 2 below-floor Research Quality artifacts before widening automation or treating outputs as externally useful')).toBeInTheDocument()
  expect(within(quality).getByText('Decision posture')).toBeInTheDocument()
  expect(within(quality).getByText('useful signals 2 / 3 decisions')).toBeInTheDocument()
  expect(within(quality).getByText('publication-ready 0')).toBeInTheDocument()
  expect(within(quality).getByText('follow-up recommended 2')).toBeInTheDocument()
  expect(within(quality).getByText('posture followup only')).toBeInTheDocument()
  expect(within(quality).getByText('Mixed project')).toBeInTheDocument()
  expect(within(quality).getAllByRole('link', { name: 'project: Mixed project' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#project:project-mixed')).toBe(true)
  expect(within(quality).getAllByRole('link', { name: 'run: run-mixed' }).some((link) => link.getAttribute('href') === '/control/dashboard-v2#run:run-mixed')).toBe(true)
  expect(within(quality).getAllByText('Run the mixed follow-up before treating this as paper-ready.').length).toBeGreaterThan(0)
  expect(within(quality).getByText('useful signals are present but none are bounded-paper-ready; run or review the listed follow-ups before treating this as publication output')).toBeInTheDocument()
  expect(within(quality).getByText('Paper blockers')).toBeInTheDocument()
  expect(within(quality).getByText('paper-ready 0 / 3 decisions')).toBeInTheDocument()
  expect(within(quality).getByText('non strong evidence 3')).toBeInTheDocument()
  expect(within(quality).getByText('mixed or unsupported hypothesis 2')).toBeInTheDocument()
  expect(within(quality).getByText('sample Mixed project')).toBeInTheDocument()
  expect(within(quality).getByText('not bounded paper ready / non strong evidence / mixed or unsupported hypothesis')).toBeInTheDocument()
  expect(within(quality).getByText('no paper-ready decisions; dominant blocker is non-strong evidence across 3 decisions')).toBeInTheDocument()
  expect(within(quality).getByText('Follow-up readiness')).toBeInTheDocument()
  expect(within(quality).getByText('ready follow-ups 1 / 2 recommended')).toBeInTheDocument()
  expect(within(quality).getByText('underspecified 1')).toBeInTheDocument()
  expect(within(quality).getByText('missing stop 1')).toBeInTheDocument()
  expect(within(quality).getByText('deepen 2')).toBeInTheDocument()
  expect(within(quality).getAllByText('Mixed follow-up').length).toBeGreaterThan(0)
  expect(within(quality).getByText('Mixed follow-up must improve accuracy by 5 points.')).toBeInTheDocument()
  expect(within(quality).getByText('Prioritized follow-up')).toBeInTheDocument()
  expect(within(quality).getByText((_, element) => element?.textContent === 'priority 75')).toBeInTheDocument()
  expect(within(quality).getByText('mixed hypothesis / moderate evidence / deepen followup')).toBeInTheDocument()
  expect(within(quality).getByText('1 recommended follow-up is underspecified; fill missing readiness fields before queueing it')).toBeInTheDocument()
  expect(within(quality).getByText('Follow-up scope')).toBeInTheDocument()
  expect(within(quality).getByText('global ready 733')).toBeInTheDocument()
  expect(within(quality).getByText('global: Global Follow-up Project')).toBeInTheDocument()
  expect(within(quality).getByText('quality window: Mixed project')).toBeInTheDocument()
  expect(within(quality).getByText('different follow-up scopes')).toBeInTheDocument()
  expect(within(quality).getByText('Global ranked follow-up and Research Quality window priority are different scopes; use the global action for queue selection and the quality-window sample for quality review.')).toBeInTheDocument()
  expect(within(quality).getByText('Window comparison')).toBeInTheDocument()
  expect(within(quality).getByText('admitted rate 0.6 now / 0.5 previous')).toBeInTheDocument()
  expect(within(quality).getByText('fresh grounded 9')).toBeInTheDocument()
  expect(within(quality).getByText('moonshot 10')).toBeInTheDocument()
  expect(within(quality).getByText('home-training 3')).toBeInTheDocument()
  expect(within(quality).getByText('long-context 4')).toBeInTheDocument()
  expect(within(quality).getByText('high similarity pairs 0')).toBeInTheDocument()
  expect(within(quality).getByText('quality report stale: 120.0h old; refresh before relying on unattended automation')).toBeInTheDocument()
  expect(within(quality).getByText('Refresh source')).toBeInTheDocument()
  expect(within(quality).getByText('missing database URL')).toBeInTheDocument()
  expect(within(quality).getByText('configure the Research Quality database URL so the read-only refresh can update the report')).toBeInTheDocument()
  expect(within(quality).getByText('Affected artifact')).toBeInTheDocument()
  expect(within(quality).getByText('Weak Evidence Project')).toBeInTheDocument()
  expect(within(quality).getByText('weak_or_missing_evidence_strength')).toBeInTheDocument()
  expect(within(quality).getByText('inspect provider-generation failures before trusting new idea volume')).toBeInTheDocument()
  expect(within(quality).queryByText('No critical quality-layer warnings from the read-only audit heuristics.')).not.toBeInTheDocument()
})

it('prefers active research signal reasons over recovered context', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      research_signal_quality: {
        status: 'clean',
        ok: true,
        signal_verdict: 'review_required',
        signal_label: 'Research signal: review required',
        signal_operator_action: 'review recent follow-up quality before increasing throughput',
        signal_reasons: [
          {
            code: 'provider_generation_recovered',
            severity: 'info',
            message: 'provider generation recovered after malformed responses',
            operator_action: 'provider generation recovered; review the last malformed model before widening automation',
            status: 'recovered',
            active: false,
          },
          {
            code: 'useful_followup_decline',
            severity: 'warning',
            message: 'useful adjacent follow-up signal declined',
            operator_action: 'review recent follow-up quality before increasing throughput',
            status: 'active',
            active: true,
          },
        ],
      },
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  const quality = await screen.findByLabelText('Research signal quality')
  expect(within(quality).getByText('Signal verdict')).toBeInTheDocument()
  expect(within(quality).getByText('Research signal: review required')).toBeInTheDocument()
  expect(within(quality).getByText('useful adjacent follow-up signal declined')).toBeInTheDocument()
  expect(within(quality).getByText('review recent follow-up quality before increasing throughput')).toBeInTheDocument()
  expect(within(quality).queryByText('provider generation recovered after malformed responses')).not.toBeInTheDocument()
})

it('surfaces the movement diagnosis before lane and action controls', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      flags: {},
      movement_diagnosis: {
        status: 'blocked',
        primary_reason: 'No admitted GB10 candidates.',
        blockers: [
          {
            kind: 'no_admitted_candidates',
            title: 'No admitted candidates',
            summary: 'Generate or promote work before dispatching an idle lane.',
            action_hash: '#research',
            action_label: 'Open research',
          },
        ],
      },
      top_actions: [
        {
          kind: 'investigate_followup',
          priority: 40,
          tone: 'warn',
          title: 'Investigate follow-up candidates',
          summary: 'Promote the strongest candidate before dispatching.',
          action_label: 'Open research',
          action_hash: '#research',
          target: {},
        },
      ],
      paper_pipeline: { write_needed: 0, finalize_needed: 0, publish_ready: 0 },
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      generated_at: '2026-05-20T12:00:05Z',
      worker_lanes: [
        {
          lane_key: 'gb10',
          label: 'GB10 lane',
          machine_target: 'gb10',
          status: 'idle',
          queued_count: 0,
          dispatch_available: false,
          feed_pressure: { next_autopilot_action: 'generate_candidate' },
        },
      ],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  const diagnosis = (await screen.findByText('Why no work is moving?')).closest('section') as HTMLElement
  const lanes = screen.getByLabelText('Worker lanes')
  const controls = screen.getByLabelText('Primary action')

  expect(Boolean(diagnosis.compareDocumentPosition(lanes) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  expect(Boolean(diagnosis.compareDocumentPosition(controls) & Node.DOCUMENT_POSITION_FOLLOWING)).toBe(true)
  expect(within(diagnosis).getByText('No admitted candidates')).toBeInTheDocument()
})

it('keeps overview command result raw JSON inside collapsed details', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 1 },
      paper_counts: {},
      movement_diagnosis: { status: 'actionable', primary_reason: 'Dispatch ready.', blockers: [] },
      flags: {},
      top_actions: [{
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Dispatch',
        action_hash: '#queue:queued',
      }],
      primary_operator_action: {
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Check dispatch',
        action_hash: '#queue:queued',
      },
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      label: 'Long-haul mode: READY',
      blockers: [],
      checks: [{ name: 'queue_unpaused', ok: true }],
      summary: { queued: 1, active: 0, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      action: 'dry_run_dispatch',
      reason: 'dry-run dispatch selected candidate',
      candidate: { project_id: 'project-1', machine_target: 'gb10' },
    }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:10Z',
      counts: { active: 0, queued: 1 },
      paper_counts: {},
      movement_diagnosis: { status: 'actionable', primary_reason: 'Dispatch ready.', blockers: [] },
      flags: {},
      top_actions: [{
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Dispatch',
        action_hash: '#queue:queued',
      }],
      primary_operator_action: {
        kind: 'dispatch_next',
        title: 'Dispatch GB10 lane',
        summary: 'One queued candidate matches the idle lane.',
        action_label: 'Check dispatch',
        action_hash: '#queue:queued',
      },
      recent_events: [],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  await screen.findByText('Can I leave this running?')
  fireEvent.click(within(screen.getByLabelText('Primary action')).getByRole('button', { name: 'Check readiness' }))
  await within(screen.getByLabelText('Readiness check')).findByText('Long-haul mode: READY')
  fireEvent.click(screen.getByRole('button', { name: 'Check dispatch' }))
  await screen.findByText('dry-run dispatch selected candidate')

  const resultCard = screen.getByText('Selected work').closest('.command-result-summary') as HTMLElement
  resultCard.querySelectorAll('.json-block').forEach((block) => {
    expect(block.closest('details.raw-details')).not.toBeNull()
  })
})

it('shows recent activity inside the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      recent_events: [
        { id: 42, event_type: 'Queue Alert', summary: 'GB10 lane became idle', created_at: '2026-05-20T12:00:01Z' },
      ],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getByText('Recent activity')).toBeInTheDocument()
  expect(screen.getByText('GB10 lane became idle')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Queue Alert/ })).toHaveAttribute('href', '/control/dashboard-v2#event:42')
})

it('does not claim secondary readiness passed before readiness data loads', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  const secondaryReadiness = screen.getByLabelText('Automation readiness')
  expect(within(secondaryReadiness).getByText('Automation readiness unavailable')).toBeInTheDocument()
  expect(within(secondaryReadiness).queryByText('All reported long-haul readiness checks passed.')).not.toBeInTheDocument()
})

it('does not answer leave-running as ready before readiness is checked', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No movement blockers.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: false,
      label: 'Long-haul mode: BLOCKED — queued/active state inconsistent',
      blockers: ['queue_counts_consistent: blocked'],
      checks: [{ name: 'queue_counts_consistent', ok: false }],
      summary: { queued: 3, active: 2, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  const leaveRunningHero = (await screen.findByText('Can I leave this running?')).closest('section') as HTMLElement
  expect(within(leaveRunningHero).getByRole('heading', { level: 1, name: 'Check readiness first' })).toBeInTheDocument()
  expect(within(leaveRunningHero).getByText('Run the readiness check before leaving automation unattended.')).toBeInTheDocument()

  fireEvent.click(within(screen.getByLabelText('Readiness check')).getByRole('button', { name: 'Check readiness' }))

  expect(await within(leaveRunningHero).findByText('Not yet')).toBeInTheDocument()
  expect(screen.getAllByText('queue_counts_consistent: blocked').length).toBeGreaterThan(0)
})

it('checks automation readiness above the fold on demand', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      label: 'Long-haul mode: READY',
      blockers: [],
      checks: [{ name: 'queue_unpaused', ok: true }],
      summary: { queued: 0, active: 0, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
  const readinessCard = screen.getByLabelText('Readiness check')
  expect(readinessCard).toHaveTextContent('Not checked')
  expect(globalThis.fetch).not.toHaveBeenCalledWith('/control/api/v1/automation-readiness', expect.any(Object))

  fireEvent.click(within(readinessCard).getByRole('button', { name: 'Check readiness' }))

  expect(await within(readinessCard).findByText('Long-haul mode: READY')).toBeInTheDocument()
  expect(globalThis.fetch).toHaveBeenNthCalledWith(3, '/control/api/v1/automation-readiness', expect.any(Object))
})

it('shows automation readiness in the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: false,
      label: 'Long-haul mode: BLOCKED — queued/active state inconsistent',
      blockers: ['queue_counts_consistent: blocked', 'latest provider generation attempt failed'],
      checks: [
        { name: 'queue_unpaused', ok: true },
        { name: 'maintenance_off', ok: true },
        { name: 'research_timer_active', ok: true },
        { name: 'corpus_timer_active', ok: true },
        { name: 'research_last_result_success', ok: true },
        { name: 'corpus_last_result_success', ok: true },
        { name: 'research_tick_recent', ok: true },
        { name: 'corpus_tick_recent_when_needed', ok: true },
        { name: 'queue_counts_consistent', ok: false },
        { name: 'provider_generation_attempts_ok', ok: false },
      ],
      summary: { queued: 3, active: 2, queue_paused: false, maintenance_mode: false },
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalledTimes(2))
  expect(globalThis.fetch).not.toHaveBeenCalledWith('/control/api/v1/automation-readiness', expect.any(Object))

  fireEvent.click(screen.getByText('Show secondary details'))

  const secondaryReadiness = screen.getByLabelText('Automation readiness')
  expect(await within(secondaryReadiness).findByText('Automation readiness')).toBeInTheDocument()
  expect(await within(secondaryReadiness).findByText('Long-haul mode: BLOCKED — queued/active state inconsistent')).toBeInTheDocument()
  expect(within(secondaryReadiness).getAllByText('queue_counts_consistent: blocked')).toHaveLength(2)
  expect(within(secondaryReadiness).getByText('provider_generation_attempts_ok: blocked')).toBeInTheDocument()
  expect(globalThis.fetch).toHaveBeenNthCalledWith(3, '/control/api/v1/automation-readiness', expect.any(Object))
})

it('shows active work inside the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 1, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'One CPU job is running.', blockers: [] },
      flags: {},
      active_items: [
        { project_id: 'project-cpu', current_run_id: 'run-cpu', project_name: 'Prompt-to-Test Oracle', machine_target: 'cpu-proxmox-1', updated_at: '2026-05-20T12:00:01Z' },
      ],
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, label: 'Long-haul mode: READY', blockers: [], checks: [], summary: { queued: 0, active: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  expect(screen.getByText('Active work snapshot')).toBeInTheDocument()
  expect(screen.getByText('Prompt-to-Test Oracle')).toBeInTheDocument()
  expect(screen.getByText('cpu-proxmox-1 · run-cpu')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: /Open run/ })).toHaveAttribute('href', '/control/dashboard-v2#run:run-cpu')
})

it('shows operator queue counts inside the collapsed overview secondary fold', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-20T12:00:00Z',
      counts: { active: 1, queued: 4 },
      paper_counts: {},
      operator_counts: { needs_attention: 2, running: 1, write_paper: 3, ready_to_publish: 1 },
      operator_detail_counts: { finalization_needed: 2, followup_candidate: 5 },
      movement_diagnosis: { status: 'actionable', primary_reason: 'Operator work exists.', blockers: [] },
      flags: {},
      active_items: [],
      recent_events: [],
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, label: 'Long-haul mode: READY', blockers: [], checks: [], summary: { queued: 4, active: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByText('Can I leave this running?')).toBeInTheDocument()
  fireEvent.click(screen.getByText('Show secondary details'))
  const snapshot = screen.getByLabelText('Operator queue snapshot')
  expect(within(snapshot).getByRole('heading', { name: 'Operator queue snapshot' })).toBeInTheDocument()
  expect(within(snapshot).getByText('needs attention')).toBeInTheDocument()
  expect(within(snapshot).getAllByText('2')).toHaveLength(2)
  expect(within(snapshot).getByText('write paper')).toBeInTheDocument()
  expect(within(snapshot).getByText('3')).toBeInTheDocument()
  expect(within(snapshot).getByText('followup candidate')).toBeInTheDocument()
  expect(within(snapshot).getByText('5')).toBeInTheDocument()
})


it('keeps visible resource filters aligned with hash navigation', async () => {
  globalThis.location.hash = '#queue:queued'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'queued-project', status: 'queued', title: 'Queued item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'active-project', status: 'active', title: 'Active item' }], page: { returned: 1, has_more: false } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)
  await screen.findByText('Queued item')

  globalThis.location.hash = '#queue:active'
  globalThis.dispatchEvent(new HashChangeEvent('hashchange'))

  await screen.findByText('Active item')
  expect(screen.getByLabelText(/Status/i)).toHaveValue('active')
  expect(new URL(fetchMockCallUrl(fetchMock, 0), 'https://enoch.local').searchParams.get('status')).toBe('queued')
  expect(new URL(fetchMockCallUrl(fetchMock, 1), 'https://enoch.local').searchParams.get('status')).toBe('active')
})

it('keeps unsupported hashes inside the V2 shell with route suggestions only', () => {
  globalThis.location.hash = '#unknown-workflow'
  saveToken('test-token')

  render(<App />)

  expect(screen.getByRole('heading', { name: 'Unsupported V2 route' })).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(screen.getAllByRole('link', { name: /command center/i })).toHaveLength(1)
  expect(screen.queryByRole('link', { name: 'Open this hash in legacy dashboard' })).not.toBeInTheDocument()
})

it('canonicalizes alias hashes to supported routes on load', () => {
  globalThis.location.hash = '#reviews'
  saveToken('test-token')

  render(<App />)

  expect(globalThis.location.hash).toBe('#automation')
  expect(screen.getByRole('heading', { name: 'Publication automation' })).toBeInTheDocument()
})

it('redirects legacy status hashes to the command center', () => {
  globalThis.location.hash = '#status'
  saveToken('test-token')
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    generated_at: '2026-05-21T12:00:00Z',
    queue: { queued: 0, active: 0 },
    paper_pipeline: { publish_ready: 0, published_imported: 0, publication_ready_total: 0 },
    events: [],
  }), { status: 200 }))

  render(<App />)

  expect(globalThis.location.hash).toBe('#overview')
})


it('uses V2-authored token and fallback surfaces', () => {
  render(<App />)
  expect(screen.getByRole('heading', { name: 'Bearer token required' })).toBeInTheDocument()
  expect(screen.getByLabelText('Bearer token')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Save token' })).toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'Open legacy dashboard' })).not.toBeInTheDocument()
})


it('opens direct V2 detail hashes without legacy fallback', async () => {
  globalThis.location.hash = '#run:run-1'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ run_id: 'run-1', run: { run_id: 'run-1', project_id: 'project-1', state: 'running' } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByLabelText('Dashboard detail page')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/runs/run-1', expect.any(Object))
})


it('opens direct V2 event detail hashes from the events read model', async () => {
  globalThis.location.hash = '#event:7'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ event_id: 7, event_type: 'Queue Alert', summary: 'Target event summary', entity_id: 'project-1', created_at: '2026-05-21T00:00:00Z' }], page: { returned: 1, has_more: false } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByLabelText('Dashboard detail page')).toBeInTheDocument()
  await screen.findByRole('heading', { name: 'Target event summary', level: 1 })
  expect(screen.getByText('Event detail · 7 · Target event summary')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/events?event_id=7&include_payload=true&page_size=1&sort=recent', expect.any(Object))
})





it('keeps corpus hash filters in the V2 corpus read model', async () => {
  globalThis.location.hash = '#corpus?status=draft_review&search=manifest'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ paper_pipeline: { publish_ready: 0, published_imported: 0, publication_ready_total: 0 } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-manifest', status: 'draft_review', title: 'Manifest review paper' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Corpus import' })).toBeInTheDocument()
  expect(await screen.findByText('Manifest review paper')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/papers?page_size=50&sort=recent&status=draft_review&search=manifest', expect.any(Object))
})

it('keeps project and run hash search filters in V2 read models', async () => {
  globalThis.location.hash = '#projects?status=testing&search=oracle'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'project-filtered', project_name: 'Oracle project', origin_idea_status: 'testing' }], page: { returned: 1 } }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ run_id: 'run-filtered', state: 'running', current_activity: 'oracle replay' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Projects' })).toBeInTheDocument()
  expect(await screen.findByText('Oracle project')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(1, '/control/api/v1/projects?page_size=50&sort=recent&status=testing&search=oracle', expect.any(Object))

  globalThis.location.hash = '#runs:running?search=replay'
  globalThis.dispatchEvent(new HashChangeEvent('hashchange'))

  expect(await screen.findByRole('heading', { name: 'Runs' })).toBeInTheDocument()
  expect(await screen.findByText('oracle replay')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/v1/runs?page_size=50&sort=recent&state=running&search=replay', expect.any(Object))
})

it('keeps queue hash search filters in the V2 queue read model', async () => {
  globalThis.location.hash = '#queue:queued?search=gb10'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ project_id: 'queued-gb10', status: 'queued', title: 'GB10 queued work' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Queue' })).toBeInTheDocument()
  expect(await screen.findByText('GB10 queued work')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/queue?page_size=50&sort=priority&status=queued&search=gb10&queue=all', expect.any(Object))
})

it('keeps paper hash filters in the V2 papers read model', async () => {
  globalThis.location.hash = '#papers?status=publication_draft&search=trace-oracle'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ paper_id: 'paper-filtered', status: 'publication_draft', title: 'Trace oracle paper' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Papers' })).toBeInTheDocument()
  expect(await screen.findByText('Trace oracle paper')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/papers?page_size=50&sort=recent&status=publication_draft&search=trace-oracle', expect.any(Object))
})

it('keeps event hash filters in the V2 events read model', async () => {
  globalThis.location.hash = '#events?event_type=Queue%20Alert&search=active-lane'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ rows: [{ id: 'event-filtered', event_type: 'Queue Alert', summary: 'active-lane blocked' }], page: { returned: 1 } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Events' })).toBeInTheDocument()
  expect(await screen.findByText('active-lane blocked')).toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/v1/events?page_size=50&sort=recent&event_type=Queue+Alert&search=active-lane', expect.any(Object))
})


it('opens legacy review hashes in the V2 automation page instead of legacy fallback', async () => {
  globalThis.location.hash = '#review:paper-legacy'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ counts: {}, rows: [] }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ item: { paper_id: 'paper-legacy', project_name: 'Legacy review paper', review_status: 'triage_ready', paper_status: 'publication_draft' }, checklist: { items: [] } }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Publication automation' })).toBeInTheDocument()
  expect(await screen.findByText('Legacy review paper')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenNthCalledWith(2, '/control/api/publication-automation/paper-legacy', expect.any(Object))
})


it('opens intake hashes in the V2 ideas intake page instead of legacy fallback', async () => {
  globalThis.location.hash = '#intake'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      latest_sync: { source: 'idea_intake', status: 'ok', observed_at: '2026-05-21T00:00:00Z', payload: { payload_omitted: true, skipped_row_count: 1 } },
      projection_counts: { queued: 1 },
      skipped_reasons: { duplicate: 1 },
      queued_projection: [{ idea_id: 'idea-1', title: 'Better queue policy', idea_status: 'admitted', queue_status: 'queued', next_action_hint: 'dispatch', source_kind: 'synthetic' }],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Ideas intake' })).toBeInTheDocument()
  expect(await screen.findByText('Better queue policy')).toBeInTheDocument()
  expect(screen.getByText('duplicate')).toBeInTheDocument()
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/intake/ideas?page_size=100', expect.any(Object))
})

it('opens intake idea hashes as first-class V2 details', async () => {
  globalThis.location.hash = '#idea:idea-1'
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      latest_sync: { source: 'idea_intake', status: 'ok', observed_at: '2026-05-21T00:00:00Z' },
      projection_counts: { queued: 1 },
      queued_projection: [
        { idea_id: 'idea-1', title: 'Direct idea detail', idea_status: 'admitted', queue_status: 'queued', next_action_hint: 'dispatch', source_kind: 'synthetic' },
        { idea_id: 'idea-2', title: 'Other idea', idea_status: 'candidate', queue_status: '' },
      ],
    }), { status: 200 }))
  saveToken('test-token')

  render(<App />)

  expect(await screen.findByRole('heading', { name: 'Ideas intake' })).toBeInTheDocument()
  const detail = await screen.findByLabelText('Intake idea detail')
  expect(detail).toHaveTextContent('Direct idea detail')
  expect(detail).toHaveTextContent('idea-1')
  expect(detail).toHaveTextContent('dispatch')
  expect(screen.queryByText('This V2 page is not implemented yet')).not.toBeInTheDocument()
  expect(fetchMock).toHaveBeenCalledWith('/control/api/intake/ideas?page_size=100', expect.any(Object))
})

it('uses compact secondary page headers instead of repeating the command-center hero', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
    ok: true,
    generated_at: '2026-05-21T10:00:00Z',
    page: { returned: 0, has_more: false },
    rows: [],
  }), { status: 200 }))
  saveToken('test-token')
  globalThis.location.hash = '#projects'

  const { container } = render(<App />)

  expect(await screen.findByRole('heading', { level: 1, name: 'Projects' })).toBeInTheDocument()
  expect(document.querySelector('.app-header-context')).toHaveTextContent('Projects')
  expect(screen.queryByRole('heading', { name: 'Operator command center' })).not.toBeInTheDocument()
  expect(container.querySelector('.page-hero')).toBeNull()
  expect(screen.getByText('Data source')).toBeInTheDocument()
})

it('routes global search to the projects list with a search query', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-21T10:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T10:00:05Z', worker_lanes: [] }), { status: 200 }))
    .mockResolvedValue(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-21T10:00:00Z',
      page: { returned: 0, has_more: false },
      rows: [],
    }), { status: 200 }))
  saveToken('test-token')
  globalThis.location.hash = '#overview'

  render(<App />)
  await screen.findByText('Can I leave this running?')

  fireEvent.change(screen.getByLabelText('Global search'), { target: { value: 'oracle lane' } })
  fireEvent.click(screen.getByRole('button', { name: 'Search projects' }))

  expect(globalThis.location.hash).toBe('#projects?search=oracle%20lane')
})

it('toggles the dashboard theme from the shell header', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({
      ok: true,
      generated_at: '2026-05-21T10:00:00Z',
      counts: { active: 0, queued: 0 },
      paper_counts: {},
      movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] },
      flags: {},
    }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-21T10:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)
  await screen.findByText('Can I leave this running?')

  expect(document.documentElement.dataset.theme).toBe('dark')
  fireEvent.click(screen.getByRole('button', { name: 'Switch to light theme' }))
  expect(document.documentElement.dataset.theme).toBe('light')
  expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument()
})

it('opens keyboard shortcut help from the header button and question-mark shortcut', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(new Response(JSON.stringify({ ok: true, generated_at: '2026-05-20T12:00:00Z', counts: { active: 0, queued: 0 }, paper_counts: {}, movement_diagnosis: { status: 'ready', primary_reason: 'No blockers.', blockers: [] }, flags: {} }), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ generated_at: '2026-05-20T12:00:05Z', worker_lanes: [] }), { status: 200 }))
  saveToken('test-token')

  render(<App />)
  await screen.findByText('Can I leave this running?')

  fireEvent.click(screen.getByRole('button', { name: 'Show keyboard shortcuts' }))
  expect(screen.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeInTheDocument()
  expect(screen.getByText('Focus global project search')).toBeInTheDocument()

  fireEvent.click(screen.getByRole('button', { name: 'Close' }))
  expect(screen.queryByRole('heading', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument()

  const keyboardTarget = globalThis as unknown as Window
  fireEvent.keyDown(keyboardTarget, { key: '?' })
  expect(screen.getByRole('heading', { name: 'Keyboard shortcuts' })).toBeInTheDocument()

  fireEvent.keyDown(keyboardTarget, { key: '/' })
  expect(screen.getByRole('textbox', { name: /global search/i })).not.toHaveFocus()

  fireEvent.keyDown(keyboardTarget, { key: 'Escape' })
  expect(screen.queryByRole('heading', { name: 'Keyboard shortcuts' })).not.toBeInTheDocument()

  fireEvent.keyDown(keyboardTarget, { key: '/' })
  expect(screen.getByRole('textbox', { name: /global search/i })).toHaveFocus()
})
