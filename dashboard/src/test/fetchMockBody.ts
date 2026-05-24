type FetchMock = {
  mock: {
    calls: unknown[][]
  }
}

export function fetchMockCallUrl(fetchMock: FetchMock, callIndex: number): string {
  const input = fetchMock.mock.calls[callIndex]?.[0]
  if (typeof input === 'string') return input
  if (input instanceof URL) return input.href
  if (input instanceof Request) return input.url
  throw new TypeError(`Expected fetch mock call ${callIndex} URL to be a string, URL, or Request`)
}

export function fetchMockRequestBody(fetchMock: FetchMock, callIndex: number): string {
  const init = fetchMock.mock.calls[callIndex]?.[1] as RequestInit | undefined
  const body = init?.body
  if (typeof body === 'string') return body
  throw new TypeError(`Expected fetch mock call ${callIndex} body to be a string`)
}
