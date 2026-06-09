import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const srcDir = resolve(__dirname)

function source(relativePath: string): string {
  return readFileSync(resolve(srcDir, relativePath), 'utf8')
}

describe('Sonar maintainability guards', () => {
  it('keeps overview state bindings and paper strip actions free of known Sonar findings', () => {
    const overviewSource = source('overviewPage.tsx')
    const paperStripSource = source('components/PaperMiniStrip.tsx')

    expect(overviewSource).not.toContain('const [secondaryOpen, setSecondaryOpen]')
    expect(paperStripSource).toContain('paperPipelineClosestAction(finalizeNeeded, writeNeeded, publishReady)')
    expect(paperStripSource).not.toContain("finalizeNeeded > 0 ? 'Finalize drafts'")
  })
})
