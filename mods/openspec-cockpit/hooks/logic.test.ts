import {
  describe,
  expect,
  test,
} from 'claude-code/testing'

import type { Snapshot } from '../types'
import {
  countTasks,
  cycleStep,
  formatClock,
  gateOf,
  gateWarning,
  hasRecentReviewRun,
  graphFreshness,
  handoffNextSteps,
  handoffTitle,
  isReviewToolCall,
  parseOffset,
  porcelainPaths,
  postArchiveReminder,
  statusLine,
} from './logic'

const HANDOFF = `# Passation — \`/opsx:apply\` de \`offline-catalog\`, S4 : frontend, groupes 13 à 20 (2026-10-17 11:14)

> Session suivante : lis ce document.

## Où on en est
- Change OpenSpec : \`offline-catalog\`. Étape : apply.

## Prochaine étape
1. \`graphify check-update .\` (graph frais au 2026-10-17 11:14), \`git status\`, \`docker ps\`.
2. Lire les tâches 13 à 20, le design §7.
3. Reformuler, proposer le découpage, **attendre le GO**.
4. Sur GO : workflow en mode allégé :
   - frontend-dev séquentiel 13→16 ;

## Outils suggérés
- Agents \`frontend-dev\`.
`

const MINUTE = 60 * 1000

describe('handoffs', () => {
  test('the title drops the prefix, the date and the backticks', () => {
    expect(handoffTitle(HANDOFF, 'x.md')).toBe('/opsx:apply de offline-catalog, S4 : frontend, groupes 13 à 20')
  })

  test('next steps are the numbered items of their section only, cleaned', () => {
    expect(handoffNextSteps(HANDOFF)).toEqual([
      'graphify check-update . (graph frais au 2026-10-17 11:14), git status, docker ps.',
      'Lire les tâches 13 à 20, le design §7.',
      'Reformuler, proposer le découpage, attendre le GO.',
      'Sur GO : workflow en mode allégé',
    ])
  })

  test('an English handoff gives its title and next steps', () => {
    const english = '# Handoff — S4 frontend (2026-10-17 11:14)\n\n## Next step\n1. Read tasks 13 to 20.\n2. Restate, wait for GO.\n\n## Suggested tools\n- x\n'
    expect(handoffTitle(english, 'x.md')).toBe('S4 frontend')
    expect(handoffNextSteps(english)).toEqual(['Read tasks 13 to 20.', 'Restate, wait for GO.'])
  })

  test('a handoff without the section has no next steps', () => {
    expect(handoffNextSteps('# Passation — x\n\n## Objectif\n1. nope\n')).toEqual([])
  })
})

describe('OpenSpec', () => {
  test('tasks count checked and unchecked boxes, nested ones included', () => {
    expect(countTasks('- [x] 1.1 a\n- [ ] 1.2 b\n  - [X] 1.2.1 c\n* [x] not a task\n')).toEqual({ done: 2, total: 3 })
  })

  test('the cycle step follows the artifacts and the task count', () => {
    const base = { name: 'c', lastModified: 0, hasTasks: true, hasDesignOrSpecs: true }
    expect(cycleStep(null, false)).toBe('idle')
    expect(cycleStep(null, true)).toBe('post-archive')
    expect(cycleStep({ ...base, hasTasks: false, hasDesignOrSpecs: false, tasks: { done: 0, total: 0 } }, false)).toBe('framing')
    expect(cycleStep({ ...base, hasTasks: false, tasks: { done: 0, total: 0 } }, false)).toBe('ff')
    expect(cycleStep({ ...base, tasks: { done: 96, total: 164 } }, false)).toBe('apply')
    expect(cycleStep({ ...base, tasks: { done: 164, total: 164 } }, false)).toBe('closing')
  })
})

describe('git and graph', () => {
  test('porcelain paths keep the rename target and unquote', () => {
    expect(porcelainPaths(' M a.ts\n?? "b c.ts"\nR  old.ts -> new.ts\n')).toEqual(['a.ts', 'b c.ts', 'new.ts'])
  })

  test('the graph is stale when a dirty file is newer than the build', () => {
    const graph = graphFreshness({ builtAt: 1000, headCommitAt: 500, dirtyMtimes: [900, 1500, 2000], hasPendingSemanticUpdate: false, isUsed: true })
    expect(graph).toMatchObject({ state: 'stale', newerFiles: 2, reason: '2 fichiers modifiés après le build' })
  })

  test('the graph is stale when a commit is a minute newer than the build', () => {
    expect(graphFreshness({ builtAt: 0, headCommitAt: 2 * MINUTE, dirtyMtimes: [], hasPendingSemanticUpdate: false, isUsed: true }).state).toBe('stale')
    expect(graphFreshness({ builtAt: 0, headCommitAt: 30 * 1000, dirtyMtimes: [], hasPendingSemanticUpdate: false, isUsed: true }).state).toBe('fresh')
  })

  test('a missing graph says so', () => {
    expect(graphFreshness({ builtAt: undefined, headCommitAt: 0, dirtyMtimes: [], hasPendingSemanticUpdate: false, isUsed: true }).state).toBe('missing')
  })
})

describe('gates', () => {
  const fresh = graphFreshness({ builtAt: 10, headCommitAt: 0, dirtyMtimes: [], hasPendingSemanticUpdate: false, isUsed: true })
  const stale = graphFreshness({ builtAt: 10, headCommitAt: 0, dirtyMtimes: [20], hasPendingSemanticUpdate: false, isUsed: true })

  test('commands map to their gate', () => {
    expect(gateOf('opsx:new')).toBe('new')
    expect(gateOf('openspec-apply-change')).toBe('apply')
    expect(gateOf('opsx:verify')).toBe('verify')
    expect(gateOf('opsx:bulk-archive')).toBe('archive')
    expect(gateOf('opsx:ff')).toBe(null)
  })

  test('each gate warns only when its condition is unmet', () => {
    expect(gateWarning('apply', { graph: fresh, dirtyCount: 3, hasReview: false })).toBe(null)
    expect(gateWarning('apply', { graph: stale, dirtyCount: 0, hasReview: true })).toContain('/opsx:apply')
    expect(gateWarning('verify', { graph: fresh, dirtyCount: 0, hasReview: true })).toBe(null)
    expect(gateWarning('verify', { graph: fresh, dirtyCount: 0, hasReview: false })).toContain('code-reviewer')
    expect(gateWarning('archive', { graph: stale, dirtyCount: 0, hasReview: false })).toBe(null)
    expect(gateWarning('archive', { graph: fresh, dirtyCount: 4, hasReview: true })).toContain('4 fichiers')
  })

  test('a project without graphify is never asked for a graph', () => {
    const unused = graphFreshness({ builtAt: undefined, headCommitAt: 0, dirtyMtimes: [], hasPendingSemanticUpdate: false, isUsed: false })
    expect(unused.state).toBe('unused')
    expect(gateWarning('new', { graph: unused, dirtyCount: 0, hasReview: false })).toBe(null)
    expect(gateWarning('apply', { graph: unused, dirtyCount: 0, hasReview: false })).toBe(null)
  })

  test('the post-archive reminder names the backlog and the graph only where the project has them', () => {
    expect(postArchiveReminder({ hasBacklog: true, usesGraph: true })).toBe(
      'Post-archive : 1. backlog → ✅ SHIPPED · 2. impact doc ? (sinon le dire) · 3. graphify update . (--force si suppressions/renommages)',
    )
    expect(postArchiveReminder({ hasBacklog: false, usesGraph: false })).toBe('Post-archive : 1. impact doc ? (sinon le dire)')
  })

  test('a review workflow finished within a day counts as the review', () => {
    const now = 48 * 60 * MINUTE
    const run = { id: 'r', sessionId: 's', status: 'completed' as const, agentsStarted: 3, agentsDone: 3, name: 'review-close-out' }
    expect(hasRecentReviewRun([{ ...run, finishedAt: now - 3 * MINUTE }], now)).toBe(true)
    expect(hasRecentReviewRun([{ ...run, finishedAt: now - 25 * 60 * MINUTE }], now)).toBe(false)
    expect(hasRecentReviewRun([{ ...run, name: 'apply-s5', finishedAt: now - MINUTE }], now)).toBe(false)
    expect(hasRecentReviewRun([{ ...run, status: 'running' as const, finishedAt: undefined }], now)).toBe(false)
  })

  test('a review is seen through the agent, a review skill or a workflow dispatching it', () => {
    expect(isReviewToolCall('Agent', { subagent_type: 'code-reviewer' })).toBe(true)
    expect(isReviewToolCall('Agent', { subagent_type: 'frontend-dev' })).toBe(false)
    expect(isReviewToolCall('Skill', { skill: 'code-review' })).toBe(true)
    expect(isReviewToolCall('Skill', { skill: 'review' })).toBe(true)
    expect(isReviewToolCall('Workflow', { script: "agent('x', { agentType: 'code-reviewer' })" })).toBe(true)
    expect(isReviewToolCall('Bash', { command: 'code-reviewer' })).toBe(false)
  })
})

describe('formatting', () => {
  test('clock reads in the machine zone', () => {
    expect(parseOffset('+0200\n')).toBe(120)
    expect(parseOffset('-0530')).toBe(-330)
    expect(formatClock(Date.UTC(2026, 9, 17, 9, 14), 120)).toBe('17/10 11:14')
  })

  test('the status line joins branch, change, step and graph', () => {
    const snapshot: Snapshot = {
      takenAt: 0,
      root: '/repo',
      branch: 'feat/offline-catalog',
      dirtyCount: 9,
      change: { name: 'offline-catalog', done: 96, total: 164, step: 'apply', otherCount: 0 },
      step: 'apply',
      graph: { state: 'fresh', newerFiles: 0 },
      handoff: null,
      recentHandoffs: [],
      groups: [],
      decisions: [],
      archivedChange: null,
      recentCommits: [],
      shortstat: null,
    }
    expect(statusLine(snapshot)).toBe('⎇ feat/offline-catalog ±9 │ offline-catalog 96/164 · apply │ graph ✓')
  })
})
