import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { TopAction } from '../types'
import { usePrimaryActionController } from './usePrimaryActionController'

const dispatchAction: TopAction = {
  kind: 'dispatch_next',
  title: 'Dispatch queued work',
  action_label: 'Dispatch work',
}

const writePaperAction: TopAction = {
  kind: 'write_paper',
  title: 'Write a paper',
  action_label: 'Draft paper',
}

afterEach(() => {
  vi.restoreAllMocks()
})

it('ignores a dry-run result that resolves after the selected action changes', async () => {
  let resolveDryRun: (response: Response) => void = () => undefined
  const dryRunPromise = new Promise<Response>((resolve) => {
    resolveDryRun = resolve
  })
  vi.spyOn(globalThis, 'fetch').mockImplementationOnce(() => dryRunPromise)
  const onRefresh = vi.fn()
  const { result, rerender } = renderHook(
    ({ action }) => usePrimaryActionController(action, onRefresh),
    { initialProps: { action: dispatchAction } },
  )

  let runPromise: Promise<void> = Promise.resolve()
  act(() => {
    runPromise = result.current.runDryRun()
  })
  rerender({ action: writePaperAction })
  await act(async () => {
    resolveDryRun(new Response(JSON.stringify({ action: 'dry_run_dispatch_next' }), { status: 200 }))
    await runPromise
  })

  expect(result.current.result).toBeNull()
  expect(result.current.isPending).toBe(false)
  expect(onRefresh).not.toHaveBeenCalled()
})

it('records the current action command family when a dry-run result is still current', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response(JSON.stringify({ action: 'dry_run_dispatch_next' }), { status: 200 }))
  const onRefresh = vi.fn()
  const { result } = renderHook(() => usePrimaryActionController(dispatchAction, onRefresh))

  await act(async () => {
    await result.current.runDryRun()
  })

  expect(result.current.result).toMatchObject({
    payload: { action: 'dry_run_dispatch_next' },
    context: { commandFamily: 'dispatch' },
  })
  expect(result.current.isPending).toBe(false)
  expect(onRefresh).toHaveBeenCalledTimes(1)
})
