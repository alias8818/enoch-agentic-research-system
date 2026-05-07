# Dashboard performance notes

Status: dashboard read-path optimization slices shipped on 2026-05-06.

## Problem found

Live timing showed the redesigned dashboard shell was waiting on backend read paths, not browser rendering or LAN latency. The slowest pages shared two patterns:

- Supabase/Postgres connections were opened for each helper query, adding roughly 750 ms per round trip from the control VM.
- Some list endpoints were only bounded after fetching broader ledgers into Python, then filtering, sorting, and paging in application code.

## Supabase/Postgres guidance applied

The implementation follows the Supabase/Postgres performance guidance that indexes should support frequent filters/orderings and that slow queries should be inspected with query plans rather than guessed. Edge Functions are useful for low-latency HTTP compute near users, but they would add another network hop for this private operator dashboard. For this workload, the right place to use Supabase compute is inside Postgres: SQL filters, SQL ordering, SQL pagination, indexes, views, and future RPC/materialized read models.

## Changes made

- Reused a guarded server-side Postgres connection inside `SupabaseControlPlaneStore` so repeated dashboard reads do not pay connection setup every time.
- Aborted stale browser requests on tab changes and loaded secondary overview health checks after primary operator cards render.
- Moved `queue_page`, `paper_page`, and `run_page` filtering/sorting/pagination into SQL with `limit page_size + 1` instead of fetching all rows and slicing in Python.
- Added read-model indexes for common dashboard orderings:
  - `queue_items(updated_at desc, project_id desc)`
  - `queue_items(status, updated_at desc, project_id desc)`
  - `queue_items(dispatch_priority asc, selection_rank asc, updated_at desc, project_id desc)`
  - `papers(updated_at desc, paper_id desc)`
  - `papers(paper_status, updated_at desc, paper_id desc)`
  - `runs(updated_at desc, run_id desc)`
  - `runs(state, updated_at desc, run_id desc)`
- Bounded the ideas dashboard response by default and omitted the large latest-intake payload unless explicitly requested with `include_latest_payload=true`.

## Live timing evidence

Representative warmed timings from the control VM after deployment:

| Endpoint | Before | After |
| --- | ---: | ---: |
| `/control/api/v1/queue` | 3.73 s | 0.70 s |
| `/control/api/v1/runs` | 1.28 s | 0.23 s |
| `/control/api/v1/papers` | 2.36 s | 0.46 s |
| `/control/api/v1/events` | 0.94 s | 0.23 s |
| `/control/api/publication-automation` | 1.55 s | 0.38 s |
| `/control/api/intake/ideas` | 5.56 s / 1.1 MB | 1.13 s / 58 KB |
| `/control/api/v1/overview` | ~1-2 s, broad ledger inputs | ~1.0-1.1 s warmed, gate-aware counts preserved |
| `/control/api/intake/ideas` | 1.5 s default after payload bounding | ~0.55-0.62 s warmed, no large observation payload fetch |

`/control/api/v1/overview` now uses the same batched Supabase connection, derives active/queued/blocked counts from one status query, and narrows the overview ledger inputs to rows that can affect operator-visible decisions: paper eligibility candidates, explicit needs-attention queue rows, finalized/imported publication rows, and draft/archive paper rows. The Python read model still owns the final gate-aware semantics so raw completed/no-paper rows cannot become actionable paper work.

Browser-side routing now renders the primary overview before secondary health checks, aborts stale in-flight requests when the operator changes tabs, and keeps late overview responses from overwriting the newly selected page. The Supabase ideas page also uses a batched read path and omits the large latest-intake payload by default instead of fetching it and hiding it later.

## Next performance lane

Remaining bottlenecks are now the intentionally rich list rows, especially project/queue rows with related paper fields. The next safe improvement is a dedicated lightweight list-row projection for queue/project pages, but only if operators still feel page transitions are too slow. If overview needs to go lower than ~1s, use a Postgres RPC/materialized read model only after proving exact parity for `operator_counts`, `operator_detail_counts`, `paper_pipeline`, bounded active items, and bounded recent events. Do not replace the overview with raw SQL counts unless the result is proven to preserve the current decision-gated semantics.
