export function PageHeader({
  title,
  subtitle,
  dataSource,
  action,
  toolbar,
  breadcrumb,
}: Readonly<{
  title: string
  subtitle: string
  dataSource?: string
  action?: React.ReactNode
  toolbar?: React.ReactNode
  breadcrumb?: { label: string; href?: string }[]
}>) {
  return (
    <header className="page-header page-header--compact">
      <div className="page-header-main">
        <div className="page-header-copy">
          {breadcrumb?.length ? (
            <nav className="page-breadcrumb" aria-label="Breadcrumb">
              {breadcrumb.map((item, index) => (
                <span key={`${item.label}-${index}`} className="page-breadcrumb-item">
                  {item.href
                    ? <a className="page-breadcrumb-link" href={item.href}>{item.label}</a>
                    : <span aria-current="page">{item.label}</span>}
                  {index < breadcrumb.length - 1 ? <span className="page-breadcrumb-sep" aria-hidden="true">/</span> : null}
                </span>
              ))}
            </nav>
          ) : null}
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
