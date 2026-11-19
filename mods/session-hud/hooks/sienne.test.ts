import { describe, expect, test } from 'claude-code/testing'

import { GALET, NATIVE, RIM, backdrop, bar, chip, contrast, disc, dot, icon, modeOf, pills, ring, surface, tileFill, timeline } from './shared/sienne'

const ids = (svg: string): string[] => [...svg.matchAll(/\bid="([^"]+)"/g)].map(match => match[1] ?? '')

describe('the Galet look', () => {
  test('every native text colour stays legible on both bases', () => {
    for (const colour of [NATIVE.accent, NATIVE.ok, NATIVE.danger, GALET.text.ochre, GALET.text.sage, GALET.text.rose]) {
      expect(contrast(colour, '#ffffff')).toBeGreaterThanOrEqual(3)
      expect(contrast(colour, '#1e1c1a')).toBeGreaterThanOrEqual(3)
    }
  })

  test('a surface is a pastel with round corners and a rim that does not show; a chip is as tall as its text', () => {
    expect(surface('sage')).toEqual({ borderStyle: 'round', borderColor: RIM, backgroundColor: GALET.fill.sage })
    expect(surface('ochre', 'deep').backgroundColor).toBe(GALET.deep.ochre)
    expect(RIM).toBe('rgba(0,0,0,0)')
    expect(chip('#fff')).toMatchObject({ borderStyle: 'round', paddingY: 0, backgroundColor: '#fff' })
  })

  test('the mode comes from the theme setting, and a tile follows it', () => {
    expect(modeOf('dark')).toBe('dark')
    expect(modeOf('dark-daltonized')).toBe('dark')
    expect(modeOf('light-ansi')).toBe('light')
    expect(modeOf('auto')).toBe('auto')
    expect(modeOf(undefined)).toBe('auto')
    expect(tileFill('light')).toBe('#ffffff')
    expect(tileFill('dark')).toBe('rgba(255,255,255,.06)')
    expect(tileFill('auto', 'sage')).toBe(GALET.deep.sage)
  })

  test('every drawing carries both schemes and reduced motion', () => {
    const drawings = [dot('running', { pulse: true }), ring(0.4), bar(200, 0.5), timeline(300, ['a', 'b', 'c'], 1), disc('A'), icon('question'), pills([{ label: 'x', tone: 'ok' }]).source, backdrop()]
    for (const svg of drawings) {
      expect(svg).toContain('prefers-color-scheme: dark')
      expect(svg).toContain('prefers-reduced-motion')
    }
    const fixed = ring(0.4, { scheme: 'dark' })
    expect(fixed).not.toContain('prefers-color-scheme')
    expect(fixed).toContain('#e3a46e')
    expect(backdrop({ scheme: 'dark' })).toContain('#17110d')
  })

  test('the drawings are flat: no gradient, glass, shadow or sweeping light', () => {
    const drawings = [ring(0.4, { size: 54, label: '79%' }), bar(200, 0.5), timeline(300, ['a', 'b', 'c'], 1), pills([{ label: 'review à faire', tone: 'danger' }]).source, disc('B', { state: 'recommended' })]
    for (const svg of drawings) {
      expect(svg).not.toContain('Gradient')
      expect(svg).not.toContain('feDropShadow')
      expect(svg).not.toContain('class="glide')
      expect(svg).not.toContain('class="shimmer')
    }
  })

  test('two drawings never share an id', () => {
    const shared = ids(backdrop()).filter(id => ids(ring(0.3, { id: 'x' })).includes(id))
    expect(shared).toEqual([])
  })

  test('a finished bar is sage and paler; a bar under way is in the accent', () => {
    expect(bar(200, 1, { done: true })).toContain('style="fill:var(--ok)" opacity=".55"')
    expect(bar(200, 0.5)).toContain('style="fill:var(--accent)"')
  })

  test('a chip names its tone in its own colour, on a pastel of it, and carries a hint', () => {
    const drawn = pills([{ label: 'graph périmé', tone: 'warning', hint: 'à rafraîchir' }]).source
    expect(drawn).toMatch(/<text[^>]*style="fill:var\(--warning\)"[^>]*>graph périmé</)
    expect(drawn).toContain('fill-opacity=".14"')
    expect(drawn).toContain('<title>à rafraîchir</title>')
  })

  test('chips wrap onto a second row when the width runs out', () => {
    const items = ['graphe à jour', 'arbre sale', 'revue faite', 'tests verts'].map(label => ({ label, tone: 'ok' as const }))
    const wide = pills(items, { maxWidth: 1000 })
    const narrow = pills(items, { maxWidth: 240 })
    expect(narrow.height).toBeGreaterThan(wide.height)
    expect(narrow.width).toBeLessThanOrEqual(240)
  })

  test('the timeline fills the steps done, half-fills the current one, names the current one in the text colour', () => {
    const svg = timeline(300, ['cadrage', 'ff', 'apply', 'review'], 2)
    expect(svg.match(/style="fill:var\(--accent\)"/g)?.length).toBe(3)
    expect(svg).toContain('opacity=".45"')
    expect(svg).toMatch(/font-weight="600" style="fill:var\(--text\)">apply</)
    expect(timeline(300, ['a', 'b'], 2).match(/style="fill:var\(--accent\)"/g)?.length).toBe(2)
  })

  test('a disc fills ochre once chosen, sage when recommended, and stays a pale pebble otherwise', () => {
    expect(disc('A', { state: 'chosen' })).toContain('style="fill:var(--accent)"')
    expect(disc('B', { state: 'recommended' })).toContain('style="fill:var(--ok)"')
    expect(disc('C')).toContain('style="fill:var(--disc)"')
  })

  test('ring and bar clamp their fraction', () => {
    expect(ring(1.7)).toEqual(ring(1))
    expect(bar(200, -1)).toEqual(bar(200, 0))
  })

  test('a hollow dot is a ring for a step still ahead', () => {
    expect(dot('muted', { hollow: true })).toContain('fill="none"')
    expect(dot('muted')).not.toContain('fill="none"')
  })

  test('sizes stay under the Svg limit', () => {
    expect(backdrop().length).toBeLessThan(131072)
  })
})
