// The cockpit pane: a Terre de Sienne dashboard on the desktop, plain text in a terminal.
// It opens on a large ring (the change's tasks) and the cycle's timeline, then the next action, then the
// change's groups, decisions, the post-archive ritual and the handoff.

import type { EngineInterface, RenderChildren, RenderInput } from 'claude-code'

import type { CockpitBackground, Snapshot } from '../types'
import { fillPrompt, runAction, toggleRitual, toggleSection } from './actions'
import { type NextAction, formatClock, nextAction, percent, plural, postArchiveRitual, progressBar, resumePrompt, stepIndexOf, stepLabel, truncate } from './logic'
import { type BackgroundSnapshot, renderCompact as renderBackground, renderTextPane as renderBackgroundText } from './shared/background-view'
import type { Service } from './shared/services'
import { type Family, GALET, NATIVE, type Tone, bar, chip, dot, pills, ring, surface, timeline } from './shared/sienne'

export type PaneData = {
  shot: Snapshot
  /** The background tasks: workflow runs, this session's agents, services; null until first collected. */
  background: CockpitBackground | null
  review: boolean
  collapsedSections: Record<string, boolean>
  commitDraft: string | null
  marks: Record<string, boolean>
  busyWith: string | null
  root: string
  home: string
  offset: number
  now: number
  onRefresh: () => void
}

/** The cycle's steps, in order, as the timeline names them. */
export const CYCLE = ['cadrage', 'ff', 'apply', 'review', 'verify', 'commit', 'archive'] as const

const TONE_COLOR: Record<NextAction['tone'], string> = {
  running: 'claude',
  warning: 'warning',
  danger: 'error',
  ok: 'success',
  neutral: 'subtle',
}

/** The pastel the next action is drawn in: ochre while work goes on, honey or rose when a gate holds, sage when all is done. */
const NEXT_FAMILY: Record<NextAction['tone'], Family> = {
  running: 'ochre',
  warning: 'honey',
  danger: 'rose',
  ok: 'sage',
  neutral: 'ochre',
}

/** The background tasks as background-tasks draws them, and how many are running. */
function backgroundData(data: PaneData): { view: { snapshot: BackgroundSnapshot | null; services: Service[]; now: number }; running: number } {
  const tasks = data.background
  const snapshot = tasks === null ? null : ({ runs: tasks.runs, agents: tasks.agents, takenAt: tasks.takenAt } as BackgroundSnapshot)
  const services = (tasks?.services ?? []) as Service[]
  const running =
    services.length + (snapshot?.agents.length ?? 0) + (snapshot?.runs.filter(run => run.status === 'running' || run.status === 'silent').length ?? 0)
  return { view: { snapshot, services, now: data.now }, running }
}

/** The terminal's text pane. */
export function renderTextPane($: EngineInterface, e: RenderInput<'Pane'>, data: PaneData) {
  const { Box, Text, Button } = $.ui.resolve(e)
  const { shot, now, offset, review } = data
  const change = shot.change
  const graph = shot.graph
  const width = Math.max(24, e.props.bodyColumns)
  const action = nextAction({ snapshot: shot, hasReview: review, commitDraft: data.commitDraft, marks: data.marks, now })
  return (
    <Box flexDirection="column">
      <Text bold>Prochaine action</Text>
      <Text color={TONE_COLOR[action.tone]}>{action.title}</Text>
      {action.detail !== undefined && <Text dimColor wrap="truncate-end">{action.detail}</Text>}
      <Text> </Text>
      <Text bold>Change</Text>
      {change === null ? (
        <Text dimColor>Aucun change actif · {stepLabel(shot.step)}</Text>
      ) : (
        <Box flexDirection="column">
          <Text wrap="truncate-end">{change.name}</Text>
          <Text>
            {progressBar(change.done, change.total, Math.min(20, Math.max(8, width - 18)))} {change.done}/{change.total} · {percent(change.done, change.total)} %
          </Text>
          <Text color="suggestion">étape {stepLabel(change.step)}</Text>
        </Box>
      )}
      <Text wrap="truncate-end">
        ⎇ {shot.branch ?? '?'} · {shot.dirtyCount === 0 ? 'arbre propre' : plural(shot.dirtyCount, 'non commité', 'non commités')} ·{' '}
        {graph.state === 'unused' ? '' : graph.state === 'fresh' ? 'graph ✓ · ' : 'graph périmé · '}review {review ? '✓' : '✗'}
      </Text>
      <Text> </Text>
      <Text bold>En arrière-plan</Text>
      {renderBackgroundText($, e, backgroundData(data).view)}
      <Text> </Text>
      <Text bold>Passations</Text>
      {shot.recentHandoffs.map(handoff => (
        <Button key={`handoff-${handoff.file}`} plain onPress={() => void fillPrompt($, resumePrompt(handoff))}>
          <Text dimColor>{formatClock(handoff.writtenAt, offset)}</Text> {truncate(handoff.title, width - 14)}
        </Button>
      ))}
      <Text> </Text>
      <Button key="refresh" label="Rafraîchir" onPress={() => void data.onRefresh()} />
    </Box>
  )
}

/** The desktop dashboard. */
export function renderRichPane($: EngineInterface, e: RenderInput<'Pane', 'desktop' | 'vscode'>, data: PaneData) {
  const { Box, Text, Button, Svg, Markdown } = $.ui.resolve(e)
  const { shot, review, now, offset } = data
  const change = shot.change
  const graph = shot.graph
  // The desktop lays a pane out at about 8.9 CSS pixels per column (62 columns for 550 px, measured on screen).
  const width = Math.max(260, Math.floor(e.props.bodyColumns * 8.9) - 4)
  const isCollapsed = (id: string) => data.collapsedSections[id] === true

  // A section: its title in sentence case behind a quiet chevron, its meta on the right; the title folds it.
  const section = (id: string, title: string, meta: string | null, body: RenderChildren, metaColor?: string) => (
    <Box key={`section-${id}`} flexDirection="column" gap="sm">
      <Box flexDirection="row" alignItems="center" gap="sm" justifyContent="space-between">
        <Button key={`toggle-${id}`} plain label={`${isCollapsed(id) ? '▸' : '▾'}  ${title}`} onPress={() => void toggleSection($, id)} />
        {meta !== null && (
          <Text size="caption" color={metaColor} dimColor={metaColor === undefined} wrap="truncate-end">
            {meta}
          </Text>
        )}
      </Box>
      {!isCollapsed(id) && body}
    </Box>
  )

  // -- the head: the change's ring, its name and step, the cycle's timeline
  const stepIndex = stepIndexOf(shot.step, review, shot.dirtyCount)
  const ringLabel = change === null ? '—' : `${change.done}/${change.total}`
  const head = (
    <Box key="head" flexDirection="column" gap="md">
      <Box flexDirection="row" gap="md" alignItems="center">
        <Svg key="head-ring" alt={change === null ? 'Aucun change' : `${change.name} ${ringLabel}`} source={ring(change === null || change.total === 0 ? 0 : change.done / change.total, { size: 54, label: change === null ? '—' : `${percent(change.done, change.total)}%`, id: 'head' })} width={54} height={54} isInteractive />
        <Box flexDirection="column" flexGrow={1} flexShrink={1} minWidth={0} gap="xs">
          <Text weight="semibold" wrap="truncate-end">
            {change?.name ?? 'Aucun change actif'}
          </Text>
          <Text size="caption" dimColor wrap="truncate-end">
            {change === null ? stepLabel(shot.step) : `${stepLabel(change.step)} · ${change.done} tâches sur ${change.total}`}
          </Text>
          <Text size="caption" dimColor wrap="truncate-end">
            {shot.branch ?? '?'} · {shot.dirtyCount === 0 ? 'arbre propre' : plural(shot.dirtyCount, 'non commité', 'non commités')}
          </Text>
        </Box>
      </Box>
      <Svg key="head-timeline" alt={`Cycle : ${stepIndex >= 0 && stepIndex < CYCLE.length ? CYCLE[stepIndex] : stepIndex >= CYCLE.length ? 'terminé' : 'aucun change'}`} source={timeline(width, [...CYCLE], stepIndex, { id: 'cycle' })} width={Math.max(240, width)} height={26} />
    </Box>
  )

  // -- the next action and the cycle's gates
  const action = nextAction({ snapshot: shot, hasReview: review, commitDraft: data.commitDraft, marks: data.marks, now })
  const gates = pills(
    [
      ...(graph.state === 'unused'
        ? []
        : [
            graph.state === 'fresh'
              ? { label: 'graph frais', tone: 'ok' as Tone, hint: 'graphify-out/graph.json est à jour' }
              : { label: 'graph périmé', tone: 'warning' as Tone, hint: graph.reason ?? 'graph à rafraîchir' },
          ]),
      review
        ? { label: 'review vue', tone: 'ok' as Tone, hint: 'code-reviewer vu dans la session ou un workflow de review de moins de 24 h' }
        : { label: 'review à faire', tone: 'danger' as Tone, hint: 'code-reviewer obligatoire avant /opsx:verify' },
      shot.dirtyCount === 0
        ? { label: 'arbre propre', tone: 'ok' as Tone, hint: 'rien à commiter' }
        : { label: plural(shot.dirtyCount, 'non commité', 'non commités'), tone: 'warning' as Tone, hint: 'commit manuel avant /opsx:archive' },
    ],
    { maxWidth: width - 24 },
  )

  // -- progression and decisions
  const currentGroup = shot.groups.find(group => group.done < group.total)
  const decisions = shot.decisions
  const pending = decisions.filter(decision => decision.status === 'open' || decision.status === 'agent')
  const decided = decisions.filter(decision => decision.status === 'owner').length
  const informed = decisions.filter(decision => decision.status === 'informed').length
  const ritual =
    shot.step === 'post-archive' && shot.archivedChange !== null
      ? postArchiveRitual({ archived: shot.archivedChange, graphBuiltAt: graph.builtAt, usesGraph: graph.state !== 'unused', marks: data.marks })
      : null
  const handoff = shot.handoff
  const barWidth = Math.max(56, Math.min(120, Math.floor(width * 0.22)))

  return (
    <Box flexDirection="column" gap="md">
      {head}

      <Box key="next" flexDirection="column" gap="xs" {...surface(NEXT_FAMILY[action.tone])} paddingX="md" paddingY="md">
        <Text size="caption" weight="medium" color={GALET.text[NEXT_FAMILY[action.tone]]}>
          Prochaine action
        </Text>
        <Text weight="semibold" wrap="wrap">
          {action.title}
        </Text>
        {action.detail !== undefined && action.detail !== '' && (
          <Text size="footnote" dimColor wrap="wrap">
            {action.detail}
          </Text>
        )}
        {action.actions.length > 0 && (
          <Box flexDirection="row" gap="sm" flexWrap="wrap">
            {action.actions.map((button, index) => (
              <Button
                key={`action-${button.key}`}
                variant={index === 0 ? 'primary' : 'secondary'}
                label={button.kind === 'graph' && data.busyWith === 'graph' ? 'graph en cours…' : button.label}
                onPress={() => void runAction($, button, data.root, data.home, data.onRefresh)}
              />
            ))}
          </Box>
        )}
        <Box flexDirection="row" paddingTop="xs">
          <Svg key="gates" alt="Portes du cycle" source={gates.source} width={gates.width} height={gates.height} isInteractive />
        </Box>
      </Box>

      {(() => {
        const tasks = backgroundData(data)
        return section(
          'background',
          'En arrière-plan',
          tasks.running > 0 ? `${tasks.running} en cours` : 'rien ne tourne',
          renderBackground($, e, tasks.view),
          tasks.running > 0 ? NATIVE.accent : undefined,
        )
      })()}

      {shot.groups.length > 0 &&
        section(
          'groups',
          'Progression par groupe',
          currentGroup !== undefined ? `groupe ${currentGroup.number} · ${currentGroup.done}/${currentGroup.total}` : 'tout coché',
          // Every group drawn whole, with no button: a clicked button in a long list made the desktop pull the pane back to it.
          <Box flexDirection="column" gap="xs">
            {shot.groups.map(group => {
              const isCurrent = group === currentGroup
              return (
                <Box key={`group-${group.number}`} flexDirection="row" gap="sm" alignItems="center" {...(isCurrent ? chip(GALET.deep.ochre) : {})}>
                  <Box flexGrow={1} flexShrink={1} minWidth={0}>
                    <Text size="footnote" wrap="truncate-end" weight={isCurrent ? 'semibold' : 'regular'} dimColor={group.done === group.total && !isCurrent}>
                      {group.number}. {group.title}
                    </Text>
                  </Box>
                  <Svg
                    key={`group-${group.number}-bar`}
                    alt={`${group.done}/${group.total}`}
                    source={bar(barWidth, group.total === 0 ? 0 : group.done / group.total, { done: group.total > 0 && group.done === group.total, id: `group-${group.number}` })}
                    width={barWidth}
                    height={5} />
                  <Text size="caption" dimColor tabular>
                    {group.done}/{group.total}
                  </Text>
                </Box>
              )
            })}
          </Box>,
        )}

      {decisions.length > 0 &&
        section(
          'decisions',
          'Décisions',
          `${decided} prises · ${pending.filter(item => item.status === 'agent').length} à confirmer · ${pending.filter(item => item.status === 'open').length} ouvertes`,
          <Box flexDirection="column" gap="xs">
            {pending.slice(0, 6).map(decision => (
              <Box key={`decision-row-${decision.source}-${decision.key}`} flexDirection="row" gap="sm" alignItems="center">
                <Svg
                  key={`decision-dot-${decision.source}-${decision.key}`}
                  alt={decision.status === 'agent' ? 'à confirmer' : 'ouverte'}
                  source={dot(decision.status === 'agent' ? 'warning' : 'running')}
                  width={12}
                  height={12}
                />
                <Box flexGrow={1} flexShrink={1} minWidth={0}>
                  <Button key={`decision-${decision.source}-${decision.key}`} plain onPress={() => void fillPrompt($, `Sur « ${truncate(decision.text, 80)} » : `)}>
                    <Text wrap="truncate-end">{decision.text}</Text>
                  </Button>
                </Box>
                <Box flexShrink={0} {...chip(GALET.deep[decision.status === 'agent' ? 'honey' : 'ochre'])}>
                  <Text size="caption" color={GALET.text[decision.status === 'agent' ? 'honey' : 'ochre']} wrap="truncate">
                    {decision.status === 'agent' ? 'à confirmer' : 'ouverte'}
                  </Text>
                </Box>
              </Box>
            ))}
            {pending.length === 0 && <Text dimColor>Rien en attente.</Text>}
            <Text size="caption" dimColor>
              {plural(decided, 'décision prise', 'décisions prises')}
              {informed > 0 ? ` · ${plural(informed, 'amendement noté', 'amendements notés')}` : ''} · owner-points et dernière passation
            </Text>
          </Box>,
        )}

      {ritual !== null &&
        section(
          'ritual',
          `Post-archive · ${shot.archivedChange?.name ?? ''}`,
          `${ritual.filter(item => item.isDone).length}/${ritual.length}`,
          <Box flexDirection="column" gap="xs">
            {ritual.map(item =>
              item.isAuto ? (
                <Text key={`ritual-${item.key}`} color={item.isDone ? NATIVE.ok : undefined} dimColor={!item.isDone}>
                  {item.isDone ? '✓ ' : '○ '}
                  {item.label}
                </Text>
              ) : (
                <Button key={`ritual-${item.key}`} plain onPress={() => void toggleRitual($, `${item.key}:${shot.archivedChange?.name ?? ''}`)}>
                  <Text color={item.isDone ? NATIVE.ok : undefined}>{item.isDone ? '✓ ' : '○ '}</Text>
                  <Text dimColor={!item.isDone}>{item.label}</Text>
                </Button>
              ),
            )}
          </Box>,
        )}

      {handoff !== null &&
        section(
          'handoff',
          'Passation',
          formatClock(handoff.writtenAt, offset),
          <Box flexDirection="column" gap="xs" {...surface('stone')} paddingX="md" paddingY="md">
            <Text weight="semibold" wrap="wrap">
              {handoff.title}
            </Text>
            {handoff.nextSteps.slice(0, 4).map((step, index) => (
              <Text key={`handoff-step-${index}`} size="footnote" dimColor wrap="wrap">
                {index + 1}. {truncate(step, 160)}
              </Text>
            ))}
            <Box flexDirection="row" gap="sm">
              <Button key="resume-pane" variant="secondary" label="Reprendre" onPress={() => void fillPrompt($, resumePrompt(handoff))} />
            </Box>
            {shot.recentHandoffs.slice(1, 4).map(older => (
              <Button key={`handoff-${older.file}`} plain onPress={() => void fillPrompt($, resumePrompt(older))}>
                <Text dimColor>{formatClock(older.writtenAt, offset)}</Text> <Text dimColor>{truncate(older.title, 70)}</Text>
              </Button>
            ))}
          </Box>,
        )}

      <Box flexDirection="row" gap="sm" alignItems="center" justifyContent="space-between">
        <Text size="caption" dimColor>
          Mis à jour {formatClock(shot.takenAt, offset)}
        </Text>
        <Button key="refresh" plain dimColor label="Rafraîchir" onPress={() => void data.onRefresh()} />
      </Box>
    </Box>
  )
}
