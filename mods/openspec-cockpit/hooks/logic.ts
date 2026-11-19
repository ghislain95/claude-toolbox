// Pure logic of the cockpit: OpenSpec heuristics, the cycle's gates and French formatting.
// No `$` here, so every function is testable under `claude plugin test`.

import type {
  ActiveChange,
  CycleStep,
  GraphFreshness,
  HandoffSummary,
  Snapshot,
  Toggles,
} from '../types'


export const DEFAULT_TOGGLES: Toggles = { status: true, gates: true, pane: true }

export const TOGGLE_NAMES: Record<string, keyof Toggles> = {
  statut: 'status',
  status: 'status',
  portes: 'gates',
  gates: 'gates',
  panneau: 'pane',
  pane: 'pane',
}

export const TOGGLE_LABELS: Record<keyof Toggles, string> = {
  status: 'statut',
  gates: 'portes',
  pane: 'panneau',
}

const MINUTE = 60 * 1000

const HOUR = 60 * MINUTE

const DAY = 24 * HOUR

export function cleanMarkdown(text: string): string {
  return text
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/\*\*([^*]+)\*\*/g, '$1')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/\s+/g, ' ')
    .trim()
}

export function plural(count: number, singular: string, pluralForm: string): string {
  return `${count} ${count === 1 ? singular : pluralForm}`
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : text.slice(0, Math.max(1, max - 1)).trimEnd() + '…'
}

export function handoffTitle(markdown: string, file: string): string {
  const heading = markdown.split('\n').find(line => line.startsWith('# '))
  if (heading === undefined) return file.replace(/\.md$/, '')
  return cleanMarkdown(
    heading
      .slice(2)
      .replace(/^Passation\s*[—–-]\s*/i, '')
      .replace(/\s*\(\d{4}-\d{2}-\d{2}[^)]*\)\s*$/, ''),
  )
}

/** The top-level items of the `## Prochaine étape` section, first line of each. */
export function handoffNextSteps(markdown: string): string[] {
  const lines = markdown.split('\n')
  const start = lines.findIndex(line => /^##\s+Prochaine/i.test(line))
  if (start === -1) return []
  const steps: string[] = []
  for (const line of lines.slice(start + 1)) {
    if (/^##\s/.test(line)) break
    const item = /^(\d+)\.\s+(.*)$/.exec(line) ?? /^[-*]\s+(.*)$/.exec(line)
    if (item === null) continue
    const body = (item.length === 3 ? item[2] : item[1]) ?? ''
    steps.push(cleanMarkdown(body).replace(/\s*:$/, ''))
  }
  return steps
}

export function parseHandoff(file: string, markdown: string, writtenAt: number): HandoffSummary {
  return {
    file,
    title: handoffTitle(markdown, file),
    writtenAt,
    nextSteps: handoffNextSteps(markdown),
  }
}

export function resumePrompt(file: string): string {
  return `Lis .claude/passation/${file}, reformule-moi l'objectif et la prochaine étape, puis attends mon GO.`
}

export type TaskCount = { done: number; total: number }

export function countTasks(tasksMarkdown: string): TaskCount {
  let done = 0
  let total = 0
  for (const line of tasksMarkdown.split('\n')) {
    const box = /^\s*- \[([ xX])\]/.exec(line)
    if (box === null) continue
    total += 1
    if (box[1] !== ' ') done += 1
  }
  return { done, total }
}

export type ChangeFacts = {
  name: string
  lastModified: number
  hasTasks: boolean
  hasDesignOrSpecs: boolean
  tasks: TaskCount
}

export function cycleStep(change: ChangeFacts | null, recentArchive: boolean): CycleStep {
  if (change === null) return recentArchive ? 'post-archive' : 'idle'
  if (!change.hasTasks || change.tasks.total === 0) {
    return change.hasDesignOrSpecs ? 'ff' : 'framing'
  }
  return change.tasks.done < change.tasks.total ? 'apply' : 'closing'
}

export function pickActiveChange(changes: ChangeFacts[], recentArchive: boolean): ActiveChange | null {
  const sorted = [...changes].sort((a, b) => b.lastModified - a.lastModified)
  const top = sorted[0]
  if (top === undefined) return null
  return {
    name: top.name,
    done: top.tasks.done,
    total: top.tasks.total,
    step: cycleStep(top, recentArchive),
    otherCount: sorted.length - 1,
  }
}

export function stepLabel(step: CycleStep): string {
  switch (step) {
    case 'framing':
      return 'cadrage'
    case 'ff':
      return 'ff'
    case 'apply':
      return 'apply'
    case 'closing':
      return 'review → verify → commit → archive'
    case 'post-archive':
      return 'post-archive'
    case 'idle':
      return 'aucun change'
  }
}

/** Paths of `git status --porcelain` lines, the target side of a rename. */
export function porcelainPaths(output: string): string[] {
  return output
    .split('\n')
    .filter(line => line.length > 3)
    .map(line => {
      const path = line.slice(3)
      const arrow = path.indexOf(' -> ')
      const target = arrow === -1 ? path : path.slice(arrow + 4)
      return target.replace(/^"(.*)"$/, '$1')
    })
}

export function graphFreshness(input: {
  builtAt: number | undefined
  headCommitAt: number | undefined
  dirtyMtimes: number[]
  hasPendingSemanticUpdate: boolean
  /** The project has graphify: a graph, a graphify-out/ folder or a graphify skill. */
  isUsed: boolean
}): GraphFreshness {
  const { builtAt, headCommitAt, dirtyMtimes, hasPendingSemanticUpdate, isUsed } = input
  if (builtAt === undefined) {
    return isUsed ? { state: 'missing', newerFiles: 0, reason: 'graphify-out/graph.json absent' } : { state: 'unused', newerFiles: 0 }
  }
  const newerFiles = dirtyMtimes.filter(mtime => mtime > builtAt).length
  if (newerFiles > 0) {
    const files = plural(newerFiles, 'fichier modifié', 'fichiers modifiés')
    return { state: 'stale', builtAt, newerFiles, reason: `${files} après le build` }
  }
  if (headCommitAt !== undefined && headCommitAt > builtAt + 60 * 1000) {
    return { state: 'stale', builtAt, newerFiles, reason: 'un commit est plus récent que le graph' }
  }
  if (hasPendingSemanticUpdate) {
    return { state: 'stale', builtAt, newerFiles, reason: 'changements non-code en attente (needs_update)' }
  }
  return { state: 'fresh', builtAt, newerFiles }
}

export function graphBadge(graph: GraphFreshness): string {
  if (graph.state === 'fresh') return 'graph ✓'
  if (graph.state === 'missing') return 'graph absent'
  return 'graph périmé'
}

/** `17/10 11:14` in the machine's zone, given its offset east of UTC in minutes. */
export function formatClock(timestamp: number, offsetMinutes: number): string {
  const local = new Date(timestamp + offsetMinutes * MINUTE)
  const two = (n: number) => String(n).padStart(2, '0')
  return `${two(local.getUTCDate())}/${two(local.getUTCMonth() + 1)} ${two(local.getUTCHours())}:${two(local.getUTCMinutes())}`
}

/** `+0200` (the output of `date +%z`) as minutes east of UTC. */
export function parseOffset(text: string): number {
  const match = /([+-])(\d{2})(\d{2})/.exec(text)
  if (match === null) return 0
  const minutes = Number(match[2]) * 60 + Number(match[3])
  return match[1] === '-' ? -minutes : minutes
}

export function progressBar(done: number, total: number, width: number): string {
  if (total <= 0) return '▱'.repeat(width)
  const filled = Math.round((done / total) * width)
  return '▰'.repeat(filled) + '▱'.repeat(width - filled)
}

export function percent(done: number, total: number): number {
  return total <= 0 ? 0 : Math.round((done / total) * 100)
}

export function statusLine(snapshot: Snapshot): string {
  const parts: string[] = []
  if (snapshot.branch !== null) {
    parts.push(`⎇ ${snapshot.branch}${snapshot.dirtyCount > 0 ? ` ±${snapshot.dirtyCount}` : ''}`)
  }
  const change = snapshot.change
  if (change !== null) {
    const more = change.otherCount > 0 ? ` (+${change.otherCount})` : ''
    const tasks = change.total > 0 ? ` ${change.done}/${change.total}` : ''
    parts.push(`${change.name}${tasks}${more} · ${stepLabel(change.step)}`)
  } else {
    parts.push(stepLabel(snapshot.step))
  }
  if (snapshot.graph.state !== 'unused') parts.push(graphBadge(snapshot.graph))
  return parts.join(' │ ')
}

export type GateKind = 'new' | 'apply' | 'verify' | 'archive'

export function gateOf(commandName: string): GateKind | null {
  if (/^(opsx:(new|propose)|openspec-(new-change|propose))$/.test(commandName)) return 'new'
  if (/^(opsx:apply|openspec-apply-change)$/.test(commandName)) return 'apply'
  if (/^(opsx:verify|openspec-verify-change)$/.test(commandName)) return 'verify'
  if (/^(opsx:(bulk-)?archive|openspec-(bulk-)?archive-change)$/.test(commandName)) return 'archive'
  return null
}

export function gateWarning(
  gate: GateKind,
  facts: { graph: GraphFreshness; dirtyCount: number; hasReview: boolean },
): string | null {
  switch (gate) {
    case 'new':
    case 'apply':
      if (facts.graph.state === 'fresh' || facts.graph.state === 'unused') return null
      return `⚠ Graph ${facts.graph.state === 'missing' ? 'absent' : 'périmé'} (${facts.graph.reason ?? '?'}) — lance graphify update . avant ${gate === 'new' ? '/opsx:new' : '/opsx:apply'}`
    case 'verify':
      return facts.hasReview
        ? null
        : '⚠ Aucun code-reviewer vu (ni cette session, ni un workflow review < 24 h) — review obligatoire avant /opsx:verify'
    case 'archive':
      if (facts.dirtyCount === 0) return null
      return `⚠ Arbre non commité (${plural(facts.dirtyCount, 'fichier', 'fichiers')}) — commit manuel avant /opsx:archive`
  }
}

/** A review workflow (its name or label says « review ») that finished less than a day ago. */
export function hasRecentReviewRun(runs: { status: string; finishedAt?: number; name?: string; label?: string }[], now: number): boolean {
  return runs.some(
    run => run.status === 'completed' && run.finishedAt !== undefined && now - run.finishedAt < 24 * 60 * 60 * 1000 && /review/i.test(`${run.name ?? ''} ${run.label ?? ''}`),
  )
}

/** A tool call that runs a code review: the code-reviewer agent, a review skill, a workflow dispatching it. */
export function isReviewToolCall(tool: string, input: Record<string, unknown>): boolean {
  if (tool === 'Agent' || tool === 'Task') return input.subagent_type === 'code-reviewer'
  if (tool === 'Skill') return typeof input.skill === 'string' && /(^|:)(code-)?review$/.test(input.skill)
  if (tool === 'Workflow') return typeof input.script === 'string' && input.script.includes('code-reviewer')
  return false
}

export function togglesLine(toggles: Toggles): string {
  return (Object.keys(TOGGLE_LABELS) as Array<keyof Toggles>)
    .map(key => `${TOGGLE_LABELS[key]} ${toggles[key] ? '✓' : '✗'}`)
    .join(' · ')
}

/** The post-archive steps as one line, without the backlog or the graph when the project has none. */
export function postArchiveReminder(input: { hasBacklog: boolean; usesGraph: boolean }): string {
  const steps = [
    ...(input.hasBacklog ? ['backlog → ✅ SHIPPED'] : []),
    'impact doc ? (sinon le dire)',
    ...(input.usesGraph ? ['graphify update . (--force si suppressions/renommages)'] : []),
  ]
  return `Post-archive : ${steps.map((step, index) => `${index + 1}. ${step}`).join(' · ')}`
}

export function summaryMarkdown(input: {
  snapshot: Snapshot
  now: number
  offsetMinutes: number
  hasReview: boolean
}): string {
  const { snapshot, now, offsetMinutes, hasReview } = input
  const lines: string[] = [`**Où j'en suis** — ${formatClock(now, offsetMinutes)}`, '']
  const dirty =
    snapshot.dirtyCount === 0 ? 'arbre propre' : `${plural(snapshot.dirtyCount, 'fichier non commité', 'fichiers non commités')}`
  lines.push(`- **Branche** \`${snapshot.branch ?? '?'}\` · ${dirty}`)
  const change = snapshot.change
  if (change !== null) {
    const more = change.otherCount > 0 ? ` (+${change.otherCount} autre(s) change(s) actif(s))` : ''
    lines.push(
      `- **Change** \`${change.name}\` · ${change.done}/${change.total} (${percent(change.done, change.total)} %) · étape **${stepLabel(change.step)}**${more}`,
    )
  } else {
    lines.push(`- **Change** aucun actif · ${stepLabel(snapshot.step)}`)
  }
  const graph = snapshot.graph
  const usesGraph = graph.state !== 'unused'
  const built = graph.builtAt !== undefined ? ` (build ${formatClock(graph.builtAt, offsetMinutes)})` : ''
  if (usesGraph) lines.push(`- **Graph** ${graph.state === 'fresh' ? '✓ frais' : `✗ ${graph.reason ?? graph.state}`}${built}`)
  const handoff = snapshot.handoff
  if (handoff !== null) {
    lines.push(
      `- **Dernière passation** ${formatClock(handoff.writtenAt, offsetMinutes)} — ${handoff.title} (\`.claude/passation/${handoff.file}\`)`,
    )
    handoff.nextSteps.slice(0, 4).forEach((step, index) => lines.push(`  ${index + 1}. ${truncate(step, 140)}`))
  }
  const gates: string[] = [
    ...(usesGraph ? [`graph ${graph.state === 'fresh' ? '✓' : '✗'}`] : []),
    `review ${hasReview ? '✓' : '✗'}`,
    snapshot.dirtyCount === 0 ? 'commit ✓' : 'commit ✗',
  ]
  lines.push(`- **Portes** ${gates.join(' · ')}`)
  return lines.join('\n')
}

/** Index in the 7-step cycle (cadrage … archive); 7 once archived, -1 with nothing in flight. */
export function stepIndexOf(step: CycleStep, hasReview: boolean, dirtyCount: number): number {
  switch (step) {
    case 'framing':
      return 0
    case 'ff':
      return 1
    case 'apply':
      return 2
    case 'closing':
      return !hasReview ? 3 : dirtyCount > 0 ? 5 : 6
    case 'post-archive':
      return 7
    case 'idle':
      return -1
  }
}

function text(value: unknown): string {
  return typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : ''
}

export function gateLevel(gate: GateKind): 'warning' | 'danger' {
  return gate === 'verify' ? 'danger' : 'warning'
}

export type ActionButton = { key: string; label: string; kind: 'fill' | 'graph' | 'copy'; value: string }

export type NextAction = {
  title: string
  detail?: string
  tone: 'running' | 'warning' | 'danger' | 'ok' | 'neutral'
  actions: ActionButton[]
}

export type RitualItem = { key: string; label: string; isDone: boolean; isAuto: boolean }

/** The post-archive ritual, auto-checked where the files tell; the backlog and graph steps only where the project has them. */
export function postArchiveRitual(input: {
  archived: { name: string; archivedAt: number; isBacklogShipped: boolean | null }
  graphBuiltAt: number | undefined
  usesGraph: boolean
  marks: Record<string, boolean>
}): RitualItem[] {
  const { archived, graphBuiltAt, usesGraph, marks } = input
  const items: RitualItem[] = []
  if (archived.isBacklogShipped !== null) {
    items.push({ key: 'backlog', label: `Backlog : ${archived.name} → ✅ SHIPPED`, isDone: archived.isBacklogShipped, isAuto: true })
  }
  items.push({ key: 'doc', label: 'Impact doc traité (ou « aucun impact doc »)', isDone: marks[`doc:${archived.name}`] === true, isAuto: false })
  if (usesGraph) {
    items.push({
      key: 'graph',
      label: 'Graph rafraîchi après l’archive (--force si suppressions)',
      isDone: graphBuiltAt !== undefined && graphBuiltAt > archived.archivedAt,
      isAuto: true,
    })
  }
  items.push({ key: 'memo', label: 'Mémoire et passation à jour', isDone: marks[`memo:${archived.name}`] === true, isAuto: false })
  return items
}

export function nextAction(input: {
  snapshot: Snapshot
  hasReview: boolean
  commitDraft: string | null
  marks: Record<string, boolean>
  now: number
}): NextAction {
  const { snapshot, hasReview, commitDraft, marks, now } = input
  const usesGraph = snapshot.graph.state !== 'unused'
  const graphStale = snapshot.graph.state === 'stale' || snapshot.graph.state === 'missing'
  const graphButton: ActionButton = { key: 'graph', label: 'graphify update .', kind: 'graph', value: '' }
  if (snapshot.step === 'post-archive' && snapshot.archivedChange !== null) {
    const ritual = postArchiveRitual({ archived: snapshot.archivedChange, graphBuiltAt: snapshot.graph.builtAt, usesGraph, marks })
    const remaining = ritual.filter(item => !item.isDone)
    if (remaining.length === 0) {
      return { title: 'Rituel post-archive bouclé', detail: 'Prochain change : voir le backlog', tone: 'ok', actions: [{ key: 'new', label: '/opsx:new', kind: 'fill', value: '/opsx:new ' }] }
    }
    const actions: ActionButton[] = []
    if (snapshot.archivedChange.isBacklogShipped === false) {
      actions.push({ key: 'backlog', label: 'Backlog SHIPPED', kind: 'fill', value: `Passe la ligne backlog de ${snapshot.archivedChange.name} en ✅ SHIPPED.` })
    }
    if (usesGraph && !(snapshot.graph.builtAt !== undefined && snapshot.graph.builtAt > snapshot.archivedChange.archivedAt)) actions.push(graphButton)
    return {
      title: `Rituel post-archive · ${ritual.length - remaining.length}/${ritual.length}`,
      detail: remaining.map(item => item.label).join(' · '),
      tone: 'warning',
      actions,
    }
  }
  const change = snapshot.change
  if (change === null) {
    return { title: 'Aucun change en cours', detail: 'Choisir le prochain dans le backlog', tone: 'neutral', actions: [{ key: 'new', label: '/opsx:new', kind: 'fill', value: '/opsx:new ' }] }
  }
  switch (change.step) {
    case 'framing':
      return {
        title: 'Cadrage : trancher les questions, puis valider le proposal',
        detail: graphStale ? 'Graph périmé : le rafraîchir avant le recon' : undefined,
        tone: graphStale ? 'warning' : 'neutral',
        actions: graphStale ? [graphButton] : [{ key: 'ff', label: '/opsx:ff', kind: 'fill', value: '/opsx:ff' }],
      }
    case 'ff':
      return { title: 'Générer les artefacts', tone: 'neutral', actions: [{ key: 'ff', label: '/opsx:ff', kind: 'fill', value: '/opsx:ff' }] }
    case 'apply': {
      if (graphStale) {
        return { title: 'Rafraîchir le graph avant de continuer', detail: snapshot.graph.reason, tone: 'warning', actions: [graphButton] }
      }
      const group = snapshot.groups.find(candidate => candidate.done < candidate.total)
      return {
        title: group !== undefined ? `Continuer l'apply · groupe ${group.number}` : "Continuer l'apply",
        detail: group !== undefined ? `${group.title} · ${group.done} sur ${group.total}` : `${change.done} tâches sur ${change.total}`,
        tone: 'neutral',
        actions: [{ key: 'apply', label: '/opsx:apply', kind: 'fill', value: '/opsx:apply' }],
      }
    }
    case 'closing': {
      if (!hasReview) {
        return {
          title: 'Lancer la review du diff',
          detail: 'code-reviewer obligatoire avant /opsx:verify',
          tone: 'danger',
          actions: [{ key: 'review', label: 'code-reviewer', kind: 'fill', value: 'Lance code-reviewer sur le diff non commité.' }],
        }
      }
      if (snapshot.dirtyCount > 0) {
        const actions: ActionButton[] = [{ key: 'verify', label: '/opsx:verify', kind: 'fill', value: '/opsx:verify' }]
        if (commitDraft !== null) actions.push({ key: 'copy', label: 'Copier le commit', kind: 'copy', value: commitDraft })
        return { title: 'Verify, puis commit manuel', detail: plural(snapshot.dirtyCount, 'fichier non commité', 'fichiers non commités'), tone: 'warning', actions }
      }
      return { title: 'Archiver le change', tone: 'neutral', actions: [{ key: 'archive', label: '/opsx:archive', kind: 'fill', value: '/opsx:archive' }] }
    }
    default:
      return { title: stepLabel(change.step), tone: 'neutral', actions: [] }
  }
}

