import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const css = readFileSync(resolve(dirname(fileURLToPath(import.meta.url)), 'style.css'), 'utf8')

describe('style.css P7 guards', () => {
  it('styles native filter selects without replacing dropdown behavior', () => {
    expect(css).toContain('.filter-bar select')
    expect(css).toContain('appearance: none')
    expect(css).toContain('.filter-bar select:focus-visible')
  })

  it('tightens table density and primary title wrapping', () => {
    expect(css).toContain('.data-table td')
    expect(css).toMatch(/\.data-table td[\s\S]*padding:\s*0\.56rem 0\.72rem/)
    expect(css).toContain('-webkit-line-clamp: 2')
  })

  it('keeps detail panel scrolling inside the drawer body', () => {
    expect(css).toMatch(/\.detail-panel[\s\S]*overflow:\s*hidden/)
    expect(css).toMatch(/\.detail-body[\s\S]*min-height:\s*0/)
    expect(css).toMatch(/\.detail-body[\s\S]*overflow:\s*auto/)
  })

  it('defines focus-visible rings for keyboard navigation', () => {
    expect(css).toContain('--focus-ring')
    expect(css).toContain('.primary-button:focus-visible')
    expect(css).toContain('.selectable-row:focus-visible')
    expect(css).toContain('.cell-link:focus-visible')
  })
})
