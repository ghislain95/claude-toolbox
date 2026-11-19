import {
  describe,
  expect,
  test,
} from 'claude-code/testing'

import type { Snapshot } from '../types'

import {
  nextAction,
  postArchiveRitual,
} from './logic'
import {
  handoffDecisions,
  ownerDecisions,
  taskGroups,
} from './parse'

describe('OpenSpec files', () => {
  test('task groups count the boxes under each numbered section, titles without the agent note', () => {
    const tasks = '# Tasks\n\n## 13. Frontend — config (agent: frontend-dev)\n- [x] 13.1 a\n- [ ] 13.2 b\n## 14. Contract\n- [x] 14.1\n## Notes\n- [ ] not a task of 14\n'
    expect(taskGroups(tasks)).toEqual([
      { number: '13', title: 'Frontend — config', done: 1, total: 2 },
      { number: '14', title: 'Contract', done: 1, total: 1 },
    ])
  })

  test('owner points read decided, informed and deferred rows', () => {
    const table = [
      '| # | Point | Decision | Date |',
      '|---|---|---|---|',
      '| 8 | fake-store pin | **Option A** — keep the pin | 2026-10-12 |',
      '| 22 | Amendments | **Informed** — whole seconds | 2026-10-14 |',
      '| 7 | Product copy | Deferred: validated in group 18 | 2026-10-12 |',
    ].join('\n')
    expect(ownerDecisions(table).map(decision => [decision.key, decision.status])).toEqual([
      ['#8', 'owner'],
      ['#22', 'informed'],
      ['#7', 'open'],
    ])
    expect(ownerDecisions(table)[0]?.text).toBe('fake-store pin → Option A')
  })

  test('handoff decisions: ✅ owner, 🟡 agent with its nested items, open questions', () => {
    const handoff = [
      '## Décisions prises',
      '- Cadre S3 : zéro appel cloud — ✅ validée par l’utilisateur.',
      '- Choix des agents, pas confirmés — 🟡 :',
      '  - le publieur seulement avec CATALOG_JOB=publish ;',
      '## Questions ouvertes',
      '- Découpage : 13-20 en une session ?',
      '## Prochaine étape',
      '- not a decision',
    ].join('\n')
    expect(handoffDecisions(handoff).map(decision => decision.status)).toEqual(['owner', 'agent', 'open'])
    expect(handoffDecisions(handoff)[1]?.text).toBe('le publieur seulement avec CATALOG_JOB=publish ;')
  })
})

describe('next action', () => {
  const base: Snapshot = {
    takenAt: 0,
    root: '/repo',
    branch: 'feat/x',
    dirtyCount: 0,
    change: { name: 'x', done: 4, total: 10, step: 'apply', otherCount: 0 },
    step: 'apply',
    graph: { state: 'fresh', newerFiles: 0, builtAt: 10 },
    handoff: null,
    recentHandoffs: [],
    groups: [
      { number: '1', title: 'Back', done: 3, total: 3 },
      { number: '2', title: 'Front', done: 1, total: 7 },
    ],
    decisions: [],
    archivedChange: null,
    recentCommits: [],
    shortstat: null,
  }
  const ask = (snapshot: Snapshot, hasReview = false, commitDraft: string | null = null) =>
    nextAction({ snapshot, hasReview, commitDraft, marks: {}, now: 100 })

  test('apply: a stale graph first, then the current group', () => {
    expect(ask({ ...base, graph: { state: 'stale', newerFiles: 2, reason: '2 fichiers', builtAt: 1 } }).actions[0]?.kind).toBe('graph')
    expect(ask(base)).toMatchObject({ title: "Continuer l'apply · groupe 2", detail: 'Front · 1 sur 7' })
  })

  test('closing walks review, verify with the commit copy, then archive', () => {
    const closing: Snapshot = { ...base, change: { ...base.change!, done: 10, step: 'closing' }, step: 'closing', dirtyCount: 3 }
    expect(ask(closing).tone).toBe('danger')
    expect(ask(closing, true, 'feat(x): y').actions.map(action => action.kind)).toEqual(['fill', 'copy'])
    expect(ask({ ...closing, dirtyCount: 0 }, true).actions[0]?.value).toBe('/opsx:archive')
  })

  test('post-archive counts the ritual, auto-checking the backlog and the graph', () => {
    const archived = { name: 'x', archivedAt: 50, isBacklogShipped: true }
    const ritual = postArchiveRitual({ archived, graphBuiltAt: 40, usesGraph: true, marks: { 'doc:x': true } })
    expect(ritual.map(item => item.isDone)).toEqual([true, true, false, false])
    const action = ask({ ...base, change: null, step: 'post-archive', archivedChange: archived, graph: { state: 'fresh', newerFiles: 0, builtAt: 40 } })
    expect(action.title).toBe('Rituel post-archive · 1/4')
    expect(action.actions.map(item => item.kind)).toEqual(['graph'])
  })

  test('without a backlog file or graphify, the ritual keeps only the doc and memory steps', () => {
    const archived = { name: 'x', archivedAt: 50, isBacklogShipped: null }
    const ritual = postArchiveRitual({ archived, graphBuiltAt: undefined, usesGraph: false, marks: {} })
    expect(ritual.map(item => item.key)).toEqual(['doc', 'memo'])
    const action = ask({ ...base, change: null, step: 'post-archive', archivedChange: archived, graph: { state: 'unused', newerFiles: 0 } })
    expect(action.title).toBe('Rituel post-archive · 0/2')
    expect(action.actions).toEqual([])
  })
})

