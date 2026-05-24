import { displayText } from './displayText'

const PUBLIC_CORPUS_REPO = 'alias8818/enoch-ai-research-corpus'
const SYSTEM_REPO = 'alias8818/enoch-agentic-research-system'

function corpusSlug(row: Record<string, unknown>): string {
  return displayText(row.artifact_slug || row.related_artifact_slug).trim()
}

export function publicCorpusArtifactUrl(row: Record<string, unknown>): string | null {
  const slug = corpusSlug(row)
  if (!slug) return null
  return `https://github.com/${PUBLIC_CORPUS_REPO}/tree/main/papers/${encodeURIComponent(slug)}`
}

export function publicCorpusPaperUrl(row: Record<string, unknown>): string | null {
  const artifactUrl = publicCorpusArtifactUrl(row)
  if (!artifactUrl) return null
  return `${artifactUrl}/paper.md`
}

export function publicReleaseValidatorUrl(): string {
  return `https://github.com/${SYSTEM_REPO}/blob/main/scripts/validate_public_release.py`
}

export function publicCorpusIndexUrl(): string {
  return `https://github.com/${PUBLIC_CORPUS_REPO}/blob/main/papers/index.json`
}
