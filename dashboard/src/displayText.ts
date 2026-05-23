export function displayText(value: unknown, fallback = ''): string {
  if (value === null || value === undefined) return fallback
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value)
  }
  return fallback
}

function parseCountNumber(value: unknown): number {
  if (typeof value === 'number') return value
  if (typeof value === 'string') return Number(value.trim())
  return Number.NaN
}

function floorPositiveCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return '0'
  return String(Math.floor(value))
}

/** Non-negative integer count for operator queue and similar numeric fields. */
export function displayCount(value: unknown): string {
  if (value === null || value === undefined || typeof value === 'boolean') return '0'
  return floorPositiveCount(parseCountNumber(value))
}
