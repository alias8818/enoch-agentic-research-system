import { dashboardV2Href } from '../routes'
import type { OverviewResponse } from '../types'

export function PaperMiniStrip({ pipeline }: { pipeline: OverviewResponse['paper_pipeline'] }) {
  const steps = [
    ['Write', pipeline?.write_needed ?? 0, '#papers?status=publication_draft'],
    ['Finalize', pipeline?.finalize_needed ?? 0, '#automation'],
    ['Publish', pipeline?.publish_ready ?? 0, '#corpus'],
  ] as const
  return (
    <section className="paper-strip">
      <div>
        <p className="eyebrow">Paper pipeline</p>
        <h2>Write → Finalize → Publish</h2>
      </div>
      <div className="paper-steps">
        {steps.map(([label, count, href]) => (
          <a key={label} href={dashboardV2Href(href)}>
            <span>{label}</span>
            <strong>{count}</strong>
          </a>
        ))}
      </div>
    </section>
  )
}
