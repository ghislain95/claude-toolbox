// The band's figures, formatted in French. No `$` here: every function is testable on its own.

import type { HudFigures } from '../types'

const MINUTE = 60 * 1000
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

export type Tone = 'ok' | 'warning' | 'danger' | 'neutral' | 'muted'

/** One figure of the band: its value, what it is, how alarming, and a gauge (0 to 1) when it fills up. */
export type HudItem = { key: string; value: string; label: string; tone: Tone; gauge?: number; hint?: string }

export function formatDuration(ms: number): string {
  const safe = Math.max(0, ms)
  if (safe < MINUTE) return `${Math.round(safe / 1000)} s`
  if (safe < HOUR) return `${Math.round(safe / MINUTE)} min`
  if (safe < DAY) {
    const totalMinutes = Math.round(safe / MINUTE)
    const hours = Math.floor(totalMinutes / 60)
    const minutes = totalMinutes % 60
    if (hours === 24) return '1 j'
    return minutes === 0 ? `${hours} h` : `${hours} h ${String(minutes).padStart(2, '0')}`
  }
  return `${Math.round(safe / DAY)} j`
}

/** 12.4 → « 12,40 $ ». */
export function formatUsd(usd: number): string {
  return `${usd.toFixed(2).replace('.', ',')} $`
}

/** 443 491 → « 443 k », 1 234 567 → « 1,2 M ». */
export function formatTokens(count: number): string {
  if (count < 1000) return String(count)
  if (count < 1000000) return `${Math.round(count / 1000)} k`
  return `${(count / 1000000).toFixed(1).replace('.', ',').replace(',0', '')} M`
}

/** `claude-opus-5-5` → « Opus 5.5 »; an unknown id as it is. */
export function modelLabel(model: string): string {
  const id = model.replace(/\[.*\]$/, '').replace(/-\d{8}$/, '')
  const family = /(opus|sonnet|haiku|fable)/.exec(id)?.[1]
  if (family === undefined) return id
  const version = (id.replace(family, '').match(/\d+/g) ?? []).slice(0, 2).join('.')
  return `${family.charAt(0).toUpperCase()}${family.slice(1)}${version === '' ? '' : ` ${version}`}`
}

/** Green under 60 %, amber under 85 %, red beyond. */
export function toneOfPercent(percent: number): Tone {
  return percent >= 85 ? 'danger' : percent >= 60 ? 'warning' : 'ok'
}

/** « 5h » and « 7d » rate limits as the band names them. */
function limitLabel(kind: string): string {
  if (/five|5h|session/i.test(kind)) return 'limite 5 h'
  if (/seven|7d|week/i.test(kind)) return 'limite semaine'
  return 'limite'
}

/** The figures of the band, left to right: context, spend, session time, tools, errors, model. */
export function hudItems(figures: HudFigures, now: number): HudItem[] {
  const items: HudItem[] = []
  if (figures.contextPercent !== null) {
    const tokens =
      figures.contextTokens !== null && figures.contextWindow !== null
        ? `${formatTokens(figures.contextTokens)} sur ${formatTokens(figures.contextWindow)} tokens`
        : undefined
    items.push({
      key: 'context',
      value: `${Math.round(figures.contextPercent)} %`,
      label: 'contexte',
      tone: toneOfPercent(figures.contextPercent),
      gauge: Math.min(1, Math.max(0, figures.contextPercent / 100)),
      hint: tokens,
    })
  }
  if (figures.costUsd !== null) {
    items.push({ key: 'spend', value: formatUsd(figures.costUsd), label: 'coût', tone: 'neutral' })
  } else if (figures.rateLimit !== null) {
    items.push({
      key: 'spend',
      value: `${Math.round(figures.rateLimit.percent)} %`,
      label: limitLabel(figures.rateLimit.kind),
      tone: toneOfPercent(figures.rateLimit.percent),
      gauge: Math.min(1, Math.max(0, figures.rateLimit.percent / 100)),
    })
  }
  items.push({ key: 'time', value: formatDuration(now - figures.startedAt), label: 'session', tone: 'neutral' })
  items.push({ key: 'tools', value: String(figures.toolCalls), label: figures.toolCalls === 1 ? 'outil' : 'outils', tone: 'neutral' })
  if (figures.toolErrors > 0) {
    items.push({ key: 'errors', value: String(figures.toolErrors), label: figures.toolErrors === 1 ? 'erreur' : 'erreurs', tone: 'danger' })
  }
  if (figures.model !== null) items.push({ key: 'model', value: modelLabel(figures.model), label: '', tone: 'muted' })
  return items
}

/** « 3 en arrière-plan », or null when nothing runs. */
export function backgroundLabel(count: number): string | null {
  return count <= 0 ? null : `${count} en arrière-plan`
}

/** The band on one line of text, for the terminal. */
export function bandLine(items: HudItem[], background: number): string {
  const parts = items.map(item => (item.label === '' ? item.value : `${item.value} ${item.label}`))
  const tasks = backgroundLabel(background)
  return [...parts, ...(tasks === null ? [] : [`⚙ ${tasks}`])].join(' · ')
}

/** About how wide the band draws each part, in CSS pixels (measured on the desktop: values in footnote type, labels in caption). */
const VALUE_PX = 6.8
const LABEL_PX = 5.6
const GAUGE_PX = 18
const ITEM_GAP_PX = 14
const BAND_CHROME_PX = 50

function itemPx(item: HudItem, showLabels: boolean): number {
  const label = showLabels && item.label !== '' ? item.label.length * LABEL_PX + 4 : 0
  return (item.gauge !== undefined ? GAUGE_PX : 0) + item.value.length * VALUE_PX + label + ITEM_GAP_PX
}

/**
 * What fits the band's width, so that no item is ever squeezed onto two lines: everything when there is room,
 * then the values without their labels, then without the model.
 */
export function fitBand(items: HudItem[], widthPx: number, extraText: string): { items: HudItem[]; showLabels: boolean } {
  const room = widthPx - BAND_CHROME_PX - (extraText === '' ? 0 : extraText.length * 6.4 + ITEM_GAP_PX)
  const width = (list: HudItem[], showLabels: boolean) => list.reduce((sum, item) => sum + itemPx(item, showLabels), 0)
  if (width(items, true) <= room) return { items, showLabels: true }
  if (width(items, false) <= room) return { items, showLabels: false }
  return { items: items.filter(item => item.key !== 'model'), showLabels: false }
}
