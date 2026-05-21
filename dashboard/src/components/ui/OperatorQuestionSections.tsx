import type { DetailOperatorSummary } from '../../detailOperatorSummary'
export function OperatorQuestionSections({ sections, recentActivity, actionNeeded }: { sections: DetailOperatorSummary['sections']; recentActivity: string | null; actionNeeded: string | null }) {
  if (!sections.length && !recentActivity && !actionNeeded) return null
  return (
    <section className="detail-operator-questions" aria-label="Operator questions">
      {sections.map((section) => (
        <article key={section.title} className="detail-operator-question">
          <h4>{section.title}</h4>
          <dl className="detail-field-grid">
            {section.answers.map((answer) => (
              <div key={`${section.title}-${answer.label}`} className="detail-field"><dt>{answer.label}</dt><dd>{answer.value}</dd></div>
            ))}
          </dl>
        </article>
      ))}
      {recentActivity ? <article className="detail-operator-question"><h4>What happened most recently?</h4><p>{recentActivity}</p></article> : null}
      {actionNeeded ? <article className="detail-operator-question detail-operator-question--attention"><h4>Action needed now</h4><p>{actionNeeded}</p></article> : null}
    </section>
  )
}
