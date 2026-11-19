// Shared by the mods of this repository: the Galet look (successor of Terre de Sienne). Soft pastel surfaces
// with round corners and no visible rim, one tone per kind of card, flat drawings with no gradient, glass,
// shadow or sweeping light. Copied into each mod's hooks/shared/ by scripts/sync-shared.sh: edit it here,
// then run the script.
//
// Two kinds of colour live here:
// - GALET: the raw colours a native element (Box, Text) may carry. A native colour has one value for the
//   light and the dark theme, so every fill is translucent: it reads as a pale pastel on light and a deep one
//   on dark. A Box with a fill alone is drawn with square corners on the desktop; a round border rounds it,
//   so every surface carries a round border in a colour that does not show (`surface`).
// - TOKENS: the colours of the SVG drawings, which carry both themes and switch with prefers-color-scheme.
//
// Every drawing is a standalone <svg>. With scheme 'auto' (the default) it carries both themes; 'light' or
// 'dark' pins one. Every animation stops under prefers-reduced-motion.

export type Scheme = 'auto' | 'light' | 'dark'
export type Tone = 'ok' | 'running' | 'warning' | 'danger' | 'accent' | 'muted'
export type TokenName = 'base' | 'halo1' | 'halo2' | 'halo3' | 'text' | 'mute' | 'accent' | 'ok' | 'running' | 'warning' | 'danger' | 'track' | 'disc'

export const TOKENS: { light: Record<TokenName, string>; dark: Record<TokenName, string> } = {
  light: {
    base: '#f4ece0', halo1: '#eab26a', halo2: '#d98a5c', halo3: '#f0cf9a',
    text: '#1f1b17', mute: '#6b635b', accent: '#bf6f3a',
    ok: '#5d8a5a', running: '#bf6f3a', warning: '#a8802c', danger: '#b0503f',
    track: 'rgba(40,28,16,.10)', disc: 'rgba(40,28,16,.08)',
  },
  dark: {
    base: '#17110d', halo1: '#c8693c', halo2: '#e0a458', halo3: '#7a3b22',
    text: '#ece6df', mute: '#a49b91', accent: '#e3a46e',
    ok: '#93bf8c', running: '#e3a46e', warning: '#dcb466', danger: '#e08a78',
    track: 'rgba(255,240,225,.12)', disc: 'rgba(255,240,225,.10)',
  },
}

/** A kind of card, by the colour family it is drawn in. */
export type Family = 'ochre' | 'sage' | 'honey' | 'rose' | 'stone'

/**
 * The raw colours native elements may carry: one value each, legible on the light and the dark theme.
 * `text` colours are mid tones (≥ 3:1 on both bases for semibold); fills are translucent pastels.
 */
export const GALET = {
  text: { ochre: '#c0702a', sage: '#568a52', honey: 'warning', rose: '#c0503f', stone: 'subtle' } as Record<Family, string>,
  /** A card's surface. */
  fill: {
    ochre: 'rgba(191,111,58,.10)',
    sage: 'rgba(93,138,90,.12)',
    honey: 'rgba(190,140,40,.12)',
    rose: 'rgba(176,80,63,.10)',
    stone: 'rgba(128,120,110,.09)',
  } as Record<Family, string>,
  /** A tile or a tag inside a card: the card's tint once more, so it reads as a deeper pebble on either theme. */
  deep: {
    ochre: 'rgba(191,111,58,.12)',
    sage: 'rgba(93,138,90,.16)',
    honey: 'rgba(190,140,40,.14)',
    rose: 'rgba(176,80,63,.13)',
    stone: 'rgba(128,120,110,.11)',
  } as Record<Family, string>,
  /** Under the pointer: one step deeper. */
  hover: {
    ochre: 'rgba(191,111,58,.20)',
    sage: 'rgba(93,138,90,.24)',
    honey: 'rgba(190,140,40,.22)',
    rose: 'rgba(176,80,63,.20)',
    stone: 'rgba(128,120,110,.18)',
  } as Record<Family, string>,
} as const

/**
 * The app's light or dark mode, as the session's `theme` setting names it (`dark`, `light-daltonized`…);
 * `auto` when it follows the system, which a native colour cannot know.
 */
export type Mode = 'light' | 'dark' | 'auto'

export function modeOf(theme: unknown): Mode {
  return typeof theme !== 'string' ? 'auto' : theme.startsWith('dark') ? 'dark' : theme.startsWith('light') ? 'light' : 'auto'
}

/**
 * A tile or a chip inside a card: white on the light theme, a faint veil of light on the dark one (one shade
 * above the card, as the mock draws them). Where the mode is unknown, the card's tint once more.
 */
export function tileFill(mode: Mode, family: Family = 'ochre'): string {
  return mode === 'light' ? '#ffffff' : mode === 'dark' ? 'rgba(255,255,255,.06)' : GALET.deep[family]
}

/**
 * A soft chip's props: a pill with round ends and no rim, as tall as its text. Around a Button, `pressable`
 * leaves no margin and clips what passes the round edge, so the button's hover is exactly the pill.
 */
export function chip(
  fill: string,
  o: { pressable?: boolean } = {},
): { borderStyle: 'round'; borderColor: string; backgroundColor: string; paddingX: number; paddingY: number; overflow?: 'hidden' } {
  const base = { borderStyle: 'round' as const, borderColor: RIM, backgroundColor: fill, paddingX: o.pressable === true ? 0 : 1, paddingY: 0 }
  // The button's own hover is clipped to the pill's round edge, so it never shows past it.
  return o.pressable === true ? { ...base, overflow: 'hidden' } : base
}

/** The border a Galet surface carries: round, for the corners, in a colour that does not show. */
export const RIM = 'rgba(0,0,0,0)'

/** The props of a Galet surface: a pastel fill with round corners and no visible rim. */
export function surface(family: Family, depth: 'fill' | 'deep' | 'hover' = 'fill'): { borderStyle: 'round'; borderColor: string; backgroundColor: string } {
  return { borderStyle: 'round', borderColor: RIM, backgroundColor: GALET[depth][family] }
}

/** Which family a drawing tone belongs to. */
export function familyOf(tone: Tone): Family {
  return tone === 'ok' ? 'sage' : tone === 'warning' ? 'honey' : tone === 'danger' ? 'rose' : tone === 'muted' ? 'stone' : 'ochre'
}

/**
 * The colours earlier versions gave native elements; kept for the terminal's framed cards and the text that
 * names a tone. Accent, sage and danger stay legible on both bases.
 */
export const NATIVE = {
  accent: '#c0702a',
  accentBorder: 'rgba(192,112,42,.45)',
  accentFill: 'rgba(191,111,58,.10)',
  ok: '#568a52',
  danger: '#c0503f',
} as const

/** The narrowest a full-width drawing (the timeline) is ever drawn, in CSS pixels. */
export const MIN_WIDTH = 240

const TONE_VAR: Record<Tone, string> = {
  ok: 'var(--ok)', running: 'var(--running)', warning: 'var(--warning)', danger: 'var(--danger)', accent: 'var(--accent)', muted: 'var(--mute)',
}

const FONT = '-apple-system,BlinkMacSystemFont,&quot;SF Pro Text&quot;,Inter,sans-serif'
const EASE = 'cubic-bezier(.23,1,.32,1)'

function vars(scheme: 'light' | 'dark'): string {
  return Object.entries(TOKENS[scheme]).map(([name, value]) => `--${name}:${value}`).join(';')
}

/** The <style> every drawing opens with: the colour variables, the shared animations, reduced motion. */
export function styleSheet(scheme: Scheme = 'auto'): string {
  const colours =
    scheme === 'auto'
      ? `:root{${vars('light')}}@media (prefers-color-scheme: dark){:root{${vars('dark')}}}`
      : `:root{${vars(scheme)}}`
  return (
    `<style>${colours}` +
    // What is running breathes, slowly; what arrives eases in once.
    `.wave{transform-box:fill-box;transform-origin:center;animation:wave 2.4s ${EASE} infinite}` +
    `@keyframes wave{0%{opacity:.4;transform:scale(1)}80%,100%{opacity:0;transform:scale(2.1)}}` +
    `.fill{animation:fill 1.1s ${EASE} both}@keyframes fill{from{stroke-dashoffset:var(--from)}}` +
    `.grow{transform-box:fill-box;transform-origin:left center;animation:grow .9s ${EASE} both}@keyframes grow{from{transform:scaleX(0)}}` +
    `.drift1{animation:drift1 24s ease-in-out infinite alternate}@keyframes drift1{to{transform:translate(220px,140px) scale(1.15)}}` +
    `.drift2{animation:drift2 31s ease-in-out infinite alternate}@keyframes drift2{to{transform:translate(-260px,-120px) scale(.9)}}` +
    `.drift3{animation:drift3 38s ease-in-out infinite alternate}@keyframes drift3{to{transform:translate(160px,-160px)}}` +
    `@media (prefers-reduced-motion: reduce){*{animation:none!important}.motion{display:none}}` +
    `</style>`
  )
}

function open(width: number, height: number, scheme: Scheme, extra = ''): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"${extra}>${styleSheet(scheme)}`
}

function clamp01(value: number): number {
  return Number.isFinite(value) ? Math.max(0, Math.min(1, value)) : 0
}

export function escapeXml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

/** Cuts `text` with an ellipsis so it fits `maxPx` at about `pxPerChar` per character. */
export function fitText(text: string, maxPx: number, pxPerChar = 7): string {
  const max = Math.max(1, Math.floor(maxPx / pxPerChar))
  return text.length <= max ? text : `${text.slice(0, Math.max(1, max - 1)).trimEnd()}…`
}

/** A status dot; a pulsing one breathes out a soft wave; a hollow one is a ring, for a step still ahead. */
export function dot(tone: Tone, o: { pulse?: boolean; hollow?: boolean; size?: number; scheme?: Scheme } = {}): string {
  const size = o.size ?? 12
  const c = size / 2
  const r = size / 4
  if (o.hollow === true) {
    return `${open(size, size, o.scheme ?? 'auto')}<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke-width="1.5" style="stroke:${TONE_VAR[tone]}"/></svg>`
  }
  const fill = `style="fill:${TONE_VAR[tone]}"`
  const wave = o.pulse === true ? `<circle class="wave motion" cx="${c}" cy="${c}" r="${r}" ${fill}/>` : ''
  return `${open(size, size, o.scheme ?? 'auto')}${wave}<circle cx="${c}" cy="${c}" r="${r}" ${fill}/></svg>`
}

/** A ring filled to `fraction` from twelve o'clock, a flat stroke with round caps that fills as it appears. */
export function ring(fraction: number, o: { size?: number; tone?: Tone; label?: string; scheme?: Scheme; id?: string } = {}): string {
  const size = o.size ?? 16
  const stroke = size >= 48 ? 5 : size >= 24 ? 3 : 2.5
  const c = size / 2
  const r = c - stroke / 2 - (size >= 48 ? 1 : 0)
  const circumference = 2 * Math.PI * r
  const offset = circumference * (1 - clamp01(fraction))
  const paint = TONE_VAR[o.tone ?? 'accent']
  const label =
    o.label !== undefined
      ? `<text x="${c}" y="${c}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="${Math.round(size * 0.24)}" font-weight="500" style="fill:var(--text)">${escapeXml(o.label)}</text>`
      : ''
  return (
    `${open(size, size, o.scheme ?? 'auto')}` +
    `<circle cx="${c}" cy="${c}" r="${r.toFixed(2)}" fill="none" stroke-width="${stroke}" style="stroke:var(--track)"/>` +
    `<circle class="fill" cx="${c}" cy="${c}" r="${r.toFixed(2)}" fill="none" stroke-width="${stroke}" stroke-linecap="round" ` +
    `stroke-dasharray="${circumference.toFixed(2)}" stroke-dashoffset="${offset.toFixed(2)}" style="--from:${circumference.toFixed(2)};stroke:${paint}" transform="rotate(-90 ${c} ${c})"/>` +
    `${label}</svg>`
  )
}

/**
 * A soft bar filled to `fraction`, growing once as it appears. A finished one (`done`) is drawn in sage, paler,
 * so the eye goes to what is still under way.
 */
export function bar(width: number, fraction: number, o: { done?: boolean; tone?: Tone; scheme?: Scheme; id?: string } = {}): string {
  const w = Math.max(40, Math.round(width))
  const h = 5
  const filled = Math.round(w * clamp01(fraction))
  const tone = o.done === true ? 'ok' : o.tone ?? 'accent'
  return (
    `${open(w, h, o.scheme ?? 'auto')}` +
    `<rect width="${w}" height="${h}" rx="${h / 2}" style="fill:var(--track)"/>` +
    (filled > 0 ? `<rect class="grow" width="${filled}" height="${h}" rx="${h / 2}" style="fill:${TONE_VAR[tone]}"${o.done === true ? ' opacity=".55"' : ''}/>` : '') +
    `</svg>`
  )
}

export type IconName = 'question' | 'report' | 'qa' | 'commit' | 'check' | 'tool' | 'info' | 'warning' | 'cockpit' | 'flag' | 'hand' | 'next' | 'file' | 'chevron' | 'chevronDown'

/** Each icon drawn with strokes in an 18 × 18 box. */
const ICON_PATHS: Record<IconName, string> = {
  question: '<circle cx="9" cy="9" r="7"/><path d="M6.8 7a2.3 2.3 0 1 1 3.2 2.1c-.7.3-1 .8-1 1.4"/><path d="M9 13.2v.1"/>',
  report: '<rect x="3.5" y="2.5" width="11" height="13" rx="2"/><path d="M6.5 6.5h5M6.5 9.5h5M6.5 12.5h3"/>',
  qa: '<rect x="3" y="3" width="12" height="12" rx="3"/><path d="M6 9.2l2 2 4-4.4"/>',
  commit: '<circle cx="9" cy="9" r="3.5"/><path d="M1 9h4.5M12.5 9H17"/>',
  check: '<path d="M4 9.5l3.2 3.2L14 5.5"/>',
  tool: '<path d="M11.5 3.2a3.5 3.5 0 0 0-4.3 4.6L3 12l3 3 4.2-4.2a3.5 3.5 0 0 0 4.6-4.3l-2.1 2.1-2-.5-.5-2z"/>',
  info: '<circle cx="9" cy="9" r="7"/><path d="M9 8v4.5M9 5.5v.1"/>',
  warning: '<path d="M9 2.5l7 12.5H2z"/><path d="M9 7.5v3.5M9 13v.1"/>',
  cockpit: '<circle cx="9" cy="9" r="7"/><path d="M9 9l3.5-3.5"/><path d="M4.5 11.5h1.5M12 11.5h1.5"/>',
  flag: '<path d="M4 16V3h9l-1.7 3.2L13 9.5H4"/>',
  hand: '<path d="M3 11.5l4.2 3.5h6.3l1.7-6.8-1.7-.7-1.5 2.5V3.5l-1.8-.3-.5 5.3-.6-6.3-1.9.1.1 6.3L5 5.5l-1.7.5z"/>',
  next: '<path d="M3 9h11M10 4.8L14.2 9 10 13.2"/>',
  file: '<path d="M4 2.3h6l4 4v9.4H4z"/><path d="M10 2.3v4h4"/>',
  chevron: '<path d="M6.5 4.5L11 9l-4.5 4.5"/>',
  chevronDown: '<path d="M4.5 6.5L9 11l4.5-4.5"/>',
}

/** A small stroked icon. */
export function icon(name: IconName, o: { size?: number; tone?: Tone; scheme?: Scheme } = {}): string {
  const size = o.size ?? 16
  const scale = size / 18
  return (
    `${open(size, size, o.scheme ?? 'auto')}<g transform="scale(${scale})" fill="none" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" ` +
    `style="stroke:${TONE_VAR[o.tone ?? 'accent']}">${ICON_PATHS[name]}</g></svg>`
  )
}

/**
 * An option's letter in a soft disc: `chosen` fills it in ochre, `recommended` in sage, otherwise a pale
 * pebble with the letter in the secondary colour.
 */
export function disc(letter: string, o: { state?: 'chosen' | 'recommended' | 'plain'; size?: number; scheme?: Scheme } = {}): string {
  const size = o.size ?? 22
  const c = size / 2
  const state = o.state ?? 'plain'
  const fill = state === 'chosen' ? 'var(--accent)' : state === 'recommended' ? 'var(--ok)' : 'var(--disc)'
  const ink = state === 'plain' ? 'var(--mute)' : '#fff'
  return (
    `${open(size, size, o.scheme ?? 'auto')}<circle cx="${c}" cy="${c}" r="${c}" style="fill:${fill}"/>` +
    `<text x="${c}" y="${c}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="${Math.round(size * 0.5)}" font-weight="600" style="fill:${ink}">${escapeXml(letter.slice(0, 2))}</text></svg>`
  )
}

/**
 * The phases as soft segments: done ones filled, the current one half-filled, the rest a pale track; each
 * named underneath, the current one in the text colour.
 */
export function timeline(width: number, steps: string[], current: number, o: { scheme?: Scheme; id?: string } = {}): string {
  const w = Math.max(MIN_WIDTH, Math.round(width))
  const h = 26
  const gap = 4
  const n = Math.max(1, steps.length)
  const segment = (w - gap * (n - 1)) / n
  const at = current >= steps.length ? steps.length : current
  const parts = steps
    .map((step, index) => {
      const x = index * (segment + gap)
      const isDone = index < at
      const isCurrent = index === at
      const fill = isDone || isCurrent ? 'var(--accent)' : 'var(--track)'
      const label = escapeXml(fitText(step, segment + gap, 5.8))
      return (
        `<rect x="${x.toFixed(1)}" width="${segment.toFixed(1)}" height="6" rx="3" style="fill:${fill}"${isCurrent ? ' opacity=".45"' : ''}/>` +
        `<text x="${(x + segment / 2).toFixed(1)}" y="21" text-anchor="middle" font-family="${FONT}" font-size="10"${isCurrent ? ' font-weight="600"' : ''} style="fill:${isCurrent ? 'var(--text)' : 'var(--mute)'}">${label}</text>`
      )
    })
    .join('')
  return `${open(w, h, o.scheme ?? 'auto')}${parts}</svg>`
}

/**
 * Soft chips, each a pastel of its tone with its label in that tone, wrapping onto a new row past `maxWidth`;
 * measured, so the caller sizes the Svg from `width` and `height`. A `hint` becomes the chip's tooltip.
 */
export function pills(
  items: { label: string; tone: Tone; hint?: string }[],
  o: { maxWidth?: number; scheme?: Scheme } = {},
): { source: string; width: number; height: number } {
  const row = 22
  const gap = 6
  const maxWidth = Math.max(80, o.maxWidth ?? Number.POSITIVE_INFINITY)
  let x = 0
  let y = 0
  let width = 1
  const chips = items.map(item => {
    const w = Math.min(maxWidth, Math.round(item.label.length * 6.2 + 20))
    if (x > 0 && x + w > maxWidth) {
      x = 0
      y += row + gap
    }
    const colour = TONE_VAR[item.tone]
    const label = escapeXml(fitText(item.label, w - 18, 6.2))
    const chip =
      `<g>${item.hint !== undefined ? `<title>${escapeXml(item.hint)}</title>` : ''}` +
      `<rect x="${x}" y="${y}" width="${w}" height="${row}" rx="${row / 2}" style="fill:${colour}" fill-opacity=".14"/>` +
      `<text x="${x + w / 2}" y="${y + row / 2}" text-anchor="middle" dominant-baseline="central" font-family="${FONT}" font-size="11" font-weight="500" style="fill:${colour}">${label}</text></g>`
    x += w + gap
    width = Math.max(width, x - gap)
    return chip
  })
  const height = y + row
  return { source: `${open(width, height, o.scheme ?? 'auto')}${chips.join('')}</svg>`, width, height }
}

/** The window's backdrop: the base colour, three blurred halos drifting slowly, a light grain. */
export function backdrop(o: { scheme?: Scheme } = {}): string {
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1600 1000" preserveAspectRatio="xMidYMid slice">${styleSheet(o.scheme ?? 'auto')}` +
    `<defs><filter id="s-bd-blur" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="90"/></filter>` +
    `<filter id="s-bd-grain"><feTurbulence type="fractalNoise" baseFrequency=".9" numOctaves="2" stitchTiles="stitch"/>` +
    `<feColorMatrix values="0 0 0 0 .5 0 0 0 0 .5 0 0 0 0 .5 0 0 0 .09 0"/></filter></defs>` +
    `<rect width="1600" height="1000" style="fill:var(--base)"/>` +
    `<g filter="url(#s-bd-blur)" opacity=".6">` +
    `<circle class="drift1" cx="250" cy="150" r="320" style="fill:var(--halo1)"/>` +
    `<circle class="drift2" cx="1350" cy="850" r="380" style="fill:var(--halo2)"/>` +
    `<circle class="drift3" cx="800" cy="520" r="240" style="fill:var(--halo3)"/></g>` +
    `<rect width="1600" height="1000" filter="url(#s-bd-grain)"/></svg>`
  )
}

/** The WCAG contrast ratio of two #rrggbb colours. */
export function contrast(fg: string, bg: string): number {
  const luminance = (hex: string): number => {
    const value = hex.replace('#', '')
    const channels = [0, 2, 4].map(at => parseInt(value.slice(at, at + 2), 16) / 255)
    const [r = 0, g = 0, b = 0] = channels.map(c => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b
  }
  const [light = 0, dark = 0] = [luminance(fg), luminance(bg)].sort((a, b) => b - a)
  return (light + 0.05) / (dark + 0.05)
}
