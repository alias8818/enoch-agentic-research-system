import { describe, expect, it } from 'vitest'
import {
  publicCorpusArtifactUrl,
  publicCorpusIndexUrl,
  publicCorpusPaperUrl,
  publicReleaseValidatorUrl,
} from './corpusLinks'

describe('corpusLinks', () => {
  it('builds public corpus artifact links from artifact_slug', () => {
    expect(publicCorpusArtifactUrl({ artifact_slug: 'controlled-drill' })).toBe(
      'https://github.com/alias8818/enoch-ai-research-corpus/tree/main/papers/controlled-drill',
    )
    expect(publicCorpusPaperUrl({ artifact_slug: 'controlled-drill' })).toBe(
      'https://github.com/alias8818/enoch-ai-research-corpus/tree/main/papers/controlled-drill/paper.md',
    )
  })

  it('returns null when slug is missing', () => {
    expect(publicCorpusArtifactUrl({ paper_id: 'paper-1' })).toBeNull()
  })

  it('exposes release validator and corpus index helpers', () => {
    expect(publicReleaseValidatorUrl()).toContain('validate_public_release.py')
    expect(publicCorpusIndexUrl()).toContain('papers/index.json')
  })
})
