import { type Engine, expect, mock, test } from 'claude-code/testing'
import type { On } from 'claude-code'

const MINUTE = 60 * 1000
const NOW = Date.UTC(2026, 10, 6, 10, 0)
const SCROLL = { offset: 0, bodyRows: 10 }
const BAND = (isWorking: boolean) => ({
  component: 'AbovePrompt' as const,
  props: { hasSurvey: false, isCollapsed: false, isWorking, maxRows: 10, bodyColumns: 120, scroll: SCROLL, view: {} },
})

type Seen = { commands: string[]; toasts: string[]; clock: ReturnType<typeof mock.clock> }

function world(on: On): Seen {
  const seen: Seen = { commands: [], toasts: [], clock: mock.clock(on, { now: NOW }) }
  on('session.start', ($, e) => ({ cwd: e.cwd }))
  on('session.usage', () => ({
    value: { startedAt: NOW - 72 * MINUTE, context: { tokens: 84000, window: 200000, percent: 42 }, rateLimits: [], cost: { usd: 3.12 } } as never,
  }))
  on('session.model', () => ({ value: 'claude-opus-5-5' }))
  on('command.run', ($, e) => {
    seen.commands.push(e.command)
    return { text: '' }
  })
  on('ui.toast', ($, e) => {
    seen.toasts.push(String(e.text))
    return { value: undefined } as never
  })
  on('tool.call', () => ({ result: 'ok' }))
  on('classic.Stop', () => ({}))
  return seen
}

function start($: Engine) {
  return $.session.start({ cwd: '/anywhere', surface: 'desktop', isInteractive: true })
}

test('the band shows the session in any project, with the background count once a turn ends with tasks in flight', async ($, on) => {
  const seen = world(on)
  await start($)
  const band = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BAND(true) })
  expect(await band.find({ type: 'Text', text: '42 %' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: '3,12 $' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: '1 h 12' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: 'Opus 5.5' })).toBeDefined()
  expect(await band.find({ type: 'Button', key: 'background' })).toBeUndefined()

  await $.classic.Stop({
    stop_hook_active: false,
    background_tasks: [
      { id: 't1', type: 'shell', status: 'running', description: 'frontend', command: 'npm run dev -- --port 5173' },
      { id: 't2', type: 'workflow', status: 'running', description: 'run', name: 'apply' },
      { id: 't3', type: 'shell', status: 'completed', description: 'build', command: 'npm run build' },
    ],
  } as never)
  expect(await band.find({ type: 'Button', key: 'background' }).then(found => found?.props.label)).toBe('2 en arrière-plan ▴')
  // A click unfolds the list above the band: each task, its port, its kind; « Tout afficher » opens the pane.
  await band.press({ key: 'background' })
  expect(await band.find({ type: 'Text', text: 'frontend' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: ':5173' })).toBeDefined()
  expect(await band.find({ type: 'Text', text: 'workflow' })).toBeDefined()
  expect(await band.find({ type: 'Button', key: 'background' }).then(found => found?.props.label)).toBe('2 en arrière-plan ▾')
  expect(seen.commands).toEqual([])
  await band.press({ key: 'show-all' })
  expect(seen.commands).toEqual(['arriere-plan'])
  await band.press({ key: 'background' })
  expect(await band.find({ type: 'Text', text: ':5173' })).toBeUndefined()
})

test('a reload of the module keeps the tasks the last turn’s end reported', async ($, on) => {
  world(on)
  await start($)
  await $.classic.Stop({
    stop_hook_active: false,
    background_tasks: [{ id: 't1', type: 'shell', status: 'running', description: 'frontend', command: 'npm run dev -- --port 5173' }],
  } as never)
  // A reload runs register and session.start again; the state stays.
  await start($)
  const band = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BAND(false) })
  expect(await band.find({ type: 'Button', key: 'background' }).then(found => found?.props.label)).toBe('1 en arrière-plan ▴')
})

test('tool calls reach the band at the next refresh, not one by one', async ($, on) => {
  const seen = world(on)
  await start($)
  const band = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BAND(false) })
  for (let index = 0; index < 4; index++) await $.tool.call({ tool: 'Read', tool_use_id: `r${index}`, file_path: '/a' } as never)
  expect(await band.find({ type: 'Text', text: '0' })).toBeDefined()
  await seen.clock.advance(31 * 1000)
  expect(await band.find({ type: 'Text', text: '4' })).toBeDefined()
})

test('the terminal gets one line of text', async ($, on) => {
  world(on)
  await start($)
  const band = await $.ui.mount({ plugin: 'session-hud', surface: 'terminal', ...BAND(false) })
  expect(await band.find({ type: 'Text', text: /^42 % contexte · 3,12 \$ coût · 1 h 12 session · 0 outils · Opus 5.5$/ })).toBeDefined()
})

// ---------------------------------------------------------------- Terre de Sienne

type Backdrops = { set: unknown[]; store: Map<string, unknown> }

function withBackdrop(on: On): Backdrops {
  const seen: Backdrops = { set: [], store: new Map() }
  on('theme.set', ($, e) => {
    seen.set.push(e.backdrop)
    return { value: { isDrawn: true as const, requestId: 'b' } }
  })
  on('theme.clear', () => {
    seen.set.push(undefined)
    return { value: { isDrawn: false as const, reason: 'cleared' } }
  })
  on('store.get', ($, e) => ({ value: seen.store.get(e.key) }))
  on('store.set', ($, e) => {
    seen.store.set(e.key, e.value)
    return { value: undefined }
  })
  on('command.register', ($, e) => ({ value: { command: e.name } }))
  return seen
}

const BACKDROP = (plugin: string) => ({
  component: 'Backdrop' as const,
  props: { scene: 'sienne', plugin, glass: { blur: 16, opacity: 0.6 } },
})

test('the backdrop stays off at start; turned on, it draws only its own', async ($, on) => {
  world(on)
  const seen = withBackdrop(on)
  on('ui.render', { component: 'Backdrop' }, ($, e) => {
    const { Box } = $.ui.resolve(e)
    return <Box key="engine-backdrop" />
  })
  await start($)
  expect(seen.set).toEqual([])
  seen.store.set('backdrop', 'on')
  await start($)
  expect(seen.set).toEqual([{ scene: 'sienne' }])
  const mine = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BACKDROP('session-hud') })
  expect(String((await mine.find({ type: 'Svg' }))?.props.source)).toContain('feTurbulence')
  const other = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BACKDROP('other') })
  expect(await other.find({ type: 'Svg' })).toBeUndefined()
  expect(await other.find({ type: 'Box', key: 'engine-backdrop' })).toBeDefined()
})

test('/fond toggles the backdrop and remembers it', async ($, on) => {
  world(on)
  const seen = withBackdrop(on)
  await start($)
  const ORIGIN = { kind: 'composer' as const }
  const PRESENTATION = { isFullscreen: true, columns: 120 }
  expect(seen.set).toEqual([])
  await $.command.run({ command: 'fond', args: '', origin: ORIGIN, presentation: PRESENTATION })
  expect(seen.store.get('backdrop')).toBe('on')
  expect(seen.set.at(-1)).toEqual({ scene: 'sienne' })
  await $.command.run({ command: 'fond', args: '', origin: ORIGIN, presentation: PRESENTATION })
  expect(seen.store.get('backdrop')).toBe('off')
  expect(seen.set.at(-1)).toBeUndefined()
  seen.set = []
  await start($)
  expect(seen.set).toEqual([])
})

test('the band wears Galet: its drawings follow the theme, it lies on the app’s own frame, no Nord colour is left', async ($, on) => {
  world(on)
  withBackdrop(on)
  await start($)
  await $.classic.Stop({
    stop_hook_active: false,
    background_tasks: [{ id: 't1', type: 'shell', status: 'running', description: 'frontend', command: 'npm run dev -- --port 5173' }],
  } as never)
  const band = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BAND(true) })
  await band.press({ key: 'background' })
  const drawings = await band.findAll({ type: 'Svg' })
  expect(drawings.length).toBeGreaterThan(1)
  for (const drawing of drawings) expect(String(drawing.props.source)).toContain('prefers-color-scheme: dark')
  const boxes = await band.findAll({ type: 'Box' })
  // No surface of its own round the row: the app's frame is the band's only one. The list above it is an ochre pebble.
  expect(boxes.find(found => found.key === 'band')?.props.backgroundColor).toBeUndefined()
  expect(boxes.some(found => found.props.backgroundColor === 'rgba(191,111,58,.10)' && found.props.borderStyle === 'round')).toBe(true)
  const everything = JSON.stringify([...boxes, ...(await band.findAll({ type: 'Text' })), ...drawings].map(found => found.props)).toUpperCase()
  for (const colour of ['#88C0D0', '#A3BE8C', '#EBCB8B', '#BF616A', '#7B88A1', '#4C566A', '#D8DEE9']) expect(everything).not.toContain(colour)
})

test('animated drawings are drawn interactive, the only way the desktop runs their motion', async ($, on) => {
  world(on)
  withBackdrop(on)
  await start($)
  const band = await $.ui.mount({ plugin: 'session-hud', surface: 'desktop', ...BAND(true) })
  const svgs = await band.findAll({ type: 'Svg' })
  expect(svgs.find(found => found.props.alt === 'Claude travaille')?.props.isInteractive).toBe(true)
  const moving = svgs.filter(found => found.props.alt !== 'bande de session')
  expect(moving.length).toBeGreaterThan(1)
  for (const found of moving) expect(found.props.isInteractive).toBe(true)
  // The pill does not move: it stays a plain image.
  expect(svgs.find(found => found.props.alt === 'bande de session')?.props.isInteractive).toBeUndefined()
})
