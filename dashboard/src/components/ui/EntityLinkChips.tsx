import type { EntityLink } from '../../detailOperatorSummary'
import { dashboardV2Href } from '../../routes'
export function EntityLinkChips({ links }: { links: EntityLink[] }) {
  if (!links.length) return null
  return (
    <div className="detail-entity-links" aria-label="Related entity links">
      {links.map((link) => (
        <a key={`${link.kind}-${link.id}`} className="detail-id-chip detail-id-chip--link" href={dashboardV2Href(`#${link.kind}:${encodeURIComponent(link.id)}`)} title={link.id}>{link.kind}: {link.label}</a>
      ))}
    </div>
  )
}
