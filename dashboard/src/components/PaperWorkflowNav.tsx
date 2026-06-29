import { dashboardV2Href } from '../routes'

type PaperWorkflowPage = 'papers' | 'corpus' | 'automation'

const PAPER_WORKFLOW_LINKS: ReadonlyArray<{
  page: PaperWorkflowPage
  label: string
  href: string
  detail: string
}> = [
  {
    page: 'papers',
    label: 'Papers',
    href: dashboardV2Href('#papers'),
    detail: 'Drafts, statuses, and publication gate state',
  },
  {
    page: 'corpus',
    label: 'Paper corpus import',
    href: dashboardV2Href('#corpus'),
    detail: 'Missing public corpus import rows',
  },
  {
    page: 'automation',
    label: 'Paper actions',
    href: dashboardV2Href('#automation'),
    detail: 'Rewrite, finalization, reject, and checklist actions',
  },
]

export function PaperWorkflowNav({ active }: Readonly<{ active: PaperWorkflowPage }>) {
  return (
    <nav className="paper-workflow-nav" aria-label="Papers workflow">
      {PAPER_WORKFLOW_LINKS.map((item) => {
        const isActive = active === item.page
        return (
          <a
            key={item.page}
            className={isActive ? 'paper-workflow-link paper-workflow-link--active' : 'paper-workflow-link'}
            href={item.href}
            aria-current={isActive ? 'page' : undefined}
          >
            <span>{item.label}</span>
            <small>{item.detail}</small>
          </a>
        )
      })}
    </nav>
  )
}
