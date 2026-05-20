import { legacyDashboardHref } from '../navigation'
import type { OverviewResponse } from '../types'

export function PaperMiniStrip({ pipeline }: { pipeline: OverviewResponse['paper_pipeline'] }) {
  const steps = [
    ['Write', pipeline?.write_needed ?? 0, '#papers?status=publication_draft'],
    ['Finalize', pipeline?.finalize_needed ?? 0, '#automation'],
    ['Publish', pipeline?.publish_ready ?? 0, '#corpus'],
  ] as const
  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-950 p-5">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-bold text-white">Paper pipeline</h2>
        <span className="text-xs uppercase tracking-[0.2em] text-zinc-500">Write → Finalize → Publish</span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        {steps.map(([label, count, href]) => (
          <a key={label} href={legacyDashboardHref(href)} className="rounded-xl border border-zinc-800 bg-black/20 p-4 hover:border-zinc-600">
            <div className="text-sm text-zinc-400">{label}</div>
            <div className="mt-2 text-2xl font-black tabular-nums text-white">{count}</div>
          </a>
        ))}
      </div>
    </section>
  )
}
