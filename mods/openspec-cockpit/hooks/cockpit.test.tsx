import { type Engine, expect, mock, test } from 'claude-code/testing'
import type { FsEntry, On } from 'claude-code'


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
  on('classic.Stop', () => ({}))
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

function start($: Engine) {
  return $.session.start({ cwd: '/repo', surface: 'desktop', isInteractive: true })
}

test('the summary command reads branch, change, graph and the latest handoff', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  expect(seen.commands).toEqual(['cockpit', 'ou-en-suis-je', 'cockpit-toggle'])

  const result = await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const text = result.text ?? ''
  expect(text).toContain('**Branche** `feat/offline-catalog` · 1 fichier non commité')
  expect(text).toContain('`offline-catalog` · 2/4 (50 %) · étape **apply**')
  expect(text).toContain('✗ 1 fichier modifié après le build (build 17/10 11:30)')
  expect(text.includes('Workflows')).toBe(false)
  expect(text).toContain('**Dernière passation** 17/10 11:14 — /opsx:apply de offline-catalog, S4 : frontend')
  expect(text).toContain('1. graphify check-update ., git status.')
  // review-close-out, a review workflow finished 3 minutes ago, counts as the review.
  expect(text).toContain('**Portes** graph ✗ · review ✓ · commit ✗')

  expect(seen.statuses.at(-1)).toBe('⎇ feat/offline-catalog ±1 │ offline-catalog 2/4 · apply │ graph périmé')
  // Finished workflows are announced by background-tasks now.
  expect(seen.toasts).toEqual([])
})

test('the cockpit opens by itself, and draws text in the terminal', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  expect(seen.opened).toEqual(['cockpit'])
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })

  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'terminal', ...PANE })
  expect(await ui.find({ type: 'Text', text: /2\/4 · 50 %/ })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'étape apply' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Workflows/ })).toBeUndefined()
  expect(await ui.findAll({ type: 'Button', text: /S3 infra|S4 : frontend/ })).toHaveLength(2)
  await ui.press({ key: 'handoff-2026-10-15-1740-s3.md' })
  expect(seen.fills.at(-1)).toContain('.claude/passation/2026-10-15-1740-s3.md')
})

test('on desktop the cockpit opens on a large ring and the phase timeline, then gate pills and the handoff', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })

  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'desktop', ...PANE })
  const drawings = await ui.findAll({ type: 'Svg' })
  for (const svg of drawings) {
    expect(Number(svg.props.height)).toBeLessThan(150)
    expect(String(svg.props.source)).toContain('prefers-color-scheme: dark')
  }
  // The head: a 54 px ring labelled with the change's share done, then the cycle's segments at the current step.
  expect(drawings[0]?.props.width).toBe(54)
  expect(String(drawings[0]?.props.source)).toContain('>50%</text>')
  expect(String(drawings[1]?.props.alt)).toBe('Cycle : apply')
  // The ring fills as it appears: drawn interactive, the only way the desktop runs its motion. The segments stand still.
  expect(drawings[0]?.props.isInteractive).toBe(true)
  expect(drawings[1]?.props.isInteractive).not.toBe(true)
  expect(await ui.find({ type: 'Text', text: 'offline-catalog' })).toBeDefined()
  const gates = String(drawings.find(svg => svg.props.alt === 'Portes du cycle')?.props.source ?? '')
  expect(gates).toContain('graph périmé')
  expect(gates).toContain('review vue')
  expect(gates).toContain('1 non commité')
  // The background tasks show here at a glance, as background-tasks draws them: running runs, this session's
  // agents, finished runs. The other sessions of the project are gone (never asked back).
  // A section's title is the press that folds it, its arrow in the same button.
  expect(await ui.find({ type: 'Button', key: 'toggle-background' }).then(found => found?.props.label)).toBe('▾  En arrière-plan')
  expect(await ui.find({ type: 'Text', text: 'impl:14' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'review-close-out' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: 'Offline catalog S3' })).toBeUndefined()

  await ui.press({ key: 'resume-pane' })
  expect(seen.fills.at(-1)).toContain('.claude/passation/2026-10-17-1114-s4.md')
  await ui.press({ key: 'handoff-2026-10-15-1740-s3.md' })
  expect(seen.fills.at(-1)).toContain('.claude/passation/2026-10-15-1740-s3.md')
})

test('group progress uses soft bars, the finished groups paler, and no button', async ($, on) => {
  const tree = projectTree()
  tree['/repo/openspec/changes/offline-catalog/tasks.md'] = file('## 1. Infra\n- [x] 1.1\n- [x] 1.2\n\n## 2. Frontend\n- [x] 2.1\n- [ ] 2.2\n- [ ] 2.3\n', NOW - 60 * MINUTE)
  world(on, '/repo', tree)
  await start($)
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'desktop', ...PANE })
  const bars = (await ui.findAll({ type: 'Svg' })).filter(svg => /^\d+\/\d+$/.test(String(svg.props.alt)) && svg.props.height === 5)
  expect(bars.map(svg => svg.props.alt)).toEqual(['2/2', '1/3'])
  expect(String(bars[0]?.props.source)).toContain('opacity=".55"')
  expect(String(bars[1]?.props.source)).not.toContain('opacity=".55"')
  expect((await ui.findAll({ type: 'Button' })).filter(button => String(button.key).startsWith('group-'))).toHaveLength(0)
})

const RETIRED_COLOURS = ['#88C0D0', '#A3BE8C', '#EBCB8B', '#BF616A', '#B48EAD', '#7B88A1', '#4C566A', '#D8DEE9', '#81A1C1']

test('no colour of the retired palette survives in the pane', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'desktop', ...PANE })
  const everything = JSON.stringify(
    [...(await ui.findAll({ type: 'Box' })), ...(await ui.findAll({ type: 'Text' })), ...(await ui.findAll({ type: 'Svg' }))].map(found => found.props),
  ).toUpperCase()
  for (const colour of RETIRED_COLOURS) expect(everything).not.toContain(colour)
})

test('a dev server Claude left running shows in the cockpit at the turn’s end, with its port', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  await $.classic.Stop({
    stop_hook_active: false,
    background_tasks: [{ id: 's1', type: 'shell', status: 'running', description: 'Frontend dev server', command: 'npm run dev -- --port 5173' }],
  } as never)
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'desktop', ...PANE })
  expect(await ui.find({ type: 'Text', text: 'Frontend dev server' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: ':5173' })).toBeDefined()
})

test('a gate alert is drawn under the command that raised it', async ($, on) => {
  world(on, '/repo', projectTree())
  await start($)
  await $.prompt.submit({ text: '/opsx:apply', command: { name: 'opsx:apply', args: '' }, wait: false, origin: ORIGIN })
  await $.session.append({
    message: { type: 'user', role: 'user', content: [{ type: 'text', text: '/opsx:apply' }] },
    door: 'prompt',
    origin: ORIGIN,
    uuid: 'u-1',
  } as never)
  const ui = await $.ui.mount({
    plugin: 'openspec-cockpit',
    surface: 'desktop',
    component: 'UserMessage',
    requestId: 'u-1',
    props: { text: '/opsx:apply', origin: ORIGIN, isExpanded: false } as never,
  })
  expect(await ui.find({ type: 'Text', text: '/opsx:apply' })).toBeDefined()
  expect(await ui.find({ type: 'Text', text: /Graph périmé \(1 fichier modifié après le build\)/ })).toBeDefined()

  const other = await $.ui.mount({
    plugin: 'openspec-cockpit',
    surface: 'desktop',
    component: 'UserMessage',
    requestId: 'u-2',
    props: { text: 'bonjour', origin: ORIGIN, isExpanded: false } as never,
  })
  expect(await other.find({ type: 'Text', text: /Porte/ })).toBeUndefined()
})

test('gates warn on a stale graph before apply and a dirty tree before archive, never block', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  const submit = (name: string) =>
    $.prompt.submit({ text: `/${name}`, command: { name, args: '' }, wait: false, origin: ORIGIN })

  expect((await submit('opsx:apply')).text).toBe('/opsx:apply')
  expect(seen.toasts).toContain('⚠ Graph périmé (1 fichier modifié après le build) — lance graphify update . avant /opsx:apply')
  await submit('opsx:archive')
  expect(seen.toasts).toContain('⚠ Arbre non commité (1 fichier) — commit manuel avant /opsx:archive')
  const gateToasts = () => seen.toasts.filter(toast => toast.startsWith('⚠')).length
  const count = gateToasts()
  await submit('opsx:ff')
  expect(gateToasts()).toBe(count)
})

test('a switched-off brick stays off, and is remembered', async ($, on) => {
  const seen = world(on, '/repo', projectTree())
  await start($)
  const toggled = await $.command.run({ command: 'cockpit-toggle', args: 'portes off', origin: ORIGIN, presentation: PRESENTATION })
  expect(toggled.text).toContain('portes ✗')
  expect(seen.store.get('toggles')).toMatchObject({ gates: false })

  await $.command.run({ command: 'cockpit-toggle', args: 'statut', origin: ORIGIN, presentation: PRESENTATION })
  expect(seen.statuses.at(-1)).toBeUndefined()
})

test('a project without openspec/ nor .claude/passation/ stays silent', async ($, on) => {
  const seen = world(on, '/other', {})
  await start($)
  expect(seen.commands).toEqual([])
  expect(seen.statuses).toEqual([])
  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'desktop', ...BAND })
  expect(await ui.find({ type: 'Text' })).toBeUndefined()
})


const MESSAGE = (requestId: string, text: string) => ({
  component: 'AssistantMessage' as const,
  requestId,
  props: { text, isFirstOfReply: true },
})

test('the pane leads with the next action: the stale graph', async ($, on) => {
  const tree = projectTree()
  world(on, '/repo', tree)
  await start($)
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface, ...PANE })
    expect(await ui.find({ type: 'Text', text: 'Rafraîchir le graph avant de continuer' })).toBeDefined()
    await ui.unmount()
  }
  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'desktop', ...PANE })
  expect(await ui.find({ type: 'Button', key: 'action-graph' })).toBeDefined()
  await ui.press({ key: 'toggle-handoff' })
  expect(await ui.find({ type: 'Button', key: 'resume-pane' })).toBeUndefined()
})

test('an OpenSpec project without graphify shows no graph and is never asked for one', async ($, on) => {
  const tree = projectTree()
  delete tree['/repo/graphify-out/graph.json']
  const seen = world(on, '/repo', tree)
  await start($)
  const result = await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const text = result.text ?? ''
  expect(text).toContain('**Portes** review ✓ · commit ✗')
  expect(text.includes('**Graph**')).toBe(false)
  expect(seen.statuses.at(-1)).toBe('⎇ feat/offline-catalog ±1 │ offline-catalog 2/4 · apply')
  await $.prompt.submit({ text: '/opsx:apply', command: { name: 'opsx:apply', args: '' }, wait: false, origin: ORIGIN })
  expect(seen.toasts.filter(toast => toast.startsWith('⚠'))).toEqual([])
})

/** A repository just after an archive: no active change, the archived one ten minutes old. */
function archivedTree(): Record<string, Node> {
  const tree = projectTree()
  for (const path of Object.keys(tree)) if (path.includes('/changes/offline-catalog') || path.includes('wf_live')) delete tree[path]
  tree['/repo/openspec/changes/archive/2026-10-17-pantry-import'] = dir(NOW - 10 * MINUTE)
  return tree
}

test('the post-archive ritual finds the backlog under docs/ and drops the steps a project has no file for', async ($, on) => {
  const tree = archivedTree()
  tree['/repo/docs'] = dir(NOW)
  tree['/repo/docs/product'] = dir(NOW)
  tree['/repo/docs/product/Backlog.md'] = file('| nutrition-score | ✅ SHIPPED |\n| pantry-import | ✅ SHIPPED |\n', NOW)
  world(on, '/repo', tree)
  await start($)
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const ui = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'terminal', ...PANE })
  // Backlog shipped, graph built before the archive, doc and memory unchecked.
  expect(await ui.find({ type: 'Text', text: 'Rituel post-archive · 1/4' })).toBeDefined()
  await ui.unmount()

  delete tree['/repo/docs/product/Backlog.md']
  delete tree['/repo/graphify-out/graph.json']
  await $.command.run({ command: 'ou-en-suis-je', args: '', origin: ORIGIN, presentation: PRESENTATION })
  const bare = await $.ui.mount({ plugin: 'openspec-cockpit', surface: 'terminal', ...PANE })
  expect(await bare.find({ type: 'Text', text: 'Rituel post-archive · 0/2' })).toBeDefined()
  await bare.unmount()
})
