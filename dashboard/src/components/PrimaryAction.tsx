import { legacyDashboardHref } from '../navigation'
import type { TopAction } from '../types'

export function PrimaryAction({ action }: { action?: TopAction }) {
  if (!action) {
    return (
      <section className="rounded-2xl border border-emerald-500/20 bg-zinc-950 p-5">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-zinc-500">Primary action</p>
        <h2 className="mt-2 text-xl font-bold text-white">Nothing to click right now</h2>
        <p className="mt-1 text-sm text-zinc-400">The backend action model did not rank an operator action.</p>
      </section>
    )
  }
  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-sky-500/30 bg-zinc-950 p-5 md:flex-row md:items-center md:justify-between">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-zinc-500">Primary action</p>
        <h2 className="mt-2 text-xl font-bold text-white">{action.title}</h2>
        <p className="mt-1 text-sm text-zinc-400">{action.summary}</p>
      </div>
      <a className="rounded-xl bg-sky-500 px-4 py-2 text-center text-sm font-bold text-white hover:bg-sky-400" href={legacyDashboardHref(action.action_hash)}>
        {action.action_label || 'Open'}
      </a>
    </section>
  )
}
