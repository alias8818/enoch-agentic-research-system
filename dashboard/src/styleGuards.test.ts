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

  it('keeps disabled buttons and queue step labels above the contrast floor', () => {
    expect(css).toMatch(/\.primary-button:disabled,[^{]*\{[^}]*color:\s*#f4f1ea/)
    expect(css).toMatch(/\.queue-action-steps__item \{[^}]*color:\s*#a69f96/)
    expect(css).toMatch(/\.queue-action-steps__item--ready \{[^}]*background:\s*rgba\(0,0,0,0\.24\)/)
    expect(css).not.toMatch(/\.primary-button:disabled,[^{]*\{[^}]*color:\s*rgba\(244, 241, 234, 0\.38\)/)
    expect(css).not.toMatch(/\.primary-button:disabled,[^{]*\{[^}]*color:\s*rgba\(244, 241, 234, 0\.56\)/)
    expect(css).not.toMatch(/\.primary-button:disabled,[^{]*\{[^}]*color:\s*rgba\(244, 241, 234, 0\.72\)/)
    expect(css).not.toMatch(/\.queue-action-steps__item \{[^}]*color:\s*#837d75/)
    expect(css).not.toMatch(/\.queue-action-steps__item--ready \{[^}]*background:\s*rgba\(34,197,94,0\.1\)/)
  })
})
