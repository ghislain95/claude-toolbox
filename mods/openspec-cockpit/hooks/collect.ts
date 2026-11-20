// Gathers the cockpit's snapshot from the repository: git, the OpenSpec folders, graphify-out and
// the handoff folders (.claude/handoff, .claude/passation). Read-only.

import type { EngineInterface, FsEntry } from 'claude-code'

import type { Decision, HandoffSummary, Snapshot, TaskGroup } from '../types'
import { type ChangeFacts, countTasks, cycleStep, graphFreshness, parseHandoff, pickActiveChange, porcelainPaths } from './logic'
import { handoffDecisions, ownerDecisions, taskGroups } from './parse'


export type Context = {
  root: string
  home: string
  git: string
  offsetMinutes: number
}

const DAY = 24 * 60 * 60 * 1000
/** Handoff folders, newest convention first. */
const HANDOFF_DIRS = ['.claude/handoff', '.claude/passation']

const GIT_CANDIDATES = ['git', '/opt/homebrew/bin/git', '/usr/local/bin/git', '/usr/bin/git']

export async function resolveGit($: EngineInterface): Promise<string> {
  for (const candidate of GIT_CANDIDATES) {
    try {
      const result = await $.process.run([candidate, '--version'], { timeoutMs: 3000 })
      if (result.exitCode === 0) return candidate
    } catch {
      // try the next one
    }
  }
  return 'git'
}

async function run($: EngineInterface, argv: string[], cwd: string): Promise<string | undefined> {
  try {
    const result = await $.process.run(argv, { cwd, timeoutMs: 10000 })
    return result.exitCode === 0 ? result.stdout : undefined
  } catch {
    return undefined
  }
}

async function mtimeOf($: EngineInterface, path: string): Promise<number | undefined> {
  try {
    return (await $.fs.stat(path)).mtimeMs
  } catch {
    return undefined
  }
}

async function readText($: EngineInterface, path: string): Promise<string | undefined> {
  try {
    return (await $.fs.read(path)) as string
  } catch {
    return undefined
  }
}

export async function collectGit($: EngineInterface, context: Context) {
  const { root, git } = context
  const [branchOut, statusOut, headOut, builtAt, hasPendingSemanticUpdate, logOut, statOut, hasGraphifyFolder, hasGraphifySkill] = await Promise.all([
    run($, [git, 'rev-parse', '--abbrev-ref', 'HEAD'], root),
    run($, [git, 'status', '--porcelain'], root),
    run($, [git, 'log', '-1', '--format=%ct'], root),
    mtimeOf($, `${root}/graphify-out/graph.json`),
    $.fs.exists(`${root}/graphify-out/needs_update`).catch(() => false),
    run($, [git, 'log', '-20', '--format=%h%x09%s'], root),
    run($, [git, 'diff', '--shortstat', 'HEAD'], root),
    $.fs.exists(`${root}/graphify-out`).catch(() => false),
    $.fs.exists(`${root}/.claude/skills/graphify`).catch(() => false),
  ])
  const paths = porcelainPaths(statusOut ?? '').filter(path => !path.startsWith('graphify-out/'))
  const dirtyMtimes = (
    await Promise.all(paths.slice(0, 400).map(path => mtimeOf($, `${root}/${path.replace(/\/$/, '')}`)))
  ).filter((mtime): mtime is number => mtime !== undefined)
  const headSeconds = Number((headOut ?? '').trim())
  return {
    branch: branchOut?.trim() || null,
    dirtyCount: paths.length,
    recentCommits: (logOut ?? '')
      .split('\n')
      .filter(line => line.includes('\t'))
      .map(line => ({ hash: line.split('\t')[0] ?? '', subject: line.split('\t').slice(1).join('\t') })),
    shortstat: statOut?.trim() || null,
    graph: graphFreshness({
      builtAt,
      headCommitAt: Number.isFinite(headSeconds) && headSeconds > 0 ? headSeconds * 1000 : undefined,
      dirtyMtimes,
      hasPendingSemanticUpdate,
      isUsed: builtAt !== undefined || hasGraphifyFolder || hasGraphifySkill,
    }),
  }
}

async function collectChanges($: EngineInterface, root: string, now: number) {
  const changesDir = `${root}/openspec/changes`
  let entries: Awaited<ReturnType<EngineInterface['fs']['list']>> = []
  try {
    entries = await $.fs.list(changesDir)
  } catch {
    return { change: null, step: 'idle' as const, groups: [], decisions: [], archivedChange: null }
  }
  const archived = await $.fs.list(`${changesDir}/archive`).catch(() => [])
  const newestArchive = Math.max(0, ...archived.map(entry => entry.mtimeMs))
  const recentArchive = now - newestArchive < DAY
  const facts: ChangeFacts[] = []
  for (const entry of entries) {
    if (entry.kind !== 'dir' || entry.name === 'archive') continue
    const dir = `${changesDir}/${entry.name}`
    const files = await $.fs.list(dir).catch(() => [])
    const names = new Set(files.map(file => file.name))
    const tasks = names.has('tasks.md') ? await readText($, `${dir}/tasks.md`) : undefined
    facts.push({
      name: entry.name,
      lastModified: Math.max(entry.mtimeMs, ...files.map(file => file.mtimeMs)),
      hasTasks: tasks !== undefined,
      hasDesignOrSpecs: names.has('design.md') || names.has('specs'),
      tasks: countTasks(tasks ?? ''),
    })
  }
  const change = pickActiveChange(facts, recentArchive)
  let groups: TaskGroup[] = []
  let decisions: Decision[] = []
  if (change !== null) {
    const dir = `${changesDir}/${change.name}`
    const [tasks, owner] = await Promise.all([readText($, `${dir}/tasks.md`), readText($, `${dir}/verification/owner-points.md`)])
    groups = taskGroups(tasks ?? '')
    decisions = ownerDecisions(owner ?? '')
  }
  const newest = archived.filter(entry => entry.kind === 'dir').sort((a, b) => b.mtimeMs - a.mtimeMs)[0]
  const archivedChange =
    newest !== undefined && now - newest.mtimeMs < 3 * DAY
      ? {
          name: newest.name.replace(/^\d{4}-\d{2}-\d{2}-/, ''),
          archivedAt: newest.mtimeMs,
          isBacklogShipped: await isShipped($, root, newest.name.replace(/^\d{4}-\d{2}-\d{2}-/, '')),
        }
      : null
  return { change, step: change?.step ?? cycleStep(null, recentArchive), groups, decisions, archivedChange }
}

/** Whether the backlog marks the change SHIPPED; null when the project has no backlog file. */
async function isShipped($: EngineInterface, root: string, changeName: string): Promise<boolean | null> {
  const backlog = (await backlogFiles($, root, 0))[0] ?? (await backlogFiles($, `${root}/docs`, 3))[0]
  if (backlog === undefined) return null
  const out = await run($, ['/usr/bin/grep', '-F', changeName, backlog], root)
  return (out ?? '').split('\n').some(line => /SHIPPED/.test(line))
}

function isBacklogFile(entry: FsEntry): boolean {
  return entry.kind === 'file' && /backlog/i.test(entry.name) && entry.name.endsWith('.md')
}

/** The `*backlog*.md` files in a folder, then in its subfolders down to `depth` levels (archives skipped), sorted. */
async function backlogFiles($: EngineInterface, dir: string, depth: number): Promise<string[]> {
  const entries = await $.fs.list(dir).catch((): FsEntry[] => [])
  const found = entries.filter(isBacklogFile).map(entry => `${dir}/${entry.name}`).sort()
  if (depth === 0) return found
  const folders = entries.filter(entry => entry.kind === 'dir' && entry.name !== 'archive' && !entry.name.startsWith('.'))
  const nested = await Promise.all(folders.map(entry => backlogFiles($, `${dir}/${entry.name}`, depth - 1)))
  return [...found, ...nested.flat().sort()]
}

async function collectHandoffs($: EngineInterface, root: string) {
  // `.claude/handoff` since handoff 0.2.0; `.claude/passation` holds the files older versions wrote.
  const listed = await Promise.all(
    HANDOFF_DIRS.map(async dir =>
      (await $.fs.list(`${root}/${dir}`).catch((): FsEntry[] => []))
        .filter(entry => entry.kind === 'file' && entry.name.endsWith('.md'))
        .map(entry => ({ dir, entry })),
    ),
  )
  const files = listed
    .flat()
    .sort((a, b) => b.entry.name.localeCompare(a.entry.name))
    .slice(0, 5)
  const handoffs: HandoffSummary[] = []
  let decisions: Decision[] = []
  for (const { dir, entry } of files) {
    const text = await readText($, `${root}/${dir}/${entry.name}`)
    if (text === undefined) continue
    if (handoffs.length === 0) decisions = handoffDecisions(text)
    handoffs.push(parseHandoff(dir, entry.name, text, entry.mtimeMs))
  }
  return { handoffs, decisions }
}

export async function collectSnapshot($: EngineInterface, context: Context): Promise<Snapshot> {
  const now = await $.clock.now()
  const [gitFacts, changes, handoffFacts] = await Promise.all([
    collectGit($, context),
    collectChanges($, context.root, now),
    collectHandoffs($, context.root),
  ])
  return {
    takenAt: now,
    root: context.root,
    branch: gitFacts.branch,
    dirtyCount: gitFacts.dirtyCount,
    change: changes.change,
    step: changes.step,
    graph: gitFacts.graph,
    handoff: handoffFacts.handoffs[0] ?? null,
    recentHandoffs: handoffFacts.handoffs,
    groups: changes.groups,
    decisions: [...changes.decisions, ...handoffFacts.decisions],
    archivedChange: changes.archivedChange,
    recentCommits: gitFacts.recentCommits,
    shortstat: gitFacts.shortstat,
  }
}

