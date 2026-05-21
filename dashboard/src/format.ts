export function shortId(value: string): string {
  if (value.length <= 30) return value
  return `${value.slice(0, 14)}…${value.slice(-10)}`
}
