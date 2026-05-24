import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { type RefObject, useEffect, useRef, useState } from 'react'
import { RoutedPage } from './appRouting'
import { getSavedToken, saveToken } from './api/client'
import { KeyboardShortcutHelp } from './components/KeyboardShortcutHelp'
import { DASHBOARD_V2_PATH, canonicalDashboardHash, dashboardRouteTitle, dashboardV2Href, parseDashboardRoute } from './routes'
import type { DashboardRoute } from './routes'
import { detailParentPage } from './routePolicy'
import { applyTheme, getSavedTheme, saveTheme, toggleTheme, type DashboardTheme } from './theme'
import { useDashboardKeyboardShortcuts } from './useDashboardKeyboardShortcuts'

function TokenGate({ onSave }: Readonly<{ onSave: () => void }>) {
  const [token, setToken] = useState(getSavedToken())
  return (
    <main className="auth-frame">
      <section className="auth-card">
        <p className="eyebrow">Enoch Dashboard V2</p>
        <h1>Bearer token required</h1>
        <p>The React dashboard does not call authenticated APIs until a token is saved locally in this browser.</p>
        <form
          className="auth-form"
          onSubmit={(event) => {
            event.preventDefault()
            saveToken(token)
            onSave()
          }}
        >
          <input type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Bearer token" aria-label="Bearer token" />
          <button className="primary-button" type="submit">Save token</button>
        </form>
      </section>
    </main>
  )
}

function currentRoute(): DashboardRoute {
  const rawHash = globalThis.location.hash || '#overview'
  const canonical = canonicalDashboardHash(rawHash)
  if (canonical !== rawHash) {
    globalThis.history.replaceState(globalThis.history.state, '', `${DASHBOARD_V2_PATH}${canonical}`)
  }
  return parseDashboardRoute(canonical)
}

function navClass(route: DashboardRoute, page: DashboardRoute['page']): string {
  const active = route.page === page || (route.page === 'detail' && detailParentPage(route.kind) === page)
  if (active) return 'nav-link nav-link--active'
  return 'nav-link'
}

const MORE_NAV_PAGES = new Set<DashboardRoute['page']>(['events', 'observability', 'corpus', 'research', 'intake', 'automation', 'unsupported'])

function moreNavClass(route: DashboardRoute): string {
  if (MORE_NAV_PAGES.has(route.page)) return 'nav-more nav-more--active'
  return 'nav-more'
}

function projectsSearchHref(query: string): string {
  const trimmed = query.trim()
  if (!trimmed) return dashboardV2Href('#projects')
  return dashboardV2Href(`#projects?search=${encodeURIComponent(trimmed)}`)
}

function themeSwitchAriaLabel(theme: DashboardTheme): string {
  if (theme === 'dark') return 'Switch to light theme'
  return 'Switch to dark theme'
}

function themeSwitchButtonLabel(theme: DashboardTheme): string {
  if (theme === 'dark') return 'Light theme'
  return 'Dark theme'
}

function applyThemeToggle(theme: DashboardTheme, setTheme: (next: DashboardTheme) => void): void {
  const next = toggleTheme(theme)
  setTheme(next)
  saveTheme(next)
}

function GlobalSearchForm({ inputRef }: Readonly<{ inputRef: RefObject<HTMLInputElement | null> }>) {
  const [query, setQuery] = useState('')
  return (
    <form
      className="app-global-search"
      onSubmit={(event) => {
        event.preventDefault()
        globalThis.location.href = projectsSearchHref(query)
      }}
    >
      <label htmlFor="app-global-search-input">Global search</label>
      <input
        id="app-global-search-input"
        ref={inputRef}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search projects"
      />
      <button className="secondary-button" type="submit">Search projects</button>
    </form>
  )
}

function DashboardNav({ route, onClearToken }: Readonly<{ route: DashboardRoute; onClearToken: () => void }>) {
  return (
    <nav className="app-nav" aria-label="Dashboard V2 navigation">
      <a className={navClass(route, 'overview')} href={dashboardV2Href('#overview')}>Overview</a>
      <a className={navClass(route, 'projects')} href={dashboardV2Href('#projects')}>Projects</a>
      <a className={navClass(route, 'queue')} href={dashboardV2Href('#queue:queued')}>Queue</a>
      <a className={navClass(route, 'runs')} href={dashboardV2Href('#runs')}>Runs</a>
      <a className={navClass(route, 'papers')} href={dashboardV2Href('#papers')}>Papers</a>
      <details className={moreNavClass(route)}>
        <summary>More</summary>
        <div className="nav-menu">
          <a className={navClass(route, 'events')} href={dashboardV2Href('#events')}>Events</a>
          <a className={navClass(route, 'observability')} href={dashboardV2Href('#observability')}>Observability</a>
          <a className={navClass(route, 'corpus')} href={dashboardV2Href('#corpus')}>Corpus</a>
          <a className={navClass(route, 'research')} href={dashboardV2Href('#research')}>Research</a>
          <a className={navClass(route, 'intake')} href={dashboardV2Href('#intake')}>Intake</a>
          <a className={navClass(route, 'automation')} href={dashboardV2Href('#automation')}>Automation</a>
          <button className="nav-link" type="button" onClick={onClearToken}>Clear token</button>
        </div>
      </details>
    </nav>
  )
}

function ShellHeader({
  route,
  theme,
  searchInputRef,
  onOpenShortcuts,
  onToggleTheme,
  onClearToken,
}: Readonly<{
  route: DashboardRoute
  theme: DashboardTheme
  searchInputRef: RefObject<HTMLInputElement | null>
  onOpenShortcuts: () => void
  onToggleTheme: () => void
  onClearToken: () => void
}>) {
  return (
    <header className="app-header app-header--compact">
      <div className="app-brand">
        <a className="app-brand-link" href={dashboardV2Href('#overview')}>
          <span className="eyebrow">Enoch Dashboard V2</span>
        </a>
        <p className="app-header-context">{dashboardRouteTitle(route)}</p>
      </div>
      <DashboardNav route={route} onClearToken={onClearToken} />
      <div className="app-header-tools">
        <GlobalSearchForm inputRef={searchInputRef} />
        <button className="secondary-button" type="button" aria-label="Show keyboard shortcuts" onClick={onOpenShortcuts}>
          Shortcuts
        </button>
        <button
          className="secondary-button"
          type="button"
          aria-label={themeSwitchAriaLabel(theme)}
          onClick={onToggleTheme}
        >
          {themeSwitchButtonLabel(theme)}
        </button>
      </div>
    </header>
  )
}

function Shell() {
  const [hasToken, setHasToken] = useState(Boolean(getSavedToken()))
  const [route, setRoute] = useState<DashboardRoute>(() => currentRoute())
  const [theme, setTheme] = useState<DashboardTheme>(() => getSavedTheme())
  const [shortcutHelpOpen, setShortcutHelpOpen] = useState(false)
  const searchInputRef = useRef<HTMLInputElement | null>(null)

  useEffect(() => {
    applyTheme(theme)
  }, [theme])

  useEffect(() => {
    const onHashChange = () => setRoute(currentRoute())
    globalThis.addEventListener('hashchange', onHashChange)
    return () => globalThis.removeEventListener('hashchange', onHashChange)
  }, [])

  useDashboardKeyboardShortcuts({
    helpOpen: shortcutHelpOpen,
    onToggleHelp: () => setShortcutHelpOpen((current) => !current),
    onCloseHelp: () => setShortcutHelpOpen(false),
    searchInputRef,
  })

  if (!hasToken) return <TokenGate onSave={() => setHasToken(Boolean(getSavedToken()))} />
  return (
    <main className="app-frame">
      <div className="app-shell">
        <ShellHeader
          route={route}
          theme={theme}
          searchInputRef={searchInputRef}
          onOpenShortcuts={() => setShortcutHelpOpen(true)}
          onToggleTheme={() => applyThemeToggle(theme, setTheme)}
          onClearToken={() => {
            saveToken('')
            setHasToken(false)
          }}
        />
        <RoutedPage route={route} />
        <KeyboardShortcutHelp open={shortcutHelpOpen} onClose={() => setShortcutHelpOpen(false)} />
      </div>
    </main>
  )
}

export function App() {
  const [queryClient] = useState(() => new QueryClient())
  return <QueryClientProvider client={queryClient}><Shell /></QueryClientProvider>
}
