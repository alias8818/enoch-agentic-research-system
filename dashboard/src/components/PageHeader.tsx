export function PageHeader({
  title,
  subtitle,
  dataSource,
  action,
  toolbar,
}: {
  title: string
  subtitle: string
  dataSource?: string
  action?: React.ReactNode
  toolbar?: React.ReactNode
}) {
  return (
    <header className="page-header page-header--compact">
      <div className="page-header-main">
        <div className="page-header-copy">
          <h1>{title}</h1>
          <p>{subtitle}</p>
          {dataSource ? (
            <details className="page-meta-details">
              <summary>Data source</summary>
              <p>{dataSource}</p>
            </details>
          ) : null}
        </div>
        {action ? <div className="page-header-action">{action}</div> : null}
      </div>
      {toolbar ? <div className="page-header-toolbar">{toolbar}</div> : null}
    </header>
  )
}
