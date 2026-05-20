import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from '@tanstack/react-query'
import { FormEvent, useState } from 'react'
import { apiGet, getSavedToken, saveToken } from './api/client'
import { CommandHero } from './components/CommandHero'
import { MovementDiagnosis } from './components/MovementDiagnosis'
import { PaperMiniStrip } from './components/PaperMiniStrip'
import { PrimaryAction } from './components/PrimaryAction'
import { SafetyBar } from './components/SafetyBar'
import { WorkerLanes } from './components/WorkerLanes'
import type { OverviewResponse, StatusResponse } from './types'

const queryClient = new QueryClient()

function TokenGate({ onSave }: { onSave: () => void }) {
  const [token, setToken] = useState(getSavedToken())
  function submit(event: FormEvent) {
    event.preventDefault()
    saveToken(token)
    onSave()
  }
  return (
    <main className="min-h-screen bg-zinc-950 p-6 text-zinc-100">
      <section className="mx-auto mt-24 max-w-xl rounded-3xl border border-zinc-800 bg-zinc-900 p-8 shadow-2xl">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-sky-300">Enoch Dashboard V2</p>
        <h1 className="mt-4 text-3xl font-black">Bearer token required</h1>
        <p className="mt-3 text-sm text-zinc-400">The React dashboard does not call authenticated APIs until a token is saved locally in this browser.</p>
        <form className="mt-6 flex gap-3" onSubmit={submit}>
          <input className="min-w-0 flex-1 rounded-xl border border-zinc-700 bg-black px-4 py-3 text-white" type="password" value={token} onChange={(event) => setToken(event.target.value)} placeholder="Bearer token" />
          <button className="rounded-xl bg-sky-500 px-4 py-3 font-bold text-white">Save</button>
        </form>
        <a className="mt-6 inline-block text-sm text-zinc-400 underline" href="/control/dashboard">Open legacy dashboard</a>
      </section>
    </main>
  )
}

function OverviewPage() {
  const queryClient = useQueryClient()
  const overview = useQuery({ queryKey: ['overview'], queryFn: () => apiGet<OverviewResponse>('/control/api/v1/overview?active_limit=8&event_limit=6') })
  const status = useQuery({ queryKey: ['status'], queryFn: () => apiGet<StatusResponse>('/control/api/status') })
  const refresh = () => void queryClient.invalidateQueries()

  if (overview.isLoading) {
    return <div className="rounded-3xl border border-zinc-800 bg-zinc-950 p-8 text-zinc-300">Loading command center…</div>
  }
  if (overview.isError || !overview.data) {
    return <div className="rounded-3xl border border-red-900 bg-red-950/40 p-8 text-red-100">Command state unavailable: {String(overview.error?.message || 'unknown error')}</div>
  }

  const data = overview.data
  const diagnosis = data.movement_diagnosis || { status: 'unknown', primary_reason: 'No movement diagnosis returned.', blockers: [] }
  return (
    <div className="space-y-5">
      <CommandHero overview={data} diagnosis={diagnosis} />
      <SafetyBar flags={data.flags} onRefresh={refresh} />
      <PrimaryAction action={data.top_actions?.[0]} />
      <WorkerLanes lanes={status.data?.worker_lanes || []} onRefresh={refresh} />
      <PaperMiniStrip pipeline={data.paper_pipeline} />
      <MovementDiagnosis diagnosis={diagnosis} />
      <details className="rounded-2xl border border-dashed border-zinc-800 bg-zinc-950/50 p-5 text-zinc-400">
        <summary className="cursor-pointer font-bold text-zinc-200">Show secondary details</summary>
        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <a className="rounded-xl border border-zinc-800 p-4 hover:border-zinc-600" href="/control/dashboard#queue:active">Active work</a>
          <a className="rounded-xl border border-zinc-800 p-4 hover:border-zinc-600" href="/control/dashboard#papers">Papers</a>
          <a className="rounded-xl border border-zinc-800 p-4 hover:border-zinc-600" href="/control/dashboard#events">Recent activity</a>
        </div>
      </details>
    </div>
  )
}

function Shell() {
  const [hasToken, setHasToken] = useState(Boolean(getSavedToken()))
  if (!hasToken) return <TokenGate onSave={() => setHasToken(Boolean(getSavedToken()))} />
  return (
    <main className="min-h-screen bg-[#09090b] p-4 text-zinc-100 md:p-8">
      <div className="mx-auto max-w-7xl space-y-6">
        <header className="flex flex-col gap-3 border-b border-zinc-800 pb-5 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="text-xs font-bold uppercase tracking-[0.32em] text-sky-300">Enoch Dashboard V2</p>
            <h1 className="mt-2 text-2xl font-black tracking-tight text-white">Operator command center</h1>
          </div>
          <nav className="flex gap-3 text-sm">
            <a className="text-zinc-400 hover:text-white" href="/control/dashboard">Legacy dashboard</a>
            <button className="text-zinc-400 hover:text-white" type="button" onClick={() => { saveToken(''); setHasToken(false) }}>Clear token</button>
          </nav>
        </header>
        <OverviewPage />
      </div>
    </main>
  )
}

export function App() {
  return <QueryClientProvider client={queryClient}><Shell /></QueryClientProvider>
}
