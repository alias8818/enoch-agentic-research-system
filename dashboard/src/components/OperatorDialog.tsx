import { useCallback, useState } from 'react'

type DialogTone = 'info' | 'warn' | 'danger'

type DialogRequest = {
  kind: 'confirm' | 'notice'
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  tone?: DialogTone
  resolve: (value: boolean) => void
}

type ConfirmOptions = Omit<DialogRequest, 'kind' | 'resolve'>
type NoticeOptions = Omit<DialogRequest, 'kind' | 'resolve' | 'cancelLabel'>

function toneClasses(tone: DialogTone | undefined): string {
  if (tone === 'danger') return 'border-red-500/40 bg-red-950/40 text-red-100'
  if (tone === 'warn') return 'border-amber-500/40 bg-amber-950/30 text-amber-100'
  return 'border-sky-500/30 bg-zinc-950 text-zinc-100'
}

export function useOperatorDialog() {
  const [request, setRequest] = useState<DialogRequest | null>(null)

  const close = useCallback((value: boolean) => {
    setRequest((current) => {
      current?.resolve(value)
      return null
    })
  }, [])

  const confirm = useCallback((options: ConfirmOptions) => new Promise<boolean>((resolve) => {
    setRequest({ ...options, kind: 'confirm', resolve })
  }), [])

  const notify = useCallback((options: NoticeOptions) => new Promise<void>((resolve) => {
    setRequest({ ...options, kind: 'notice', resolve: () => resolve() })
  }), [])

  const dialog = request ? (
    <dialog className={`fixed left-1/2 top-1/2 z-50 w-[min(92vw,32rem)] -translate-x-1/2 -translate-y-1/2 rounded-3xl border p-0 shadow-2xl shadow-black/70 backdrop:bg-black/70 ${toneClasses(request.tone)}`} open aria-label={request.title}>
      <div className="p-6">
        <p className="text-xs font-bold uppercase tracking-[0.24em] text-zinc-400">Operator confirmation</p>
        <h2 className="mt-3 text-2xl font-black text-white">{request.title}</h2>
        <p className="mt-3 text-sm leading-6 text-zinc-300">{request.message}</p>
        <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
          {request.kind === 'confirm' ? (
            <button className="rounded-xl border border-zinc-700 px-4 py-2 text-sm font-bold text-white hover:border-zinc-500" type="button" onClick={() => close(false)}>{request.cancelLabel || 'Cancel'}</button>
          ) : null}
          <button className="rounded-xl bg-sky-500 px-4 py-2 text-sm font-bold text-white hover:bg-sky-400" type="button" onClick={() => close(true)} autoFocus>{request.confirmLabel || 'Continue'}</button>
        </div>
      </div>
    </dialog>
  ) : null

  return { confirm, notify, dialog }
}
