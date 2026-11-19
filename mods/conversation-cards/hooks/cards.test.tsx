import { type Engine, expect, mock, test } from 'claude-code/testing'
import type { FsEntry, On } from 'claude-code'

import { CONTRACT_QA, PLAN_21_22, QA_FOLLOW_UP, PLANNER_GUIDE, REPORT_21_22, S5_REPORT, WITH_COCKPIT_BLOCK } from './fixtures'

// A fake Larder-like repository at /repo, with Claude's project folder under /home.

const MINUTE = 60 * 1000
const NOW = Date.UTC(2026, 9, 17, 10, 0) // 12:00 at +0200
const HANDOFF_AT = Date.UTC(2026, 9, 17, 9, 14) // 11:14 at +0200
const PROJECT = '/home/.claude/projects/-repo'

const HANDOFF = `# Passation — \`/opsx:apply\` de \`offline-catalog\`, S4 : frontend (2026-10-17 11:14)

## Prochaine étape
1. \`graphify check-update .\`, \`git status\`.
2. Lire les tâches 13 à 20.
3. Attendre le GO.
`

type Node = { kind: 'file' | 'dir'; text?: string; mtimeMs: number }

function file(text: string, mtimeMs: number): Node {
  return { kind: 'file', text, mtimeMs }
}

function dir(mtimeMs: number): Node {
  return { kind: 'dir', mtimeMs }
}

function projectTree(): Record<string, Node> {
  return {
    '/repo/openspec': dir(NOW - 60 * MINUTE),
    '/repo/openspec/changes': dir(NOW - 60 * MINUTE),
    '/repo/openspec/changes/offline-catalog': dir(NOW - 60 * MINUTE),
    '/repo/openspec/changes/offline-catalog/tasks.md': file('- [x] 1.1\n- [x] 1.2\n- [ ] 2.1\n- [ ] 2.2\n', NOW - 60 * MINUTE),
    '/repo/openspec/changes/offline-catalog/design.md': file('# Design', NOW - 600 * MINUTE),
    '/repo/openspec/changes/archive': dir(NOW - 7 * 24 * 60 * MINUTE),
    '/repo/openspec/changes/archive/2026-10-10-nutrition-score': dir(NOW - 7 * 24 * 60 * MINUTE),
    '/repo/.claude': dir(NOW),
    '/repo/.claude/passation': dir(HANDOFF_AT),
    '/repo/.claude/passation/2026-10-17-1114-s4.md': file(HANDOFF, HANDOFF_AT),
    '/repo/.claude/passation/2026-10-15-1740-s3.md': file('# Passation — S3 infra (2026-10-15 17:40)\n', HANDOFF_AT - 2 * 24 * 60 * MINUTE),
    '/repo/graphify-out/graph.json': file('{}', NOW - 30 * MINUTE),
    '/repo/frontend/a.ts': file('', NOW - 10 * MINUTE),
    [`${PROJECT}/S1/custom-title.json`]: file('{"customTitle":"Apply S4"}', NOW),
    [`${PROJECT}/S1/subagents/workflows/wf_live`]: dir(NOW - MINUTE),
    [`${PROJECT}/S1/subagents/workflows/wf_live/journal.jsonl`]: file(
      '{"type":"launched"}\n{"type":"started","label":"impl:13","phase":"Group 13"}\n',
      NOW - 12 * MINUTE,
    ),
    [`${PROJECT}/S1/subagents/workflows/wf_live/agent-a.meta.json`]: file('{}', NOW - 12 * MINUTE),
    [`${PROJECT}/S1/subagents/workflows/wf_live/agent-a.jsonl`]: file('', NOW - MINUTE),
    [`${PROJECT}/S2/custom-title.json`]: file('{"customTitle":"Apply groups"}', NOW),
    [`${PROJECT}/S2/workflows/wf_done.json`]: file(
      JSON.stringify({
        runId: 'wf_done',
        workflowName: 'review-close-out',
        status: 'completed',
        durationMs: 59 * MINUTE,
        agentCount: 3,
        timestamp: new Date(NOW - 3 * MINUTE).toISOString(),
        startTime: NOW - 62 * MINUTE,
      }),
      NOW - 3 * MINUTE,
    ),
  }
}

type World = {
  prompt: string
  copied: string[]
  opened: string[]
  toasts: string[]
  statuses: (string | undefined)[]
  fills: string[]
  commands: string[]
  store: Map<string, unknown>
}

function world(on: On, root: string, tree: Record<string, Node>): World {
  const seen: World = { prompt: '', copied: [], opened: [], toasts: [], statuses: [], fills: [], commands: [], store: new Map() }
  mock.clock(on, { now: NOW })
  on('store.get', ($, e) => ({ value: seen.store.get(e.key) }))
  on('store.set', ($, e) => {
    seen.store.set(e.key, e.value)
    return { value: undefined }
  })
  mock.env(on, { HOME: '/home' })

  const isUnder = (path: string, parent: string) => path.startsWith(`${parent}/`) && !path.slice(parent.length + 1).includes('/')
  on('session.root', () => ({ value: root }))
  on('fs.exists', ($, e) => ({ value: e.path in tree }))
  on('fs.stat', ($, e) => {
    const node = tree[e.path]
    if (node === undefined) return { deny: `ENOENT ${e.path}` }
    return { value: { kind: node.kind, size: node.text?.length ?? 0, mtimeMs: node.mtimeMs, isLink: false } }
  })
  on('fs.read', ($, e) => {
    const node = tree[e.path]
    if (node?.text === undefined) return { deny: `ENOENT ${e.path}` }
    return { value: node.text }
  })
  on('fs.list', ($, e) => {
    if (!(e.path in tree)) return { deny: `ENOENT ${e.path}` }
    const entries = Object.entries(tree)
      .filter(([path]) => isUnder(path, e.path))
      .map(([path, node]): FsEntry => ({
        name: path.slice(e.path.length + 1),
        kind: node.kind,
        size: node.text?.length ?? 0,
        mtimeMs: node.mtimeMs,
        isLink: false,
      }))
    return { value: entries }
  })
  on('process.run', ($, e) => {
    const argv = e.argv.join(' ')
    const ok = (stdout: string) => ({ value: { exitCode: 0, stdout, stderr: '', isStdoutTruncated: false, isStderrTruncated: false } })
    if (argv === 'git --version') return ok('git version 2.47')
    if (argv.startsWith('git rev-parse')) return ok('feat/offline-catalog\n')
    if (argv.startsWith('git status')) return ok(' M frontend/a.ts\n')
    if (argv.startsWith('git log -20')) return ok('abc1234\tfeat(offline-catalog): add the catalog infrastructure\n')
    if (argv.startsWith('git log')) return ok(`${Math.round((NOW - 120 * MINUTE) / 1000)}\n`)
    if (argv === '/bin/date +%z') return ok('+0200\n')
    if (argv.startsWith('git diff --shortstat')) return ok(' 18 files changed, 2304 insertions(+), 120 deletions(-)\n')
    if (argv.includes('JetBrains/Toolbox/scripts/idea')) {
      seen.opened.push(argv)
      return ok('')
    }
    if (argv === '/usr/bin/pbcopy') {
      seen.copied.push(e.init?.stdin ?? '')
      return ok('')
    }
    if (e.argv[0] === '/usr/bin/grep' && e.argv[1] === '-F') {
      const text = tree[e.argv[3] ?? '']?.text
      if (text === undefined) return { value: { exitCode: 2, stdout: '', stderr: 'No such file', isStdoutTruncated: false, isStderrTruncated: false } }
      return ok(text.split('\n').filter(line => line.includes(e.argv[2] ?? '')).join('\n'))
    }
    if (e.argv[0] === '/usr/bin/tail') return ok(tree[e.argv[3] ?? '']?.text ?? '')
    if (argv.startsWith('/usr/bin/find') && e.argv.includes('-quit')) {
      const suffix = (e.argv[e.argv.indexOf('-path') + 1] ?? '').replace(/^\*/, '')
      return ok(Object.keys(tree).filter(path => path.startsWith(`${e.argv[1]}/`) && path.endsWith(suffix)).slice(0, 1).join('\n'))
    }
    if (argv.startsWith('/usr/bin/find')) {
      return ok(Object.keys(tree).filter(path => /journal\.jsonl$|\/workflows\/wf_[^/]+\.json$/.test(path)).join('\n'))
    }
    return { value: { exitCode: 1, stdout: '', stderr: 'unexpected', isStdoutTruncated: false, isStderrTruncated: false } }
  })
  on('mcp.call', () => ({
    value: {
    isError: false,
    content: [
      {
        type: 'text' as const,
        text: JSON.stringify([
          { title: 'Offline catalog S3', cwd: '/repo', isRunning: true, lastActivityAt: new Date(NOW).toISOString() },
          { title: 'Other project', cwd: '/elsewhere', isRunning: false, lastActivityAt: new Date(NOW).toISOString() },
        ]),
      },
    ],
    },
  }))
  on('tool.register', ($, e) => ({ value: { tool: `mcp__openspec-cockpit__${e.name}` } }) as never)
  on('command.register', ($, e) => {
    seen.commands.push(e.name)
    return { value: { command: e.name } }
  })
  on('ui.toast', ($, e) => {
    seen.toasts.push(e.text)
    return { value: undefined }
  })
  on('ui.status', ($, e) => {
    seen.statuses.push(e.text)
    return { value: undefined }
  })
  on('ui.notify', () => ({ value: { isSent: false as const, reason: 'no-surface' as const } }))
  on('prompt.fill', ($, e) => {
    seen.fills.push(e.text)
    seen.prompt = e.mode === 'append' ? `${seen.prompt}${e.text}` : e.text
    return { isFilled: true }
  })
  on('prompt.read', () => ({ value: { text: seen.prompt, cursor: seen.prompt.length } as never }))
  on('prompt.submit', ($, e) => ({ text: e.text }))
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({
    value: {
      startedAt: NOW - 72 * MINUTE,
      context: { tokens: 84000, window: 200000, percent: 42 },
      rateLimits: [],
      cost: { usd: 3.12 },
    } as never,
  }))
  on('agent.list', () => ({
    value: [
      { id: 'a1', type: 'frontend-dev', description: 'impl:14', status: 'running' },
      { id: 'a2', type: 'tester', description: 'done', status: 'completed' },
    ] as never,
  }))
  on('ui.open', ($, e) => {
    seen.opened.push(e.id)
    return { value: { isPlaced: true as const } }
  })
  // What the engine draws at its own sites, so a test can see what the plugin handed on.
  on('ui.render', { component: 'Spinner' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-spinner">{`${e.props.word}${e.props.suffix}`}</Text>
  })
  on('ui.render', { component: 'ToolUse' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-tool">ENGINE ROW</Text>
  })
  on('ui.render', { component: 'AssistantMessage' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-assistant">{`ENGINE:${e.props.text}`}</Text>
  })
  on('model.complete', () => ({
    value: { isAnswered: true, text: '- Panneau v3 livré\n- 62 tests verts', usage: { input_tokens: 1, output_tokens: 1, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 } } as never,
  }))
  on('prompt.compose', () => ({ sections: [{ id: 'intro', text: 'You are Claude Code.', scope: 'shared' as const }] }))
  on('ui.render', { component: 'UserMessage' }, ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text key="engine-user">{e.props.text}</Text>
  })
  // What the engine draws in the band when no plugin does: an empty marker.
  on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine-band" />
  })
  return seen
}

const SCROLL = { offset: 0, bodyRows: 10 }
const BAND = {
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isCollapsed: false, isWorking: false, maxRows: 10, bodyColumns: 100, scroll: SCROLL, view: {} },
}
const PANE = {
  component: 'Pane' as const,
  requestId: 'cockpit',
  props: { title: 'Cockpit', isFocused: false, bodyColumns: 70, placement: 'dock' as const, scroll: SCROLL, view: {} },
}
const ORIGIN = { kind: 'composer' as const }
const PRESENTATION = { isFullscreen: true, columns: 120 }

const MESSAGE = (requestId: string, text: string) => ({
  component: 'AssistantMessage' as const,
  requestId,
  props: { text, isFirstOfReply: true },
})

/** A text the card shows, as a Text or as the alt of a drawing. */
async function shows(ui: { find: (query: { type?: string; text?: string | RegExp }) => Promise<unknown>; findAll: (query: { type?: string }) => Promise<{ props: Record<string, unknown> }[]> }, text: string | RegExp): Promise<boolean> {
  if ((await ui.find({ type: 'Text', text })) !== undefined) return true
  const alts = (await ui.findAll({ type: 'Svg' })).map(found => String(found.props.alt ?? ''))
  return alts.some(alt => (typeof text === 'string' ? alt.includes(text) : text.test(alt)))
}

function start($: Engine) {
  return $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true })
}

test('the spinner keeps its word and gains the context', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({
      plugin: 'conversation-cards',
      surface,
      component: 'Spinner',
      props: { word: 'Thinking', message: null, suffix: '…', mode: 'thinking' },
    })
    expect(await shows(ui, 'Thinking · contexte 42 %…')).toBe(true)
    await ui.unmount()
  }
})

test('tool calls read as compact cards that open onto Claude Code\'s own row', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const BASH = {
    component: 'ToolUse' as const,
    requestId: 'toolu_1',
    props: {
      tool_use_id: 'toolu_1',
      tool: 'Bash',
      input: { command: 'git status --short', description: 'Show the working tree status' },
      isRunning: false,
      isErrored: false,
      isInterrupted: false,
    },
  }
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'conversation-cards', surface, ...BASH })
    expect(await shows(ui, 'Show the working tree status')).toBe(true)
    expect(await shows(ui, 'git status --short')).toBe(true)
    expect(await shows(ui, '✓')).toBe(true)
    expect(await shows(ui, 'ENGINE ROW')).toBe(false)
    await ui.press({ key: 'open-toolu_1' })
    expect(await shows(ui, 'ENGINE ROW')).toBe(true)
    await ui.press({ key: 'open-toolu_1' })
    await ui.unmount()
  }
  const edit = await $.ui.mount({
    plugin: 'conversation-cards',
    surface: 'desktop',
    component: 'ToolUse',
    requestId: 'toolu_2',
    props: { tool_use_id: 'toolu_2', tool: 'Edit', input: { file_path: '/repo/a.ts' }, isRunning: false, isErrored: false, isInterrupted: false },
  })
  expect(await shows(edit, 'ENGINE ROW')).toBe(true)
})

test('a question card shows every option with its explanation and the reason, and answers go out together', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  const text = [
    'Deux points à trancher.',
    '',
    '### Q1 · Découpage de S4',
    'Tout en une session, ou découper ?',
    '- A · une session — 36 tâches, un workflow long',
    '- B · découper (recommandé) — deux workflows courts',
    'Recommandation : B, parce que 17 touche rendering/.',
    '',
    '### Q2 · Port',
    '- A · libérer 8080 — tuer k9s',
    '- B · API sur 8081 — surcharger le proxy',
  ].join('\n')
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'conversation-cards', surface, ...MESSAGE(`m1-${surface}`, text) })
    expect(await shows(ui, 'Découpage de S4')).toBe(true)
    // The terminal keeps its star and « Pourquoi B »; the desktop's Galet tiles say it quietly.
    expect(await shows(ui, surface === 'terminal' ? '★ recommandé' : /^\s*recommandé$/)).toBe(true)
    expect(await shows(ui, surface === 'terminal' ? /Pourquoi B/ : /Recommandation ·/)).toBe(true)
    expect(await shows(ui, /17 touche rendering/)).toBe(true)
    expect(await shows(ui, 'ENGINE:Deux points à trancher.')).toBe(true)
    expect(await shows(ui, /### Q1/)).toBe(false)
    await ui.unmount()
  }
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('m1', text) })
  seen.prompt = 'Mon brouillon en cours'
  await ui.press({ key: 'q-m1-Q1-B' })
  expect(await shows(ui, '→ B')).toBe(true)
  expect(seen.prompt).toBe('Mon brouillon en cours')
  await ui.press({ key: 'q-m1-Q2-opinion' })
  await ui.press({ key: 'note-button-m1-q:Q2' })
  expect(seen.prompt).toBe('Mon brouillon en cours\n[Q2 · Port] ')
  seen.prompt += 'k9s me sert encore'
  await ui.press({ key: 'send-button-m1' })
  expect(seen.prompt).toBe(
    'Mon brouillon en cours\n[Q2 · Port] k9s me sert encore\n\n── Réponses aux cartes ──\nQ1 : B · découper\nQ2 : ton avis ?\n── fin des réponses ──',
  )
  await ui.press({ key: 'q-m1-Q1-A' })
  await ui.press({ key: 'send-button-m1' })
  expect(seen.prompt.match(/── Réponses aux cartes ──/g)?.length).toBe(1)
  expect(seen.prompt).toContain('Q1 : A · une session')
})

test('a report: asks and decisions to answer, reserves open, sections one by one, findings, commit tracked, QA', async ($, on) => {
  const tree = projectTree()
  tree['/repo/frontend/src/loader.ts'] = file('export {}', NOW)
  const seen = world(on, '/repo', tree)
  await start($)
  await $.command.run({ command: 'cartes', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const text = [
    '# Groupe 15 — bilan',
    '## Fait',
    '- 2/4 tâches',
    '- chargeur branché',
    '## Décisions',
    '- garder le cache mémoire',
    '## Trouvé et corrigé',
    '- MAJEUR · frontend/src/loader.ts:12 · état oublié → reset, corrigé',
    '## Réserves',
    '- la notice reste en anglais',
    '## Tests',
    'Tests : 2905 passés, 0 échecs',
    '## QA',
    '- [ ] le planning se charge',
    "## Ce que j'attends de toi",
    '1. Commiter',
    '2. Valider la notice',
    '```text',
    'feat(offline-catalog): add the catalog loader',
    '',
    'Loads the manifest.',
    '```',
    '```text',
    'feat(offline-catalog): add the catalog infrastructure',
    '',
    'Already in.',
    '```',
  ].join('\n')
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('m2', text) })
  expect(await shows(ui, "Ce que j'attends de toi")).toBe(true)
  expect(await ui.find({ type: 'Markdown', text: /la notice reste en anglais/ })).toBeDefined()
  expect(await ui.find({ type: 'Markdown', text: /chargeur branché/ })).toBeUndefined()
  await ui.press({ key: 'section-toggle-m2-done' })
  expect(await ui.find({ type: 'Markdown', text: /chargeur branché/ })).toBeDefined()
  expect(await shows(ui, /^ENGINE:/)).toBe(false)
  const figures = (await ui.findAll({ type: 'Svg' })).map(found => String(found.props.source)).join('\n')
  expect(figures).toContain('2905 tests ✓')
  expect(await shows(ui, 'corrigé')).toBe(true)
  await ui.press({ key: 'finding-file-m2-0' })
  expect(seen.opened.at(-1)).toContain('--line 12 /repo/frontend/src/loader.ts')
  expect(await shows(ui, 'Commité · abc1234')).toBe(true)
  await ui.press({ key: 'commit-copy-m2-0' })
  expect(seen.copied.at(-1)).toBe('feat(offline-catalog): add the catalog loader\n\nLoads the manifest.')
  await ui.press({ key: 'mark-m2-ask:0-ok' })
  await ui.press({ key: 'note-button-m2-ask:1' })
  expect(seen.prompt).toBe('[Demande 2 · Valider la notice] ')
  seen.prompt += 'texte FR validé'
  await ui.press({ key: 'mark-m2-dec:0-ko' })
  expect(seen.prompt).toContain('[Décision 1 · garder le cache mémoire — à corriger] ')
  await ui.press({ key: 'mark-m2-qa:0-ok' })
  expect(await shows(ui, /À tester de ton côté · 1\/1 OK/)).toBe(true)
  await ui.press({ key: 'send-button-m2' })
  expect(seen.prompt).toContain('── Réponses aux cartes ──\nDemandes : 1 OK\nDécisions :\n- ✎ à corriger 1. garder le cache mémoire\nQA : 1/1 OK\n── fin des réponses ──')
  await ui.press({ key: 'report-toggle-m2' })
  expect(await shows(ui, /^ENGINE:# Groupe 15/)).toBe(true)
})

test('a long plain message offers a summary on demand', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const long = `${'Une phrase sans structure particulière. '.repeat(60)}`
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('long1', long) })
  expect(await shows(ui, /^ENGINE:Une phrase/)).toBe(true)
  await ui.press({ key: 'brief-long1-button' })
  expect(await shows(ui, 'En bref')).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'brief-long1-button' })).toBeUndefined()
})

test('a plain message is left to the engine, and the cards switch off', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const plain = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('m3', 'Vert. Je passe à la suite.') })
  expect(await shows(plain, 'ENGINE:Vert. Je passe à la suite.')).toBe(true)
  await $.command.run({ command: 'cartes', args: 'off', origin: ORIGIN, presentation: PRESENTATION })
  const off = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('m4', '### Q1 · X\n- A · a\n- B · b') })
  expect(await shows(off, /^ENGINE:### Q1/)).toBe(true)
})

test('a background task notification shrinks to one line', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({
    plugin: 'conversation-cards',
    surface: 'desktop',
    component: 'UserMessage',
    requestId: 'n1',
    props: {
      text: 'Monitor event: mutation replay results\nmore lines',
      origin: { kind: 'task-notification' },
      isExpanded: false,
      task: { id: 't1', status: 'completed', durationMs: 65000 },
    } as never,
  })
  expect(await shows(ui, 'Monitor event: mutation replay results')).toBe(true)
  expect(await shows(ui, /completed · 1 min/)).toBe(true)
  expect(await shows(ui, /more lines/)).toBe(false)
})

test('the display contract joins the system prompt, and leaves it when switched off', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const compose = () =>
    $.prompt.compose({ model: 'claude-opus-5-5', promptModel: 'claude-opus-5-5', surfaces: ['desktop'], tools: [], outputStyle: null, traits: [], sections: [] } as never)
  const ids = async () => (await compose()).sections.map(section => section.id)
  expect(await ids()).toEqual(['intro', 'conversation-cards:contract'])
  expect((await compose()).sections[1]?.text).toContain('### Q1 · <short title>')
  await $.command.run({ command: 'cartes', args: 'contrat off', origin: ORIGIN, presentation: PRESENTATION })
  expect(await ids()).toEqual(['intro'])
})

test('a message drawn while session.start is still running is a card once it has run (reload race)', async ($, on) => {
  world(on, '/repo', projectTree())
  const text = "# Bilan\n## Fait\n- x\n## Tests\nTests : 3 passés, 0 échecs\n## Ce que j'attends de toi\n1. Relire"
  // Mounted first: a reload draws the transcript before session.start; the session's state carries the project over.
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('early', text) })
  await start($)
  expect(await shows(ui, "Ce que j'attends de toi")).toBe(true)
  const tool = await $.ui.mount({
    plugin: 'conversation-cards',
    surface: 'desktop',
    component: 'ToolUse',
    requestId: 'toolu_early',
    props: { tool_use_id: 'toolu_early', tool: 'Bash', input: { command: 'ls', description: 'List files' }, isRunning: false, isErrored: false, isInterrupted: false },
  })
  expect(await shows(tool, 'List files')).toBe(true)
})

test('a QA note opens a labelled line in the prompt, and the block lists every line that is not OK', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  const text = "# Bilan\nLe chargeur est branché ; reste à le vérifier à l'écran.\n## Fait\n- x\n## Tests\nTests : 3 passés, 0 échecs\n## QA\n- [ ] le planning se charge\n- [ ] le bouton répond\n## Ce que j'attends de toi\nTester"
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('qa1', text) })
  expect(await ui.find({ type: 'Markdown', text: /reste à le vérifier/ })).toBeDefined()
  expect(await ui.find({ type: 'Input' })).toBeUndefined()
  await ui.press({ key: 'note-button-qa1-qa:1' })
  expect(seen.prompt).toBe('[QA 2 · le bouton répond] ')
  seen.prompt += 'reste gris au survol'
  await ui.press({ key: 'mark-qa1-qa:0-ok' })
  await ui.press({ key: 'mark-qa1-qa:1-ko' })
  await ui.press({ key: 'send-button-qa1' })
  expect(seen.prompt).toBe(
    '[QA 2 · le bouton répond] reste gris au survol\n\n── Réponses aux cartes ──\nQA : 1/2 OK, 1 KO\n- ✗ 2. le bouton répond\n── fin des réponses ──',
  )
})

test('a report that also asks a question shows the question card inside it', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const text = "# Bilan\n## Fait\n- x\n## Tests\nTests : 3 passés, 0 échecs\n## Ce que j'attends de toi\n### Q1 · Envoi\n- A · préremplir — tu relis\n- B · envoyer direct (recommandé) — plus rapide\n"
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('rq', text) })
  expect(await ui.find({ type: 'Button', key: 'q-rq-Q1-B' })).toBeDefined()
})

test('the S5 report card keeps its order: three asks, then a QA card with the set-up commands and its checks, the commit in its own card', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('s5', S5_REPORT) })
  // Three asks, no more: the checklist no longer piles up under « Message de commit ».
  expect((await ui.findAll({ type: 'Button' })).filter(button => button.key?.startsWith('mark-s5-ask:') === true).map(button => button.key)).toEqual([
    'mark-s5-ask:0-ok',
    'mark-s5-ask:1-ok',
    'mark-s5-ask:2-ok',
  ])
  expect(await shows(ui, 'Message de commit')).toBe(false)
  // The QA: its commands kept, each with a copy button, and its checks with OK / KO.
  expect((await ui.findAll({ type: 'Code' })).map(code => String(code.props.source))).toContain('cd frontend && npm run dev')
  expect((await ui.findAll({ type: 'Button' })).filter(button => button.key?.endsWith('-copy') === true && button.key.startsWith('qa-prep-s5')).length).toBe(3)
  expect(await shows(ui, 'Ouverture sur la semaine')).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'mark-s5-qa:2-ko' })).toBeDefined()
  expect(await shows(ui, /^Commit prêt|^Commité/)).toBe(true)
})

test('a QA written to the contract shows « Fais » and « Attendu » under each check', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('cq', CONTRACT_QA) })
  expect(await shows(ui, /^Fais : recharge la page, puis change de semaine\.$/)).toBe(true)
  expect(await shows(ui, /^Attendu : le planning est rempli/)).toBe(true)
  expect((await ui.findAll({ type: 'Code' })).map(code => String(code.props.source))).toEqual(['cd backend && npm start -- --profile=local'])
})

test('a reply to the QA answers stays as written, with a compact « QA à refaire » card under it to mark each check again', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('fu', QA_FOLLOW_UP) })
  // The message itself, untouched.
  expect(await shows(ui, /^ENGINE:\*\*La QA 1 est en fait OK/)).toBe(true)
  expect(await shows(ui, 'QA à refaire · 0/3 OK')).toBe(true)
  expect((await ui.findAll({ type: 'Button' })).filter(button => /^mark-fu-qa:\d-ko$/.test(button.key ?? '')).length).toBe(3)
  // Claude's own OK is a claim for the user to confirm, on QA 1 and QA 4 only.
  expect((await ui.findAll({ type: 'Text', text: /^Claude la juge OK/ })).length).toBe(2)
  // The message is drawn whole above: the card holds no « Fais » nor steps again.
  expect(await shows(ui, /^Fais : depuis la semaine en cours/)).toBe(false)
  expect(await ui.find({ type: 'Markdown', text: /Show Network request blocking/ })).toBeUndefined()
  // Once marked, the claim gives way to the user's verdict.
  await ui.press({ key: 'mark-fu-qa:0-ok' })
  expect((await ui.findAll({ type: 'Text', text: /^Claude la juge OK/ })).length).toBe(1)
})

test('a framing keeps its text, with « À confirmer » and « Ce que j’attends de toi » under it and the files it cites', async ($, on) => {
  const tree = projectTree()
  tree['/repo/openspec/changes/offline-catalog/verification'] = dir(NOW)
  tree['/repo/openspec/changes/offline-catalog/verification/scenario-coverage.md'] = file('| scenario |', NOW)
  const seen = world(on, '/repo', tree)
  await start($)
  await $.command.run({ command: 'cartes', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('pl', PLAN_21_22) })
  expect(await shows(ui, /^ENGINE:Commit `c28fa52` vu/)).toBe(true)
  expect(await shows(ui, 'À confirmer')).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'mark-pl-dec:1-ko' })).toBeDefined()
  // The message is drawn whole above: the card shows the points, not their sub-points again.
  expect(await ui.find({ type: 'Markdown', text: /les docs du groupe 21/ })).toBeUndefined()
  expect((await ui.findAll({ type: 'Button' })).filter(button => /^mark-pl-ask:\d-ok$/.test(button.key ?? '')).length).toBe(4)
  await ui.press({ key: 'file-pl-verification/scenario-coverage.md-' })
  // Cited from the change's folder, opened there: never an empty file created at the root.
  expect(seen.opened.at(-1)).toContain('/repo/openspec/changes/offline-catalog/verification/scenario-coverage.md')
})

test('a cited file that is nowhere in the project says so and opens nothing', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('nf', '## Hypothèses\n- relire `docs/nope/missing.md` avant le run') })
  await ui.press({ key: 'file-nf-docs/nope/missing.md-' })
  expect(seen.toasts).toContain('Fichier introuvable : docs/nope/missing.md')
  expect(seen.opened.filter(entry => entry.includes('JetBrains'))).toEqual([])
})

test('the 21-22 report: the « Reco » table becomes five choices to settle, and what Claude does itself has no button', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('r2', REPORT_21_22) })
  const buttons = (await ui.findAll({ type: 'Button' })).map(button => button.key ?? '')
  expect(buttons.filter(key => /^mark-r2-pick:\d-ok$/.test(key)).length).toBe(5)
  // « Je fais de mon côté, sans décision de ta part » is no ask: nothing to mark there.
  expect(buttons.filter(key => key.startsWith('mark-r2-ask:'))).toEqual([])
  expect(await ui.find({ type: 'Markdown', text: /aligner la Data Strategy sur l'ADR/ })).toBeDefined()
  expect(await shows(ui, /^Reco : Les aligner maintenant$/)).toBe(true)
  expect(await shows(ui, '· « planifieur » contre « planificateur » → « planificateur » partout')).toBe(true)
})

test('a message with a cockpit block: the block is hidden, the cards follow it, information has no button', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('cb', WITH_COCKPIT_BLOCK) })
  const engine = String((await ui.find({ type: 'Text', text: /^ENGINE:/ }))?.text ?? '')
  expect(engine.includes('```cockpit')).toBe(false)
  expect(engine.includes('| 1 | Parcours, annexe B |')).toBe(true)
  expect(await shows(ui, 'À trancher')).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'mark-cb-pick:1-ok' })).toBeDefined()
  expect(await ui.find({ type: 'Button', key: 'mark-cb-dec:0-ok' })).toBeDefined()
  expect(await ui.find({ type: 'Button', key: 'mark-cb-ask:0-ok' })).toBeDefined()
  expect(await shows(ui, 'Ce que je fais ensuite')).toBe(true)
  expect((await ui.findAll({ type: 'Button' })).filter(button => button.key?.includes('info') === true)).toEqual([])
  await ui.press({ key: 'mark-cb-pick:0-ok' })
  await ui.press({ key: 'send-button-cb' })
  expect(seen.prompt).toContain('À trancher :\n- ✓ reco 1. Parcours, annexe B contredit le glossaire')
})

test('the iPhone walkthrough: the message once, then a compact QA card of names under their parts, no button on the preparation', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('ig', PLANNER_GUIDE) })
  const engine = String((await ui.find({ type: 'Text', text: /^ENGINE:/ }))?.text ?? '')
  expect(engine.includes('**Préparation**')).toBe(true)
  expect(engine.includes('```cockpit')).toBe(false)
  // Thirteen checks to mark, not the four preparation steps on top of them.
  expect((await ui.findAll({ type: 'Button' })).filter(button => /^mark-ig-qa:\d+-ko$/.test(button.key ?? '')).length).toBe(13)
  expect(await shows(ui, 'À tester de ton côté · 0/13 OK')).toBe(true)
  expect(await shows(ui, "(c) Temps d'affichage")).toBe(true)
  expect(await shows(ui, 'Partie 2 — la session (b), avec la mémoire enregistrée sur le Mac')).toBe(true)
  // Nothing of the message is repeated: no « Fais », no step, no command.
  expect(await shows(ui, /^Fais :/)).toBe(false)
  expect(await shows(ui, /^Préparation$/)).toBe(false)
  expect((await ui.findAll({ type: 'Button' })).filter(button => /^mark-ig-ask:\d-ok$/.test(button.key ?? '')).length).toBe(2)
  expect(await shows(ui, 'Ce que je fais ensuite')).toBe(true)
})

test('the block’s « vérifier » lines name the checks of a compact QA card', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const text = ['Lance les deux vérifications, dans cet ordre.', '', '```cockpit', 'vérifier: Ouverture sur la semaine', 'verifier: Bascule de thème', '```'].join('\n')
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('vf', text) })
  expect(await shows(ui, 'À tester de ton côté · 0/2 OK')).toBe(true)
  expect(await shows(ui, 'Bascule de thème')).toBe(true)
  expect(await ui.find({ type: 'Button', key: 'mark-vf-qa:1-ko' })).toBeDefined()
})

// ---------------------------------------------------------------- Galet

/** Any drawing the kit mounted: only its `findAll` is read. */
type Drawing = Pick<Awaited<ReturnType<Engine['ui']['mount']>>, 'findAll'>

/** The « en attente » dot of a question, as its Svg source; '' when the question has none. */
async function waitingDot(ui: Drawing): Promise<string> {
  const dots = (await ui.findAll({ type: 'Svg' })).filter(found => found.props.alt === 'en attente')
  return String(dots[0]?.props.source ?? '')
}

const ONE_QUESTION = ['### Q1 · Découpage de S4', '- A · une session — long', '- B · découper (recommandé) — court'].join('\n')

test('a question opens on its Q1 tag and a dot that breathes until answered; the terminal keeps its text header', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('rq', ONE_QUESTION) })
  expect(await shows(ui, 'Q1')).toBe(true)
  expect(await shows(ui, 'Découpage de S4')).toBe(true)
  expect(await waitingDot(ui)).toContain('class="wave')
  await ui.press({ key: 'q-rq-Q1-B' })
  expect(await waitingDot(ui)).toBe('')
  expect(await shows(ui, '→ B')).toBe(true)
  const text = await $.ui.mount({ plugin: 'conversation-cards', surface: 'terminal', ...MESSAGE('rq-t', ONE_QUESTION) })
  expect(await text.findAll({ type: 'Svg' })).toHaveLength(0)
  expect(await shows(text, 'Découpage de S4')).toBe(true)
})

test('a commit that landed says so in its title, with a check', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  await $.command.run({ command: 'cartes', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const text = ['Fait.', '', '```text', 'feat(offline-catalog): add the catalog infrastructure', '', 'Body line.', '```'].join('\n')
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('rc', text) })
  expect(await shows(ui, 'Commité · abc1234')).toBe(true)
  expect((await ui.findAll({ type: 'Svg' })).some(found => found.props.alt === 'fait')).toBe(true)
})

test('cards are Galet pebbles: a pastel of their tone, round corners, no visible rim', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('rb', ONE_QUESTION) })
  const frames = await ui.findAll({ type: 'Box' })
  expect(frames.some(found => found.props.backgroundColor === 'rgba(191,111,58,.10)' && found.props.borderStyle === 'round' && found.props.borderColor === 'rgba(0,0,0,0)')).toBe(true)
  const everything = JSON.stringify(frames.map(found => found.props))
  expect(everything).not.toContain('rgba(192,112,42,.45)"')
})

test('outside OpenSpec, a commit card does not ask for a change-id scope', async ($, on) => {
  const tree = projectTree()
  for (const path of Object.keys(tree)) if (path.startsWith('/repo/openspec')) delete tree[path]
  world(on, '/repo', tree)
  await start($)
  await $.command.run({ command: 'cartes', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const text = ['Fait.', '', '```text', 'feat(widget): add the clock', '', 'Body line.', '```'].join('\n')
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('nc', text) })
  expect(await shows(ui, /pas un change-id/)).toBe(false)
  expect(await shows(ui, /scope widget/)).toBe(true)
})

test('only the latest reply moves: once the person sends anything, the earlier questions rest', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  const ui = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('old', ONE_QUESTION) })
  expect(await waitingDot(ui)).toContain('class="wave')
  // Answered by typing, not through the card: the question gets no mark, yet it is settled.
  await $.prompt.submit({ text: 'On découpe.', wait: false, origin: ORIGIN } as never)
  expect(await waitingDot(ui)).not.toContain('class="wave')
  expect(await waitingDot(ui)).not.toBe('')
  expect(await shows(ui, 'en attente')).toBe(true)
  // Claude's next reply asks again: that one moves.
  const next = await $.ui.mount({ plugin: 'conversation-cards', surface: 'desktop', ...MESSAGE('new', ONE_QUESTION) })
  expect(await waitingDot(next)).toContain('class="wave')
})
