// conversation-cards: Claude's messages drawn as cards in the transcript, in every project. Questions with
// their options, end-of-task reports, QA, the cockpit block, commits; compact tool rows; the spinner's
// context; the display contract that keeps the shapes the cards read. The message itself is never changed.

import { atom, memberOf, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { CardToggles } from '../types'
import { messageShape, renderDeliverables, renderLong, renderQuestions, renderReport } from './cards'
import { readMode } from './shared/mode'
import { collectFacts, resolveGit } from './facts'
import { CONTRACT, spinnerSuffix, togglesText } from './logic'
import { withoutCockpitBlock, withoutQuestions } from './parse'
import { formatDuration } from './shared/format'
import { renderToolUse } from './tools'

const DEFAULT_TOGGLES: CardToggles = { cards: true, contract: true }

const toggles = atom({ plugin: 'conversation-cards', key: 'toggles' } as const, DEFAULT_TOGGLES)
const projectRoot = atom({ plugin: 'conversation-cards', key: 'projectRoot' } as const, null)
const cardFacts = atom({ plugin: 'conversation-cards', key: 'cardFacts' } as const, { changeNames: [], recentCommits: [] })
const contextPercent = atom({ plugin: 'conversation-cards', key: 'contextPercent' } as const, null)
const isMessageOpen = atom({ plugin: 'conversation-cards', key: 'isMessageOpen' } as const, false)
const qaMarks = atom({ plugin: 'conversation-cards', key: 'qaMarks' } as const, {})
const reportOpen = atom({ plugin: 'conversation-cards', key: 'reportOpen' } as const, {})
const briefs = atom({ plugin: 'conversation-cards', key: 'briefs' } as const, null)
const settled = atom({ plugin: 'conversation-cards', key: 'settled' } as const, [])

const REFRESH_MS = 30 * 1000

/** How often the app's light or dark mode is looked at. */
const MODE_MS = 5000

let home = ''
let git = 'git'
let inFlight: Promise<void> | undefined
/** Claude's replies drawn as cards so far: once the person sends anything, they are all settled. */
let drawnReplies = new Set<string>()
/** The app's light or dark mode when last looked at: a change redraws the cards (their tiles differ). */
let lastMode: string | null = null

/** Facts the cards read (change names, recent commits) and the context, written only when they change. */
async function collectAndPublish($: EngineInterface): Promise<void> {
  try {
    const root = await read($, projectRoot)
    if (root === null) return
    const [facts, usage] = await Promise.all([collectFacts($, root, git), $.session.usage().catch(() => null)])
    if (JSON.stringify(facts) !== JSON.stringify(await read($, cardFacts))) await update($, cardFacts, () => facts)
    const percent = usage?.context.percent ?? null
    if (percent !== (await read($, contextPercent))) await update($, contextPercent, () => percent)
  } finally {
    inFlight = undefined
  }
}

/** One collection at a time: a call while one runs shares it. */
function refresh($: EngineInterface): Promise<void> {
  if (inFlight === undefined) inFlight = collectAndPublish($).catch(() => undefined)
  return inFlight
}

async function toggleMessage($: EngineInterface, messageId: string): Promise<void> {
  await update($, memberOf(isMessageOpen, { requestId: messageId }), value => !value)
}

async function setToggles($: EngineInterface, change: (current: CardToggles) => CardToggles): Promise<CardToggles> {
  let after = DEFAULT_TOGGLES
  await update($, toggles, current => {
    after = change(current)
    return after
  })
  await $.store.set('toggles', after)
  $.ui.invalidate('ui.render')
  return after
}

export const register: Register = on => {
  home = ''
  git = 'git'
  inFlight = undefined
  drawnReplies = new Set()

  // A change of theme redraws: a few native colours (tiles, chips) differ between light and dark.
  on('config.set', async ($, e, next) => {
    const result = await next(e)
    if (e.key === 'theme') $.ui.invalidate('ui.render')
    return result
  })

  on('session.start', async ($, e, next) => {
    const [root, homeDir, gitPath, stored] = await Promise.all([
      $.session.root(),
      $.env.get('HOME'),
      resolveGit($),
      $.store.get('toggles'),
    ])
    home = homeDir ?? ''
    git = gitPath
    await Promise.all([
      update($, projectRoot, () => root),
      update($, toggles, () => ({ ...DEFAULT_TOGGLES, ...((stored as Partial<CardToggles> | undefined) ?? {}) })),
    ])
    await $.command.register({
      name: 'cartes',
      description: 'Cartes du fil : état, on/off, ou la consigne de format (contrat on/off)',
      argumentHint: '[on|off|contrat on|contrat off]',
    })
    void refresh($)
    $.clock.every(REFRESH_MS, () => void refresh($))
    // The app's appearance is not a setting of the session: look at it every few seconds, redraw on a change.
    $.clock.every(MODE_MS, async () => {
      const mode = await readMode($)
      if (lastMode !== null && mode !== lastMode) $.ui.invalidate('ui.render')
      lastMode = mode
    })
    // A reload redraws the transcript before this hook has run: draw it again now that the facts are set.
    $.ui.invalidate('ui.render')
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    void refresh($)
    return result
  }).catch(($, e, next) => next(e))

  // The display contract: Claude keeps the shapes the cards read.
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e)
    if (!(await read($, toggles)).contract) return composed
    return { sections: [...composed.sections, { id: 'conversation-cards:contract', text: CONTRACT, scope: 'session' as const }] }
  }).catch(($, e, next) => next(e))

  // The person answered (through a card or by typing): every reply drawn until now is settled and stops moving.
  on('prompt.submit', async ($, e, next) => {
    if (drawnReplies.size > 0) {
      const replies = [...drawnReplies]
      await update($, settled, previous => [...new Set([...previous, ...replies])].slice(-500))
    }
    return next(e)
  }).catch(($, e, next) => next(e))

  // How long each tool took, for its row: one member per call, so only that row redraws.
  on('tool.call', async ($, e, next) => {
    const startedAt = await $.clock.now()
    const result = await next(e)
    const now = await $.clock.now()
    await $.state.set(
      { plugin: 'conversation-cards', key: 'toolTimes', id: e.tool_use_id },
      { durationMs: now - startedAt, isError: result.deny !== undefined || result.isError === true },
    )
    return result
  }).catch(($, e, next) => next(e))

  on('command.run', { command: 'cartes' }, async ($, e) => {
    const [first, second] = e.args.trim().toLowerCase().split(/\s+/)
    if (first === undefined || first === '') {
      await refresh($)
      return { text: `Cartes — ${togglesText(await read($, toggles))}. Usage : /cartes [on|off|contrat on|contrat off]` }
    }
    if (first === 'contrat') {
      const after = await setToggles($, current => ({ ...current, contract: second === 'on' ? true : second === 'off' ? false : !current.contract }))
      return { text: `Cartes — ${togglesText(after)} (mémorisé).` }
    }
    if (first !== 'on' && first !== 'off') return { text: `Inconnu « ${first} ». Usage : /cartes [on|off|contrat on|contrat off]` }
    const after = await setToggles($, current => ({ ...current, cards: first === 'on' }))
    return { text: `Cartes — ${togglesText(after)} (mémorisé).` }
  })

  on('ui.render', { component: 'Spinner' }, async ($, e, next) => {
    const suffix = spinnerSuffix(await read($, contextPercent))
    if (suffix === '') return next(e)
    return next({ ...e, props: { ...e.props, suffix: `${suffix}${e.props.suffix}` } })
  })

  on('ui.render', { component: 'AssistantMessage' }, async ($, e, next) => {
    const [root, switches] = await Promise.all([read($, projectRoot), read($, toggles)])
    if (root === null || !switches.cards) return next(e)
    const shape = messageShape(e.props.text)
    if (shape === null) return next(e)
    drawnReplies.add(e.requestId)
    const [mode, facts, isOpen, marks, sectionsOpen, brief, settledReplies] = await Promise.all([
      e.surface === 'desktop' || e.surface === 'vscode' ? readMode($) : Promise.resolve('auto' as const),
      read($, cardFacts),
      read($, memberOf(isMessageOpen, e)),
      read($, memberOf(qaMarks, e)),
      read($, memberOf(reportOpen, e)),
      read($, memberOf(briefs, e)),
      read($, settled),
    ])
    const messageId = e.requestId
    const cardContext = {
      messageId,
      root,
      home,
      changeNames: facts.changeNames,
      recentCommits: facts.recentCommits,
      isOpen,
      marks,
      sectionsOpen,
      brief,
      onToggle: () => void toggleMessage($, messageId),
      isSettled: settledReplies.includes(messageId),
      isRich: e.surface === 'desktop' || e.surface === 'vscode',
      mode,
    }
    // The cockpit block feeds the cards; the person reads the message without it.
    const shown = withoutCockpitBlock(e.props.text)
    const drawn = shape.hasCockpitBlock ? { ...e, props: { ...e.props, text: shown } } : e
    if (shape.report !== null) return renderReport($, e, shape, cardContext, isOpen ? await next(drawn) : null)
    if (shape.questions.length > 0) {
      const rest = withoutQuestions(shown)
      return renderQuestions($, e, shape, cardContext, rest === '' ? null : await next({ ...e, props: { ...e.props, text: rest } }))
    }
    const hasDeliverables =
      shape.commits.length > 0 ||
      shape.qa.length > 0 ||
      shape.findings.length > 0 ||
      shape.phrase !== null ||
      shape.decisions.length > 0 ||
      shape.asks.length > 0 ||
      shape.picks.length > 0 ||
      shape.infos.length > 0
    if (hasDeliverables) return renderDeliverables($, e, shape, cardContext, await next(drawn))
    return renderLong($, e, cardContext, shown, await next(drawn))
  })

  on('ui.render', { component: 'ToolUse' }, async ($, e, next) => {
    const root = await read($, projectRoot)
    if (root === null) return next(e)
    return renderToolUse($, e, next, root)
  })

  // A background task's notification: one quiet line, the full row under ctrl+o.
  on('ui.render', { component: 'UserMessage' }, async ($, e, next) => {
    if (e.props.origin.kind !== 'task-notification' || e.props.isExpanded || !(await read($, toggles)).cards) return next(e)
    const { Box, Text } = $.ui.resolve(e)
    const status = e.props.task?.status ?? ''
    const isFailed = /fail|kill|error/i.test(status)
    const duration = typeof e.props.task?.durationMs === 'number' ? ` · ${formatDuration(e.props.task.durationMs)}` : ''
    const summary = e.props.text.split('\n')[0] ?? ''
    return (
      <Box flexDirection="row" gap={1} alignItems="center">
        <Text color={isFailed ? 'error' : 'success'}>{isFailed ? '✗' : '⚙'}</Text>
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text dimColor size="footnote" wrap="truncate-end">
            {summary}
          </Text>
        </Box>
        <Text dimColor size="caption">
          {status}
          {duration}
        </Text>
      </Box>
    )
  })
}
