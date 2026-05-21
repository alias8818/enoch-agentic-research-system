import { dashboardV2Href } from '../routes'
import type { MovementDiagnosis as MovementDiagnosisType } from '../types'

const commonReasons = [
  'no admitted candidates',
  'lane queue full',
  'lane active',
  'queue paused',
  'readiness blocked',
  'no matching machine target',
  'paper gate blocked',
  'evidence missing',
]

export function MovementDiagnosis({ diagnosis }: { diagnosis: MovementDiagnosisType }) {
  const blockers = diagnosis.blockers || []
  return (
    <section className="movement-panel" aria-label="Why no work is moving?">
      <div className="movement-head">
        <div>
          <p className="eyebrow">Operator answer</p>
          <h2>Why no work is moving?</h2>
          <p>Backend-diagnosed blocker before lane controls. The frontend does not infer queue truth.</p>
        </div>
        <span>{diagnosis.status || 'unknown'}</span>
      </div>
      {blockers.length ? (
        <div className="movement-list">
          {blockers.map((blocker) => (
            <div key={`${blocker.kind}-${blocker.title}`} className="movement-row">
              <div>
                <strong>{blocker.title}</strong>
                <p>{blocker.summary}</p>
              </div>
              {blocker.action_hash && <a className="text-link" href={dashboardV2Href(blocker.action_hash)}>{blocker.action_label || 'Open'}</a>}
            </div>
          ))}
        </div>
      ) : (
        <p className="movement-empty">No movement blockers reported.</p>
      )}
      <div className="reason-strip" aria-label="Movement reasons covered">
        {commonReasons.map((reason) => <span key={reason}>{reason}</span>)}
      </div>
    </section>
  )
}
