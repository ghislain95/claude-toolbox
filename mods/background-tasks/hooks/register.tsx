// background-tasks: the « En arrière-plan » pane, in every project. The services Claude started
// (dev servers…), the project's workflow runs with their phases and agents, and this session's agents.
// `/arriere-plan` opens or closes it; the session-hud band's counter runs that command.
//
// The pane reads values written every 30 seconds and at each turn's end, and only when they change:
// never per tool call, so it does not redraw while subagents work.

import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { BackgroundSnapshot } from '../types'
import { renderPane, renderTextPane } from './shared/background-view'
import { mergeServices } from './shared/services'
import { collectSessionAgents, collectWorkflows } from './shared/collect-workflows'
import { announcement, runsToAnnounce } from './shared/workflows'

const snapshot = atom({ plugin: 'background-tasks', key: 'snapshot' } as const, null)
const services = atom({ plugin: 'background-tasks', key: 'services' } as const, [])

const PANE = 'background'
const REFRESH_MS = 30 * 1000

let context: { root: string; home: string } | undefined
let inFlight: Promise<void> | undefined

async function collect($: EngineInterface, where: { root: string; home: string }): Promise<void> {
  try {
    const now = await $.clock.now()
    const [runs, agents] = await Promise.all([collectWorkflows($, where, now), collectSessionAgents($, where)])
    const next: BackgroundSnapshot = { runs, agents, takenAt: now }
    const previous = await read($, snapshot)
    // A write redraws the pane: only when something it shows changed.
    if (JSON.stringify({ ...next, takenAt: 0 }) !== JSON.stringify(previous === null ? null : { ...previous, takenAt: 0 })) {
      await update($, snapshot, () => next)
    }
    await announceFinishedRuns($, next, now)
  } finally {
    inFlight = undefined
  }
}

/** One collection at a time: a call while one runs shares it. */
function refresh($: EngineInterface): Promise<void> {
  if (context === undefined) return Promise.resolve()
  if (inFlight === undefined) inFlight = collect($, context).catch(() => undefined)
  return inFlight
}

/** A run that just finished says so once, in a toast and a notification. */
async function announceFinishedRuns($: EngineInterface, shot: BackgroundSnapshot, now: number): Promise<void> {
  const announced = ((await $.store.get('announcedRuns')) as string[] | undefined) ?? []
  const fresh = runsToAnnounce(shot.runs, announced, now)
  if (fresh.length === 0) return
  await $.store.set('announcedRuns', [...announced, ...fresh.map(run => run.id)].slice(-200))
  for (const run of fresh) {
    $.ui.toast(announcement(run), { timeoutMs: 12000 })
    void $.ui.notify(announcement(run), { title: context?.root.split('/').filter(Boolean).at(-1) ?? 'Claude' }).catch(() => undefined)
  }
}

/** Opening it waits a moment at start, so it lands under the panes opened right away (the cockpit). */
const OPEN_DELAY_MS = 1500

async function openPane($: EngineInterface): Promise<void> {
  void refresh($)
  await $.ui.open({ id: PANE, title: 'En arrière-plan' }).catch(() => undefined)
}

/** The person's choice, kept across sessions: the pane opens by itself unless they closed it. */
async function rememberPane($: EngineInterface, state: 'on' | 'off'): Promise<void> {
  await $.store.set('pane', state).catch(() => undefined)
}

async function togglePane($: EngineInterface): Promise<string> {
  const isOpen = (await $.ui.panes()).some(pane => pane.id === PANE)
  if (isOpen) {
    await rememberPane($, 'off')
    await $.ui.close({ id: PANE })
    return 'Panneau « En arrière-plan » fermé (il ne s’ouvrira plus tout seul ; /arriere-plan le rouvre).'
  }
  await rememberPane($, 'on')
  await openPane($)
  return 'Panneau « En arrière-plan » ouvert.'
}

export const register: Register = on => {
  context = undefined
  inFlight = undefined

  // A change of theme redraws: a few native colours (tiles, chips) differ between light and dark.
  on('config.set', async ($, e, next) => {
    const result = await next(e)
    if (e.key === 'theme') $.ui.invalidate('ui.render')
    return result
  })

  on('session.start', async ($, e, next) => {
    const [root, home] = await Promise.all([$.session.root(), $.env.get('HOME')])
    context = { root, home: home ?? '' }
    await $.command
      .register({ name: 'arriere-plan', description: 'Ouvre ou ferme le panneau des tâches en arrière-plan : services, workflows, agents' })
      .catch(() => undefined)
    void refresh($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    // The tasks show at a glance: the pane opens by itself unless the person closed it. In an OpenSpec project
    // the cockpit shows them in its own pane (the desktop tabs two panes, it does not stack them).
    const hasCockpit = (await $.fs.exists(`${root}/openspec`).catch(() => false)) || (await $.fs.exists(`${root}/.claude/handoff`).catch(() => false)) || (await $.fs.exists(`${root}/.claude/passation`).catch(() => false))
    if (!hasCockpit && ((await $.store.get('pane').catch(() => undefined)) ?? 'on') !== 'off') {
      $.clock.after(OPEN_DELAY_MS, () => void openPane($))
    }
    return next(e)
  })

  // Closed by its close mark: remembered, so it stays closed in the next sessions.
  on('ui.close', async ($, e, next) => {
    if (e.id === PANE && e.origin.kind === 'person') await rememberPane($, 'off')
    return next(e)
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'arriere-plan' }, async $ => ({ text: await togglePane($) }))

  // The services: background shells still in flight when a turn ends.
  on('classic.Stop', async ($, e, next) => {
    const now = await $.clock.now()
    const tasks = (e.background_tasks ?? []).map(task => ({ id: task.id, type: task.type, status: task.status, description: task.description, command: task.command }))
    const previous = await read($, services)
    const merged = mergeServices(previous, tasks, now)
    if (JSON.stringify(merged) !== JSON.stringify(previous)) await update($, services, () => merged)
    void refresh($)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
    return result
  }).catch(($, e, next) => next(e))

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const [shot, running, now] = await Promise.all([read($, snapshot), read($, services), $.clock.now()])
    const data = { snapshot: shot, services: running, now }
    if (e.surface === 'desktop' || e.surface === 'vscode') return renderPane($, e as typeof e & { surface: 'desktop' | 'vscode' }, data)
    return renderTextPane($, e, data)
  })
}
