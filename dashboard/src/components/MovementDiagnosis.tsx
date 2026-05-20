import { legacyDashboardHref } from '../navigation'
import type { MovementDiagnosis as MovementDiagnosisType } from '../types'

export function MovementDiagnosis({ diagnosis }: { diagnosis: MovementDiagnosisType }) {
  return (
    <section className="rounded-2xl border border-zinc-800 bg-zinc-950 p-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-lg font-bold text-white">Why no work is moving?</h2>
          <p className="text-sm text-zinc-400">Backend-diagnosed movement state. The frontend does not infer queue truth.</p>
        </div>
        <span className="rounded-full border border-zinc-700 px-3 py-1 text-xs font-bold uppercase tracking-wide text-zinc-300">{diagnosis.status || 'unknown'}</span>
      </div>
      <div className="space-y-3">
        {(diagnosis.blockers || []).map((blocker) => (
          <div key={`${blocker.kind}-${blocker.title}`} className="flex flex-col gap-2 rounded-xl border border-zinc-800 bg-black/20 p-4 md:flex-row md:items-center md:justify-between">
            <div>
              <strong className="text-sm text-white">{blocker.title}</strong>
              <p className="mt-1 text-sm text-zinc-400">{blocker.summary}</p>
            </div>
            {blocker.action_hash && <a className="text-sm font-bold text-sky-300" href={legacyDashboardHref(blocker.action_hash)}>{blocker.action_label || 'Open'}</a>}
          </div>
        ))}
      </div>
    </section>
  )
}
