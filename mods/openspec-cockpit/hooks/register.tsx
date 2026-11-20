// openspec-cockpit: the OpenSpec dashboard pane (next action, the change's progress, decisions, the post-archive
// ritual, the handoff), the cycle's gates on the commands that cross them, the status line and the status tool.
// The transcript's cards live in conversation-cards; the band and the background tasks in their own mods.

import { atom, memberOf, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CockpitBackground, GateAlert, Toggles } from '../types'
import { type Context, collectGit, collectSnapshot, resolveGit } from './collect'
import {
  DEFAULT_TOGGLES,
  TOGGLE_NAMES,
  gateLevel,
  gateOf,
  gateWarning,
  hasRecentReviewRun,
  isReviewToolCall,
  parseOffset,
  postArchiveReminder,
  statusLine,
  summaryMarkdown,
  togglesLine,
} from './logic'
import { renderRichPane, renderTextPane } from './pane'
import { collectSessionAgents, collectWorkflows } from './shared/collect-workflows'
import { mergeServices, type Service } from './shared/services'
import { commitBlocks } from './shared/commits'

const busy = atom({ plugin: 'openspec-cockpit', key: 'busy' } as const, null)
const collapsed = atom({ plugin: 'openspec-cockpit', key: 'collapsed' } as const, {})
const commitDraft = atom({ plugin: 'openspec-cockpit', key: 'commitDraft' } as const, null)
const gateAlerts = atom({ plugin: 'openspec-cockpit', key: 'gateAlerts' } as const, null)
const hasReview = atom({ plugin: 'openspec-cockpit', key: 'hasReview' } as const, false)
const ritualMarks = atom({ plugin: 'openspec-cockpit', key: 'ritualMarks' } as const, {})
const snapshot = atom({ plugin: 'openspec-cockpit', key: 'snapshot' } as const, null)
const toggles = atom({ plugin: 'openspec-cockpit', key: 'toggles' } as const, DEFAULT_TOGGLES)


const background = atom({ plugin: 'openspec-cockpit', key: 'background' } as const, null)
const PANE = 'cockpit'
const REFRESH_MS = 30 * 1000

let context: Context | undefined
let inFlight: Promise<void> | undefined
let isPostArchivePending = false
let pendingAlert: GateAlert | undefined

/** The post-archive reminder, once the snapshot shows the archived change. */
async function remindPostArchive($: EngineInterface): Promise<void> {
  if (!(await read($, toggles)).gates) return
  const shot = await read($, snapshot)
  const isBacklogShipped = shot?.archivedChange?.isBacklogShipped
  $.ui.toast(
    postArchiveReminder({ hasBacklog: isBacklogShipped !== undefined && isBacklogShipped !== null, usesGraph: shot?.graph.state !== 'unused' }),
    { timeoutMs: 20000 },
  )
}

async function collectAndPublish($: EngineInterface, current: Context): Promise<void> {
  try {
    const shot = await collectSnapshot($, current)
    const where = { root: current.root, home: current.home }
    const [runs, agents] = await Promise.all([
      collectWorkflows($, where, shot.takenAt).catch(() => []),
      collectSessionAgents($, where).catch(() => []),
    ])
    // A review run as a workflow (in any session of the project) counts for the review gate.
    if (!(await read($, hasReview)) && hasRecentReviewRun(runs, shot.takenAt)) await update($, hasReview, () => true)
    await publishBackground($, { runs, agents })
    await update($, snapshot, () => shot)
    const switches = await read($, toggles)
    $.ui.status(switches.status ? statusLine(shot) : undefined)
  } finally {
    inFlight = undefined
  }
}

/** The background tasks, written only when what the pane shows changed (never once per tool call). */
async function publishBackground($: EngineInterface, change: Partial<CockpitBackground>): Promise<void> {
  const previous = await read($, background)
  const next: CockpitBackground = { runs: [], agents: [], services: [], ...(previous ?? {}), ...change, takenAt: 0 }
  if (JSON.stringify(next) !== JSON.stringify(previous)) await update($, background, () => next)
}

/** One collection at a time: a call while one runs shares it. */
function refresh($: EngineInterface): Promise<void> {
  if (context === undefined) return Promise.resolve()
  if (inFlight === undefined) inFlight = collectAndPublish($, context).catch(() => undefined)
  return inFlight
}

async function reviewSeen($: EngineInterface): Promise<boolean> {
  return read($, hasReview)
}

/** Toggles, folded sections and ritual ticks come back from the store at start and after /clear. */
async function loadStored($: EngineInterface): Promise<Toggles> {
  const [stored, folded, marks] = await Promise.all([$.store.get('toggles'), $.store.get('collapsed'), $.store.get('ritualMarks')])
  const merged = { ...DEFAULT_TOGGLES, ...((stored as Partial<Toggles> | undefined) ?? {}) }
  await Promise.all([
    update($, toggles, () => merged),
    update($, collapsed, () => (folded as Record<string, boolean> | undefined) ?? {}),
    update($, ritualMarks, () => (marks as Record<string, boolean> | undefined) ?? {}),
  ])
  return merged
}

export const register: Register = on => {
  context = undefined
  inFlight = undefined
  isPostArchivePending = false
  pendingAlert = undefined

  on('session.start', async ($, e, next) => {
    const root = await $.session.root()
    const isOpenSpecProject =
      (await $.fs.exists(`${root}/openspec`)) || (await $.fs.exists(`${root}/.claude/handoff`)) || (await $.fs.exists(`${root}/.claude/passation`))
    if (!isOpenSpecProject) return next(e)

    const [home, git, offset] = await Promise.all([
      $.env.get('HOME'),
      resolveGit($),
      $.process
        .run(['/bin/date', '+%z'])
        .then(result => result.stdout)
        .catch(() => ''),
    ])
    context = { root, home: home ?? '', git, offsetMinutes: parseOffset(offset) }
    const switches = await loadStored($)

    await Promise.all([
      $.command.register({ name: 'cockpit', description: 'Ouvre/ferme le panneau cockpit (prochaine action, progression, décisions, passation)' }),
      $.command.register({ name: 'ou-en-suis-je', description: 'Résumé : branche, change et étape, graph, dernière passation, portes' }),
      $.command.register({
        name: 'cockpit-toggle',
        description: 'Active/désactive une brique du cockpit : statut, portes, panneau',
        argumentHint: '[statut|portes|panneau] [on|off]',
      }),
      $.tool
        .register({
          name: 'status',
          description:
            'OpenSpec cockpit summary: branch and uncommitted files, active OpenSpec change with task counts and cycle step, graphify freshness (when the project uses it), latest handoff and its next steps, cycle gates. Read-only.',
          inputSchema: { type: 'object', properties: {} },
        })
        .catch(() => undefined),
    ])

    void refresh($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    if (switches.pane) void $.ui.open({ id: PANE, title: 'Cockpit' }).catch(() => undefined)

    return next(e)
  })

  on('classic.SessionStart', { source: ['clear', 'resume', 'fork'] }, async ($, e, next) => {
    if (context !== undefined) {
      await loadStored($)
      void refresh($)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (context === undefined) return result
    const shouldRemind = isPostArchivePending
    isPostArchivePending = false
    void refresh($).then(() => (shouldRemind ? remindPostArchive($) : undefined))
    return result
  })

  on('tool.call', async ($, e, next) => {
    if (context === undefined) return next(e)
    if (isReviewToolCall(String(e.tool), e as unknown as Record<string, unknown>) && !(await read($, hasReview))) await update($, hasReview, () => true)
    return next(e)
  }).catch(($, e, next) => next(e))

  on('tool.call', { tool: /^mcp__openspec-cockpit__status$/ }, async $ => {
    await refresh($)
    const shot = await read($, snapshot)
    if (shot === null || context === undefined) return { result: 'No cockpit data: this project has neither openspec/ nor a handoff folder.' }
    const now = await $.clock.now()
    return { result: summaryMarkdown({ snapshot: shot, now, offsetMinutes: context.offsetMinutes, hasReview: await reviewSeen($) }) }
  }).catch(($, e, next) => (next.called ? next(e) : { deny: 'openspec-cockpit: the status could not be read.' }))

  on('prompt.submit', async ($, e, next) => {
    const gate = context !== undefined && e.command !== undefined ? gateOf(e.command.name) : null
    if (context !== undefined && gate !== null) {
      if (gate === 'archive') isPostArchivePending = true
      if ((await read($, toggles)).gates) {
        const facts = await collectGit($, context)
        const warning = gateWarning(gate, { graph: facts.graph, dirtyCount: facts.dirtyCount, hasReview: await reviewSeen($) })
        if (warning !== null) {
          $.ui.toast(warning, { timeoutMs: 15000 })
          pendingAlert = { text: warning, level: gateLevel(gate) }
        }
      }
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // The services: background shells still in flight when a turn ends (a dev server, a watcher).
  on('classic.Stop', async ($, e, next) => {
    if (context !== undefined) {
      const now = await $.clock.now()
      const tasks = (e.background_tasks ?? []).map(task => ({ id: task.id, type: task.type, status: task.status, description: task.description, command: task.command }))
      const previous = ((await read($, background))?.services ?? []) as Service[]
      await publishBackground($, { services: mergeServices(previous, tasks, now) })
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // The row a gated prompt became carries its alert; Claude's commit messages are kept for the copy button.
  on('session.append', async ($, e, next) => {
    const alert = pendingAlert
    if (alert !== undefined && e.agentId === undefined && (e.door === 'prompt' || e.door === 'command')) {
      pendingAlert = undefined
      await $.state.set({ plugin: 'openspec-cockpit', key: 'gateAlerts', id: e.uuid }, alert)
    }
    if (context !== undefined && e.agentId === undefined && e.message.role === 'assistant' && Array.isArray(e.message.content)) {
      const text = e.message.content
        .map(block => ((block as { type?: string }).type === 'text' ? String((block as { text?: unknown }).text ?? '') : ''))
        .join('\n')
      const commits = commitBlocks(text)
      const last = commits[commits.length - 1]
      if (last !== undefined) await update($, commitDraft, () => last.text)
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'cockpit' }, async $ => {
    const isOpen = (await $.ui.panes()).some(pane => pane.id === PANE)
    if (isOpen) {
      await $.ui.close({ id: PANE })
      return { text: 'Cockpit fermé.' }
    }
    void refresh($)
    const opened = await $.ui.open({ id: PANE, title: 'Cockpit' })
    return { text: opened.isPlaced ? 'Cockpit ouvert.' : `Cockpit en attente : ${opened.reason}` }
  })

  on('command.run', { command: 'ou-en-suis-je' }, async $ => {
    await refresh($)
    const shot = await read($, snapshot)
    if (shot === null || context === undefined) return { text: 'Cockpit : aucune donnée (projet sans openspec/ ni dossier de handoff).' }
    const now = await $.clock.now()
    return {
      text: summaryMarkdown({
        snapshot: shot,
        now,
        offsetMinutes: context.offsetMinutes,
        hasReview: await reviewSeen($),
      }),
    }
  })

  on('command.run', { command: 'cockpit-toggle' }, async ($, e) => {
    const [name, value] = e.args.trim().toLowerCase().split(/\s+/)
    if (name === undefined || name === '') {
      return {
        text: `Cockpit — ${togglesLine(await read($, toggles))}. Usage : /cockpit-toggle <statut|portes|panneau> [on|off]`,
      }
    }
    const key = TOGGLE_NAMES[name]
    if (key === undefined) return { text: `Brique inconnue « ${name} ». Choix : statut, portes, panneau.` }
    let after: Toggles = DEFAULT_TOGGLES
    await update($, toggles, current => {
      const isOn = value === 'on' ? true : value === 'off' ? false : !current[key]
      after = { ...current, [key]: isOn }
      return after
    })
    await $.store.set('toggles', after)
    if (key === 'status') {
      const shot = await read($, snapshot)
      $.ui.status(after.status && shot !== null ? statusLine(shot) : undefined)
    }
    return { text: `Cockpit — ${togglesLine(after)} (mémorisé pour les prochaines sessions).` }
  })

  // The row a gated prompt became carries its alert under it.
  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    const alert = await read($, memberOf(gateAlerts, e))
    if (alert === null) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const color = alert.level === 'danger' ? 'error' : 'warning'
    return (
      <Box flexDirection="column" gap={1}>
        {await next(e)}
        <Box key="gate-alert" borderStyle="round" borderColor={color} paddingX={1} flexDirection="row" gap={1}>
          <Text color={color} weight="semibold">
            {alert.level === 'danger' ? '✗ Porte' : '! Porte'}
          </Text>
          <Text color={color} wrap="wrap">
            {alert.text.replace(/^⚠\s*/, '')}
          </Text>
        </Box>
      </Box>
    )
  })

  // ------------------------------------------------------------ the cockpit pane

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const shot = await read($, snapshot)
    if (shot === null || context === undefined) {
      const { Text } = $.ui.resolve(e)
      return <Text dimColor>Collecte en cours…</Text>
    }
    const now = await $.clock.now()
    const [tasks, folded, draft, marks, busyWith] = await Promise.all([
      read($, background),
      read($, collapsed),
      read($, commitDraft),
      read($, ritualMarks),
      read($, busy),
    ])
    const data = {
      shot,
      background: tasks,
      review: await reviewSeen($),
      collapsedSections: folded,
      commitDraft: draft,
      marks,
      busyWith,
      root: context.root,
      home: context.home,
      offset: context.offsetMinutes,
      now,
      onRefresh: () => void refresh($),
    }
    if (e.surface === 'desktop' || e.surface === 'vscode') return renderRichPane($, e, data)
    if (e.surface === 'mobile') {
      const { Text } = $.ui.resolve(e)
      return <Text>{statusLine(shot)}</Text>
    }
    return renderTextPane($, e, data)
  })

}
