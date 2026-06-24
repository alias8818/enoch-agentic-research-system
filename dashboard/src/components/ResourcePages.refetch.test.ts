import { afterEach, expect, it, vi } from 'vitest'
import { getSavedToken, saveToken } from '../api/client'
import { handleBackgroundRefetchError, isAuthLapsedError } from './ResourcePages'

afterEach(() => {
  vi.restoreAllMocks()
  saveToken('')
})

it('classifies apiGet/apiPost 401 error messages as auth lapsed (regression #354)', () => {
  // apiGet throws `new Error('path -> 401: detail')` on 401.
  const err = new Error('/control/api/v1/queue?queue=queued -> 401: unauthorized')
  expect(isAuthLapsedError(err)).toBe(true)
})

it('does not classify 5xx error messages as auth lapsed', () => {
  const err = new Error('/control/api/v1/queue -> 500: server error')
  expect(isAuthLapsedError(err)).toBe(false)
})

it('classifies Response-shaped wrappers with status 401 as auth lapsed', () => {
  expect(isAuthLapsedError({ status: 401, statusText: 'Unauthorized' })).toBe(true)
  expect(isAuthLapsedError({ status: '401' })).toBe(true)
  expect(isAuthLapsedError({ status: 500 })).toBe(false)
})

it('does not classify null or undefined as auth lapsed', () => {
  expect(isAuthLapsedError(null)).toBe(false)
  expect(isAuthLapsedError(undefined)).toBe(false)
})

it('case-insensitively matches the 401 marker in error messages', () => {
  expect(isAuthLapsedError(new Error('GET /api -> 401'))).toBe(true)
  expect(isAuthLapsedError(new Error('GET /api -> 401 Unauthorized'))).toBe(true)
})

it('on 401 clears the saved token and dispatches enoch:auth-lapsed', () => {
  saveToken('expired-token')
  const dispatchSpy = vi.spyOn(globalThis, 'dispatchEvent')

  handleBackgroundRefetchError(new Error('/control/api/v1/queue -> 401: unauthorized'))

  expect(getSavedToken()).toBe('')
  expect(dispatchSpy).toHaveBeenCalledTimes(1)
  const event = dispatchSpy.mock.calls[0]?.[0] as CustomEvent
  expect(event).toBeInstanceOf(CustomEvent)
  expect(event.type).toBe('enoch:auth-lapsed')
})

it('on non-401 errors preserves the token and logs at warn level', () => {
  saveToken('still-valid-token')
  const dispatchSpy = vi.spyOn(globalThis, 'dispatchEvent')
  const warnSpy = vi.spyOn(globalThis.console, 'warn').mockImplementation(() => undefined)

  handleBackgroundRefetchError(new Error('/control/api/v1/queue -> 500: server error'))

  expect(getSavedToken()).toBe('still-valid-token')
  expect(dispatchSpy).not.toHaveBeenCalled()
  expect(warnSpy).toHaveBeenCalledTimes(1)
})

it('on non-401 Response-shaped wrapper logs and does not dispatch', () => {
  saveToken('still-valid-token')
  const dispatchSpy = vi.spyOn(globalThis, 'dispatchEvent')
  const warnSpy = vi.spyOn(globalThis.console, 'warn').mockImplementation(() => undefined)

  handleBackgroundRefetchError({ status: 503, statusText: 'Service Unavailable' })

  expect(getSavedToken()).toBe('still-valid-token')
  expect(dispatchSpy).not.toHaveBeenCalled()
  expect(warnSpy).toHaveBeenCalledTimes(1)
})

it('on undefined error preserves the token and does not throw', () => {
  saveToken('still-valid-token')
  const dispatchSpy = vi.spyOn(globalThis, 'dispatchEvent')
  const warnSpy = vi.spyOn(globalThis.console, 'warn').mockImplementation(() => undefined)

  expect(() => handleBackgroundRefetchError(undefined)).not.toThrow()
  expect(() => handleBackgroundRefetchError(null)).not.toThrow()

  expect(getSavedToken()).toBe('still-valid-token')
  expect(dispatchSpy).not.toHaveBeenCalled()
  // We do not require warn to be called for null/undefined because there is
  // nothing meaningful to log; the key contract is "do not throw, do not
  // clear token, do not dispatch".
})