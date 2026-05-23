import { displayText } from './displayText'

export function formatReadinessErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return displayText(error, 'unknown error')
}
