// Shared by the mods of this repository: the background tasks drawn (services, workflow runs, this session's
// agents), for background-tasks' own pane and for the cockpit's section. Compact: one line per thing, two
// when it has figures; a running workflow shows its phases, the running one with its agents.
// Copied into each mod's hooks/shared/ by scripts/sync-shared.sh: edit it here, then run the script.

import type { EngineInterface, RenderChildren, RenderInput } from 'claude-code'

import type { SessionAgent } from './collect-workflows'
import { formatAgo, formatDuration, formatTokens, plural, truncate } from './format'
import type { Service } from './services'
import { NATIVE, bar as barSvg, dot, surface } from './sienne'
import { type PhaseRow, type RunAgent, type WorkflowRun, agentFiguresLine, phaseRows, runName } from './workflows'

/** The project's workflow runs and this session's agents, gathered every 30 seconds. */
export type BackgroundSnapshot = { runs: WorkflowRun[]; agents: SessionAgent[]; takenAt: number }

/** The desktop's elements (Svg included): the rich pane is drawn there and in VS Code. */
type Elements = Extract<ReturnType<EngineInterface['ui']['resolve']>, { Svg: unknown }>

/** The desktop lays a pane out at about 8.9 CSS pixels per column (measured on screen). */
const PIXELS_PER_COLUMN = 8.9

/** The run's tokens: its agents' contexts added up, as Claude Code's task list does. */
function runTokens(run: WorkflowRun): number {
  return (run.agents ?? []).reduce((sum, agent) => sum + (agent.tokens ?? 0), 0)
}

function sectionTitle(els: Elements, key: string, title: string, meta: string | null): RenderChildren {
  const { Box, Text } = els
  return (
    <Box key={key} flexDirection="row" gap="sm" alignItems="center">
      <Text size="footnote" weight="semibold">
        {title}
      </Text>
      {meta !== null && (
        <Text size="caption" dimColor>
          {meta}
        </Text>
      )}
    </Box>
  )
}

/** A thing at work or done: a dot, its name, what it is, how long; figures on a second line. */
function thingRow(
  els: Elements,
  key: string,
  input: { name: string; kind?: string; isRunning: boolean; time: string; figures?: string; isDim?: boolean },
): RenderChildren {
  const { Box, Text, Svg } = els
  return (
    <Box key={key} flexDirection="column">
      <Box flexDirection="row" gap="sm" alignItems="center">
        <Svg key={`${key}-dot`} alt={input.isRunning ? 'en cours' : 'terminé'} source={dot(input.isRunning ? 'running' : 'ok', { pulse: input.isRunning })} width={12} height={12} isInteractive />
        <Box flexGrow={1} flexShrink={1} minWidth={0} flexDirection="row" gap="xs">
          <Text wrap="truncate-end" weight={input.isRunning ? 'medium' : 'regular'} dimColor={input.isDim === true}>
            {input.name}
          </Text>
          {input.kind !== undefined && (
            <Text size="caption" dimColor wrap="truncate-end">
              {input.kind}
            </Text>
          )}
        </Box>
        <Text size="caption" dimColor tabular>
          {input.time}
        </Text>
      </Box>
      {input.figures !== undefined && input.figures !== '' && (
        <Box paddingLeft={3}>
          <Text size="caption" dimColor wrap="truncate-end">
            {input.figures}
          </Text>
        </Box>
      )}
    </Box>
  )
}

function serviceRows(els: Elements, services: readonly Service[], now: number): RenderChildren {
  return services.map(service =>
    thingRow(els, `service-${service.id}`, {
      name: truncate(service.label, 60),
      kind: service.port !== null ? `:${service.port}` : undefined,
      isRunning: true,
      time: formatDuration(now - service.firstSeenAt),
      figures: truncate(service.command, 90),
    }),
  )
}

function agentRow(els: Elements, key: string, agent: RunAgent, now: number): RenderChildren {
  const isRunning = agent.state === 'running'
  return thingRow(els, key, {
    name: agent.label,
    kind: agent.type,
    isRunning,
    isDim: !isRunning,
    time:
      agent.startedAt === undefined ? (isRunning ? 'en cours' : '✓') : formatDuration((isRunning ? now : agent.lastActivityAt ?? now) - agent.startedAt),
    figures: agentFiguresLine(agent),
  })
}

function phaseLine(els: Elements, run: WorkflowRun, row: PhaseRow, now: number): RenderChildren {
  const { Box, Text, Svg } = els
  const key = `run-${run.id}-phase-${row.title}`
  const agents = (run.agents ?? []).filter(agent => agent.phase === row.title)
  const source =
    row.state === 'upcoming' ? dot('muted', { hollow: true }) : dot(row.state === 'running' ? 'running' : row.state === 'done' ? 'ok' : 'muted', { pulse: row.state === 'running' })
  return (
    <Box key={key} flexDirection="column" gap="xs">
      <Box flexDirection="row" gap="sm" alignItems="center">
        <Svg key={`${key}-dot`} alt={row.state} source={source} width={12} height={12} isInteractive />
        <Box flexGrow={1} flexShrink={1} minWidth={0} flexDirection="row" gap="sm">
          <Text
            wrap="truncate-end"
            weight={row.state === 'running' ? 'semibold' : 'regular'}
            color={row.state === 'running' ? NATIVE.accent : undefined}
            dimColor={row.state !== 'running'}
          >
            {row.title}
          </Text>
          {row.state !== 'running' && row.detail !== undefined && (
            <Text size="caption" dimColor wrap="truncate-end">
              {row.detail}
            </Text>
          )}
        </Box>
        <Text size="caption" dimColor tabular>
          {row.started > 0 ? `${row.done}/${row.started}` : row.state === 'upcoming' ? 'à venir' : ''}
        </Text>
      </Box>
      {row.state === 'running' && (
        <Box flexDirection="column" gap="xs" paddingLeft={3}>
          {row.detail !== undefined && (
            <Text size="caption" dimColor wrap="wrap">
              {row.detail}
            </Text>
          )}
          {agents.slice(-4).map(agent => agentRow(els, `${key}-agent-${agent.id}`, agent, now))}
        </Box>
      )}
    </Box>
  )
}

function liveRunCard(els: Elements, run: WorkflowRun, width: number, now: number): RenderChildren {
  const { Box, Text, Svg } = els
  const rows = phaseRows(run)
  const done = rows.filter(row => row.state === 'done' || row.state === 'skipped').length
  const tokens = runTokens(run)
  const isRunning = run.status === 'running'
  const meta = [
    plural(run.agentsStarted, 'agent', 'agents'),
    tokens > 0 ? `${formatTokens(tokens)} tokens` : null,
    run.startedAt !== undefined ? formatDuration(now - run.startedAt) : null,
    run.status === 'silent' && run.lastActivityAt !== undefined ? `muet ${formatDuration(now - run.lastActivityAt)}` : null,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ')
  const bar = rows.length > 0 ? barSvg(width - 28, (done + 0.5) / rows.length, { id: `run-${run.id}` }) : null
  return (
    <Box key={`run-${run.id}`} flexDirection="column" gap="sm" {...surface(isRunning ? 'ochre' : 'stone')} paddingX="md" paddingY="md">
      <Box flexDirection="row" gap="sm" alignItems="center">
        <Box flexGrow={1} flexShrink={1} minWidth={0}>
          <Text weight="semibold" wrap="truncate-end">
            {runName(run)}
          </Text>
        </Box>
        <Text size="caption" dimColor tabular>
          {meta}
        </Text>
      </Box>
      {run.description !== undefined && (
        <Text size="caption" dimColor wrap="wrap">
          {truncate(run.description, 200)}
        </Text>
      )}
      {bar !== null && <Svg key={`run-${run.id}-bar`} alt={`${done} phases sur ${rows.length}`} source={bar} width={Math.max(40, Math.round(width - 28))} height={5} />}
      {rows.map(row => phaseLine(els, run, row, now))}
      {rows.length === 0 && (run.agents ?? []).slice(-4).map(agent => agentRow(els, `run-${run.id}-agent-${agent.id}`, agent, now))}
      {run.sessionTitle !== undefined && (
        <Text size="caption" dimColor wrap="truncate-end">
          {run.sessionTitle}
        </Text>
      )}
    </Box>
  )
}

function finishedRunRow(els: Elements, run: WorkflowRun, now: number): RenderChildren {
  const { Box, Text, Svg } = els
  const facts = [
    run.agentsStarted > 0 ? plural(run.agentsStarted, 'agent', 'agents') : null,
    run.durationMs !== undefined ? formatDuration(run.durationMs) : null,
    run.finishedAt !== undefined ? formatAgo(now - run.finishedAt) : null,
  ]
    .filter((part): part is string => part !== null)
    .join(' · ')
  return (
    <Box key={`done-${run.id}`} flexDirection="row" gap="sm" alignItems="center">
      <Svg key={`done-${run.id}-dot`} alt={run.status} source={dot(run.status === 'failed' ? 'danger' : 'ok')} width={12} height={12} />
      <Box flexGrow={1} flexShrink={1} minWidth={0}>
        <Text wrap="truncate-end" dimColor>
          {runName(run)}
        </Text>
      </Box>
      <Text size="caption" dimColor tabular>
        {facts}
      </Text>
    </Box>
  )
}

function sessionAgentRow(els: Elements, agent: SessionAgent, now: number): RenderChildren {
  return thingRow(els, `agent-${agent.id}`, {
    name: agent.description !== '' ? agent.description : agent.type,
    kind: agent.description !== '' ? agent.type : undefined,
    isRunning: true,
    time: agent.startedAt !== undefined ? formatDuration(now - agent.startedAt) : 'en cours',
    figures: agentFiguresLine(agent),
  })
}

export type PaneData = { snapshot: BackgroundSnapshot | null; services: readonly Service[]; now: number }

export function renderPane($: EngineInterface, e: RenderInput<'Pane', 'desktop' | 'vscode'>, data: PaneData) {
  const els = $.ui.resolve(e)
  const { Box, Text, Svg } = els
  const { snapshot, services, now } = data
  const width = Math.max(240, Math.floor(e.props.bodyColumns * PIXELS_PER_COLUMN) - 4)
  const runs = snapshot?.runs ?? []
  const liveRuns = runs.filter(run => run.status === 'running' || run.status === 'silent')
  const doneRuns = runs.filter(run => run.status === 'completed' || run.status === 'failed').slice(0, 4)
  const agents = snapshot?.agents ?? []
  const isEmpty = services.length === 0 && liveRuns.length === 0 && agents.length === 0
  return (
    <Box flexDirection="column" gap="lg">
      {isEmpty && (
        <Box key="empty" flexDirection="row" gap="sm" alignItems="center">
          <Svg key="empty-dot" alt="au repos" source={dot('muted')} width={12} height={12} />
          <Text dimColor>Rien ne tourne en arrière-plan.</Text>
        </Box>
      )}
      {services.length > 0 && (
        <Box key="services" flexDirection="column" gap="sm">
          {sectionTitle(els, 'services-title', 'Services', `${services.length}`)}
          {serviceRows(els, services, now)}
        </Box>
      )}
      {liveRuns.length > 0 && (
        <Box key="runs" flexDirection="column" gap="sm">
          {sectionTitle(els, 'runs-title', 'Workflows', plural(liveRuns.length, 'en cours', 'en cours'))}
          {liveRuns.map(run => liveRunCard(els, run, width, now))}
        </Box>
      )}
      {agents.length > 0 && (
        <Box key="agents" flexDirection="column" gap="sm">
          {sectionTitle(els, 'agents-title', 'Agents de cette session', `${agents.length}`)}
          {agents.map(agent => sessionAgentRow(els, agent, now))}
        </Box>
      )}
      {doneRuns.length > 0 && (
        <Box key="finished" flexDirection="column" gap="sm">
          {sectionTitle(els, 'finished-title', 'Terminés récemment', null)}
          {doneRuns.map(run => finishedRunRow(els, run, now))}
        </Box>
      )}
    </Box>
  )
}

/**
 * The background tasks in a few lines, for the cockpit's section: a service with its port, a workflow with its
 * phase, its agents and its time and a soft bar under it, an agent of this session; nothing more.
 */
export function renderCompact($: EngineInterface, e: RenderInput<'Pane', 'desktop' | 'vscode'>, data: PaneData) {
  const els = $.ui.resolve(e)
  const { Box, Text, Svg } = els
  const { snapshot, services, now } = data
  const width = Math.max(240, Math.floor(e.props.bodyColumns * PIXELS_PER_COLUMN) - 4)
  const runs = snapshot?.runs ?? []
  const liveRuns = runs.filter(run => run.status === 'running' || run.status === 'silent')
  const doneRuns = runs.filter(run => run.status === 'completed' || run.status === 'failed').slice(0, 2)
  const agents = snapshot?.agents ?? []
  const line = (key: string, isRunning: boolean, name: string, middle: RenderChildren, right: string, isDim = false) => (
    <Box key={key} flexDirection="row" gap="sm" alignItems="center">
      <Svg key={`${key}-dot`} alt={isRunning ? 'en cours' : 'actif'} source={dot(isRunning ? 'running' : 'ok', { pulse: isRunning })} width={12} height={12} isInteractive={isRunning} />
      <Box flexGrow={1} flexShrink={1} minWidth={0}>
        <Text wrap="truncate-end" dimColor={isDim}>
          {name}
        </Text>
      </Box>
      {middle}
      <Text size="caption" dimColor tabular>
        {right}
      </Text>
    </Box>
  )
  // Nothing running: the section's own meta says so (« rien ne tourne »), no line repeats it.
  if (services.length === 0 && liveRuns.length === 0 && agents.length === 0 && doneRuns.length === 0) return null
  return (
    <Box flexDirection="column" gap="xs">
      {services.map(service =>
        line(
          `service-${service.id}`,
          false,
          truncate(service.label, 60),
          service.port !== null ? (
            <Text key={`service-${service.id}-port`} mono size="footnote" tabular>
              :{service.port}
            </Text>
          ) : null,
          'service',
        ),
      )}
      {liveRuns.map(run => {
        const rows = phaseRows(run)
        const done = rows.filter(row => row.state === 'done' || row.state === 'skipped').length
        const facts = [run.phase, run.agentsStarted > 0 ? plural(run.agentsStarted, 'agent', 'agents') : null].filter((part): part is string => part !== undefined && part !== null).join(' · ')
        return (
          <Box key={`run-${run.id}`} flexDirection="column" gap="xs">
            {line(
              `run-${run.id}-line`,
              true,
              runName(run),
              facts !== '' ? (
                <Text key={`run-${run.id}-facts`} size="caption" dimColor wrap="truncate-end">
                  {facts}
                </Text>
              ) : null,
              run.startedAt !== undefined ? formatDuration(now - run.startedAt) : '',
            )}
            {rows.length > 0 && (
              <Box paddingLeft={2}>
                <Svg key={`run-${run.id}-bar`} alt={`${done} phases sur ${rows.length}`} source={barSvg(width - 24, (done + 0.5) / rows.length, { id: `run-${run.id}` })} width={Math.max(40, Math.round(width - 24))} height={5} />
              </Box>
            )}
          </Box>
        )
      })}
      {agents.map(agent =>
        line(`agent-${agent.id}`, true, agent.description !== '' ? agent.description : agent.type, null, agent.startedAt !== undefined ? formatDuration(now - agent.startedAt) : 'en cours'),
      )}
      {doneRuns.map(run =>
        line(`done-${run.id}`, false, runName(run), null, run.finishedAt !== undefined ? formatAgo(now - run.finishedAt) : run.status === 'failed' ? 'échoué' : 'terminé', true),
      )}
    </Box>
  )
}

/** The pane as text, for the terminal. */
export function renderTextPane($: EngineInterface, e: RenderInput<'Pane'>, data: PaneData) {
  const { Box, Text } = $.ui.resolve(e)
  const { snapshot, services, now } = data
  const runs = snapshot?.runs ?? []
  const lines = [
    ...services.map(service => `● ${service.label}${service.port !== null ? ` :${service.port}` : ''} · ${formatDuration(now - service.firstSeenAt)}`),
    ...runs.map(run => `${run.status === 'running' ? '▶' : run.status === 'silent' ? '⏸' : run.status === 'failed' ? '✗' : '✓'} ${runName(run)}`),
    ...(snapshot?.agents ?? []).map(agent => `● ${agent.description || agent.type}`),
  ]
  return (
    <Box flexDirection="column">
      {lines.length === 0 ? <Text dimColor>Rien ne tourne en arrière-plan.</Text> : lines.map((line, index) => <Text key={`line-${index}`} wrap="truncate-end">{line}</Text>)}
    </Box>
  )
}
