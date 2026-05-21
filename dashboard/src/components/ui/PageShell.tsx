import type { ReactNode } from 'react'
import { PageHeader } from '../PageHeader'
export function PageShell({ title, subtitle, dataSource, children, action, toolbar, breadcrumb }: { title: string; subtitle: string; dataSource?: string; children: ReactNode; action?: ReactNode; toolbar?: ReactNode; breadcrumb?: { label: string; href?: string }[] }) {
  return (
    <section className="page-stack">
      <PageHeader title={title} subtitle={subtitle} dataSource={dataSource} action={action} toolbar={toolbar} breadcrumb={breadcrumb} />
      {children}
    </section>
  )
}
