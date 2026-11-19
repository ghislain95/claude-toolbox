// session-hud: one line above the prompt, in every project. The session's context, its cost or rate
// limit, its time, its tool calls and errors, the model, and how many tasks run in the background
// (a click opens the background-tasks pane when that mod is installed). It also sets the window's
// Terre de Sienne backdrop on the desktop (/fond turns it off or on).
//
// The band reads one value, written every 30 seconds and at each turn's end: never per tool call,
// so it does not redraw while subagents work.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { BackgroundItem, HudFigures } from '../types'
import { type Tone as HudTone, backgroundLabel, bandLine, fitBand, hudItems } from './hud'
import { GALET, NATIVE, type Tone, backdrop, chip, dot, ring, surface } from './shared/sienne'
import { KIND_LABEL, isInFlight, portOf, taskKind, taskLabel } from './shared/tasks'

const figures = atom({ plugin: 'session-hud', key: 'figures' } as const, null)
const isListOpen = atom({ plugin: 'session-hud', key: 'isListOpen' } as const, false)

const REFRESH_MS = 30 * 1000
const BACKDROP_ID = 'sienne'

/** The band's tones as Sienne draws them, and as a native Text colours them. */
const DRAWN_TONE: Record<HudTone, Tone> = { ok: 'ok', warning: 'warning', danger: 'danger', neutral: 'accent', muted: 'muted' }
const TEXT_COLOUR: Record<HudTone, string | undefined> = { ok: NATIVE.ok, warning: 'warning', danger: NATIVE.danger, neutral: undefined, muted: undefined }

/** Tool calls and errors since the last refresh, handed to the band in one go. */
let pendingCalls = 0
let pendingErrors = 0
/**
 * Tasks in flight at the last turn's end, subagents included; undefined until this module sees a turn end.
 * The list itself lives in the session's state: a reload of the module (at the end of a turn that edited it)
 * must not wipe what the turn's end just reported.
 */
let backgroundTasks: BackgroundItem[] | undefined

async function refresh($: EngineInterface): Promise<void> {
  try {
    const [usage, model, previous] = await Promise.all([
      $.session.usage(),
      $.session.model().catch(() => null),
      read($, figures),
    ])
    const limit = [...usage.rateLimits].sort((a, b) => b.percentUsed - a.percentUsed)[0]
    const next: HudFigures = {
      startedAt: usage.startedAt,
      contextPercent: usage.context.percent ?? null,
      contextTokens: usage.context.tokens ?? null,
      contextWindow: usage.context.window,
      costUsd: usage.cost?.usd ?? null,
      rateLimit: limit === undefined ? null : { kind: limit.kind, percent: limit.percentUsed, resetsAt: limit.resetsAt ?? null },
      model,
      toolCalls: (previous?.toolCalls ?? 0) + pendingCalls,
      toolErrors: (previous?.toolErrors ?? 0) + pendingErrors,
      tasks: backgroundTasks ?? previous?.tasks ?? [],
    }
    pendingCalls = 0
    pendingErrors = 0
    if (JSON.stringify(next) !== JSON.stringify(previous)) await update($, figures, () => next)
  } catch {
    // The usage could not be read: the band keeps what it showed.
  }
}

/**
 * The backdrop is off unless the person turned it on with /fond (the Galet look draws on the app's own ground);
 * the choice is kept across sessions.
 */
async function isBackdropOn($: EngineInterface): Promise<boolean> {
  return ((await $.store.get('backdrop').catch(() => undefined)) ?? 'off') === 'on'
}

/**
 * Sets the backdrop as the session's theme, or clears the theme; says whether a surface draws it
 * (the terminal and desktop builds without the layer do not). A clear wipes whatever theme stands,
 * so it only follows the person's own /fond, never a start or a reload.
 */
async function applyBackdrop($: EngineInterface, isOn: boolean): Promise<boolean> {
  const result = await (isOn ? $.theme.set({ backdrop: { scene: BACKDROP_ID } }) : $.theme.clear()).catch(() => null)
  return result !== null && result.isDrawn === true
}

async function openBackground($: EngineInterface): Promise<void> {
  try {
    await $.command.run({ command: 'arriere-plan' })
  } catch {
    $.ui.toast('Le détail des tâches demande le mod background-tasks.')
  }
}

export const register: Register = on => {
  pendingCalls = 0
  pendingErrors = 0
  backgroundTasks = undefined

  // A change of theme redraws: a few native colours (tiles, chips) differ between light and dark.
  on('config.set', async ($, e, next) => {
    const result = await next(e)
    if (e.key === 'theme') $.ui.invalidate('ui.render')
    return result
  })

  on('session.start', async ($, e, next) => {
    void refresh($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    await $.command.register({ name: 'fond', description: 'Allume ou éteint le fond animé (éteint par défaut)' }).catch(() => undefined)
    if (await isBackdropOn($)) await applyBackdrop($, true)
    return next(e)
  })

  on('command.run', { command: 'fond' }, async $ => {
    const isOn = !(await isBackdropOn($))
    await $.store.set('backdrop', isOn ? 'on' : 'off')
    const isDrawn = await applyBackdrop($, isOn)
    if (!isOn) return { text: 'Fond animé éteint (mémorisé).' }
    return { text: isDrawn ? 'Fond animé allumé.' : 'Fond animé allumé (mémorisé) : cette version de l’app ne dessine pas encore de fond, il apparaîtra quand elle le saura.' }
  })

  // The window's backdrop: drawn for this mod's own only, another plugin's is left to it.
  on('ui.render', { component: 'Backdrop' }, async ($, e, next) => {
    if (e.props.plugin !== 'session-hud' || e.props.scene !== BACKDROP_ID) return next(e)
    // Turned off since it was set (a theme stands until cleared): nothing of ours is drawn.
    if (!(await isBackdropOn($))) return next(e)
    const { Svg } = $.ui.resolve(e) as unknown as { Svg: (props: { source: string; alt: string; width: number; height: number }) => never }
    // Sized past the window: the drawing covers it (slice) whatever the window's shape.
    const width = Math.max(2400, Math.round((e.viewport?.columns ?? 0) * 10))
    const height = Math.max(1600, Math.round((e.viewport?.rows ?? 0) * 24))
    return <Svg source={backdrop()} alt="Fond Terre de Sienne" width={width} height={height} />
  })

  on('tool.call', async ($, e, next) => {
    const result = await next(e)
    pendingCalls += 1
    if (result.deny !== undefined || result.isError === true) pendingErrors += 1
    return result
  }).catch(($, e, next) => next(e))

  // What is still in flight when a turn ends: background shells (dev servers), workflows, agents, monitors.
  on('classic.Stop', async ($, e, next) => {
    backgroundTasks = (e.background_tasks ?? []).filter(isInFlight).map(task => ({
      id: task.id,
      kind: taskKind(task.type),
      label: taskLabel(task),
      port: task.command !== undefined ? portOf(task.command) : null,
      command: task.command ?? null,
    }))
    // Into the state at once, before anything else: it outlives a reload of this module.
    const tasks = backgroundTasks
    const shown = await read($, figures)
    if (shown !== null && JSON.stringify(shown.tasks) !== JSON.stringify(tasks)) await update($, figures, value => (value === null ? value : { ...value, tasks }))
    void refresh($)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
    return result
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    if (e.props.hasSurvey) return next(e)
    const shown = await read($, figures)
    if (shown === null) return next(e)
    const now = await $.clock.now()
    const items = hudItems(shown, now)
    const tasks = backgroundLabel(shown.tasks.length)
    const isOpen = (await read($, isListOpen)) && shown.tasks.length > 0
    if (e.surface !== 'desktop' && e.surface !== 'vscode') {
      const { Text } = $.ui.resolve(e)
      return (
        <Text dimColor wrap="truncate-end">
          {bandLine(items, shown.tasks.length)}
        </Text>
      )
    }
    const { Box, Text, Button, Svg } = $.ui.resolve(e)
    // No item ever wraps: short of room, the band drops the labels, then the model (about 8.8 px a column).
    const fitted = fitBand(items, e.props.bodyColumns * 8.8, tasks !== null ? `${tasks} ▴` : '')
    const row = (
      <Box key="row" flexDirection="row" alignItems="center" gap="md" paddingX="md" paddingY={0}>
        <Svg key="working" alt={e.props.isWorking ? 'Claude travaille' : 'au repos'} source={dot(e.props.isWorking ? 'running' : 'muted', { pulse: e.props.isWorking })} width={12} height={12} isInteractive />
        {fitted.items.map(item => (
          <Box key={`item-${item.key}`} flexDirection="row" alignItems="center" gap="xs" flexShrink={0}>
            {item.gauge !== undefined && (
              <Svg key={`gauge-${item.key}`} alt={item.hint ?? `${item.value} ${item.label}`} source={ring(item.gauge, { size: 14, tone: DRAWN_TONE[item.tone], id: `gauge-${item.key}` })} width={14} height={14} isInteractive />
            )}
            <Text size="footnote" weight="semibold" tabular wrap="truncate-end" color={TEXT_COLOUR[item.tone]} dimColor={item.tone === 'muted'}>
              {item.value}
            </Text>
            {fitted.showLabels && item.label !== '' && (
              <Text size="caption" dimColor wrap="truncate-end">
                {item.label}
              </Text>
            )}
          </Box>
        ))}
        <Box flexGrow={1} />
        {tasks !== null && (
          <Box flexShrink={0} {...chip(GALET.deep.ochre, { pressable: true })}>
            <Button key="background" plain label={`${tasks} ${isOpen ? '▾' : '▴'}`} onPress={() => void update($, isListOpen, value => !value)} />
          </Box>
        )}
      </Box>
    )
    // The band: the row alone, on the app's own frame (which the app draws round any band and no mod can take
    // away), so only one surface shows.
    const banded = (
      <Box key="band" flexDirection="column">
        {row}
      </Box>
    )
    if (!isOpen) return banded
    // The list unfolds above the band: one line per task, then the way to the whole pane.
    return (
      <Box flexDirection="column" gap="xs">
        <Box key="list" flexDirection="column" gap="xs" {...surface('ochre')} paddingX="md" paddingY="sm">
          {shown.tasks.map(task => (
            <Box key={`task-${task.id}`} flexDirection="row" alignItems="center" gap="sm">
              <Svg key={`task-${task.id}-dot`} alt="en cours" source={dot('ok', { pulse: true })} width={12} height={12} isInteractive />
              <Box flexGrow={1} flexShrink={1} minWidth={0} flexDirection="row" gap="sm" alignItems="center">
                <Text wrap="truncate-end">{task.label}</Text>
                {task.port !== null && (
                  <Text weight="semibold" color={NATIVE.accent} tabular>
                    :{task.port}
                  </Text>
                )}
              </Box>
              <Text size="caption" dimColor>
                {KIND_LABEL[task.kind]}
              </Text>
            </Box>
          ))}
          <Box flexDirection="row" justifyContent="flex-end">
            <Button key="show-all" plain dimColor label="Tout afficher ▸" onPress={() => void openBackground($)} />
          </Box>
        </Box>
        {banded}
      </Box>
    )
  })
}
