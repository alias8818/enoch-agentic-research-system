import type { ReactNode } from 'react'

export type BriefingTone = 'neutral' | 'good' | 'warn' | 'risk'

function toneClass(tone: BriefingTone | undefined): string {
  if (!tone || tone === 'neutral') return 'briefing-card'
  return `briefing-card briefing-card--${tone}`
}

export function BriefingCard({
  eyebrow,
  title,
  detail,
  tone = 'neutral',
  children,
}: Readonly<{
  eyebrow: string
  title: string
  detail?: string
  tone?: BriefingTone
  children?: ReactNode
}>) {
  return (
    <section className={toneClass(tone)} aria-label={title}>
      <p className="eyebrow">{eyebrow}</p>
      <h2>{title}</h2>
      {detail ? <p className="briefing-card__detail">{detail}</p> : null}
      {children}
    </section>
  )
}

export function MetricStrip({
  items,
  ariaLabel,
}: Readonly<{
  items: ReadonlyArray<Readonly<{ label: string; value: string | number; detail?: string }>>
  ariaLabel: string
}>) {
  return (
    <dl className="metric-strip" aria-label={ariaLabel}>
      {items.map((item) => (
        <div key={`${item.label}:${item.value}`}>
          <dt>{item.label}</dt>
          <dd>{item.value}</dd>
          {item.detail ? <p>{item.detail}</p> : null}
        </div>
      ))}
    </dl>
  )
}

export function BriefingGrid({ children }: Readonly<{ children: ReactNode }>) {
  return <div className="briefing-grid">{children}</div>
}
