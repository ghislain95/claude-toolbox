export type CycleStep = 'framing' | 'ff' | 'apply' | 'closing' | 'post-archive' | 'idle'

export type ActiveChange = {
  name: string
  done: number
  total: number
  step: CycleStep
  otherCount: number
}

export type GraphFreshness = {
  /** `unused`: the project has no graphify (no graph, no graphify-out/, no graphify skill), so nothing about the graph is shown. */
  state: 'fresh' | 'stale' | 'missing' | 'unused'
  builtAt?: number
  newerFiles: number
  reason?: string
}

export type HandoffSummary = {
  /** Folder of the file, relative to the project root: `.claude/handoff`, or `.claude/passation` for files written before the rename. */
  dir: string
  file: string
  title: string
  writtenAt: number
  nextSteps: string[]
}

export type TaskGroup = { number: string; title: string; done: number; total: number }

export type Decision = {
  key: string
  text: string
  status: 'owner' | 'agent' | 'open' | 'informed'
  source: 'owner-points' | 'passation'
}

export type Snapshot = {
  takenAt: number
  root: string
  branch: string | null
  dirtyCount: number
  change: ActiveChange | null
  step: CycleStep
  graph: GraphFreshness
  handoff: HandoffSummary | null
  recentHandoffs: HandoffSummary[]
  groups: TaskGroup[]
  decisions: Decision[]
  /** `isBacklogShipped` is null when the project has no backlog file. */
  archivedChange: { name: string; archivedAt: number; isBacklogShipped: boolean | null } | null
  recentCommits: { hash: string; subject: string }[]
  shortstat: string | null
}

export type Toggles = {
  status: boolean
  gates: boolean
  pane: boolean
}

export type GateAlert = { text: string; level: 'warning' | 'danger' | 'info' }

/**
 * The background tasks the pane shows: the project's workflow runs and this session's agents (gathered every
 * 30 seconds), and the services Claude left running (from each turn's end). Shaped as hooks/shared/ draws them.
 */
export type CockpitBackground = { runs: unknown[]; agents: unknown[]; services: unknown[]; takenAt: number }

declare module 'claude-code' {
  interface PluginState {
    'openspec-cockpit': {
      snapshot: Snapshot | null
      toggles: Toggles
      hasReview: boolean
      gateAlerts: StateFamily<GateAlert | null>
      collapsed: Record<string, boolean>
      commitDraft: string | null
      ritualMarks: Record<string, boolean>
      busy: string | null
      background: CockpitBackground | null
    }
  }
}
